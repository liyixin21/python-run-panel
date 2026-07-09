"""
认证 API 路由
提供登录、登出、Token 验证功能。
用户名密码存储于 SQLite，Token 持久化到 workspace/tokens.json（24 小时有效）。
"""
import json
import os
import secrets
import time
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import PanelUser
from backend.utils import verify_password, hash_password
from backend.config import WORKSPACE_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])

# 有效 token 集合：{token: expire_timestamp}
_valid_tokens: dict[str, float] = {}
TOKEN_EXPIRE_SECONDS = 6 * 3600  # 6 小时
_TOKENS_FILE = os.path.join(WORKSPACE_DIR, "tokens.json")


def _save_tokens():
    """将 token 持久化到文件。"""
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(_TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(_valid_tokens, f)
    except Exception as e:
        logger.warning(f"持久化 token 失败: {e}")


def _load_tokens():
    """从文件恢复 token。"""
    global _valid_tokens
    try:
        if os.path.exists(_TOKENS_FILE):
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                now = time.time()
                _valid_tokens = {k: v for k, v in data.items() if isinstance(v, (int, float)) and v > now}
                if len(_valid_tokens) < len(data):
                    _save_tokens()
                logger.info(f"已从文件恢复 {len(_valid_tokens)} 个 token")
    except Exception as e:
        logger.warning(f"恢复 token 失败: {e}")


# 启动时加载已持久化的 token
_load_tokens()


def _generate_token() -> str:
    return secrets.token_hex(32)


def _clean_expired():
    now = time.time()
    expired = [t for t, exp in _valid_tokens.items() if exp < now]
    if expired:
        for t in expired:
            del _valid_tokens[t]
        _save_tokens()


@router.post("/login")
async def login(body: dict, session: AsyncSession = Depends(get_session)):
    """
    登录接口。请求体：{"username": "...", "password": "..."}
    """
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=401, detail="用户名和密码不能为空")

    result = await session.execute(
        select(PanelUser).where(PanelUser.username == username)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    _clean_expired()
    token = _generate_token()
    _valid_tokens[token] = time.time() + TOKEN_EXPIRE_SECONDS
    _save_tokens()
    logger.info(f"用户 '{username}' 已登录")
    return {"token": token, "username": username, "expires_in": TOKEN_EXPIRE_SECONDS}


@router.post("/logout")
async def logout(token: str = Depends(lambda authorization: _require_token(authorization))):
    _valid_tokens.pop(token, None)
    _save_tokens()
    logger.info("用户已登出")
    return {"success": True, "message": "已登出"}


@router.get("/status")
async def auth_status(token: str = Depends(lambda authorization: _require_token(authorization))):
    return {"authenticated": True}


@router.get("/info")
async def auth_info(token: str = Depends(lambda authorization: _require_token(authorization)),
                    session: AsyncSession = Depends(get_session)):
    """获取当前登录用户信息"""
    # 返回第一个用户的信息（单用户系统）
    result = await session.execute(select(PanelUser).limit(1))
    user = result.scalar_one_or_none()
    return {"username": user.username if user else "admin"}


def _require_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[7:]
    _clean_expired()
    if token not in _valid_tokens:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    _valid_tokens[token] = time.time() + TOKEN_EXPIRE_SECONDS
    return token


def _require_token_ws(token: Optional[str] = Query(None)) -> str:
    """WebSocket 版 token 验证：从查询参数读取 token（浏览器 WebSocket API 不支持自定义请求头）"""
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    _clean_expired()
    if token not in _valid_tokens:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    _valid_tokens[token] = time.time() + TOKEN_EXPIRE_SECONDS
    return token


verify_token = Depends(_require_token)
verify_token_ws = Depends(_require_token_ws)
