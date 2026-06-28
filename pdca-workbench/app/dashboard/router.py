# -*- coding: utf-8 -*-
"""Dashboard API 路由。"""
from __future__ import annotations

from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.auth.deps import require_role
from app.auth.models import User
from app.dashboard import service
from app.legacy import bridge

router = APIRouter(tags=["dashboard"])


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
):
    session_user = {
        "username": user.username,
        "display_name": user.display_name,
        "sales_name": getattr(user, "sales_name", "") or "",
        "role": user.role,
    }
    date_text = date or bridge.today_text()
    data = _bridge_call(service.overview, date_text, period, session_user, default={})
    # 附上 chart_data.json 最后修改时间，供前端显示"上次更新"
    try:
        chart_path = bridge.output_dir(date_text) / "chart_data.json"
        if isinstance(data, dict) and chart_path.is_file():
            data["dataUpdatedAt"] = int(chart_path.stat().st_mtime * 1000)
    except Exception:
        pass
    return data


@router.post("/api/dashboard/refresh")
async def dashboard_refresh(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """手动触发当日 KPI 数据刷新（重建 chart_data.json + dashboard.html）。约需 1-3 分钟。"""
    date_text = date or bridge.today_text()
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
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(service.sell_in, date or bridge.today_text(), period, default={})


@router.get("/api/dashboard/sell-out")
async def sell_out(
    date: str | None = None,
    period: str = Query("day"),
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(service.sell_out, date or bridge.today_text(), period, default={})


@router.get("/api/todos/today")
async def todos_today(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_todos_today, date or bridge.today_text(), default=[])


@router.get("/api/hermes-agent/tasks")
async def hermes_tasks(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_hermes_agent_tasks, date or bridge.today_text(), default=[])


@router.get("/api/customer-center/summary")
async def customer_center(
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_customer_center_summary, default=[])


@router.get("/api/hr/summary")
async def hr_summary(
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_hr_summary, default=[])


@router.get("/api/exceptions")
async def exceptions(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_exceptions, date or bridge.today_text(), default=[])


@router.get("/api/important-matters")
async def important_matters(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_important_matters, date or bridge.today_text(), default={})


@router.get("/api/task-center/summary")
async def task_center_summary(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_task_center_summary, date or bridge.today_text(), default=[])


@router.get("/api/dealer/sellin-summary")
async def dealer_sellin_summary(
    month: str = Query(""),
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    from datetime import date as _date
    m = month or _date.today().strftime("%Y-%m")
    return _bridge_call(bridge.api_dealer_sellin_summary, m, default={})


@router.get("/api/task-center/panel")
async def task_center_panel(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    return _bridge_call(bridge.api_task_center_panel, date or bridge.today_text(), default={})
