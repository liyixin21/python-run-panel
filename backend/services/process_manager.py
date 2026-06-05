"""
ProcessManager 服务类
负责 Python 脚本的异步子进程管理（启动/停止/重启）以及 APScheduler 定时任务调度。
每个项目独立管理其进程生命周期，并收集 stdout/stderr 日志。
支持：进程崩溃自动重启、WebSocket 实时日志推送。
"""
import os
import signal
import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional, Set

from fastapi import WebSocket
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import WORKSPACE_DIR
from backend.services.project_manager import project_manager

logger = logging.getLogger(__name__)


class ProcessRecord:
    """单个进程的运行记录，持有 asyncio 子进程句柄和日志缓冲区。"""

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.logs: list[str] = []
        self.max_log_lines = 500
        self.started_at: Optional[datetime] = None
        self.exit_code: Optional[int] = None
        self._log_subscribers: Set[WebSocket] = set()
        self._auto_restart = False
        self._project_name = ""
        self._entry_file = "main.py"
        self._start_cmd = ""
        self._port: Optional[int] = None
        self._stopping = False

    def append_log(self, line: str):
        self.logs.append(line)
        if len(self.logs) > self.max_log_lines:
            self.logs = self.logs[-self.max_log_lines:]
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
        self._processes: dict[int, ProcessRecord] = defaultdict(ProcessRecord)
        self.scheduler: Optional[AsyncIOScheduler] = None

    def init_scheduler(self):
        """初始化调度器 — 使用内存存储，不从 APScheduler 持久化。"""
        from apscheduler.jobstores.memory import MemoryJobStore
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": {"type": "asyncio"}},
            job_defaults={"coalesce": False, "max_instances": 1},
            timezone="Asia/Shanghai",
        )
        self.scheduler.start()
        # 从数据库恢复定时任务
        asyncio.create_task(self._restore_schedules())
        logger.info("APScheduler 调度器已启动")

    def shutdown_scheduler(self):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            logger.info("APScheduler 调度器已关闭")

    async def _restore_schedules(self):
        """应用启动后从数据库恢复之前配置的定时任务。"""
        try:
            from backend.database import async_session
            from backend.models import Schedule, Project
            from sqlalchemy import select
            async with async_session() as session:
                result = await session.execute(
                    select(Schedule).where(Schedule.enabled == True)
                )
                for s in result.scalars().all():
                    proj_result = await session.execute(
                        select(Project).where(Project.id == s.project_id)
                    )
                    proj = proj_result.scalar_one_or_none()
                    if not proj:
                        continue
                    try:
                        self._add_cron_job_internal(
                            s.project_id, proj.name, s.cron_expression,
                            s.job_type, proj.entry_file, proj.port, proj.start_cmd,
                        )
                    except Exception as e:
                        logger.warning(f"恢复定时任务失败 (schedule_id={s.id}): {e}")
        except Exception as e:
            logger.warning(f"恢复定时任务异常: {e}")

    async def start_process(self, project_id: int, project_name: str,
                            entry_file: str = "main.py", port: Optional[int] = None,
                            auto_restart: bool = False, start_cmd: str = "") -> dict:
        record = self._processes[project_id]

        if record.process is not None and record.process.returncode is None:
            return {"success": False, "message": "进程已在运行中", "pid": record.process.pid}

        project_dir = project_manager._get_project_dir(project_name)
        python_bin = project_manager.get_python_bin(project_name)

        env = os.environ.copy()
        env["VIRTUAL_ENV"] = project_manager._get_venv_dir(project_name)
        env["PATH"] = f"{project_manager._get_venv_dir(project_name)}/bin:{env.get('PATH', '')}"
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
            record.started_at = datetime.utcnow()
            record._stopping = False
            record._auto_restart = auto_restart
            record._project_name = project_name
            record._entry_file = entry_file
            record._start_cmd = start_cmd
            record._port = port

            record.process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=project_dir,
                env=env,
                preexec_fn=os.setsid,
            )

            record.append_log(f"[系统] 进程已启动，PID: {record.process.pid}")
            asyncio.create_task(self._read_output(project_id, record))
            asyncio.create_task(self._detect_port(project_id, record.process.pid))

            return {"success": True, "message": "进程已启动", "pid": record.process.pid}
        except Exception as e:
            logger.exception(f"启动进程失败: {e}")
            record.append_log(f"[系统] 启动失败: {str(e)}")
            return {"success": False, "message": f"启动失败: {str(e)}"}

    async def _read_output(self, project_id: int, record: ProcessRecord):
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
                await record.process.wait()
                record.exit_code = record.process.returncode
                record.append_log(
                    f"[系统] 进程已退出，退出码: {record.process.returncode}"
                )
                if record._auto_restart and not record._stopping and record._project_name:
                    record.append_log("[系统] 检测到进程意外退出，将在 2 秒后自动重启...")
                    await asyncio.sleep(2)
                    if record._auto_restart and not record._stopping:
                        record.append_log("[系统] 正在自动重启...")
                        await self.start_process(
                            project_id, record._project_name,
                            record._entry_file, record._port,
                            auto_restart=True, start_cmd=record._start_cmd,
                        )

    async def stop_process(self, project_id: int, force: bool = False) -> dict:
        record = self._processes[project_id]
        if record.process is None:
            return {"success": False, "message": "没有正在运行的进程"}
        if record.process.returncode is not None:
            record.append_log("[系统] 进程已经退出")
            return {"success": True, "message": "进程已经退出"}

        pid = record.process.pid
        record._stopping = True
        record._auto_restart = False
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
            return {"success": True, "message": "进程已停止"}
        except ProcessLookupError:
            record.append_log("[系统] 进程已不存在")
            return {"success": True, "message": "进程已不存在"}
        except Exception as e:
            logger.exception(f"停止进程失败: {e}")
            return {"success": False, "message": f"停止失败: {str(e)}"}

    async def restart_process(self, project_id: int, project_name: str,
                              entry_file: str = "main.py", port: Optional[int] = None,
                              auto_restart: bool = False, start_cmd: str = "") -> dict:
        await self.stop_process(project_id, force=True)
        await asyncio.sleep(0.5)
        return await self.start_process(project_id, project_name, entry_file, port, auto_restart, start_cmd=start_cmd)

    def get_process_status(self, project_id: int) -> dict:
        record = self._processes[project_id]
        running = record.process is not None and record.process.returncode is None
        return {
            "running": running,
            "pid": record.process.pid if record.process else None,
            "exit_code": record.exit_code,
            "started_at": record.started_at.isoformat() if record.started_at else None,
            "auto_restart": record._auto_restart,
        }

    def get_process_logs(self, project_id: int) -> str:
        return self._processes[project_id].get_logs()

    # ---------- 实时日志 WebSocket ----------

    async def subscribe_logs(self, project_id: int, ws: WebSocket):
        record = self._processes[project_id]
        for line in record.logs:
            try:
                await ws.send_text(line)
            except Exception:
                return
        record.add_subscriber(ws)

    def unsubscribe_logs(self, project_id: int, ws: WebSocket):
        self._processes[project_id].remove_subscriber(ws)

    # ---------- 端口自动检测 ----------

    async def _detect_port(self, project_id: int, pid: int):
        import re
        import subprocess as sp
        await asyncio.sleep(3)
        record = self._processes[project_id]

        try:
            port_patterns = [
                re.compile(r'https?://(?:0\.0\.0\.0|127\.0\.0\.1|localhost|[^/\s]+):(\d+)'),
                re.compile(r'(?:监听|端口|port| Port )\s*:?\s*(\d+)', re.IGNORECASE),
                re.compile(r'Running on .*?://.*?:(\d+)'),
            ]
            for line in record.logs:
                for pat in port_patterns:
                    m = pat.search(line)
                    if m:
                        port = int(m.group(1))
                        if 1024 <= port <= 65535:
                            record.append_log(f"[系统] 检测到进程监听端口: {port}")
                            await self._update_project_port(project_id, port)
                            return
        except Exception:
            pass

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
                                if 1024 <= port <= 65535:
                                    record.append_log(f"[系统] 检测到进程监听端口: {port}")
                                    await self._update_project_port(project_id, port)
                                    return
                            except ValueError:
                                continue
        except Exception as e:
            logger.warning(f"lsof 端口检测失败: {e}")

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

    # ---------- APScheduler 定时任务 ----------

    def _add_cron_job_internal(self, project_id: int, project_name: str,
                                cron_expression: str, job_type: str,
                                entry_file: str = "main.py", port: Optional[int] = None,
                                start_cmd: str = ""):
        """内部方法：为调度器添加任务，使用模块级包装函数避免 pickle 问题。"""
        if self.scheduler is None:
            raise RuntimeError("调度器尚未初始化")

        parts = cron_expression.strip().split()
        if len(parts) < 5:
            raise ValueError(f"无效的 cron 表达式: {cron_expression}")

        trigger = CronTrigger(
            minute=parts[0], hour=parts[1], day=parts[2],
            month=parts[3], day_of_week=parts[4],
            timezone="Asia/Shanghai",
        )

        job_id = f"sched_{job_type}_{project_id}"

        if job_type == "start":
            self.scheduler.add_job(
                _scheduled_start, trigger=trigger,
                kwargs={
                    "project_id": project_id, "project_name": project_name,
                    "entry_file": entry_file, "port": port, "start_cmd": start_cmd,
                },
                id=job_id, replace_existing=True,
            )
        elif job_type == "stop":
            self.scheduler.add_job(
                _scheduled_stop, trigger=trigger,
                kwargs={"project_id": project_id},
                id=job_id, replace_existing=True,
            )
        else:
            raise ValueError(f"无效的 job_type: {job_type}")
        logger.info(f"已添加定时任务: {job_id} ({job_type}), cron={cron_expression}")

    # 对外接口保持一致（兼容 routers 的调用）
    add_cron_job = _add_cron_job_internal

    def remove_cron_job(self, job_id: str):
        if self.scheduler is None:
            return
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"已移除定时任务: {job_id}")
        except Exception as e:
            logger.warning(f"移除定时任务失败 ({job_id}): {e}")


# ---------- 模块级调度包装函数（可 pickle，供 APScheduler 调用） ----------

_global_manager: Optional[ProcessManager] = None


def _get_manager() -> ProcessManager:
    global _global_manager
    if _global_manager is None:
        _global_manager = process_manager
    return _global_manager


async def _scheduled_start(project_id: int, project_name: str,
                            entry_file: str = "main.py", port: Optional[int] = None,
                            start_cmd: str = ""):
    """APScheduler 定时调用的启动函数（模块级，可 pickle）。"""
    mgr = _get_manager()
    await mgr.start_process(project_id, project_name, entry_file, port, start_cmd=start_cmd)


async def _scheduled_stop(project_id: int):
    """APScheduler 定时调用的停止函数（模块级，可 pickle）。"""
    mgr = _get_manager()
    await mgr.stop_process(project_id, force=False)


process_manager = ProcessManager()
