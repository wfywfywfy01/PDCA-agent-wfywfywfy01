"""Department rules are keyed by canonical IM group and calendar month."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


class DuzhanMonthlyMetric(SQLModel, table=True):
    __tablename__ = "duzhan_monthly_metrics"
    __table_args__ = (
        UniqueConstraint("channel_id", "month", name="uq_duzhan_monthly_group_month"),
        CheckConstraint("mto_daily_count >= 1 AND mto_min_wan > 0", name="ck_duzhan_mto_metrics"),
        CheckConstraint("(goal = 'amount' AND sales_target_wan IS NOT NULL AND sales_target_wan > 0) OR "
                        "(goal = 'break_zero' AND sales_target_wan IS NULL)", name="ck_duzhan_sales_goal"),
    )

    id: int | None = Field(default=None, primary_key=True)
    channel_id: str = Field(max_length=36)
    month: str = Field(max_length=7)
    goal: str = Field(max_length=16)
    sales_target_wan: float | None = None
    mto_daily_count: int = 4
    mto_min_wan: float = 30
    version: int = 1
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc),
                                 sa_column=Column(DateTime(timezone=True), nullable=False))
