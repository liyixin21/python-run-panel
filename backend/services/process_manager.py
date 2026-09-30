"""
ProcessManager 服务类
负责 Python 脚本的异步子进程管理（启动/停止/重启）。
每个项目独立管理其进程生命周期，并收集 stdout/stderr 日志。
支持：进程崩溃自动重启、WebSocket 实时日志推送。
"""
import os
import signal
import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Optional, Set

from fastapi import WebSocket
from backend.services.project_manager import project_manager
from backend.utils import utcnow

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 500


class ProcessRecord:
    """单个进程的运行记录，持有 asyncio 子进程句柄和日志缓冲区。"""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        # deque(maxlen) 追加与自动截断均为 O(1)，避免每次溢出重建整个列表
        self.logs: deque[str] = deque(maxlen=MAX_LOG_LINES)
        self.started_at: Optional[datetime] = None
        self.exit_code: Optional[int] = None
        self._log_subscribers: Set[WebSocket] = set()
        self._auto_restart = False
        self._project_name = ""
        self._entry_file = "main.py"
        self._start_cmd = ""
        self._port: Optional[int] = None
        self._stopping = False
        # 代次计数：每次启动 +1，用于让过期的自动重启任务失效
        self._generation = 0

    def append_log(self, line: str):
        self.logs.append(line)
        for ws in list(self._log_subscribers):
            try:
                asyncio.create_task(self._safe_send(ws, line))
            except Exception:
                pass

    @staticmethod
    async def _safe_send(ws: WebSocket, line: str):
        try:
            await ws.send_text(line)
        except Exception:
            pass

    def add_subscriber(self, ws: WebSocket):
        self._log_subscribers.add(ws)

    def remove_subscriber(self, ws: WebSocket):
        self._log_subscribers.discard(ws)

    def get_logs(self) -> str:
        return "\n".join(self.logs)

    def clear_logs(self):
        self.logs.clear()


