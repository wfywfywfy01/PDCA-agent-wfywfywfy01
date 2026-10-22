# -*- coding: utf-8 -*-
"""增长飞轮：素材、生成内容、开发信发送与追踪。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Column, Text
from sqlmodel import Field, SQLModel


class GrowthAsset(SQLModel, table=True):
    """输入素材：产品/服务/经销商 catalog 与经销商背调。"""

    __tablename__ = "growth_assets"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(index=True, max_length=16)  # product/service/dealer/dossier
    title: str = Field(max_length=200)
    body: str = Field(sa_column=Column(Text, nullable=False))
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GrowthContent(SQLModel, table=True):
    """一轮生成里的一个版本；round_no + variant 是飞轮对比的最小单元。"""

    __tablename__ = "growth_contents"

    id: Optional[int] = Field(default=None, primary_key=True)
    round_no: int = Field(index=True)
    kind: str = Field(index=True, max_length=8)  # seo/geo/email/ad
    topic: str = Field(max_length=300)
    variant: str = Field(max_length=4)
    angle: str = Field(default="", max_length=500)
    title: str = Field(default="", max_length=500)
    body: str = Field(sa_column=Column(Text, nullable=False))
    status: str = Field(default="draft", max_length=16)  # draft/pushed/sent/paused
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GrowthSend(SQLModel, table=True):
    """一封开发信；token 用于打开像素、点击跳转与退订。"""

    __tablename__ = "growth_sends"

    id: Optional[int] = Field(default=None, primary_key=True)
    content_id: int = Field(index=True)
    to_addr: str = Field(index=True, max_length=320)
    token: str = Field(unique=True, index=True, max_length=40)
    message_id: str = Field(default="", index=True, max_length=300)
    sent_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    opened_at: Optional[datetime] = None
    open_count: int = 0
    clicked_at: Optional[datetime] = None
    click_count: int = 0
    replied_at: Optional[datetime] = None
    reply_kind: str = Field(default="", max_length=8)  # reply/unsub
    bounced_at: Optional[datetime] = None
    tracked: bool = False


class GrowthUnsub(SQLModel, table=True):
    """退订名单；发送前强制过滤。"""

    __tablename__ = "growth_unsubs"

    email: str = Field(primary_key=True, max_length=320)
    at: datetime = Field(default_factory=datetime.utcnow)
