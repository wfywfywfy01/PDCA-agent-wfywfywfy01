# -*- coding: utf-8 -*-
"""会议记录表。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class MeetingRecord(SQLModel, table=True):
    """Vemory 会议快照（替代 _vemory_cache JSON）。"""

    __tablename__ = "meeting_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    meeting_date: str = Field(index=True, max_length=10)
    external_id: str = Field(index=True, max_length=64)
    title: str = Field(default="", max_length=512)
    meeting_type: str = Field(default="internal", max_length=32)
    bucket: str = Field(default="report", max_length=32)
    duration_minutes: int = Field(default=0)
    brief: str = Field(default="")
    todos_json: str = Field(default="[]")
    participants_json: str = Field(default="[]")
    synced_at: datetime = Field(default_factory=datetime.utcnow)
