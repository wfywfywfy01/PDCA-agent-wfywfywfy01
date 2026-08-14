# -*- coding: utf-8 -*-
"""Dashboard API 路由。"""
from __future__ import annotations

from typing import Annotated

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel import Session, select

from app.auth.deps import require_role
from app.auth.models import User
from app.dashboard import service
from app.database import get_session
from app.auth.scope import resolve_data_scope, visible_dealer_names
from app.legacy import bridge
from app.validation import require_iso_date
from app.models.dealer_store import DealerStore
from app.models.walkin_daily_report import WalkinDailyReport

router = APIRouter(tags=["dashboard"])


def _date_or_today(value: str | None) -> str:
    return require_iso_date(value or bridge.today_text())


def _session_user(user: User, session: Session) -> dict:
    payload = {
        "username": user.username,
        "display_name": user.display_name,
        "sales_name": getattr(user, "sales_name", "") or "",
        "owner_key": getattr(user, "owner_key", "") or "",
        "team_key": getattr(user, "team_key", "") or "",
        "role": user.role,
    }
    payload.update(resolve_data_scope(user, session).as_session_user_fields())
    return payload


def _scoped_task_panel(data: dict, user: User, session: Session) -> dict:
    scope = resolve_data_scope(user, session)
    result = dict(data or {})
    if scope.unrestricted:
        result["scope"] = scope.mode
        return result
    allowed = {str(value).strip().casefold() for value in scope.owner_keys if str(value).strip()}
    items = []
    for item in result.get("items", []) or []:
        owner = str(
            item.get("owner_key")
            or item.get("owner")
            or item.get("salesperson")
            or item.get("assignee")
            or ""
        ).strip().casefold()
        if owner and owner in allowed:
            items.append(item)
    done_values = {"done", "completed", "complete", "已完成"}
    done = sum(1 for item in items if str(item.get("status") or "").strip().casefold() in done_values)
    result["items"] = items
    result["summary"] = [
        {"key": "total", "label": "总任务数", "value": len(items)},
        {"key": "done", "label": "已完成", "value": done},
        {"key": "undone", "label": "未完成", "value": len(items) - done},
    ]
    result["scope"] = scope.mode
    result["scope_message"] = "仅展示当前账号权限范围内且有明确负责人的任务"
    return result


def _bridge_call(fn, *args, default=None, **kwargs):
    """执行 bridge 调用，捕获异常返回默认值。"""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("bridge 调用失败 {}: {}", fn.__name__, exc)
        if default is not None:
            return default
        raise HTTPException(status_code=503, detail="数据服务暂时不可用，请稍后重试")


def _fact(value, state: str, source: str, as_of: str, scope: str, message: str = "") -> dict:
    """Uniform truth-state contract used by the user-facing workbench."""
    return {
        "value": value,
        "state": state,
        "source": source,
        "as_of": as_of,
        "scope": scope,
        "message": message,
    }


def _sales_payload(data: dict, prefix: str) -> dict:
    wan = data.get(f"{prefix}Wan")
    amount = round(float(wan) * 10000, 2) if wan is not None else None
    return {
        "amount": amount,
        "wan": wan,
        "note": data.get(f"{prefix}Sub") or "数据尚未同步",
        "as_of": data.get("dataAsOf"),
        "source": (data.get("dataSource") or {}).get(prefix),
        "cached": bool(data.get("dataAsOf")),
    }


