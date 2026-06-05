"""
项目管理 API 路由
提供项目的完整 CRUD 操作以及与定时配置的管理。
支持通过数字 ID 或项目名称查找项目。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.database import get_session
from backend.models import Project, ProjectStatus, Schedule
from backend.services.project_manager import project_manager
from backend.services.process_manager import process_manager

router = APIRouter(prefix="/api/projects", tags=["项目管理"])


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ProjectUpdateRequest(BaseModel):
    entry_file: str | None = Field(None, max_length=256)
    start_cmd: str | None = Field(None, max_length=512)
    auto_restart: bool | None = Field(None)


class ScheduleRequest(BaseModel):
    cron_start: str | None = Field(None)
    cron_stop: str | None = Field(None)


class ProjectResponse(BaseModel):
    id: int
    name: str
    directory: str
    venv_path: str
    entry_file: str
    start_cmd: str
    port: int | None
    auto_restart: bool
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
        "auto_restart": project.auto_restart,
        "status": "running" if status_info["running"] else "stopped",
        "pid": status_info["pid"],
        "created_at": project.created_at.isoformat() if project.created_at else "",
        "updated_at": project.updated_at.isoformat() if project.updated_at else "",
    }


async def _get_project(session, identifier: str) -> Project:
    """通过名称或数字 ID 查找项目"""
    if identifier.isdigit():
        q = select(Project).where(Project.id == int(identifier))
    else:
        q = select(Project).where(Project.name == identifier)
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
    existing = await session.execute(select(Project).where(Project.name == req.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="项目名称已存在")

    try:
        meta = await project_manager.create_project(req.name)
    except FileExistsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    project = Project(name=meta["name"], directory=meta["directory"], venv_path=meta["venv_path"])
    session.add(project)
    await session.commit()
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

    await session.commit()
    await session.refresh(project)
    return _make_response(project)


@router.delete("/{identifier}")
async def delete_project(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    await process_manager.stop_process(project.id, force=True)

    schedules_result = await session.execute(
        select(Schedule).where(Schedule.project_id == project.id)
    )
    for schedule in schedules_result.scalars().all():
        process_manager.remove_cron_job(f"sched_{schedule.job_type}_{project.id}")
        await session.delete(schedule)

    project_manager.delete_project(project.name)
    await session.delete(project)
    await session.commit()

    return {"success": True, "message": "项目已删除"}


@router.get("/{identifier}/schedules")
async def get_schedules(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    result = await session.execute(
        select(Schedule).where(Schedule.project_id == project.id)
    )
    return [
        {"id": s.id, "job_type": s.job_type, "cron_expression": s.cron_expression, "enabled": s.enabled}
        for s in result.scalars().all()
    ]


@router.post("/{identifier}/schedules")
async def set_schedules(identifier: str, req: ScheduleRequest,
                        session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    old_schedules = await session.execute(
        select(Schedule).where(Schedule.project_id == project.id)
    )
    for old in old_schedules.scalars().all():
        process_manager.remove_cron_job(f"sched_{old.job_type}_{project.id}")
        await session.delete(old)

    if not req.cron_start and not req.cron_stop:
        await session.commit()
        return {"success": True, "schedules": []}

    created = []

    if req.cron_start:
        try:
            process_manager.add_cron_job(
                project_id=project.id, project_name=project.name,
                cron_expression=req.cron_start, job_type="start",
                entry_file=project.entry_file, port=project.port,
                start_cmd=project.start_cmd or "",
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"定时启动配置失败: {str(e)}")
        schedule = Schedule(project_id=project.id, job_type="start",
                           cron_expression=req.cron_start, enabled=True)
        session.add(schedule)
        created.append({"job_type": "start", "cron": req.cron_start})

    if req.cron_stop:
        try:
            process_manager.add_cron_job(
                project_id=project.id, project_name=project.name,
                cron_expression=req.cron_stop, job_type="stop",
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"定时关闭配置失败: {str(e)}")
        schedule = Schedule(project_id=project.id, job_type="stop",
                           cron_expression=req.cron_stop, enabled=True)
        session.add(schedule)
        created.append({"job_type": "stop", "cron": req.cron_stop})

    await session.commit()
    return {"success": True, "schedules": created}
