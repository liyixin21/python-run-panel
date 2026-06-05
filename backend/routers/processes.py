"""
进程管理 API 路由
提供项目的进程启动、停止、重启、状态查询、日志获取和实时日志推送功能。
支持通过数字 ID 或项目名称查找项目。
"""
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from backend.database import get_session
from backend.models import Project
from backend.services.process_manager import process_manager

router = APIRouter(prefix="/api/processes", tags=["进程管理"])


class ProcessStartRequest(BaseModel):
    entry_file: str = "main.py"
    start_cmd: str = ""
    auto_restart: bool = False


async def _get_project(session, identifier: str) -> Project:
    if identifier.isdigit():
        q = select(Project).where(Project.id == int(identifier))
    else:
        q = select(Project).where(Project.name == identifier)
    result = await session.execute(q)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/{identifier}/start")
async def start_process_ep(identifier: str, req: ProcessStartRequest = ProcessStartRequest(),
                           session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return await process_manager.start_process(
        project.id, project.name,
        entry_file=req.entry_file or project.entry_file,
        port=project.port,
        auto_restart=req.auto_restart,
        start_cmd=req.start_cmd or project.start_cmd or "",
    )


@router.post("/{identifier}/stop")
async def stop_process_ep(identifier: str, force: bool = False,
                          session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return await process_manager.stop_process(project.id, force=force)


@router.post("/{identifier}/restart")
async def restart_process_ep(identifier: str, req: ProcessStartRequest = ProcessStartRequest(),
                             session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return await process_manager.restart_process(
        project.id, project.name,
        entry_file=req.entry_file or project.entry_file,
        port=project.port,
        auto_restart=req.auto_restart,
        start_cmd=req.start_cmd or project.start_cmd or "",
    )


@router.get("/{identifier}/status")
async def get_status(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return process_manager.get_process_status(project.id)


@router.get("/{identifier}/logs")
async def get_logs(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    return {"logs": process_manager.get_process_logs(project.id)}
