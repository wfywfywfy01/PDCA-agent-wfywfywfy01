# -*- coding: utf-8 -*-
"""Alembic 迁移环境。"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

from app.config import get_settings
from app.auth.models import User  # noqa: F401
from app.auth.security_state import LoginFailRecord, TokenRevocation  # noqa: F401
from app.models.dealer_sales import DealerSales  # noqa: F401
from app.models.daily_report import DailyReport  # noqa: F401
from app.models.pdca_task import PdcaTask  # noqa: F401
from app.models.meeting import MeetingRecord  # noqa: F401
from app.models.logistics import LogisticsShipment  # noqa: F401
from app.models.onboarding_progress import OnboardingProgress  # noqa: F401
from app.models.walkin_daily_report import WalkinDailyReport  # noqa: F401
from app.models.dealer_store import DealerStore  # noqa: F401
from app.models.dealer_assignment import DealerAssignment  # noqa: F401
from app.models.monthly_target import MonthlyTarget  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.tracking_status import TrackingAutoStatus  # noqa: F401
from app.models.acquisition_login_ticket import AcquisitionLoginTicket  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
