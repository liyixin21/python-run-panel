"""
防火墙服务模块 — 通过 1Panel API 管理端口放行规则。
所有操作幂等、失败不阻塞主流程。
"""
import asyncio
import hashlib
import json
import logging
import time
import urllib.request

from backend.config import load_firewall_config

logger = logging.getLogger(__name__)


def _get_api_config() -> dict:
    """读取防火墙 API 配置。"""
    config = load_firewall_config()
    return {
        "api_key": config.get("api_key", ""),
        "base_url": config.get("base_url", "http://127.0.0.1:55555"),
    }


def _get_api_base() -> str:
    """拼接 API 基地址。"""
    cfg = _get_api_config()
    return cfg["base_url"].rstrip("/")


def _make_sign_headers(api_key: str) -> dict:
    """生成 1Panel API 签名请求头。"""
    ts = str(int(time.time()))
    token = hashlib.md5(f"1panel{api_key}{ts}".encode()).hexdigest()
    return {
        "Content-Type": "application/json",
        "1Panel-Token": token,
        "1Panel-Timestamp": ts,
    }


async def _call_api(method: str, path: str, data: dict) -> tuple[int, dict]:
    """调用 1Panel API，返回 (http_code, response_data)。"""
    cfg = _get_api_config()
    if not cfg["api_key"]:
        return 0, {}

    api_base = _get_api_base()
    url = f"{api_base}{path}"
    headers = _make_sign_headers(cfg["api_key"])
    body = json.dumps(data).encode("utf-8")
    loop = asyncio.get_event_loop()

    try:
        def _sync_call():
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))

        return await loop.run_in_executor(None, _sync_call)
    except Exception as e:
        logger.warning(f"[防火墙] 1Panel API 调用失败 ({path}): {e}")
        return 0, {}


async def test_connection(config: dict) -> tuple[bool, str]:
    """测试 1Panel API 连接。使用传入的临时配置。"""
    api_key = config.get("api_key", "")
    if not api_key:
        return False, "API Key 不能为空"

    base = config.get("base_url", "http://127.0.0.1:55555").rstrip("/")

    ts = str(int(time.time()))
    token = hashlib.md5(f"1panel{api_key}{ts}".encode()).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "1Panel-Token": token,
        "1Panel-Timestamp": ts,
    }
    body = json.dumps({"page": 1, "pageSize": 1, "type": "port"}).encode("utf-8")
    url = f"{base}/api/v2/hosts/firewall/search"
    loop = asyncio.get_event_loop()

    try:
        def _sync_call():
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))

        code, data = await loop.run_in_executor(None, _sync_call)
        if code == 200 and data.get("code") == 200:
            return True, "连接成功"
        elif code == 200:
            return False, data.get("message", "API Key 无效")
        return False, f"HTTP {code}: {data.get('message', str(data)[:100])}"
    except Exception as e:
        return False, str(e)[:200]


# ==================== 核心接口 ====================


async def check_port(port: int) -> bool:
    """检查指定端口是否已有 ACCEPT 规则。"""
    try:
        code, resp = await _call_api("POST", "/api/v2/hosts/firewall/search", {
            "page": 1, "pageSize": 100, "type": "port", "info": str(port),
        })
    except Exception as e:
        logger.warning(f"[防火墙] check_port API 异常: {e}")
        return False

    if code == 200 and resp:
        data = resp.get("data") or {}
        items = data.get("items") or []
        for item in items:
            if item.get("port") == str(port) and item.get("strategy") == "accept":
                return True
    return False


async def open_port(port: int, project_name: str) -> bool:
    """开放端口（幂等）。"""
    try:
        if await check_port(port):
            logger.info(f"[防火墙] 端口 {port} 已开放，跳过 (项目: {project_name})")
            return True
    except Exception as e:
        logger.warning(f"[防火墙] check_port 异常: {e}")

    try:
        code, resp = await _call_api("POST", "/api/v2/hosts/firewall/port", {
            "operation": "add",
            "port": str(port),
            "protocol": "tcp",
            "strategy": "accept",
            "description": project_name,
        })
        if code == 200:
            logger.info(f"[防火墙] 端口 {port} 已通过 1Panel 开放 (项目: {project_name})")
            return True
        logger.warning(f"[防火墙] 开放端口 {port} 失败: {resp}")
    except Exception as e:
        logger.warning(f"[防火墙] 开放端口 {port} 异常: {e}")
    return False


async def close_port(port: int) -> bool:
    """关闭端口规则。"""
    try:
        code, resp = await _call_api("POST", "/api/v2/hosts/firewall/port", {
            "operation": "remove",
            "port": str(port),
            "protocol": "tcp",
            "strategy": "accept",
        })
        if code == 200:
            logger.info(f"[防火墙] 端口 {port} 已通过 1Panel 移除")
            return True
        logger.warning(f"[防火墙] 移除端口 {port} 失败: {resp}")
    except Exception as e:
        logger.warning(f"[防火墙] 移除端口 {port} 异常: {e}")
    return False
