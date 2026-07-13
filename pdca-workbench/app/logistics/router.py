# -*- coding: utf-8 -*-
"""物流板块 API。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.deps import require_role
from app.auth.models import User
from app.logistics import service

router = APIRouter(prefix="/api/logistics", tags=["logistics"])


def _sales_filter_from_user(user: User, salesperson: str) -> str | None:
    return service.resolve_sales_filter(
        user.role,
        getattr(user, "sales_name", "") or "",
        user.display_name,
        user.username,
        salesperson,
    )


@router.get("/dates")
async def logistics_dates(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """有物流数据的录入日期。"""
    return {"items": service.list_available_dates()}


@router.get("/summary")
async def logistics_summary(
    date: str | None = Query(None, description="YYYY-MM-DD 或 all 表示全部"),
    salesperson: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
    open_only: bool = Query(False),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """当前用户可见的物流进展汇总。"""
    sales_filter = _sales_filter_from_user(user, salesperson)
    date_key = date or "all"
    shipments = service.load_shipments(date_key, sales_filter, status, q, open_only)
    summary = service.build_summary(shipments)
    return {
        "date": date_key,
        "salesperson": sales_filter or "全部",
        "role": user.role,
        **summary,
    }


@router.get("/shipments")
async def logistics_shipments(
    date: str | None = Query(None),
    salesperson: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
    open_only: bool = Query(False),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """运单列表（销售角色仅看自己）。"""
    sales_filter = _sales_filter_from_user(user, salesperson)
    date_key = date or "all"
    rows = service.load_shipments(date_key, sales_filter, status, q, open_only)
    return {
        "date": date_key,
        "salesperson": sales_filter or "全部",
        "count": len(rows),
        "items": rows,
    }


@router.get("/salespeople")
async def logistics_salespeople(
    user: Annotated[User, Depends(require_role("manager"))],
):
    """主管可选的销售名单。"""
    return {"items": service.list_salespeople()}


@router.post("/refresh-tracking")
async def refresh_tracking(
    user: Annotated[User, Depends(require_role("manager"))],
):
    """从 UPS/FedEx/DHL 官网抓取在途运单最新状态（SF 顺丰需图形验证码，跳过）。"""
    result = await service.refresh_tracking_statuses()
    return result
