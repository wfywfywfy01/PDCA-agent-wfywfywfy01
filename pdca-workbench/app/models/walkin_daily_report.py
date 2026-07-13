# -*- coding: utf-8 -*-
"""门店五件套日报表（每日进店来源 + 成交漏斗 + Sell-out）。

进店来源分五类（2026-07-12 起，替换旧的 自然进/预约/潜客/线上/介绍/SA 六分类）：
  walkin   - 直接进店人数
  cross    - 异业：同业其他奢侈品员工介绍
  online   - 线上：各种社媒渠道
  recruit  - 招聘：招聘的新员工自带客户
  existing - 存量：老客户
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class WalkinDailyReport(SQLModel, table=True):
    """经销商每日客流五件套数据。"""

    __tablename__ = "walkin_daily_reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    report_date: str = Field(index=True, max_length=10)   # YYYY-MM-DD
    dealer_id: str = Field(index=True, max_length=64)     # 对应 walkin JSON 里的 store id
    dealer_name: str = Field(max_length=256)

    # 五件套来源人数
    walkin_visits: int = Field(default=0)      # walkin 直接进店
    cross_visits: int = Field(default=0)       # 异业：同业其他奢侈品员工介绍
    online_visits: int = Field(default=0)      # 线上：各种社媒渠道
    recruit_visits: int = Field(default=0)     # 招聘：招聘的新员工自带客户
    existing_visits: int = Field(default=0)    # 存量：老客户

    # 转化漏斗
    touch_count: int = Field(default=0)           # 触摸产品（人次）
    use_count: int = Field(default=0)              # 试用体验（人次）
    wechat_add_count: int = Field(default=0)      # 微信添加数
    deal_count: int = Field(default=0)            # 成交组数
    deal_amount_yuan: float = Field(default=0.0)  # 成交金额（元，即 sell-out）

    notes: str = Field(default="", max_length=1024)
    submitted_by: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_visits(self) -> int:
        return (
            self.walkin_visits
            + self.cross_visits
            + self.online_visits
            + self.recruit_visits
            + self.existing_visits
        )