@router.get("/api/workbench/today")
async def workbench_today(
    date: str | None = None,
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """Return truthful, scoped facts and next actions for the current account."""
    date_text = _date_or_today(date)
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        stores = list(session.exec(
            select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
        ).all())
        store_ids = {row.store_id for row in stores}
    else:
        store_ids = set(scope.store_ids)

    report_stmt = select(WalkinDailyReport).where(WalkinDailyReport.report_date == date_text)
    if store_ids:
        report_stmt = report_stmt.where(WalkinDailyReport.dealer_id.in_(store_ids))
        reports = list(session.exec(report_stmt).all())
    else:
        reports = []
    reported_ids = {row.dealer_id for row in reports if row.dealer_id in store_ids}
    expected = len(store_ids)
    missing = max(expected - len(reported_ids), 0)

    # Logistics currently comes from its canonical CSV/tracking merge.  An
    # absent source directory is explicitly "missing", never a synthetic zero.
    from app.config import get_settings
    from app.logistics import service as logistics_service
    from app.logistics.router import _scoped_shipments

    logistics_source = get_settings().mvp_root / "inputs" / "logistics"
    if logistics_source.is_dir() and any(logistics_source.glob("*_tracking.csv")):
        shipments, _ = _scoped_shipments(logistics_service.load_shipments("all"), user, session)
        logistics_summary = logistics_service.build_summary(shipments)
        logistics_fact = _fact(
            logistics_summary.get("abnormal", 0) + logistics_summary.get("pending", 0),
            "available",
            "logistics_tracking",
            date_text,
            scope.mode,
            "异常与待核查运单",
        )
    else:
        logistics_fact = _fact(
            None,
            "missing",
            "logistics_tracking",
            date_text,
            scope.mode,
            "物流源数据尚未同步",
        )

    facts = {
        "store_count": _fact(expected, "available", "dealer_store_db", date_text, scope.mode),
        "walkin_reported": _fact(len(reported_ids), "available", "five_kit_db", date_text, scope.mode),
        "walkin_missing": _fact(missing, "available", "five_kit_db", date_text, scope.mode),
        "walkin_visits": _fact(
            sum(row.total_visits for row in reports),
            "available",
            "five_kit_db",
            date_text,
            scope.mode,
        ),
        "logistics_attention": logistics_fact,
    }
    actions = []
    if expected == 0 and not scope.unrestricted:
        actions.append({
            "priority": "blocking",
            "title": "账号尚未绑定业务范围",
            "message": "请联系管理员配置门店负责人或团队；系统已按最小权限隐藏业务数据。",
            "href": "",
        })
    elif missing:
        actions.append({
            "priority": "high",
            "title": f"补齐 {missing} 家门店今日五件套",
            "message": "零客流也需要如实上报，不能把 0 当成未上报。",
            "href": f"/store-five-kit/?date={date_text}&period=day&filter=norep",
        })
    if logistics_fact["state"] == "available" and logistics_fact["value"]:
        actions.append({
            "priority": "high",
            "title": f"处理 {logistics_fact['value']} 条物流异常/待核查",
            "message": "进入物流中心核实状态、原因和下一步。",
            "href": "/logistics-center/?status=attention",
        })
    if not actions:
        actions.append({
            "priority": "normal",
            "title": "当前没有已识别的待处理异常",
            "message": "继续跟进客户、会议待办与当日数据更新。",
            "href": "/customer-mgmt",
        })
    return {
        "date": date_text,
        "user": {"display_name": user.display_name or user.username, "role": user.role},
        "scope": {
            "mode": scope.mode,
            "team_key": scope.team_key,
            "store_ids": list(scope.store_ids),
            "store_count": expected,
        },
        "facts": facts,
        "actions": actions,
        "closure": {
            "reported": len(reported_ids),
            "expected": expected,
            "complete": expected > 0 and missing == 0,
        },
    }


@router.get("/api/dashboard/overview")
async def overview(
    date: str | None = None,
    period: str = Query("day"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    session_user = _session_user(user, session)
    date_text = _date_or_today(date)
    data = service.workbench_overview(date_text, period, session_user)
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
    if not resolve_data_scope(user, session).unrestricted:
        data = service.workbench_overview(date_text, period, _session_user(user, session))
        data = service.merge_db_sales(data, date_text, session, user)
        return _sales_payload(data, "sellIn")
    try:
        return await fetch_sell_in(date_text, period)
    except Exception as exc:
        logger.warning("vertu sell-in 失败，回退数据库快照: {}", exc)
        data = service.workbench_overview(date_text, period, _session_user(user, session))
        data = service.merge_db_sales(data, date_text, session, user)
        return _sales_payload(data, "sellIn")


@router.get("/api/dashboard/sell-out")
async def sell_out(
    date: str | None = None,
    period: str = Query("day"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    date_text = _date_or_today(date)
    # vertu-cli 2.x does not provide a dealer Sell-out shortcut. The scoped
    # database snapshot is the authoritative source and avoids a guaranteed
    # failing remote call on every homepage visit.
    data = service.workbench_overview(date_text, period, _session_user(user, session))
    data = service.merge_db_sales(data, date_text, session, user)
    return _sales_payload(data, "sellOut")


@router.get("/api/customer-center/summary")
async def customer_center(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    session_user = _session_user(user, session)
    return _bridge_call(bridge.api_customer_center_summary, session_user, default=[])


@router.get("/api/task-center/summary")
async def task_center_summary(
    date: str | None = None,
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    panel = _bridge_call(bridge.api_task_center_panel, _date_or_today(date), default={})
    return _scoped_task_panel(panel, user, session).get("summary", [])


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
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    panel = _bridge_call(bridge.api_task_center_panel, _date_or_today(date), default={})
    return _scoped_task_panel(panel, user, session)
