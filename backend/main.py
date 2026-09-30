"""
FastAPI 应用入口文件
- 初始化数据库
- 注册所有路由
- 挂载静态文件（前端构建产物）
"""
import asyncio
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import STATIC_DIR, WORKSPACE_DIR, CORS_ORIGINS
from backend.database import init_db
from backend.services.process_manager import process_manager
from backend.utils import resolve_static
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

    # 自动启动配置了 auto_start 的项目
    asyncio.create_task(_auto_start_projects())

    yield

    logger.info("应用已关闭")


async def _auto_start_projects():
    """面板启动后，自动启动所有配置了 auto_start=True 的项目"""
    try:
        from backend.models import Project
        from backend.database import async_session
        from sqlalchemy import select

        async with async_session() as session:
            result = await session.execute(
                select(Project).where(Project.auto_start == True)
            )
            projects = result.scalars().all()

        if not projects:
            return

        logger.info(f"正在自动启动 {len(projects)} 个项目...")
        for project in projects:
            try:
                result = await process_manager.start_process(
                    project_id=project.id,
                    project_name=project.name,
                    entry_file=project.entry_file,
                    port=project.port,
                    auto_restart=project.auto_restart or False,
                    start_cmd=project.start_cmd or "",
                )
                if result["success"]:
                    logger.info(f"  项目 '{project.name}' 已自动启动 (PID={result.get('pid')})")
                else:
                    logger.warning(f"  项目 '{project.name}' 自动启动失败: {result.get('message')}")
            except Exception as e:
                logger.error(f"  项目 '{project.name}' 自动启动异常: {e}")
        logger.info("自动启动完成")
    except Exception as e:
        logger.error(f"自动启动项目失败: {e}")


app = FastAPI(
    title="Python Run Panel",
    description="基于 Web 的容器化 Python 项目托管与进程管理面板",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：仅在显式配置了 CORS_ORIGINS 时启用。
# 前端与后端同源部署时无需 CORS；且 allow_origins=["*"] 与 allow_credentials=True
# 是浏览器明确拒绝的组合，配置了也不会生效。
if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"CORS 已启用，允许来源: {CORS_ORIGINS}")

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
async def websocket_logs(websocket: WebSocket, identifier: str, token: str = Query(None)):
    """WebSocket 实时日志推送：前端通过此端点接收进程日志流。

    token 通过查询参数传入（浏览器 WebSocket API 不支持自定义请求头），
    与 /ws/terminal 使用同一套校验逻辑。
    """
    from backend.routers.auth import _require_token_ws

    try:
        _require_token_ws(token)
    except Exception:
        # 未认证：拒绝握手，避免日志内容外泄
        await websocket.close(code=4401, reason="未登录")
        return

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
        """优先返回静态文件，匹配不到则返回 index.html 用于前端路由。

        所有路径都经 resolve_static 做边界校验。越出 STATIC_DIR 的请求
        （含 %2f 编码的目录穿越）直接 404，不回落到 index.html，
        避免攻击探测被伪装成正常的 SPA 路由。
        """
        target, escaped = resolve_static(static_dir, path)
        if escaped:
            logger.warning(f"拦截静态目录穿越尝试: {path!r}")
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        if target:
            return FileResponse(target)
        # API/WS 前缀不应落到 SPA 页面
        if path.startswith("api/") or path.startswith("ws/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(os.path.join(static_dir, "index.html"))

    logger.info(f"静态文件目录已配置: {static_dir}")
else:
    logger.warning(
        f"静态文件目录不存在: {static_dir} —— 前端页面将无法访问。"
        "请在 frontend/ 下执行 `npm run build` 生成静态资源。"
    )
