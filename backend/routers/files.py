"""
文件管理 API 路由
支持通过数字 ID 或项目名称查找项目。
"""
import os
import shutil
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models import Project
from backend.services.project_manager import project_manager

router = APIRouter(prefix="/api/files", tags=["文件管理"])


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


@router.get("/{identifier}/list")
async def list_files(identifier: str, sub_path: str = "",
                     session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        entries = project_manager.list_project_files(project.name, sub_path)
        return {"files": entries}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{identifier}/upload")
async def upload_files(identifier: str,
                       files: List[UploadFile] = File(..., description="待上传的文件列表"),
                       sub_path: str = Query(""),
                       session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    target_dir = os.path.join(project_dir, sub_path) if sub_path else project_dir

    real_target = os.path.realpath(target_dir)
    real_project = os.path.realpath(project_dir)
    if not real_target.startswith(real_project):
        raise HTTPException(status_code=403, detail="禁止访问项目目录之外的文件")

    os.makedirs(target_dir, exist_ok=True)

    results = []
    has_requirements = False

    for file in files:
        safe_filename = os.path.basename(file.filename or "unnamed")
        if not safe_filename:
            continue

        # 从 FormData 的 filename 中提取目录结构（如 "MyFolder/sub/file.txt"）
        upload_rel_path = file.filename or ""
        if '/' in upload_rel_path:
            sub_dir = os.path.dirname(upload_rel_path)
            nested_target = os.path.join(target_dir, sub_dir)
            real_nested = os.path.realpath(nested_target)
            if not real_nested.startswith(real_project):
                continue
            os.makedirs(nested_target, exist_ok=True)
            file_path = os.path.join(nested_target, safe_filename)
        else:
            file_path = os.path.join(target_dir, safe_filename)

        try:
            content = await file.read()
            with open(file_path, "wb") as f:
                f.write(content)
        except Exception as e:
            results.append({"success": False, "filename": safe_filename, "error": str(e)})
            continue

        if safe_filename.lower() == "requirements.txt":
            has_requirements = True

        results.append({
            "success": True, "filename": safe_filename,
            "path": os.path.relpath(file_path, project_dir), "size": len(content),
        })

    return {"success": True, "has_requirements": has_requirements, "files": results, "total": len(results)}


@router.post("/{identifier}/mkdir")
async def create_directory(identifier: str, dir_name: str = Query(...),
                           sub_path: str = Query(""),
                           session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    target_dir = os.path.join(project_dir, sub_path) if sub_path else project_dir

    real_target = os.path.realpath(os.path.join(target_dir, dir_name))
    real_project = os.path.realpath(project_dir)
    if not real_target.startswith(real_project):
        raise HTTPException(status_code=403, detail="禁止访问项目目录之外的文件")

    try:
        os.makedirs(real_target, exist_ok=True)
        return {"success": True, "path": os.path.relpath(real_target, project_dir)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建目录失败: {str(e)}")


@router.delete("/{identifier}/delete")
async def delete_file(identifier: str, file_path: str = Query(...),
                      session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    full_path = os.path.join(project_dir, file_path)

    real_target = os.path.realpath(full_path)
    real_project = os.path.realpath(project_dir)
    if not real_target.startswith(real_project):
        raise HTTPException(status_code=403, detail="禁止访问项目目录之外的文件")
    if real_target == real_project:
        raise HTTPException(status_code=400, detail="不允许删除项目根目录")

    try:
        if os.path.isdir(full_path):
            shutil.rmtree(full_path)
        else:
            os.remove(full_path)
        return {"success": True, "message": "已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/{identifier}/read")
async def read_file_content(identifier: str, file_path: str = Query(...),
                            session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    full_path = os.path.join(project_dir, file_path)

    real_target = os.path.realpath(full_path)
    real_project = os.path.realpath(project_dir)
    if not real_target.startswith(real_project):
        raise HTTPException(status_code=403, detail="禁止访问项目目录之外的文件")
    if os.path.isdir(real_target):
        raise HTTPException(status_code=400, detail="不能读取目录")

    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": os.path.basename(file_path)}
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="无法读取二进制文件")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {str(e)}")


@router.put("/{identifier}/write")
async def write_file_content(identifier: str,
                             file_path: str = Query(...),
                             request: Request = None,
                             session: AsyncSession = Depends(get_session)):
    content = await request.body()
    try:
        content = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件内容必须为 UTF-8 文本")

    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    full_path = os.path.join(project_dir, file_path)

    real_target = os.path.realpath(full_path)
    real_project = os.path.realpath(project_dir)
    if not real_target.startswith(real_project):
        raise HTTPException(status_code=403, detail="禁止访问项目目录之外的文件")

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "message": "文件已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {str(e)}")
