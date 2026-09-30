"""
文件管理 API 路由
支持通过数字 ID 或项目名称查找项目。

所有路径校验统一走 utils.safe_join（基于 os.path.commonpath 按分量比较），
修复了此前 startswith 前缀匹配导致的越权：
"/w/1_secret" 曾被误判为位于 "/w/1" 之内。
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
from backend.utils import safe_join, PathSecurityError

router = APIRouter(prefix="/api/files", tags=["文件管理"])


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


def _resolve(project_dir: str, *parts: str) -> str:
    """在项目目录内安全解析路径，越界则 403。"""
    try:
        return safe_join(project_dir, *parts)
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/{identifier}/list")
async def list_files(identifier: str, sub_path: str = "",
                     session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)
    try:
        entries = project_manager.list_project_files(project.name, sub_path)
        return {"files": entries}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PathSecurityError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/{identifier}/upload")
async def upload_files(identifier: str,
                       files: List[UploadFile] = File(..., description="待上传的文件列表"),
                       sub_path: str = Query(""),
                       session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    target_dir = _resolve(project_dir, sub_path) if sub_path else project_dir

    os.makedirs(target_dir, exist_ok=True)

    results = []
    has_requirements = False

    for file in files:
        safe_filename = os.path.basename(file.filename or "unnamed")
        if not safe_filename:
            continue

        # 从 FormData 的 filename 中提取目录结构（如 "MyFolder/sub/file.txt"）
        upload_rel_path = (file.filename or "").replace("\\", "/")
        sub_dir = os.path.dirname(upload_rel_path)
        if sub_dir:
            # 逐级校验：任何一级越界都跳过该文件
            try:
                nested_target = safe_join(target_dir, sub_dir)
            except PathSecurityError:
                results.append({
                    "success": False, "filename": safe_filename,
                    "error": "路径越界，已拒绝",
                })
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

    return {"success": True, "has_requirements": has_requirements,
            "files": results, "total": len(results)}


@router.post("/{identifier}/mkdir")
async def create_directory(identifier: str, dir_name: str = Query(...),
                           sub_path: str = Query(""),
                           session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    target_dir = _resolve(project_dir, sub_path) if sub_path else project_dir
    real_target = _resolve(target_dir, dir_name)

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
    real_target = _resolve(project_dir, file_path)

    if os.path.realpath(real_target) == os.path.realpath(project_dir):
        raise HTTPException(status_code=400, detail="不允许删除项目根目录")

    try:
        if os.path.isdir(real_target):
            shutil.rmtree(real_target)
        else:
            os.remove(real_target)
        return {"success": True, "message": "已删除"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@router.get("/{identifier}/read")
async def read_file_content(identifier: str, file_path: str = Query(...),
                            session: AsyncSession = Depends(get_session)):
    project = await _get_project(session, identifier)

    project_dir = project_manager._get_project_dir(project.name)
    real_target = _resolve(project_dir, file_path)

    if os.path.isdir(real_target):
        raise HTTPException(status_code=400, detail="不能读取目录")

    try:
        with open(real_target, "r", encoding="utf-8") as f:
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
    real_target = _resolve(project_dir, file_path)

    # 禁止把目录当作文件写入
    if os.path.isdir(real_target):
        raise HTTPException(status_code=400, detail="目标是目录，无法写入")

    try:
        # 目标父目录必须仍在项目内（real_target 已校验，此处确保不存在符号链接逃逸）
        parent = os.path.dirname(real_target)
        if not os.path.isdir(parent):
            raise HTTPException(status_code=404, detail="目标目录不存在")
        with open(real_target, "w", encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "message": "文件已保存"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败: {str(e)}")
