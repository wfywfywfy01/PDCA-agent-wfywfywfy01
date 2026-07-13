# -*- coding: utf-8 -*-
"""Dashboard API 路由。"""
from __future__ import annotations

from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel import Session

from app.auth.deps import require_role
from app.auth.models import User
from app.dashboard import service
from app.database import get_session
from app.auth.scope import visible_dealer_names
from app.legacy import bridge
from app.validation import require_iso_date

router = APIRouter(tags=["dashboard"])


def _date_or_today(value: str | None) -> str:
    return require_iso_date(value or bridge.today_text())


def _session_user(user: User) -> dict:
    return {
        "username": user.username,
        "display_name": user.display_name,
        "sales_name": getattr(user, "sales_name", "") or "",
        "role": user.role,
    }


def _bridge_call(fn, *args, default=None, **kwargs):
    """执行 bridge 调用，捕获异常返回默认值。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("bridge 调用失败 {}: {}", fn.__name__, exc)
        if default is not None:
            return default
        raise HTTPException(status_code=503, detail="数据服务暂时不可用，请稍后重试")


@router.get("/api/dashboard/overview")
async def overview(
    date: str | None = None,
    period: str = Query("day"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    session_user = _session_user(user)
    date_text = _date_or_today(date)
    data = _bridge_call(service.overview, date_text, period, session_user, default={})
    # 附上 chart_data.json 最后修改时间，供前端显示"上次更新"
    try:
        chart_path = bridge.output_dir(date_text) / "chart_data.json"
        if isinstance(data, dict) and chart_path.is_file():
            data["dataUpdatedAt"] = int(chart_path.stat().st_mtime * 1000)
    except Exception:
        pass
    # 用云端 DB 数据覆盖 bridge 返回的 sellin/sellout（公网环境无本地文件时生效）
    if isinstance(data, dict):
        try:
            data = service.merge_db_sales(data, date_text, session, user)
        except Exception as exc:
            logger.warning("merge_db_sales 失败: {}", exc)
    return data


@router.post("/api/dashboard/refresh")
async def dashboard_refresh(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """手动触发当日 KPI 数据刷新（重建 chart_data.json + dashboard.html）。约需 1-3 分钟。"""
    date_text = _date_or_today(date)
    code, _stdout, stderr = await asyncio.to_thread(bridge.run_pdca, date_text, False)
    if code != 0:
        raise HTTPException(status_code=503, detail=f"刷新失败: {(stderr or '')[:200]}")
    # 返回最新文件时间
    try:
        chart_path = bridge.output_dir(date_text) / "chart_data.json"
        updated_at = int(chart_path.stat().st_mtime * 1000) if chart_path.is_file() else None
    except Exception:
        updated_at = None
    return {"ok": True, "date": date_text, "dataUpdatedAt": updated_at}


@router.get("/api/dashboard/sell-in")
async def sell_in(
    date: str | None = None,
    period: str = Query("day"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    from app.vertu.sales import fetch_sell_in
    date_text = _date_or_today(date)
    if user.role in ("dealer", "sales"):
        data = service.overview(date_text, period, _session_user(user))
        data = service.merge_db_sales(data, date_text, session, user)
        return {"amount": data["sellInAmount"], "wan": data["sellInWan"], "note": data["sellInSub"]}
    try:
        return await fetch_sell_in(date_text, period)
    except Exception as exc:
        logger.warning("vertu sell-in 失败，回退 bridge: {}", exc)
        return _bridge_call(service.sell_in, date_text, period, default={})


@router.get("/api/dashboard/sell-out")
async def sell_out(
    date: str | None = None,
    period: str = Query("day"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    from app.vertu.sales import fetch_sell_out
    date_text = _date_or_today(date)
    if user.role in ("dealer", "sales"):
        data = service.overview(date_text, period, _session_user(user))
        data = service.merge_db_sales(data, date_text, session, user)
        return {"amount": data["sellOutAmount"], "wan": data["sellOutWan"], "note": data["sellOutSub"]}
    try:
        return await fetch_sell_out(date_text, period)
    except Exception as exc:
        logger.warning("vertu sell-out 失败，回退 bridge: {}", exc)
        return _bridge_call(service.sell_out, date_text, period, default={})


@router.get("/api/customer-center/summary")
async def customer_center(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    session_user = _session_user(user)
    return _bridge_call(bridge.api_customer_center_summary, session_user, default=[])


@router.get("/api/task-center/summary")
async def task_center_summary(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_task_center_summary, _date_or_today(date), default=[])


@router.get("/api/dealer/sellin-summary")
async def dealer_sellin_summary(
    month: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    from datetime import date as _date
    from app.vertu.sales import fetch_sellin_summary
    m = month or _date.today().strftime("%Y-%m")
    try:
        data = await fetch_sellin_summary(m)
    except Exception as exc:
        logger.warning("vertu sellin-summary 失败，回退 bridge: {}", exc)
        data = _bridge_call(bridge.api_dealer_sellin_summary, m, default={})
    names = visible_dealer_names(user, session)
    if names is None or not isinstance(data, dict):
        return data
    allowed = {name.casefold() for name in names}
    scoped = dict(data)
    scoped["dealers"] = [
        row for row in data.get("dealers", [])
        if str(row.get("name") or row.get("dealer_name") or "").casefold() in allowed
    ]
    scoped["total_wan"] = round(
        sum(float(row.get("wan") or row.get("sell_in_wan") or 0) for row in scoped["dealers"]),
        2,
    )
    scoped["has_data"] = bool(scoped["dealers"])
    scoped["trend"] = []
    return scoped


@router.get("/api/task-center/panel")
async def task_center_panel(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_task_center_panel, _date_or_today(date), default={})
