# -*- coding: utf-8 -*-

"""PostgreSQL / SQLite 数据库引擎与会话。"""

from __future__ import annotations



from loguru import logger

from sqlalchemy import text

from sqlmodel import Session, SQLModel, create_engine



from app.config import get_settings



_engine = None

_active_database_url: str | None = None

_db_mode: str = "unknown"





def _sqlite_fallback_url() -> str:

    """PostgreSQL 不可用时使用的本地 SQLite 路径。"""

    path = get_settings().data_dir / "pdca_local.sqlite"

    return f"sqlite:///{path.as_posix()}"





def get_active_database_url() -> str:

    """当前实际使用的数据库连接串。"""

    global _active_database_url

    if _active_database_url is None:

        _active_database_url = get_settings().database_url

    return _active_database_url





def get_db_mode() -> str:

    """postgresql | sqlite | sqlite-fallback | unknown"""

    return _db_mode





def get_engine():

    """懒加载 SQLAlchemy 引擎。"""

    global _engine

    if _engine is None:

        url = get_active_database_url()

        connect_args: dict = {}

        if url.startswith("sqlite"):

            connect_args["check_same_thread"] = False

        elif url.startswith("postgresql"):

            connect_args["connect_timeout"] = 3

        _engine = create_engine(

            url,

            echo=False,

            connect_args=connect_args,

            pool_pre_ping=True,

            pool_size=5,

            max_overflow=10,

            pool_timeout=5,

        )

    return _engine





def _probe_url(url: str) -> bool:

    """探测指定连接串是否可用。"""

    connect_args: dict = {}

    if url.startswith("sqlite"):

        connect_args["check_same_thread"] = False

    elif url.startswith("postgresql"):

        connect_args["connect_timeout"] = 3

    try:

        probe = create_engine(url, connect_args=connect_args, pool_pre_ping=True)

        with probe.connect() as conn:

            conn.execute(text("SELECT 1"))

        probe.dispose()

        return True

    except Exception as exc:

        logger.debug("数据库探测失败 {}: {}", url.split("@")[-1], exc)

        return False





def bootstrap_database() -> str:

    """

    启动时选择数据库：优先 PostgreSQL，失败则回退本地 SQLite。



    @returns 实际库模式

    """

    global _engine, _active_database_url, _db_mode

    settings = get_settings()

    primary = settings.database_url



    if primary.startswith("sqlite"):

        _active_database_url = primary

        _engine = None

        _db_mode = "sqlite"

        init_db()

        logger.info("使用 SQLite: {}", primary)

        return _db_mode



    if _probe_url(primary):

        _active_database_url = primary

        _engine = None

        _db_mode = "postgresql"

        init_db()

        logger.info("已连接 PostgreSQL: {}", settings.pg_connection_info.get("database"))

        return _db_mode



    fallback = _sqlite_fallback_url()

    logger.warning(

        "PostgreSQL 不可用（{}），回退本地 SQLite",

        primary.split("@")[-1] if "@" in primary else primary,

    )

    _active_database_url = fallback

    _engine = None

    _db_mode = "sqlite-fallback"

    init_db()

    logger.info("使用 SQLite 回退库: {}", fallback)

    return _db_mode





def check_db_connection() -> bool:

    """探测当前数据库连通性。"""

    try:

        with get_engine().connect() as conn:

            conn.execute(text("SELECT 1"))

        return True

    except Exception as exc:

        logger.error("数据库连接失败: {}", exc)

        return False





def init_db() -> None:

    """创建所有表（首次启动或迁移前）。"""

    from app.auth.models import User  # noqa: F401

    from app.models.daily_report import DailyReport  # noqa: F401

    from app.models.dealer_sales import DealerSales  # noqa: F401

    from app.models.logistics import LogisticsShipment  # noqa: F401

    from app.models.meeting import MeetingRecord  # noqa: F401

    from app.models.onboarding_progress import OnboardingProgress  # noqa: F401

    from app.models.pdca_task import PdcaTask  # noqa: F401

    from app.models.walkin_daily_report import WalkinDailyReport  # noqa: F401

    from app.models.dealer_store import DealerStore  # noqa: F401

    from app.models.monthly_target import MonthlyTarget  # noqa: F401

    from app.models.audit_log import AuditLog  # noqa: F401



    SQLModel.metadata.create_all(get_engine())

    _migrate_schema()

    logger.info("数据库表已就绪")





def _migrate_schema() -> None:

    """轻量 schema 补丁（SQLite/PostgreSQL）。"""

    engine = get_engine()

    dialect = engine.dialect.name

    _patches_pg = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS sales_name VARCHAR(128) DEFAULT ''",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT TRUE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS pwd_version INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS dealer_id VARCHAR(64) DEFAULT ''",
        "ALTER TABLE dealer_stores ADD COLUMN IF NOT EXISTS dealer_level VARCHAR(8) DEFAULT 'L1'",
        "ALTER TABLE dealer_stores ADD COLUMN IF NOT EXISTS sales_owner VARCHAR(64) DEFAULT ''",
        "ALTER TABLE walkin_daily_reports ADD COLUMN IF NOT EXISTS walkin_visits INTEGER DEFAULT 0",
    ]

    _patches_sqlite = [
        "ALTER TABLE users ADD COLUMN sales_name VARCHAR(128) DEFAULT ''",
        "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN DEFAULT 1",
        "ALTER TABLE users ADD COLUMN pwd_version INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN dealer_id VARCHAR(64) DEFAULT ''",
        "ALTER TABLE dealer_stores ADD COLUMN dealer_level VARCHAR(8) DEFAULT 'L1'",
        "ALTER TABLE dealer_stores ADD COLUMN sales_owner VARCHAR(64) DEFAULT ''",
        "ALTER TABLE walkin_daily_reports ADD COLUMN walkin_visits INTEGER DEFAULT 0",
    ]

    # 把之前 Excel 导入时错放到 prospect_visits 的 Walk-ins 数据迁移回 walkin_visits
    _fix_walkin = (
        "UPDATE walkin_daily_reports "
        "SET walkin_visits = prospect_visits, prospect_visits = 0 "
        "WHERE notes LIKE 'Excel导入%' AND walkin_visits = 0 AND prospect_visits > 0"
    )

    with engine.connect() as conn:

        if dialect == "postgresql":
            for sql in _patches_pg:
                try:
                    conn.exec_driver_sql(sql)
                except Exception:
                    pass
        else:
            for sql in _patches_sqlite:
                try:
                    conn.exec_driver_sql(sql)
                except Exception:
                    pass

        try:
            conn.exec_driver_sql(_fix_walkin)
        except Exception:
            pass
        conn.commit()





def get_session():

    """FastAPI 依赖：数据库会话。"""

    with Session(get_engine()) as session:

        yield session

