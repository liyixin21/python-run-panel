"""
全局配置模块
定义工作区路径、数据库路径等核心配置项。
所有路径均通过环境变量可覆盖，适配 Docker 容器化部署。
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_WORKSPACE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "workspace"
)
WORKSPACE_DIR = os.environ.get("WORKSPACE_DIR", _DEFAULT_WORKSPACE)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite+aiosqlite:///{WORKSPACE_DIR}/panel.db")

STATIC_DIR = os.environ.get("STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "static"))

# 面板登录密码（通过环境变量 PANEL_PASSWORD 设置，默认 admin）
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "admin")

# 防火墙配置文件路径
FIREWALL_CONFIG_FILE = os.path.join(WORKSPACE_DIR, "firewall_config.json")

_DEFAULT_FIREWALL_CONFIG = {
    "auto_open": True,
    "keep_rules": False,
    "api_key": "",
    "base_url": "http://127.0.0.1:55555",
}


def load_firewall_config() -> dict:
    """从 JSON 文件读取防火墙配置，文件不存在时返回默认值。"""
    try:
        if os.path.exists(FIREWALL_CONFIG_FILE):
            with open(FIREWALL_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "auto_open": bool(data.get("auto_open", True)),
                "keep_rules": bool(data.get("keep_rules", False)),
                "api_key": str(data.get("api_key", "")),
                "base_url": str(data.get("base_url", "http://127.0.0.1:55555")),
            }
    except Exception as e:
        logger.warning(f"读取防火墙配置失败，使用默认值: {e}")
    return dict(_DEFAULT_FIREWALL_CONFIG)


def save_firewall_config(config: dict) -> None:
    """将防火墙配置写入 JSON 文件。"""
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    with open(FIREWALL_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
