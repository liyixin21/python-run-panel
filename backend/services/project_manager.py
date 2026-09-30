"""
ProjectManager 服务类
负责项目文件夹的创建、删除，以及 Python 虚拟环境 (venv) 的生成与销毁。
确保不同项目间的依赖绝对隔离。

所有涉及项目名拼接路径的操作都经过 utils.safe_join 做边界校验，
防止项目名中含 "../" 时在 workspace 之外读写甚至递归删除。
"""
import os
import shutil
import asyncio
import logging
from contextlib import asynccontextmanager

from backend.config import WORKSPACE_DIR
from backend.utils import safe_join, PathSecurityError, validate_project_name

logger = logging.getLogger(__name__)


class ProjectExistsError(Exception):
    """同名项目已存在。"""


class ProjectManager:
    """
    项目生命周期管理器：
    - 创建项目时自动生成独立文件夹和专属 venv
    - 删除项目时安全清理文件夹及相关资源
    - 提供端口分配与释放逻辑
    - 按项目名加锁，避免并发创建时互相踩踏
    """

    def __init__(self):
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        # 每个项目名一把锁：把「检查 → 建目录 → 提交」串行化
        self._locks: dict[str, asyncio.Lock] = {}

    # ---------- 并发控制 ----------

    @asynccontextmanager
    async def lock_for(self, project_name: str):
        """按项目名加互斥锁，避免同名项目的并发创建互相破坏。"""
        lock = self._locks.setdefault(project_name, asyncio.Lock())
        async with lock:
            yield
        # 锁未被占用时顺手回收，避免 _locks 无限增长
        if not lock.locked() and not getattr(lock, "_waiters", None):
            self._locks.pop(project_name, None)

    # ---------- 路径 ----------

    def _get_project_dir(self, project_name: str) -> str:
        """返回指定项目的文件夹绝对路径（已做边界校验）"""
        return safe_join(WORKSPACE_DIR, project_name)

    def _get_venv_dir(self, project_name: str) -> str:
        """返回指定项目的虚拟环境绝对路径"""
        return self._get_project_dir(project_name) + os.sep + ".venv"

    async def create_project(self, project_name: str) -> dict:
        """
        创建新项目（幂等：目录已存在且 venv 完整时直接复用）：
        1. 校验项目名，防止路径穿越
        2. 在 workspace 下建立项目文件夹
        3. 使用 python -m venv 创建专属虚拟环境
        4. 配置 pip 清华镜像源
        5. 返回项目元信息字典
        """
        project_name = validate_project_name(project_name)
        project_dir = self._get_project_dir(project_name)
        venv_dir = self._get_venv_dir(project_name)

        # 如果目录已存在，检查 venv 是否完整
        if os.path.exists(project_dir):
            if self._is_venv_valid(venv_dir):
                logger.info(f"项目 '{project_name}' 目录和虚拟环境已存在，直接复用")
                return {
                    "name": project_name,
                    "directory": project_dir,
                    "venv_path": venv_dir,
                }
            # venv 不完整，清理后重新创建
            logger.warning(f"项目 '{project_name}' 目录存在但 venv 不完整，清理并重建...")
            shutil.rmtree(project_dir, ignore_errors=True)

        try:
            os.makedirs(project_dir, exist_ok=True)

            logger.info(f"正在为项目 '{project_name}' 创建虚拟环境...")
            process = await asyncio.create_subprocess_exec(
                "python3", "-m", "venv", venv_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace")
                shutil.rmtree(project_dir, ignore_errors=True)
                raise RuntimeError(f"虚拟环境创建失败: {err_msg}")

            # 配置 pip 清华镜像源
            await self._configure_pip_mirror(project_name)

            logger.info(f"项目 '{project_name}' 创建成功，venv 位于: {venv_dir}")
            return {
                "name": project_name,
                "directory": project_dir,
                "venv_path": venv_dir,
            }

        except Exception:
            shutil.rmtree(project_dir, ignore_errors=True)
            raise

    @staticmethod
    def _is_venv_valid(venv_dir: str) -> bool:
        """检查虚拟环境是否完整可用（python 和 pip 可执行文件存在）"""
        python_bin = os.path.join(venv_dir, "bin", "python")
        pip_bin = os.path.join(venv_dir, "bin", "pip")
        return os.path.isfile(python_bin) and os.path.isfile(pip_bin)

    def delete_project(self, project_name: str) -> None:
        """
        删除项目及其所有资源（文件夹、虚拟环境）。
        注意：调用前应先确保进程已停止。

        路径必须是 WORKSPACE_DIR 的直接子目录，否则拒绝删除——
        这是防止历史脏数据（如旧版本写入的 "../x"）触发越界 rmtree 的最后一道闸。
        """
        try:
            project_dir = os.path.realpath(self._get_project_dir(project_name))
        except PathSecurityError as e:
            raise PermissionError(f"拒绝删除越界路径: {e}") from e

        workspace_real = os.path.realpath(WORKSPACE_DIR)
        if os.path.dirname(project_dir) != workspace_real:
            raise PermissionError(f"拒绝删除工作区外目录: {project_dir}")

        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
            logger.info(f"项目 '{project_name}' 已删除，路径: {project_dir}")
        else:
            logger.warning(f"尝试删除不存在的项目: {project_name}")

    async def _configure_pip_mirror(self, project_name: str):
        """为新创建的虚拟环境配置 pip 清华镜像源"""
        pip_bin = self.get_pip_bin(project_name)
        if not os.path.exists(pip_bin):
            return
        index_url = "https://pypi.tuna.tsinghua.edu.cn/simple"
        try:
            process = await asyncio.create_subprocess_exec(
                pip_bin, "config", "set", "global.index-url", index_url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(process.communicate(), timeout=15)
        except Exception:
            pass

    async def install_requirements(self, project_name: str) -> dict:
        venv_dir = self._get_venv_dir(project_name)
        project_dir = self._get_project_dir(project_name)
        pip_bin = os.path.join(venv_dir, "bin", "pip")
        req_file = os.path.join(project_dir, "requirements.txt")

        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")
        if not os.path.exists(req_file):
            raise FileNotFoundError(f"requirements.txt 不存在: {req_file}")

        logger.info(f"正在为项目 '{project_name}' 安装依赖...")
        try:
            process = await asyncio.create_subprocess_exec(
                pip_bin, "install", "--default-timeout=120", "--retries=3",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                "-r", req_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            logger.error(f"项目 '{project_name}' 依赖安装超时（10分钟）")
            return {"success": False, "stdout": "", "stderr": "依赖安装超时（10分钟）", "returncode": -1}

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        if process.returncode != 0:
            logger.error(f"项目 '{project_name}' 依赖安装失败 (exit={process.returncode}):\n{stderr_str}")
        else:
            logger.info(f"项目 '{project_name}' 依赖安装成功")

        return {
            "success": process.returncode == 0,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "returncode": process.returncode,
        }

    async def stream_install_requirements(self, project_name: str):
        """流式安装 requirements.txt，逐行 yield 输出。客户端断开时自动杀死 pip 进程。"""
        venv_dir = self._get_venv_dir(project_name)
        project_dir = self._get_project_dir(project_name)
        pip_bin = os.path.join(venv_dir, "bin", "pip")
        req_file = os.path.join(project_dir, "requirements.txt")

        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")
        if not os.path.exists(req_file):
            raise FileNotFoundError(f"requirements.txt 不存在: {req_file}")

        logger.info(f"正在为项目 '{project_name}' 安装依赖（流式）...")
        process = await asyncio.create_subprocess_exec(
            pip_bin, "install", "--default-timeout=120", "--retries=3",
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            "-r", req_file,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text:
                    yield text

            await process.wait()
            success = process.returncode == 0
            if success:
                logger.info(f"项目 '{project_name}' 依赖安装成功")
            else:
                logger.error(f"项目 '{project_name}' 依赖安装失败 (exit={process.returncode})")
            yield f"__DONE__:{success}"
        finally:
            # 确保生成器被清理时（包括客户端断开）杀死子进程
            if process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                    logger.info(f"项目 '{project_name}' 安装进程已被终止（客户端断开或取消）")
                except Exception:
                    pass

    async def install_package(self, project_name: str, package_name: str) -> dict:
        venv_dir = self._get_venv_dir(project_name)
        pip_bin = os.path.join(venv_dir, "bin", "pip")

        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")

        logger.info(f"正在为项目 '{project_name}' 安装包: {package_name}")
        try:
            process = await asyncio.create_subprocess_exec(
                pip_bin, "install", "--default-timeout=120", "--retries=3",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
                package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            logger.error(f"项目 '{project_name}' 安装包 '{package_name}' 超时（10分钟）")
            return {"success": False, "stdout": "", "stderr": "安装超时（10分钟）", "returncode": -1}

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")

        if process.returncode != 0:
            logger.error(f"项目 '{project_name}' 安装包 '{package_name}' 失败 (exit={process.returncode}):\n{stderr_str}")
        else:
            logger.info(f"项目 '{project_name}' 安装包 '{package_name}' 成功")

        return {
            "success": process.returncode == 0,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "returncode": process.returncode,
        }

    async def stream_install_package(self, project_name: str, package_name: str):
        """流式安装单个包，逐行 yield 输出。客户端断开时自动杀死 pip 进程。"""
        venv_dir = self._get_venv_dir(project_name)
        pip_bin = os.path.join(venv_dir, "bin", "pip")

        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")

        logger.info(f"正在为项目 '{project_name}' 安装包（流式）: {package_name}")
        process = await asyncio.create_subprocess_exec(
            pip_bin, "install", "--default-timeout=120", "--retries=3",
            "-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
            package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            async for line in process.stdout:
                text = line.decode("utf-8", errors="replace").rstrip("\n")
                if text:
                    yield text

            await process.wait()
            success = process.returncode == 0
            if success:
                logger.info(f"项目 '{project_name}' 安装包 '{package_name}' 成功")
            else:
                logger.error(f"项目 '{project_name}' 安装包 '{package_name}' 失败 (exit={process.returncode})")
            yield f"__DONE__:{success}"
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                    logger.info(f"项目 '{project_name}' 安装包进程已被终止（客户端断开或取消）")
                except Exception:
                    pass

    async def get_installed_packages(self, project_name: str) -> dict:
        """
        获取指定项目虚拟环境中已安装的 Python 包列表。
        通过 venv/bin/pip freeze 实现。
        """
        pip_bin = self.get_pip_bin(project_name)
        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")

        process = await asyncio.create_subprocess_exec(
            pip_bin, "freeze",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        packages = []
        if process.returncode == 0:
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                line = line.strip()
                if line and "==" in line:
                    name, version = line.split("==", 1)
                    packages.append({"name": name, "version": version})

        return {
            "success": process.returncode == 0,
            "packages": packages,
            "stderr": stderr.decode("utf-8", errors="replace"),
        }

    def get_python_bin(self, project_name: str) -> str:
        """获取项目虚拟环境中 python 解释器的路径"""
        return os.path.join(self._get_venv_dir(project_name), "bin", "python")

    def get_pip_bin(self, project_name: str) -> str:
        """获取项目虚拟环境中 pip 的路径"""
        return os.path.join(self._get_venv_dir(project_name), "bin", "pip")

    async def uninstall_package(self, project_name: str, package_name: str) -> dict:
        """卸载指定项目中的单个 Python 包"""
        pip_bin = self.get_pip_bin(project_name)
        if not os.path.exists(pip_bin):
            raise FileNotFoundError(f"pip 可执行文件不存在: {pip_bin}")

        logger.info(f"正在为项目 '{project_name}' 卸载包: {package_name}")
        process = await asyncio.create_subprocess_exec(
            pip_bin, "uninstall", "-y", package_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return {
            "success": process.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": process.returncode,
        }

    def list_project_files(self, project_name: str, sub_path: str = "") -> list[dict]:
        """
        列出项目文件夹中的文件（相对于项目根目录的 sub_path）。
        返回文件/目录信息列表，过滤掉 .venv 隐藏目录。
        """
        project_dir = self._get_project_dir(project_name)
        # safe_join 已做边界校验，越界会抛 PathSecurityError
        target_dir = safe_join(project_dir, sub_path) if sub_path else project_dir

        if not os.path.exists(target_dir):
            raise FileNotFoundError(f"目录不存在: {sub_path or '/'}")

        entries = []
        with os.scandir(target_dir) as it:
            for entry in it:
                if entry.name == ".venv":
                    continue  # 隐藏虚拟环境目录
                entries.append({
                    "name": entry.name,
                    "path": os.path.relpath(entry.path, project_dir),
                    "is_dir": entry.is_dir(),
                    "size": entry.stat().st_size if entry.is_file() else 0,
                })

        # 按目录优先、名称排序
        entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
        return entries


# 全局单例
project_manager = ProjectManager()
