"""
FastAPI 应用入口文件
- 初始化数据库、调度器
- 注册所有路由
- 挂载静态文件（前端构建产物）
"""
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import STATIC_DIR, WORKSPACE_DIR
from backend.database import init_db
from backend.services.process_manager import process_manager
from backend.routers import projects, processes, files, terminal, packages, auth, settings, firewall

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理：
    - 启动时：创建 workspace 目录、初始化数据库、启动调度器
    - 关闭时：关闭调度器
    """
    # 启动阶段
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    logger.info(f"工作区目录: {WORKSPACE_DIR}")

    await init_db()
    logger.info("数据库已初始化")

    process_manager.init_scheduler()
    logger.info("APScheduler 调度器已启动")

    yield

    # 关闭阶段
    process_manager.shutdown_scheduler()
    logger.info("应用已关闭")


app = FastAPI(
    title="Python Run Panel",
    description="基于 Web 的容器化 Python 项目托管与进程管理面板",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件（开发时允许跨域，生产环境中前端与后端同源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 API 路由
# 认证路由无需鉴权
app.include_router(auth.router)

# 业务路由需要登录验证
app.include_router(projects.router, dependencies=[auth.verify_token])
app.include_router(processes.router, dependencies=[auth.verify_token])
app.include_router(files.router, dependencies=[auth.verify_token])
app.include_router(packages.router, dependencies=[auth.verify_token])
app.include_router(terminal.router)
app.include_router(settings.router, dependencies=[auth.verify_token])
app.include_router(firewall.router, dependencies=[auth.verify_token])


# WebSocket 实时日志推送端点（必须在 StaticFiles mount 之前注册）
@app.websocket("/ws/logs/{identifier}")
async def websocket_logs(websocket: WebSocket, identifier: str):
    """WebSocket 实时日志推送：前端通过此端点接收进程日志流"""
    # 通过名称或数字ID查找项目
    from backend.database import async_session
    from backend.models import Project
    from sqlalchemy import select
    
    async with async_session() as session:
        # 优先按名称查找
        q = select(Project).where(Project.name == identifier)
        result = await session.execute(q)
        project = result.scalar_one_or_none()
        
        # 如果按名称找不到，且是纯数字，则尝试按ID查找
        if not project and identifier.isdigit():
            q = select(Project).where(Project.id == int(identifier))
            result = await session.execute(q)
            project = result.scalar_one_or_none()
    
    if not project:
        await websocket.close(code=4004, reason="项目不存在")
        return
    
    project_id = project.id
    await websocket.accept()
    await process_manager.subscribe_logs(project_id, websocket)
    try:
        while True:
            try:
                await websocket.receive_text()
            except WebSocketDisconnect:
                break
    except Exception:
        pass
    finally:
        process_manager.unsubscribe_logs(project_id, websocket)


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "python-run-panel"}


# 前端 SPA 静态文件服务（必须在所有 API 路由之后注册，作为兜底）
static_dir = STATIC_DIR
if os.path.isdir(static_dir):
    @app.get("/{path:path}")
    async def serve_spa(path: str):
        """优先返回静态文件，匹配不到则返回 index.html 用于前端路由"""
        file_path = os.path.join(static_dir, path)
        if path and os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(static_dir, "index.html"))
    logger.info(f"静态文件目录已配置: {static_dir}")
else:
    logger.warning(f"静态文件目录不存在: {static_dir}")
