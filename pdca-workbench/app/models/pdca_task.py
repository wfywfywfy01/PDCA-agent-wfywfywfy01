# -*- coding: utf-8 -*-
"""PDCA 待办任务表。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class PdcaTask(SQLModel, table=True):
    """待办任务（替代 inputs/todos/*.csv）。"""

    __tablename__ = "pdca_tasks"

    id: Optional[int] = Field(default=None, primary_key=True)
    task_date: str = Field(index=True, max_length=10)
    title: str = Field(max_length=512)
    owner: str = Field(default="", index=True, max_length=128)
    status: str = Field(default="pending", max_length=32)
    priority: str = Field(default="normal", max_length=32)
    source: str = Field(default="", max_length=128)
    vps_todo_id: str = Field(default="", max_length=64)
    # 催办跟进（待办提醒）：最近一次催办时间/轮次与累计次数。
    # last_reminded_round ∈ {"morning", "afternoon", "manual", "auto-*"}，
    # 同一天同一轮只催一次（手动催办不受轮次限制）。
    last_reminded_at: Optional[datetime] = Field(default=None)
    last_reminded_round: str = Field(default="", max_length=32)
    remind_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
