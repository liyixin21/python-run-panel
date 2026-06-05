"""
全局配置模块
定义工作区路径、数据库路径等核心配置项。
所有路径均通过环境变量可覆盖，适配 Docker 容器化部署。
"""
import os

_DEFAULT_WORKSPACE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace"
)
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", _DEFAULT_WORKSPACE)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{WORKSPACE_DIR}/panel.db")

STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))
