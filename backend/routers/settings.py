"""
面板设置 API
允许修改登录用户名和密码。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import PanelUser
from backend.utils import verify_password, hash_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["面板设置"])


@router.put("/credentials")
async def update_credentials(body: dict, session: AsyncSession = Depends(get_session)):
    """
    修改用户名和/或密码。
    请求体：{ "current_password": "...", "new_username": "...", "new_password": "..." }
    至少提供 new_username 或 new_password 之一。
    current_password 用于验证身份。
    """
    current_password = body.get("current_password", "")
    new_username = body.get("new_username", "").strip()
    new_password = body.get("new_password", "")

    # 获取当前用户（取第一个）
    result = await session.execute(select(PanelUser).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=500, detail="用户数据不存在")

    # 验证当前密码
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="当前密码错误")

    changed = []

    # 修改用户名
    if new_username and new_username != user.username:
        # 检查新用户名是否已被占用
        exist = await session.execute(
            select(PanelUser).where(PanelUser.username == new_username)
        )
        if exist.scalar_one_or_none() and new_username != user.username:
            raise HTTPException(status_code=409, detail="用户名已被占用")
        user.username = new_username
        changed.append("用户名")

    # 修改密码
    if new_password:
        user.password_hash = hash_password(new_password)
        changed.append("密码")

    if not changed:
        raise HTTPException(status_code=400, detail="未提供任何修改内容")

    await session.commit()

    # 修改密码后撤销其它会话的登录态，避免旧 token 继续可用。
    # 当前请求自身的 token 无法在此获取（依赖项只挂了 verify_token），
    # 因此全部撤销，用户需重新登录一次 —— 安全性优先。
    if new_password:
        from backend.routers import auth
        revoked = auth.revoke_all_tokens()
        if revoked:
            logger.info(f"密码已变更，撤销了 {revoked} 个登录态")

    logger.info(f"用户设置已更新: {', '.join(changed)}")
    return {
        "success": True,
        "message": f"{'、'.join(changed)}已更新",
        "username": user.username,
        "reauth_required": bool(new_password),
    }
