# -*- coding: utf-8 -*-
"""Dashboard API 路由。"""
from __future__ import annotations

from typing import Annotated

import asyncio
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel
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
from app.models.pdca_task import PdcaTask

router = APIRouter(tags=["dashboard"])


def _date_or_today(value: str | None) -> str:
    return require_iso_date(value or bridge.today_text())


def _period_start(date_text: str, period: str) -> str:
    current = date_type.fromisoformat(date_text)
    if period == "week":
        return str(current - timedelta(days=current.weekday()))
    if period == "month":
        return str(current.replace(day=1))
    if period == "quarter":
        return str(current.replace(month=((current.month - 1) // 3) * 3 + 1, day=1))
    return date_text


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
    from app.statuses import is_done

    done = sum(1 for item in items if is_done(item.get("status")))
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


_STALE_HOURS = 36


def _freshness_state(as_of: str | None) -> str:
    """F6：按数据时间计算新鲜度状态（live/missing/stale）。

    无 as_of → missing；距今超过 _STALE_HOURS 小时 → stale；否则 live。
    数据库 synced_at 为 naive UTC，vertu as_of 为带时区本地时间，两者都兼容。
    """
    if not as_of:
        return "missing"
    try:
        dt = datetime.fromisoformat(str(as_of))
        now = datetime.now().astimezone()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        age_seconds = (now - dt.astimezone(now.tzinfo)).total_seconds()
        return "stale" if age_seconds > _STALE_HOURS * 3600 else "live"
    except ValueError:
        return "missing"


def _sales_payload(data: dict, prefix: str) -> dict:
    wan = data.get(f"{prefix}Wan")
    amount = round(float(wan) * 10000, 2) if wan is not None else None
    as_of = data.get("dataAsOf")
    return {
        "amount": amount,
        "wan": wan,
        "note": data.get(f"{prefix}Sub") or "数据尚未同步",
        "as_of": as_of,
        "source": (data.get("dataSource") or {}).get(prefix),
        "cached": bool(as_of),
        "state": _freshness_state(as_of),
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
        stores = [
            row for row in session.exec(
                select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
            ).all()
            if not row.store_id.lower().startswith(("qa-", "test-", "demo-"))
            and not any(marker in row.name.lower() for marker in ("测试", "演示", "demo"))
        ]
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
            "title": "跟进今日门店五件套填报",
            "message": f"系统已收到 {len(reported_ids)} 家；应报门店清单尚未确认，不展示虚假完成率。",
            "href": "/app/walkin",
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
            "roster_state": "unconfirmed",
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
    # 用云端 DB 数据覆盖 bridge 返回的 sellin/sellout（公网环境无本地文件时生效）
    if isinstance(data, dict):
        try:
            data = service.merge_db_sales(data, date_text, session, user)
        except Exception as exc:
            logger.warning("merge_db_sales 失败: {}", exc)
    # F1：数据更新时间以数据库同步时刻为准（dealer_sales.synced_at），
    # 不再依赖已停用的 chart_data.json 文件 mtime；仅在无 DB 数据时回退文件时间。
    if isinstance(data, dict):
        data_as_of = data.get("dataAsOf")
        if data_as_of:
            try:
                data["dataUpdatedAt"] = int(
                    datetime.fromisoformat(str(data_as_of)).timestamp() * 1000
                )
            except ValueError:
                pass
        elif not data.get("dataUpdatedAt"):
            try:
                chart_path = bridge.output_dir(date_text) / "chart_data.json"
                if chart_path.is_file():
                    data["dataUpdatedAt"] = int(chart_path.stat().st_mtime * 1000)
            except Exception:
                pass
    return data


@router.post("/api/dashboard/refresh")
async def dashboard_refresh(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """手动触发数据同步（vertu-cli → 数据库）。

    P1：看板数据实时来自数据库，不再经子进程重建 chart_data.json/
    dashboard.html（旧 run_pdca 链路）。此处改为跑一次全量同步并返回
    最新的数据库同步时刻。
    """
    date_text = _date_or_today(date)
    from app.models.sync import run_full_sync

    result = await asyncio.to_thread(run_full_sync, date_text)
    errors = [str(value) for value in result.values() if str(value).startswith("error:")]
    if errors:
        raise HTTPException(status_code=503, detail=f"同步失败: {'; '.join(errors)[:200]}")
    updated_at = None
    try:
        latest = session.exec(
            select(DealerSales.synced_at).where(
                DealerSales.check_date.startswith(date_text[:7])
            ).order_by(DealerSales.synced_at.desc())
        ).first()
        if latest is not None:
            updated_at = int(latest.replace(tzinfo=None).timestamp() * 1000)
    except Exception as exc:  # 数据时间获取失败不影响同步结果
        logger.warning("读取 synced_at 失败: {}", exc)
    return {"ok": True, "date": date_text, "dataUpdatedAt": updated_at, "sync": result}


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
        payload = await fetch_sell_in(date_text, period)
        payload["state"] = _freshness_state(payload.get("as_of"))
        return payload
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
    start_text = _period_start(date_text, period)
    scope = resolve_data_scope(user, session)
    stmt = select(WalkinDailyReport).where(
        WalkinDailyReport.report_date >= start_text,
        WalkinDailyReport.report_date <= date_text,
    )
    if not scope.unrestricted:
        stmt = stmt.where(WalkinDailyReport.dealer_id.in_(scope.store_ids))
    rows = [
        row for row in session.exec(stmt).all()
        if not row.dealer_id.lower().startswith(("qa-", "test-", "demo-"))
    ]
    from app.config import get_settings

    settings = get_settings()
    threshold = min(
        settings.max_reported_revenue_usd,
        settings.revenue_review_threshold_usd,
    )
    valid_rows = [row for row in rows if row.deal_amount_yuan <= threshold]
    as_of = max((row.created_at for row in rows if row.created_at), default=None)
    as_of_text = (
        as_of.replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
        if as_of and as_of.tzinfo is None
        else as_of.isoformat(timespec="seconds") if as_of else None
    )
    labels = {"day": "今日", "week": "本周", "month": "本月", "quarter": "本季度"}
    return {
        "amount": round(sum(row.deal_amount_yuan for row in valid_rows), 2) if rows else None,
        "wan": None,
        "note": (
            f"{labels.get(period, '当前区间')}五件套实报 · {len({row.dealer_id for row in rows})} 家门店 · USD"
            if rows else f"{labels.get(period, '当前区间')}尚无门店五件套回执"
        ),
        "currency": "USD",
        "as_of": as_of_text,
        "source": "five_kit_db",
        "state": "live" if rows else "missing",
        "review_count": len(rows) - len(valid_rows),
    }


@router.get("/api/customer-center/summary")
async def customer_center(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    session_user = _session_user(user, session)
    rows = service.db_customer_center_summary(session, user)
    if rows is None:
        rows = _bridge_call(bridge.api_customer_center_summary, session_user, default=[])
    return rows


def _db_task_panel(date_text: str, user: User, session: Session) -> dict | None:
    """F4：任务中心优先读 pdca_tasks 表（DB 唯一事实源）。

    无数据时返回 None，调用方回退 bridge（vertu 待办）。注意：scope 过滤
    仍由 _scoped_task_panel 完成，行为与 bridge 路径一致（fail-closed）。
    """
    rows = list(session.exec(select(PdcaTask).where(PdcaTask.task_date == date_text)).all())
    if not rows:
        return None
    items = [
        {
            "owner_key": row.owner,
            "owner": row.owner,
            "title": row.title,
            "status": row.status,
            "priority": row.priority,
            "source": row.source,
            "date": row.task_date,
        }
        for row in rows
    ]
    from app.statuses import is_done

    done = sum(1 for item in items if is_done(item.get("status")))
    return {
        "items": items,
        "summary": [
            {"key": "total", "label": "总任务数", "value": len(items)},
            {"key": "done", "label": "已完成", "value": done},
            {"key": "undone", "label": "未完成", "value": len(items) - done},
        ],
        "source": "pdca_tasks_db",
    }


@router.get("/api/task-center/summary")
async def task_center_summary(
    date: str | None = None,
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    date_text = _date_or_today(date)
    panel = _db_task_panel(date_text, user, session)
    if panel is None:
        panel = _bridge_call(bridge.api_task_center_panel, date_text, default={})
    return _scoped_task_panel(panel, user, session).get("summary", [])


@router.get("/api/dealer/sellin-summary")
async def dealer_sellin_summary(
    month: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    from datetime import date as _date
    m = month or _date.today().strftime("%Y-%m")
    # 排行与趋势读取已同步的每日月累计快照。实时订单明细接口可能超过
    # 60 秒，不能阻塞用户页面；首页总额仍使用快速 headline-kpi 实时接口。
    data = service.db_sellin_summary(m, session, user)
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
    date_text = _date_or_today(date)
    panel = _db_task_panel(date_text, user, session)
    if panel is None:
        panel = _bridge_call(bridge.api_task_center_panel, date_text, default={})
    return _scoped_task_panel(panel, user, session)


class TaskCreateBody(BaseModel):
    task_date: str | None = None
    title: str
    owner: str = ""
    priority: str = "normal"


class TaskPatchBody(BaseModel):
    status: str | None = None
    owner: str | None = None
    priority: str | None = None


def _allowed_task_owners(user: User, session: Session) -> set[str] | None:
    """返回当前账号可操作的任务负责人集合；None 表示不受限。"""
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return None
    return {
        str(value).strip().casefold()
        for value in scope.owner_keys
        if str(value).strip()
    }


@router.get("/api/task-center/tasks")
async def task_center_tasks(
    date: str | None = None,
    owner: str = Query(""),
    status: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """P4：任务列表（DB 直查，scope 过滤）。"""
    date_text = _date_or_today(date)
    stmt = select(PdcaTask).where(PdcaTask.task_date == date_text)
    if owner.strip():
        stmt = stmt.where(PdcaTask.owner == owner.strip())
    if status.strip():
        stmt = stmt.where(PdcaTask.status == status.strip())
    rows = list(session.exec(stmt.order_by(PdcaTask.id)).all())
    allowed = _allowed_task_owners(user, session)
    if allowed is not None:
        rows = [
            row for row in rows
            if str(row.owner or "").strip().casefold() in allowed
        ]
    return {
        "date": date_text,
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "task_date": row.task_date,
                "title": row.title,
                "owner": row.owner,
                "status": row.status,
                "priority": row.priority,
                "source": row.source,
                "updated_at": row.updated_at.isoformat() if row.updated_at else "",
            }
            for row in rows
        ],
    }


@router.post("/api/task-center/tasks")
async def task_center_create(
    body: TaskCreateBody,
    user: Annotated[User, Depends(require_role("sales"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """P4：创建任务。manager/admin 可指派任意负责人；sales 仅可建给自己。"""
    if not body.title.strip():
        raise HTTPException(status_code=422, detail="任务标题不能为空")
    date_text = require_iso_date(body.task_date or bridge.today_text(), field="task_date")
    allowed = _allowed_task_owners(user, session)
    owner = body.owner.strip()
    if user.role == "sales":
        owner = (
            getattr(user, "sales_name", "")
            or getattr(user, "display_name", "")
            or user.username
        )
    elif allowed is not None and owner and owner.casefold() not in allowed:
        raise HTTPException(status_code=403, detail="负责人不在当前账号权限范围内")
    from app.models import writes as db_writes

    db_writes.insert_pdca_task(
        task_date=date_text,
        title=body.title.strip(),
        owner=owner,
        status="pending",
        priority=body.priority.strip() or "normal",
        source="workbench",
    )
    from app.audit import log_action

    log_action(
        user.username,
        "task_create",
        resource=f"{date_text}:{body.title.strip()}",
        detail={"owner": owner, "priority": body.priority.strip() or "normal"},
    )
    return {"ok": True, "task_date": date_text, "title": body.title.strip(), "owner": owner}


@router.patch("/api/task-center/tasks/{task_id}")
async def task_center_patch(
    task_id: int,
    body: TaskPatchBody,
    user: Annotated[User, Depends(require_role("sales"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """P4：更新任务状态/负责人/优先级（scope 校验）。"""
    row = session.get(PdcaTask, task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    allowed = _allowed_task_owners(user, session)
    if allowed is not None:
        current_owner = str(row.owner or "").strip().casefold()
        if current_owner and current_owner not in allowed:
            raise HTTPException(status_code=403, detail="该任务不在当前账号权限范围内")
        if body.owner and body.owner.strip().casefold() not in allowed:
            raise HTTPException(status_code=403, detail="新负责人不在当前账号权限范围内")
    if body.status is not None:
        row.status = body.status.strip()
    if body.owner is not None:
        row.owner = body.owner.strip()
    if body.priority is not None:
        row.priority = body.priority.strip()
    from datetime import datetime as _dt

    row.updated_at = _dt.utcnow()
    session.add(row)
    session.commit()
    from app.audit import log_action

    changes = {
        key: value for key, value in {
            "status": body.status, "owner": body.owner, "priority": body.priority,
        }.items() if value is not None
    }
    log_action(user.username, "task_update", resource=f"task:{task_id}", detail=changes)
    return {"ok": True, "id": row.id, "status": row.status}
