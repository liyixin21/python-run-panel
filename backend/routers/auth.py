"""
认证 API 路由
提供登录、登出、Token 验证功能。
用户名密码存储于 SQLite，Token 持久化到 workspace/tokens.json。

Token 有效期由 config.TOKEN_EXPIRE_SECONDS 控制（默认 24 小时）。
每次通过校验的请求都会续期；续期按 _SAVE_THROTTLE 节流写盘，
既避免每请求一次 IO，又保证重启后不会回退到很旧的过期时间。
"""
import json
import os
import secrets
import time
import logging
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import PanelUser
from backend.utils import verify_password
from backend.config import WORKSPACE_DIR, TOKEN_EXPIRE_SECONDS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])

# 有效 token 集合：{token: expire_timestamp}
_valid_tokens: dict[str, float] = {}
_TOKENS_FILE = os.path.join(WORKSPACE_DIR, "tokens.json")
# 续期写盘的最小间隔（秒），避免高并发下频繁写文件
_SAVE_THROTTLE = 60.0
_last_saved_at = 0.0


# ---------- 持久化 ----------

def _save_tokens(force: bool = False):
    """将 token 持久化到文件（默认受节流限制）。"""
    global _last_saved_at
    now = time.time()
    if not force and now - _last_saved_at < _SAVE_THROTTLE:
        return
    try:
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        tmp_file = _TOKENS_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(_valid_tokens, f)
        os.replace(tmp_file, _TOKENS_FILE)   # 原子替换，避免读到半个文件
        _last_saved_at = now
    except Exception as e:
        logger.warning(f"持久化 token 失败: {e}")


def _load_tokens():
    """从文件恢复 token，丢弃已过期的条目。"""
    global _valid_tokens
    try:
        if os.path.exists(_TOKENS_FILE):
            with open(_TOKENS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                now = time.time()
                _valid_tokens = {
                    k: v for k, v in data.items()
                    if isinstance(v, (int, float)) and v > now
                }
                if len(_valid_tokens) < len(data):
                    _save_tokens(force=True)
                logger.info(f"已从文件恢复 {len(_valid_tokens)} 个 token")
    except Exception as e:
        logger.warning(f"恢复 token 失败: {e}")


_load_tokens()


# ---------- 内部工具 ----------

def _generate_token() -> str:
    return secrets.token_hex(32)


def _clean_expired() -> bool:
    """清理过期 token，返回是否发生了清理。"""
    now = time.time()
    expired = [t for t, exp in _valid_tokens.items() if exp < now]
    if expired:
        for t in expired:
            del _valid_tokens[t]
        return True
    return False


def _touch_token(token: str) -> None:
    """续期并（节流）落盘。"""
    _valid_tokens[token] = time.time() + TOKEN_EXPIRE_SECONDS
    _save_tokens()


def revoke_all_tokens(keep: Optional[str] = None) -> int:
    """撤销全部 token（可保留一个），用于改密后强制其它会话重新登录。"""
    revoked = 0
    for t in list(_valid_tokens.keys()):
        if keep and t == keep:
            continue
        del _valid_tokens[t]
        revoked += 1
    if revoked:
        _save_tokens(force=True)
    return revoked


# ---------- 依赖项 ----------

def _require_token(authorization: Optional[str] = Header(None)) -> str:
    """校验 Authorization: Bearer <token>，成功则续期并返回 token。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization[7:]
    _clean_expired()
    if token not in _valid_tokens:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    _touch_token(token)
    return token


def _require_token_ws(token: Optional[str] = None) -> str:
    """WebSocket 版 token 验证：从查询参数读取 token。

    浏览器 WebSocket API 不支持自定义请求头，因此只能走 query。
    """
    if not token:
        raise HTTPException(status_code=401, detail="未登录")
    _clean_expired()
    if token not in _valid_tokens:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    _touch_token(token)
    return token


verify_token = Depends(_require_token)
verify_token_ws = Depends(_require_token_ws)


# ---------- 路由 ----------

@router.post("/login")
async def login(body: dict, session: AsyncSession = Depends(get_session)):
    """登录接口。请求体：{"username": "...", "password": "..."}"""
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
    _save_tokens(force=True)
    logger.info(f"用户 '{username}' 已登录")
    return {"token": token, "username": username, "expires_in": TOKEN_EXPIRE_SECONDS}


@router.post("/logout")
async def logout(authorization: Optional[str] = Header(None)):
    """登出：撤销当前 token。未携带有效 token 也返回成功（幂等）。"""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if _valid_tokens.pop(token, None) is not None:
            _save_tokens(force=True)
            logger.info("用户已登出")
    return {"success": True, "message": "已登出"}


@router.get("/status")
async def auth_status(token: str = Depends(_require_token)):
    return {"authenticated": True}


@router.get("/info")
async def auth_info(token: str = Depends(_require_token),
                    session: AsyncSession = Depends(get_session)):
    """获取当前登录用户信息"""
    result = await session.execute(select(PanelUser).limit(1))
    user = result.scalar_one_or_none()
    return {"username": user.username if user else "admin"}