class ProcessManager:
    """异步进程管理器。"""

    def __init__(self):
        self._processes: dict[int, ProcessRecord] = {}

    def _record(self, project_id: int) -> ProcessRecord:
        """取或创建进程记录（不用 defaultdict，避免只读查询意外创建条目）。"""
        record = self._processes.get(project_id)
        if record is None:
            record = ProcessRecord()
            self._processes[project_id] = record
        return record

    def forget_process(self, project_id: int) -> None:
        """项目删除后回收记录，防止日志缓冲与订阅者集合长期驻留。"""
        self._processes.pop(project_id, None)

    async def start_process(self, project_id: int, project_name: str,
                            entry_file: str = "main.py", port: Optional[int] = None,
                            auto_restart: bool = False, start_cmd: str = "") -> dict:
        record = self._record(project_id)

        if record.process is not None and record.process.returncode is None:
            return {"success": False, "message": "进程已在运行中", "pid": record.process.pid}

        project_dir = project_manager._get_project_dir(project_name)
        python_bin = project_manager.get_python_bin(project_name)
        venv_dir = project_manager._get_venv_dir(project_name)

        if not os.path.isdir(project_dir):
            return {"success": False, "message": f"项目目录不存在: {project_dir}"}

        env = os.environ.copy()
        env["VIRTUAL_ENV"] = venv_dir
        env["PATH"] = f"{venv_dir}/bin:{env.get('PATH', '')}"
        env["PYTHONUNBUFFERED"] = "1"
        if port is not None:
            env["PORT"] = str(port)

        # 构建启动命令：自定义命令优先，否则使用 python + entry_file
        if start_cmd and start_cmd.strip():
            cmd_parts = start_cmd.strip().split()
            cmd_msg = f"自定义命令: {start_cmd}"
        else:
            script_path = os.path.join(project_dir, entry_file)
            if not os.path.exists(script_path):
                return {"success": False, "message": f"入口文件不存在: {entry_file}"}
            cmd_parts = [python_bin, script_path]
            cmd_msg = f"入口: {entry_file}"

        logger.info(f"启动项目 '{project_name}' (ID={project_id})，{cmd_msg}")

        try:
            record.clear_logs()
            record.started_at = utcnow()
            record.exit_code = None
            record._stopping = False
            record._auto_restart = auto_restart
            record._project_name = project_name
            record._entry_file = entry_file
            record._start_cmd = start_cmd
            record._port = port
            # 新一代：使此前排队中的自动重启任务失效
            record._generation += 1
            generation = record._generation

            record.process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_dir,
                env=env,
                preexec_fn=os.setsid,
            )

            record.append_log(f"[系统] 进程已启动，PID: {record.process.pid}")
            asyncio.create_task(self._read_output(project_id, record, generation))
            asyncio.create_task(self._detect_port(project_id, record.process.pid))

            return {"success": True, "message": "进程已启动", "pid": record.process.pid}
        except Exception as e:
            logger.exception(f"启动进程失败: {e}")
            record.append_log(f"[系统] 启动失败: {str(e)}")
            return {"success": False, "message": f"启动失败: {str(e)}"}

    async def _read_output(self, project_id: int, record: ProcessRecord, generation: int):
        try:
            if record.process and record.process.stdout:
                while True:
                    line = await record.process.stdout.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\n")
                    record.append_log(text)
        except Exception as e:
            logger.error(f"读取进程输出异常: {e}")
        finally:
            if record.process:
                try:
                    await record.process.wait()
                except Exception:
                    pass
                record.exit_code = record.process.returncode
                record.append_log(
                    f"[系统] 进程已退出，退出码: {record.process.returncode}"
                )
                # 仅当代次未变（期间没有新的启动/停止）才触发自动重启，
                # 否则用户在 2 秒窗口内点停止后进程仍会被拉起。
                if (record._auto_restart and not record._stopping
                        and record._project_name and record._generation == generation):
                    record.append_log("[系统] 检测到进程意外退出，将在 2 秒后自动重启...")
                    await asyncio.sleep(2)
                    if (record._auto_restart and not record._stopping
                            and record._generation == generation):
                        record.append_log("[系统] 正在自动重启...")
                        await self.start_process(
                            project_id, record._project_name,
                            record._entry_file, record._port,
                            auto_restart=True, start_cmd=record._start_cmd,
                        )

    async def stop_process(self, project_id: int, force: bool = False,
                           wait: bool = False) -> dict:
        record = self._record(project_id)

        # 无论走哪个分支，都先让代次失效并取消自动重启意图
        record._stopping = True
        record._auto_restart = False
        record._generation += 1

        if record.process is None:
            return {"success": False, "message": "没有正在运行的进程"}
        if record.process.returncode is not None:
            record.append_log("[系统] 进程已经退出")
            if record._port:
                asyncio.create_task(self._close_firewall_port(record._port, project_id))
            return {"success": True, "message": "进程已经退出"}

        pid = record.process.pid
        logger.info(f"正在停止进程 PID={pid} (force={force})")

        try:
            if force:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
                record.append_log("[系统] 进程已被强制终止")
            else:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                record.append_log("[系统] 正在发送终止信号...")
                try:
                    await asyncio.wait_for(record.process.wait(), timeout=10.0)
                    record.append_log("[系统] 进程已优雅退出")
                except asyncio.TimeoutError:
                    os.killpg(os.getpgid(pid), signal.SIGKILL)
                    record.append_log("[系统] 进程超时未退出，已强制终止")

            # 显式等待回收，让调用方（如删除项目）能拿到「确实已退出」的保证
            if wait or force:
                try:
                    await asyncio.wait_for(record.process.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning(f"进程 PID={pid} 未能在超时内回收")

            # 进程停止后，根据配置关闭防火墙端口
            if record._port:
                asyncio.create_task(self._close_firewall_port(record._port, project_id))
            return {"success": True, "message": "进程已停止"}
        except ProcessLookupError:
            record.append_log("[系统] 进程已不存在")
            if record._port:
                asyncio.create_task(self._close_firewall_port(record._port, project_id))
            return {"success": True, "message": "进程已不存在"}
        except Exception as e:
            logger.exception(f"停止进程失败: {e}")
            return {"success": False, "message": f"停止失败: {str(e)}"}

    async def restart_process(self, project_id: int, project_name: str,
                              entry_file: str = "main.py", port: Optional[int] = None,
                              auto_restart: bool = False, start_cmd: str = "") -> dict:
        await self.stop_process(project_id, force=True, wait=True)
        await asyncio.sleep(0.5)
        return await self.start_process(project_id, project_name, entry_file, port,
                                        auto_restart, start_cmd=start_cmd)

    def get_process_status(self, project_id: int) -> dict:
        record = self._processes.get(project_id)
        if record is None:
            return {"running": False, "pid": None, "exit_code": None,
                    "started_at": None, "auto_restart": False}
        running = record.process is not None and record.process.returncode is None
        return {
            "running": running,
            "pid": record.process.pid if record.process else None,
            "exit_code": record.exit_code,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "auto_restart": record._auto_restart,
        }

    def get_process_logs(self, project_id: int) -> str:
        record = self._processes.get(project_id)
        return record.get_logs() if record else ""

    def clear_process_logs(self, project_id: int):
        record = self._processes.get(project_id)
        if record:
            record.clear_logs()

    # ---------- 实时日志 WebSocket ----------

    async def subscribe_logs(self, project_id: int, ws: WebSocket):
        record = self._record(project_id)
        for line in record.logs:
            try:
                await ws.send_text(line)
            except Exception:
                return
        record.add_subscriber(ws)

    def unsubscribe_logs(self, project_id: int, ws: WebSocket):
        record = self._processes.get(project_id)
        if record:
            record.remove_subscriber(ws)

    # ---------- 端口自动检测 ----------

    async def _detect_port(self, project_id: int, pid: int):
        """检测进程监听的端口。

        旧实现固定 sleep 3 秒只试一次，启动慢的服务必然漏检且无重试，
        导致端口为空、防火墙不放行。这里改为带退避的多轮轮询，
        检测成功立即返回。
        """
        import re
        import subprocess as sp

        port_patterns = [
            re.compile(r'https?://(?:0\.0\.0\.0|127\.0\.0\.1|localhost|[^/\s]+):(\d+)'),
            re.compile(r'(?:监听|端口|port| Port )\s*:?\s*(\d+)', re.IGNORECASE),
            re.compile(r'Running on .*?://.*?:(\d+)'),
        ]

        # 轮询计划：最多约 30 秒总窗口
        delays = [1.5, 2, 3, 5, 8, 10]

        for delay in delays:
            await asyncio.sleep(delay)
            record = self._processes.get(project_id)
            if record is None or record.process is None:
                return
            if record.process.returncode is not None:
                return  # 进程已退出，无需继续检测

            # 1) 从日志中识别
            try:
                for line in list(record.logs):
                    for pat in port_patterns:
                        m = pat.search(line)
                        if m:
                            port = int(m.group(1))
                            if not (1 <= port <= 65535):
                                continue
                            record.append_log(f"[系统] 检测到进程监听端口: {port}")
                            await self._update_project_port(project_id, port)
                            await self._open_firewall_port(port, record._project_name, project_id)
                            return
            except Exception as e:
                logger.debug(f"日志端口解析异常: {e}")

            # 2) 回退到 lsof
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: sp.run(
                        ["lsof", "-i", "TCP", "-s", "TCP:LISTEN", "-P", "-n", "-p", str(pid)],
                        capture_output=True, text=True, timeout=10,
                    )
                )
                if result.returncode == 0 and result.stdout.strip():
                    for line in result.stdout.strip().split("\n")[1:]:
                        parts = line.split()
                        if len(parts) >= 9:
                            addr = parts[-1] if "->" not in parts[-1] else parts[-1].split("->")[-1].strip()
                            if ":" in addr:
                                port_str = addr.rsplit(":", 1)[-1]
                                try:
                                    port = int(port_str)
                                except ValueError:
                                    continue
                                if not (1 <= port <= 65535):
                                    continue
                                record.append_log(f"[系统] 检测到进程监听端口: {port}")
                                await self._update_project_port(project_id, port)
                                await self._open_firewall_port(port, record._project_name, project_id)
                                return
            except Exception as e:
                logger.warning(f"lsof 端口检测失败: {e}")

        record = self._processes.get(project_id)
        if record and record.process and record.process.returncode is None:
            record.append_log("[系统] 未能在 30 秒内检测到监听端口，可手动填写端口后重启")

    async def _update_project_port(self, project_id: int, port: int):
        from backend.database import async_session
        from backend.models import Project
        from sqlalchemy import select
        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one_or_none()
            if project:
                project.port = port
                await session.commit()

    async def _open_firewall_port(self, port: int, project_name: str, project_id: int):
        """根据防火墙配置决定是否自动放行端口。"""
        from backend.config import load_firewall_config
        from backend.services import firewall as firewall_service
        config = load_firewall_config()
        if not config.get("auto_open", True):
            return
        record = self._processes.get(project_id)
        if record is None:
            return
        try:
            was_open = await firewall_service.check_port(port)
            ok = await firewall_service.open_port(port, project_name)
            if ok:
                if was_open:
                    record.append_log(f"[系统] 端口 {port} 已存在于防火墙，无需重复放行")
                else:
                    record.append_log(f"[系统] 端口 {port} 已自动放行")
            else:
                record.append_log(f"[系统] 端口 {port} 自动放行失败，请检查 1Panel API 配置")
        except Exception as e:
            logger.warning(f"[防火墙] 放行端口 {port} 异常: {e}")

    async def _close_firewall_port(self, port: int, project_id: int):
        """根据防火墙配置决定是否关闭端口规则。"""
        from backend.config import load_firewall_config
        from backend.services import firewall as firewall_service
        config = load_firewall_config()
        if config.get("keep_rules", False):
            return
        record = self._processes.get(project_id)
        if record is None:
            return
        try:
            was_open = await firewall_service.check_port(port)
            ok = await firewall_service.close_port(port)
            if ok and was_open:
                record.append_log(f"[系统] 防火墙端口 {port} 规则已移除")
        except Exception as e:
            logger.warning(f"[防火墙] 关闭端口 {port} 异常: {e}")

process_manager = ProcessManager()
