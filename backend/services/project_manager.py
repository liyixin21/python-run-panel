"""
ProjectManager 服务类
负责项目文件夹的创建、删除，以及 Python 虚拟环境 (venv) 的生成与销毁。
确保不同项目间的依赖绝对隔离。
"""
import os
import shutil
import subprocess
import asyncio
import logging

from backend.config import WORKSPACE_DIR

logger = logging.getLogger(__name__)


class ProjectManager:
    """
    项目生命周期管理器：
    - 创建项目时自动生成独立文件夹和专属 venv
    - 删除项目时安全清理文件夹及相关资源
    - 提供端口分配与释放逻辑
    """

    def __init__(self):
        os.makedirs(WORKSPACE_DIR, exist_ok=True)

    def _get_project_dir(self, project_name: str) -> str:
        """返回指定项目的文件夹绝对路径"""
        return os.path.join(WORKSPACE_DIR, project_name)

    def _get_venv_dir(self, project_name: str) -> str:
        """返回指定项目的虚拟环境绝对路径"""
        return os.path.join(self._get_project_dir(project_name), ".venv")

    async def create_project(self, project_name: str) -> dict:
        """
        创建新项目：
        1. 在 workspace 下建立项目文件夹
        2. 使用 python -m venv 创建专属虚拟环境
        3. 配置 pip 清华镜像源
        4. 返回项目元信息字典
        """
        project_dir = self._get_project_dir(project_name)
        venv_dir = self._get_venv_dir(project_name)

        if os.path.exists(project_dir):
            raise FileExistsError(f"项目文件夹已存在: {project_dir}")

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

    def delete_project(self, project_name: str) -> None:
        """
        删除项目及其所有资源（文件夹、虚拟环境）。
        注意：调用前应先确保进程已停止。
        """
        project_dir = self._get_project_dir(project_name)
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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            return {"success": False, "stdout": "", "stderr": "依赖安装超时（5分钟）", "returncode": -1}

        return {
            "success": process.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": process.returncode,
        }

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
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
        except asyncio.TimeoutError:
            return {"success": False, "stdout": "", "stderr": "安装超时（5分钟）", "returncode": -1}

        return {
            "success": process.returncode == 0,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "returncode": process.returncode,
        }

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
        target_dir = os.path.join(project_dir, sub_path) if sub_path else project_dir

        if not os.path.exists(target_dir):
            raise FileNotFoundError(f"目录不存在: {target_dir}")

        # 安全检查：防止路径穿越
        real_target = os.path.realpath(target_dir)
        real_project = os.path.realpath(project_dir)
        if not real_target.startswith(real_project):
            raise PermissionError("禁止访问项目目录之外的文件")

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
