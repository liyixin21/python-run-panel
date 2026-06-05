"""
SQLAlchemy ORM 模型定义
- Project：项目元数据（名称、目录、虚拟环境、启动命令等）
- Schedule：定时任务配置（cron 启动/关闭表达式）
"""
import enum
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, Enum, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from backend.database import Base


class ProjectStatus(str, enum.Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    ERROR = "error"
    STARTING = "starting"


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    schedules = relationship("Schedule", back_populates="project", cascade="all, delete-orphan")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    job_type = Column(String(32), nullable=False, comment="任务类型: start / stop")
    cron_expression = Column(String(128), nullable=False, comment="Cron 表达式，例如 0 8 * * *")
    enabled = Column(Boolean, default=True, comment="是否启用")

    project = relationship("Project", back_populates="schedules")
