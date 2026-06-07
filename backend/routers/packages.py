"""
依赖管理 API 路由
提供 requirements.txt 安装和手动包管理功能。
支持通过数字 ID 或项目名称查找项目。
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.database import get_session
from backend.models import Project
from backend.services.project_manager import project_manager

router = APIRouter(prefix="/api/packages", tags=["依赖管理"])


class InstallPackageRequest(BaseModel):
    package_name: str = Field(..., min_length=1)


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


@router.post("/{identifier}/install-requirements")
async def install_requirements(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        async def event_stream():
            async for line in project_manager.stream_install_requirements(project.name):
                if line.startswith("__DONE__:"):
                    success = line == "__DONE__:True"
                    yield f"data: {json.dumps({'type': 'done', 'success': success})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'output', 'line': line})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"依赖安装异常: {str(e)}")


@router.post("/{identifier}/install")
async def install_package(identifier: str, req: InstallPackageRequest,
                          session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        async def event_stream():
            async for line in project_manager.stream_install_package(project.name, req.package_name):
                if line.startswith("__DONE__:"):
                    success = line == "__DONE__:True"
                    yield f"data: {json.dumps({'type': 'done', 'success': success})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'output', 'line': line})}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"包安装异常: {str(e)}")


@router.get("/{identifier}/installed")
async def get_installed_packages(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        return await project_manager.get_installed_packages(project.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{identifier}/uninstall")
async def uninstall_package(identifier: str, req: InstallPackageRequest,
                            session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        return await project_manager.uninstall_package(project.name, req.package_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
