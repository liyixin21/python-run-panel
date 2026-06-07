"""
WebSocket 终端 API 路由
基于 xterm.js 前端的全双工 Web 终端，后端使用 PTY 伪终端。
"""
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select

from backend.database import async_session
from backend.models import Project
from backend.services.terminal_manager import terminal_manager
from backend.routers.auth import verify_token_ws

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Web终端"])


@router.websocket("/ws/terminal/{project_id}")
async def websocket_terminal(
    websocket: WebSocket,
    project_id: int,
    token: str = verify_token_ws,
):
    """
    WebSocket 全双工终端端点。
    前端通过 xterm.js 建立连接，后端创建 PTY 并桥接数据流。
    认证 token 通过 URL 查询参数（?token=xxx）传递，因为浏览器 WebSocket API 不支持自定义请求头。
    """
    # 验证项目是否存在
    async with async_session() as session:
        result = await session.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            await websocket.close(code=4004, reason="项目不存在")
            return

    await websocket.accept()
    logger.info(f"WebSocket 终端连接建立: project_id={project_id}")

    try:
        session = await terminal_manager.create_session(
            project.name, websocket, cols=80, rows=24
        )

        # 主循环：接收前端输入
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")

            if msg_type == "input":
                # 用户键盘输入
                input_data = msg.get("data", "")
                await session.write(input_data.encode("utf-8"))
            elif msg_type == "resize":
                # 终端窗口大小变化
                cols = msg.get("cols", 80)
                rows = msg.get("rows", 24)
                await session.resize(cols, rows)

    except Exception as e:
        logger.error(f"WebSocket 终端异常: {e}")
    finally:
        await terminal_manager.remove_session(project.name)
        logger.info(f"WebSocket 终端连接关闭: project_id={project_id}")
