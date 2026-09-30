"""防火墙设置 API。"""
import logging

from fastapi import APIRouter, HTTPException

from backend.config import load_firewall_config, save_firewall_config
from backend.services.firewall import check_port, test_connection

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/firewall", tags=["防火墙"])

# 对外掩码：与前端 Settings.vue 的判断保持一致
_MASKED_KEY = "***"


@router.get("/check")
async def api_check_port(port: int):
    """检查指定端口是否已放行。防火墙未配置时返回 None。"""
    config = load_firewall_config()
    if not config.get("auto_open") or not config.get("api_key"):
        return {"port": port, "open": None}

    try:
        open_state = await check_port(port)
    except Exception as e:
        logger.warning(f"防火墙端口检查失败 (port={port}): {e}")
        return {"port": port, "open": None}
    return {"port": port, "open": open_state}


@router.post("/test-connection")
async def api_test_connection(body: dict):
    """测试 1Panel API 连接（使用请求体中的临时配置）。"""
    try:
        # 未提交新 Key 时（前端回显为 ***），用已保存的 Key 测试
        payload = dict(body)
        if not payload.get("api_key") or payload.get("api_key") == _MASKED_KEY:
            payload["api_key"] = load_firewall_config().get("api_key", "")
        ok, msg = await test_connection(payload)
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}


@router.get("/settings")
async def api_get_settings():
    """获取防火墙配置。API Key 以掩码返回，不回显明文。"""
    try:
        config = load_firewall_config()
    except Exception as e:
        logger.warning(f"读取防火墙配置失败: {e}")
        config = {"auto_open": True, "keep_rules": False, "api_key": "", "base_url": "http://127.0.0.1:55555"}

    result = dict(config)
    result["api_key"] = _MASKED_KEY if config.get("api_key") else ""
    return result


@router.put("/settings")
async def api_update_settings(body: dict):
    """更新防火墙配置。

    请求体中的 api_key 为空或为掩码时，保留已保存的 Key 不变，
    避免前端回显掩码后原样提交而清空凭据。
    """
    submitted_key = str(body.get("api_key", "")).strip()
    if not submitted_key or submitted_key == _MASKED_KEY:
        saved_key = load_firewall_config().get("api_key", "")
    else:
        saved_key = submitted_key

    config = {
        "auto_open": bool(body.get("auto_open", True)),
        "keep_rules": bool(body.get("keep_rules", False)),
        "api_key": saved_key,
        "base_url": str(body.get("base_url", "http://127.0.0.1:55555")),
    }
    try:
        save_firewall_config(config)
    except Exception as e:
        logger.warning(f"保存防火墙配置失败: {e}")
        raise HTTPException(status_code=500, detail=f"保存配置失败: {e}")
    logger.info("防火墙配置已更新")
    result = dict(config)
    result["api_key"] = _MASKED_KEY if config["api_key"] else ""
    return {"success": True, "config": result}
