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
    # Vemory 会议待办（事实源：Vemory OpenAPI getUserMeetingTodos）。
    # external_todo_id 为 Vemory 待办 ID（vemory:{id}），同步去重主键；
    # meeting_date 为会议日期；无截止时 task_date 回退为会议日期。
    external_todo_id: str = Field(default="", index=True, max_length=64)
    meeting_name: str = Field(default="", max_length=256)
    meeting_date: str = Field(default="", max_length=10)
    # 岗位 SOP 收敛（app/todos/sop.py）：position=岗位名（unclassified=未识别）；
    # origin_owner=收敛前的会议参与人（owner 为收敛后的执行人）。
    position: str = Field(default="", max_length=64)
    origin_owner: str = Field(default="", max_length=128)
    # 项目（事项）收敛：挂到 todo_projects.id；空=未入项目
    project_id: Optional[int] = Field(default=None, index=True)
    # IM 回复采集：最近一次回复原文与时间（"已完成"类回复标记 done 时记录）
    reply_text: str = Field(default="", max_length=1024)
    replied_at: Optional[datetime] = Field(default=None)
    # 手工修正执行人后置锁：True 时 Vemory 同步不再重算 owner
    owner_locked: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
