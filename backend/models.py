"""
SQLAlchemy ORM 模型定义
- PanelUser：面板登录用户（用户名 + 密码哈希）
- Project：项目元数据（名称、目录、虚拟环境、启动命令等）

时间字段统一存储 naive UTC，序列化时由 utils.iso_utc 补上时区标记。
"""
import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Enum, Boolean

from backend.database import Base
from backend.utils import utcnow


class ProjectStatus(str, enum.Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
    STARTING = "starting"


class PanelUser(Base):
    """面板登录用户"""
    __tablename__ = "panel_users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, comment="登录用户名")
    password_hash = Column(String(256), nullable=False, comment="PBKDF2 密码哈希")
    created_at = Column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False, comment="项目名称")
    directory = Column(String(512), nullable=False, comment="项目文件夹绝对路径")
    venv_path = Column(String(512), nullable=False, comment="虚拟环境绝对路径")
    entry_file = Column(String(256), default="main.py", comment="入口脚本文件名")
    start_cmd = Column(String(512), default="", comment="自定义启动命令，为空时使用 entry_file")
    port = Column(Integer, nullable=True, comment="进程监听的端口号")
    status = Column(Enum(ProjectStatus), default=ProjectStatus.STOPPED, nullable=False)
    pid = Column(Integer, nullable=True)
    auto_restart = Column(Boolean, default=False, comment="进程意外退出时是否自动重启")
    auto_start = Column(Boolean, default=False, comment="面板启动时是否自动启动项目")
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
