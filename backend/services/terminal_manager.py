"""
TerminalManager 服务类
基于 PTY（伪终端）和 FastAPI WebSocket 实现全双工 Web 终端。
当用户进入终端时，自动注入项目的 VIRTUAL_ENV 环境变量。

核心设计：
- 使用 run_in_executor + 非阻塞 fd 读取 PTY 输出
- close() 时先关闭 fd（使 os.read 立即返回 OSError），再 cancel task 和 kill 子进程
"""
import os
import pty
import signal
import struct
import fcntl
import termios
import asyncio
import logging
from typing import Optional

from fastapi import WebSocket

from backend.services.project_manager import project_manager

logger = logging.getLogger(__name__)


class TerminalSession:
    """单个终端会话。"""

    def __init__(self, ws: WebSocket):
        self.ws: WebSocket = ws
        self.fd: Optional[int] = None
        self.pid: Optional[int] = None
        self._closed: bool = False
        self._read_task: Optional[asyncio.Task] = None

    async def start(self, project_name: str, cols: int = 80, rows: int = 24):
        """启动 PTY 并 spawn shell。"""
        env = os.environ.copy()
        env["VIRTUAL_ENV"] = project_manager._get_venv_dir(project_name)
        venv_bin = os.path.join(project_manager._get_venv_dir(project_name), "bin")
        env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
        env["TERM"] = "xterm-256color"
        env["LANG"] = "en_US.UTF-8"
        cwd = project_manager._get_project_dir(project_name)

        self.pid, self.fd = pty.fork()

        if self.pid == 0:
            # ---- 子进程 ----
            os.chdir(cwd)
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)
            shell = "/bin/bash" if os.path.exists("/bin/bash") else "/bin/sh"
            os.execle(shell, shell, env)
        else:
            # ---- 父进程 ----
            logger.info(f"终端会话已创建: project={project_name}, PID={self.pid}")
            # 设置 fd 为非阻塞，避免 executor 线程永久卡住
            flags = fcntl.fcntl(self.fd, fcntl.F_GETFL)
            fcntl.fcntl(self.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            self._read_task = asyncio.create_task(self._read_pty_output())

    async def _read_pty_output(self):
        """后台协程：从 PTY 读取输出并推送到 WebSocket。"""
        loop = asyncio.get_event_loop()
        try:
            while not self._closed and self.fd is not None:
                data = await loop.run_in_executor(None, self._read_fd)
                if data is None:
                    break
                try:
                    await self.ws.send_bytes(data)
                except Exception:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"PTY 读取异常: {e}")
        finally:
            await self.close()

    def _read_fd(self):
        """同步方法：从 PTY fd 读取数据（在 executor 线程中运行）。"""
        if self.fd is None:
            return None
        try:
            # 短暂轮询，确保能及时检测到 fd 关闭
            import time
            deadline = time.time() + 0.5
            while time.time() < deadline:
                try:
                    data = os.read(self.fd, 4096)
                    if data:
                        return data
                    return None
                except BlockingIOError:
                    time.sleep(0.05)
            return b""
        except OSError:
            return None

    async def write(self, data: bytes):
        """写入数据到 PTY。"""
        if self.fd is not None and not self._closed:
            try:
                os.write(self.fd, data)
            except OSError:
                pass

    async def resize(self, cols: int, rows: int):
        """调整终端窗口大小。"""
        if self.fd is not None and not self._closed:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)
                if self.pid is not None:
                    os.kill(self.pid, signal.SIGWINCH)
            except OSError:
                pass

    async def close(self):
        if self._closed:
            return
        self._closed = True

        # 1. 先关闭 fd —— 这会让 executor 中的 os.read 返回 OSError，线程立即退出
        fd = self.fd
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            self.fd = None

        # 2. 等待读取 task 完成（不再阻塞，因为 fd 已关闭）
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        # 3. 杀死子进程并 waitpid
        if self.pid is not None:
            try:
                os.killpg(os.getpgid(self.pid), signal.SIGTERM)
            except OSError:
                pass
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self._waitpid_timeout, self.pid, 3.0
                )
            except Exception:
                pass
            try:
                os.kill(self.pid, 0)
                os.killpg(os.getpgid(self.pid), signal.SIGKILL)
                os.waitpid(self.pid, 0)
            except OSError:
                pass
            logger.info(f"终端会话已关闭: PID={self.pid}")
            self.pid = None

    @staticmethod
    def _waitpid_timeout(pid: int, timeout: float):
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            wpid, _ = os.waitpid(pid, os.WNOHANG)
            if wpid != 0:
                return
            time.sleep(0.1)


class TerminalManager:
    def __init__(self):
        self._sessions: dict[str, TerminalSession] = {}

    async def create_session(self, project_name: str, ws: WebSocket,
                             cols: int = 80, rows: int = 24) -> TerminalSession:
        if project_name in self._sessions:
            await self._sessions[project_name].close()
        session = TerminalSession(ws)
        self._sessions[project_name] = session
        await session.start(project_name, cols, rows)
        return session

    async def remove_session(self, project_name: str):
        if project_name in self._sessions:
            await self._sessions[project_name].close()
            del self._sessions[project_name]

    def get_session(self, project_name: str) -> Optional[TerminalSession]:
        return self._sessions.get(project_name)


terminal_manager = TerminalManager()
