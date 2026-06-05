"""
依赖管理 API 路由
提供 requirements.txt 安装和手动包管理功能。
支持通过数字 ID 或项目名称查找项目。
"""
from fastapi import APIRouter, Depends, HTTPException
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
    if identifier.isdigit():
        q = select(Project).where(Project.id == int(identifier))
    else:
        q = select(Project).where(Project.name == identifier)
    result = await session.execute(q)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


@router.post("/{identifier}/install-requirements")
async def install_requirements(identifier: str, session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        return await project_manager.install_requirements(project.name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{identifier}/install")
async def install_package(identifier: str, req: InstallPackageRequest,
                          session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        return await project_manager.install_package(project.name, req.package_name)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


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
