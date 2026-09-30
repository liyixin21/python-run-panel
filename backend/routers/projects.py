"""
项目管理 API 路由
提供项目的完整 CRUD 操作以及与定时配置的管理。
支持通过数字 ID 或项目名称查找项目。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, field_validator

from backend.database import get_session
from backend.models import Project
from backend.services.project_manager import project_manager, ProjectExistsError
from backend.services.process_manager import process_manager
from backend.utils import validate_project_name, PathSecurityError, iso_utc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        try:
            return validate_project_name(v)
        except ValueError as e:
            raise ValueError(str(e))


class ProjectUpdateRequest(BaseModel):
    entry_file: str | None = Field(None, max_length=256)
    start_cmd: str | None = Field(None, max_length=512)
    auto_restart: bool | None = Field(None)
    auto_start: bool | None = Field(None)


class ProjectResponse(BaseModel):
    id: int
    name: str
    directory: str
    venv_path: str
    entry_file: str
    start_cmd: str
    port: int | None
    auto_restart: bool
    auto_start: bool
    status: str
    pid: int | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


def _make_response(project: Project) -> dict:
    status_info = process_manager.get_process_status(project.id)
    return {
        "id": project.id,
        "name": project.name,
        "directory": project.directory,
        "venv_path": project.venv_path,
        "entry_file": project.entry_file,
        "start_cmd": project.start_cmd or "",
        "port": project.port,
        "auto_restart": bool(project.auto_restart),
        "auto_start": bool(project.auto_start),
        "status": "running" if status_info["running"] else "stopped",
        "pid": status_info["pid"],
        # 带时区标记输出，避免前端按本地时间解析造成偏差
        "created_at": iso_utc(project.created_at),
        "updated_at": iso_utc(project.updated_at),
    }


async def _get_project(session, identifier: str) -> Project:
    """通过名称或数字 ID 查找项目（优先按名称查找）"""
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
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Project).order_by(Project.created_at.desc()))
    return [_make_response(p) for p in result.scalars().all()]


@router.post("/", response_model=ProjectResponse)
async def create_project(req: ProjectCreateRequest, session: AsyncSession = Depends(get_session)):
    """创建项目。

    整个「检查 → 建目录/venv → 落库」流程按项目名加锁串行化，
    避免并发同名请求各自建完 venv 后撞唯一约束（曾导致 500 与无主目录）。
    数据库唯一约束仍是最后防线，冲突时回滚已落盘的文件并返回 409。
    """
    async with project_manager.lock_for(req.name):
        existing = await session.execute(select(Project).where(Project.name == req.name))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="项目名称已存在")

        try:
            meta = await project_manager.create_project(req.name)
        except ProjectExistsError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except PathSecurityError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))

        project = Project(
            name=meta["name"], directory=meta["directory"], venv_path=meta["venv_path"]
        )
        session.add(project)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # 竞态兜底：目录已建但记录未落库，清理避免留下孤立目录
            try:
                project_manager.delete_project(req.name)
            except Exception as e:
                logger.warning(f"清理并发创建产生的目录失败: {e}")
            raise HTTPException(status_code=409, detail="项目名称已被占用，请刷新后重试")

        await session.refresh(project)
        return _make_response(project)


@router.get("/{identifier}", response_model=ProjectResponse)
async def get_project(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return _make_response(project)


@router.put("/{identifier}", response_model=ProjectResponse)
async def update_project(identifier: str, req: ProjectUpdateRequest,
                         session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    if req.entry_file is not None:
        project.entry_file = req.entry_file
    if req.start_cmd is not None:
        project.start_cmd = req.start_cmd
    if req.auto_restart is not None:
        project.auto_restart = req.auto_restart
    if req.auto_start is not None:
        project.auto_start = req.auto_start

    await session.commit()
    await session.refresh(project)
    return _make_response(project)


@router.delete("/{identifier}")
async def delete_project(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    # 先停进程并等待其真正退出，避免 rmtree 与退出中的进程争抢文件
    await process_manager.stop_process(project.id, force=True, wait=True)
    # 回收进程记录，防止 ProcessRecord（含日志缓冲）长期驻留
    process_manager.forget_process(project.id)

    try:
        project_manager.delete_project(project.name)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    await session.delete(project)
    await session.commit()

    return {"success": True, "message": "项目已删除"}
