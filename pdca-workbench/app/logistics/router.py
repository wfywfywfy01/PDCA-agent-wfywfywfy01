# -*- coding: utf-8 -*-
"""Logistics APIs with mandatory row-level scope."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from app.auth.deps import require_role
from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope
from app.database import get_session
from app.legacy import bridge
from app.logistics import service
from app.logistics import logibot_desk
from app.validation import require_iso_date

router = APIRouter(prefix="/api/logistics", tags=["logistics"])


def _scoped_shipments(rows: list[dict], user: User, session: Session) -> tuple[list[dict], str]:
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return rows, "全部"
    owners = {normalize_scope_key(value) for value in scope.owner_keys if normalize_scope_key(value)}
    dealers = {normalize_scope_key(value) for value in scope.dealer_names if normalize_scope_key(value)}
    filtered = [
        row for row in rows
        if normalize_scope_key(row.get("salesperson")) in owners
        or (user.role == "dealer" and normalize_scope_key(row.get("customer")) in dealers)
    ]
    return filtered, "当前权限范围"


def _load_scoped(
    date: str | None,
    salesperson: str,
    status: str,
    q: str,
    open_only: bool,
    user: User,
    session: Session,
) -> tuple[list[dict], str, str]:
    date_key = date or "all"
    rows = service.load_shipments(date_key, None, status, q, open_only)
    rows, label = _scoped_shipments(rows, user, session)
    scope = resolve_data_scope(user, session)
    if salesperson.strip() and scope.unrestricted:
        requested = service.canonical_sales_name(salesperson)
        rows = [row for row in rows if service.canonical_sales_name(row.get("salesperson", "")) == requested]
        label = requested
    return rows, label, date_key


def _scope_freight(items: list[dict], user: User, session: Session) -> tuple[list[dict], str]:
    """跨境货代按录单人隔离。经销商门店账号不开放。
    @param {list} items
    @param {User} user
    @param {Session} session
    @returns {tuple}
    """
    if user.role == "dealer":
        return [], "经销商账号不开放跨境货代"
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return items, "全部"
    owners = {normalize_scope_key(value) for value in scope.owner_keys if normalize_scope_key(value)}
    sales_name = normalize_scope_key(getattr(user, "sales_name", "") or "")
    if sales_name:
        owners.add(sales_name)
    filtered = [
        item
        for item in items
        if normalize_scope_key(item.get("salesperson")) in owners
    ]
    return filtered, "当前权限范围"


@router.get("/freight")
async def freight_desk(
    view: str = Query("all"),
    q: str = Query(""),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    """日升货代运营台：状态、异常、C 级待复核。"""
    payload = logibot_desk.load_desk()
    all_items, label = _scope_freight(payload["items"], user, session)
    items = all_items
    key = q.strip().lower()
    if key:
        items = [
            item
            for item in items
            if key
            in " ".join(
                [
                    item.get("order_no") or "",
                    item.get("sf_tracking_no") or "",
                    item.get("tracking_no") or "",
                    item.get("carrier") or "",
                    item.get("salesperson") or "",
                    item.get("consignee") or "",
                    item.get("status") or "",
                ]
            ).lower()
        ]
    if view == "review":
        items = [item for item in items if item.get("needs_review")]
    elif view == "exception":
        items = [item for item in items if item.get("exception")]
    return {
        "available": payload["available"],
        "salesperson": label,
        "role": user.role,
        "summary": logibot_desk.summarize(all_items),
        "count": len(items),
        "items": items,
    }


class FreightConfirmBody(BaseModel):
    sf_tracking_no: str
    reason: str


@router.post("/freight/confirm")
async def freight_confirm(
    body: FreightConfirmBody,
    user: Annotated[User, Depends(require_role("sales"))],
    session: Annotated[Session, Depends(get_session)],
):
    """确认 C 级/待人工关联。"""
    if not body.sf_tracking_no.strip():
        raise HTTPException(status_code=422, detail="缺少顺丰单号")
    payload = logibot_desk.load_desk()
    allowed, _label = _scope_freight(payload["items"], user, session)
    allowed_sf = {item.get("sf_tracking_no") for item in allowed}
    if body.sf_tracking_no.strip() not in allowed_sf:
        raise HTTPException(status_code=404, detail="运单不存在或无权复核")
    try:
        item = logibot_desk.confirm_row(
            body.sf_tracking_no,
            body.reason,
            getattr(user, "display_name", "") or user.username,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "item": item}


@router.get("/dates")
async def logistics_dates(
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    rows, _label = _scoped_shipments(service.load_shipments("all"), user, session)
    dates = sorted({str(row.get("record_date") or "") for row in rows if row.get("record_date")}, reverse=True)
    return {"items": dates}


@router.get("/summary")
async def logistics_summary(
    date: str | None = Query(None, description="YYYY-MM-DD 或 all 表示全部"),
    salesperson: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
    open_only: bool = Query(False),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    shipments, label, date_key = _load_scoped(date, salesperson, status, q, open_only, user, session)
    return {"date": date_key, "salesperson": label, "role": user.role, **service.build_summary(shipments)}


@router.get("/shipments")
async def logistics_shipments(
    date: str | None = Query(None),
    salesperson: str = Query(""),
    status: str = Query("all"),
    q: str = Query(""),
    open_only: bool = Query(False),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    rows, label, date_key = _load_scoped(date, salesperson, status, q, open_only, user, session)
    return {"date": date_key, "salesperson": label, "count": len(rows), "items": rows}


@router.get("/salespeople")
async def logistics_salespeople(
    user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
):
    rows, _label = _scoped_shipments(service.load_shipments("all"), user, session)
    names = sorted({service.canonical_sales_name(row.get("salesperson", "")) for row in rows if row.get("salesperson")})
    return {"items": names}


class ShipmentCreateBody(BaseModel):
    tracking_number: str
    carrier: str = ""
    customer: str = ""
    ship_date: str = ""
    expected_status: str = ""
    current_status: str = ""
    note: str = ""


@router.post("/shipments")
async def create_shipment(
    body: ShipmentCreateBody,
    user: Annotated[User, Depends(require_role("sales"))],
):
    """P2：物流单号录入（JSON API）。sales 身份由服务器锁定；manager/admin 可自由录入。"""
    if not body.tracking_number.strip():
        raise HTTPException(status_code=422, detail="物流单号不能为空")
    sales_label = ""
    if user.role == "sales":
        sales_label = (getattr(user, "sales_name", "") or "").strip()
        if not sales_label:
            raise HTTPException(status_code=403, detail="账号未配置销售数据名称，请联系管理员")
    date_text = bridge.today_text()
    ship_date = require_iso_date(body.ship_date or date_text, field="ship_date")
    try:
        tracking = service.create_shipment(
            date_text,
            {
                "tracking_number": body.tracking_number.strip(),
                "carrier": body.carrier.strip(),
                "customer": body.customer.strip(),
                "ship_date": ship_date,
                "expected_status": body.expected_status.strip(),
                "current_status": body.current_status.strip(),
                "note": body.note.strip(),
                "salesperson": sales_label,
            },
            salesperson=sales_label,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "tracking_number": tracking, "record_date": date_text, "ship_date": ship_date}


@router.post("/refresh-tracking")
async def refresh_tracking(
    _user: Annotated[User, Depends(require_role("admin"))],
):
    """Global carrier sync is an admin-only operation."""
    return await service.refresh_tracking_statuses()


@router.get("/track")
async def track_shipment(
    carrier: str = Query("", description="UPS / FedEx / DHL / SF"),
    tracking_number: str = Query("", description="运单号"),
    user: Annotated[User, Depends(require_role("viewer"))] = None,
):
    """实时查询单个运单的官网状态，不依赖 CSV 批量数据源。

    支持 UPS / FedEx / DHL（顺丰官网强制图形验证码，返回提示由人工查询）。
    """
    from app.logistics import tracking_fetch

    carrier_norm = (carrier or "").strip()
    tracking = (tracking_number or "").strip()
    base = {
        "tracking_number": tracking,
        "carrier": carrier_norm,
        "status_text": "",
        "is_delivered": False,
        "fetch_ok": False,
        "error": "",
    }
    if not tracking:
        base["error"] = "请输入运单号"
        return base
    if not tracking_fetch.is_supported_carrier(carrier_norm):
        base["error"] = "暂不支持该承运商（支持 UPS / FedEx / DHL；SF 顺丰官网需人工查询）"
        return base
    try:
        results = await tracking_fetch.fetch_many([(carrier_norm, tracking)])
    except Exception as exc:  # noqa: BLE001
        base["error"] = f"查询失败：{str(exc)[:160]}"
        return base
    if not results:
        base["error"] = "未能获取查询结果"
        return base
    r = results[0]
    return {
        "tracking_number": r.tracking_number,
        "carrier": r.carrier,
        "status_text": r.status_text,
        "is_delivered": r.is_delivered,
        "fetch_ok": r.fetch_ok,
        "error": r.error,
    }
