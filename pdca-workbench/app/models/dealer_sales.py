# -*- coding: utf-8 -*-
"""经销商业绩快照表。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class DealerSales(SQLModel, table=True):
    """门店/经销商业绩（替代 data_raw JSON）。"""

    __tablename__ = "dealer_sales"

    id: Optional[int] = Field(default=None, primary_key=True)
    check_date: str = Field(index=True, max_length=10)
    dealer_name: str = Field(index=True, max_length=256)
    region: str = Field(default="", max_length=64)
    country: str = Field(default="", max_length=64)
    sell_in_wan: float = Field(default=0.0)
    sell_out_wan: float = Field(default=0.0)
    units: int = Field(default=0)
    source_file: str = Field(default="", max_length=512)
    synced_at: datetime = Field(default_factory=datetime.utcnow)
