"""
数据库引擎与会话工厂
使用 SQLAlchemy 2.0 异步风格，基于 aiosqlite 驱动。
启动时自动检测并迁移旧表结构，保证老数据可用。
"""
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from backend.config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """初始化数据库：建表 + 迁移旧表结构 + 创建默认管理员"""
    from backend.models import Project, Schedule, PanelUser

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)
        await _create_default_user(conn)


async def _migrate_schema(conn):
    """检测并修复表结构变更，兼容旧数据"""
    try:
        result = await conn.execute(text("PRAGMA table_info(projects)"))
        rows = result.all()
        columns = {r[1] for r in rows}

        if "description" in columns:
            logger.info("检测到旧 description 列，正在迁移...")
            await conn.run_sync(
                lambda sync_conn: sync_conn.execute(text("ALTER TABLE projects RENAME TO projects_old"))
            )
            # 用 sync 连接重建新表（Base.metadata 已注册）
            cols_without_desc = [c for c in columns if c != "description"]
            cols_str = ", ".join(cols_without_desc)
            await conn.execute(text(
                f"INSERT INTO projects ({cols_str}) SELECT {cols_str} FROM projects_old"
            ))
            await conn.execute(text("DROP TABLE projects_old"))
            logger.info("description 列已移除，数据已保留")

            # 重新获取列
            result = await conn.execute(text("PRAGMA table_info(projects)"))
            rows = result.all()
            columns = {r[1] for r in rows}

        if "start_cmd" not in columns:
            logger.info("正在添加 start_cmd 列...")
            await conn.execute(text(
                "ALTER TABLE projects ADD COLUMN start_cmd VARCHAR(512) DEFAULT '' NOT NULL"
            ))
            logger.info("start_cmd 列已添加")
    except Exception as e:
        logger.warning(f"数据库迁移失败 (非致命): {e}")


async def _create_default_user(conn):
    """如果 panel_users 表为空，则创建默认管理员 admin/admin"""
    from sqlalchemy import select
    from backend.models import PanelUser
    from backend.config import PANEL_PASSWORD

    result = await conn.execute(select(PanelUser).limit(1))
    if result.scalar_one_or_none() is None:
        from backend.utils import hash_password
        default_hash = hash_password(PANEL_PASSWORD)
        await conn.execute(
            text("INSERT INTO panel_users (username, password_hash, created_at) VALUES (:u, :p, :t)"),
            {"u": "admin", "p": default_hash, "t": datetime.utcnow()},
        )
        logger.info(f"已创建默认管理员 (用户名: admin)")


async def get_session() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
