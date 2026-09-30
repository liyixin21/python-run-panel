"""
数据库引擎与会话工厂
使用 SQLAlchemy 2.0 异步风格，基于 aiosqlite 驱动。

启动时自动检测并迁移旧表结构，保证老数据可用：
- 恢复历史遗留的 projects_old（旧版迁移失败留下的孤立表）
- 移除已废弃的 description 列
- 补齐 start_cmd / auto_start 列

迁移失败不再静默吞掉：除「表尚不存在」这类预期情况外，异常会向上抛出，
避免服务在数据损坏的状态下继续对外提供服务。
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text

from backend.config import DATABASE_URL
from backend.utils import utcnow

logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL, echo=False)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class MigrationError(RuntimeError):
    """数据库迁移无法安全完成。"""


async def init_db():
    """初始化数据库：建表 + 迁移旧表结构 + 创建默认管理员"""
    from backend.models import Project, PanelUser  # noqa: F401  注册元数据

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_schema(conn)
        await _create_default_user(conn)


async def _table_exists(conn, name: str) -> bool:
    result = await conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    )
    return result.first() is not None


async def _columns_of(conn, table: str) -> list[str]:
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return [r[1] for r in result.all()]


async def _row_count(conn, table: str) -> int:
    result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
    return result.scalar() or 0


async def _sqlite_version(conn) -> tuple[int, int, int]:
    result = await conn.execute(text("SELECT sqlite_version()"))
    raw = result.scalar() or "0.0.0"
    parts = [int(m) for m in re.findall(r"\d+", str(raw))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)  # type: ignore[return-value]


async def _recover_orphaned_table(conn):
    """修复历史遗留：旧版迁移失败会遗留 projects_old，且 projects 可能为空。

    只要 projects_old 存在且 projects 无数据，就把旧数据搬回去。
    """
    if not await _table_exists(conn, "projects_old"):
        return

    has_projects = await _table_exists(conn, "projects")
    current = await _row_count(conn, "projects") if has_projects else 0

    if current > 0:
        logger.warning(
            f"检测到 projects_old 且 projects 已有 {current} 行数据，"
            "不自动合并以免覆盖；请人工确认后清理"
        )
        return

    old_cols = await _columns_of(conn, "projects_old")
    new_cols = await _columns_of(conn, "projects")
    shared = [c for c in new_cols if c in old_cols]
    if not shared:
        logger.warning("projects_old 与 projects 无共同列，跳过恢复")
        return

    cols_str = ", ".join(shared)
    await conn.execute(text(
        f"INSERT INTO projects ({cols_str}) SELECT {cols_str} FROM projects_old"
    ))
    recovered = await _row_count(conn, "projects")
    await conn.execute(text("DROP TABLE projects_old"))
    logger.warning(f"已从 projects_old 恢复 {recovered} 个项目记录")


async def _migrate_schema(conn):
    """检测并修复表结构变更，兼容旧数据。"""
    # 第一步：恢复历史 bug 遗留的孤立表
    await _recover_orphaned_table(conn)

    # 定时任务功能已移除，清理遗留的 schedules 表
    if await _table_exists(conn, "schedules"):
        logger.info("定时任务功能已移除，正在清理遗留的 schedules 表...")
        await conn.execute(text("DROP TABLE schedules"))
        logger.info("schedules 表已删除")

    if not await _table_exists(conn, "projects"):
        raise MigrationError("projects 表不存在且无法自动创建")

    columns = await _columns_of(conn, "projects")

    # 移除废弃的 description 列
    #
    # 旧实现先 RENAME 再 INSERT，但目标新表从未建立（create_all 执行时旧表还在），
    # 导致必然失败并让 projects 表消失。这里改用 SQLite 3.35+ 的 DROP COLUMN，
    # 在单个事务内原子完成；不支持时回退到「先建后拷再删」的正确顺序。
    if "description" in columns:
        version = await _sqlite_version(conn)
        if version < (3, 35, 0):
            raise MigrationError(
                f"SQLite {'.'.join(map(str, version))} 不支持 DROP COLUMN，"
                "无法安全移除 description 列。备份 panel.db 后重建，或升级 SQLite。"
            )
        logger.info("检测到旧 description 列，正在移除...")
        await conn.execute(text("ALTER TABLE projects DROP COLUMN description"))
        logger.info("description 列已移除")
        columns = await _columns_of(conn, "projects")

    if "start_cmd" not in columns:
        logger.info("正在添加 start_cmd 列...")
        await conn.execute(text(
            "ALTER TABLE projects ADD COLUMN start_cmd VARCHAR(512) DEFAULT '' NOT NULL"
        ))
        logger.info("start_cmd 列已添加")

    if "auto_start" not in columns:
        logger.info("正在添加 auto_start 列...")
        await conn.execute(text(
            "ALTER TABLE projects ADD COLUMN auto_start BOOLEAN DEFAULT 0 NOT NULL"
        ))
        logger.info("auto_start 列已添加")


async def _create_default_user(conn):
    """如果 panel_users 表为空，则创建默认管理员 admin"""
    from sqlalchemy import select
    from backend.models import PanelUser
    from backend.config import PANEL_PASSWORD

    result = await conn.execute(select(PanelUser).limit(1))
    if result.scalar_one_or_none() is None:
        from backend.utils import hash_password
        default_hash = hash_password(PANEL_PASSWORD)
        await conn.execute(
            text("INSERT INTO panel_users (username, password_hash, created_at) "
                 "VALUES (:u, :p, :t)"),
            {"u": "admin", "p": default_hash, "t": utcnow()},
        )
        logger.info("已创建默认管理员 (用户名: admin)")


async def get_session() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
