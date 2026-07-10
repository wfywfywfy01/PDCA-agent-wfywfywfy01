# -*- coding: utf-8 -*-
"""管理员 API：用户管理、门店管理、月度目标、审计日志、系统操作。"""
from __future__ import annotations

import re
import traceback
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.audit import log_action
from app.auth.deps import require_role
from app.auth.models import ROLE_LEVELS, User
from app.config import get_settings
from app.database import check_db_connection, get_db_mode, get_session
from app.legacy import bridge
from app.models.audit_log import AuditLog
from app.models.dealer_store import DealerStore
from app.models.monthly_target import MonthlyTarget
from app.models.sync import run_full_sync, sync_dealer_sales_from_vps
from app.scheduler.jobs import backup_database, daily_sync_job

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ── 部署自检 ───────────────────────────────────────────────────────────────────

@router.get("/diagnostics")
async def diagnostics(_user: Annotated[User, Depends(require_role("admin"))] = None):
    """一次性自检：MVP 模块目录 / 数据库连通性 / 关键配置，方便远程排障无需登服务器。"""
    settings = get_settings()

    module_dirs = {
        "home_dashboard": settings.home_dashboard_dir,
        "walkin_cockpit": settings.walkin_cockpit_dir,
        "meeting_center": settings.meeting_center_dir,
        "logistics_center": settings.logistics_center_dir,
        "onboarding_center": settings.onboarding_center_dir,
        "signalseller_center": settings.signalseller_center_dir,
    }
    modules = {
        name: {
            "path": str(path),
            "dir_exists": path.is_dir(),
            "index_html_exists": (path / "index.html").is_file(),
        }
        for name, path in module_dirs.items()
    }

    scripts_candidates = {
        "mvp_scripts_dir": settings.scripts_dir,
        "repo_scripts_dir": settings.repo_root / "scripts",
    }
    legacy_scripts = {
        name: {
            "path": str(path),
            "dir_exists": path.is_dir(),
            "pdca_workbench_py_exists": (path / "pdca_workbench.py").is_file(),
        }
        for name, path in scripts_candidates.items()
    }

    # 直接探测遗留 pdca_workbench.py 能否加载（不走 bridge.today_text() 的兜底逻辑），
    # 捕获真实异常堆栈——这是 /walkin-cockpit、/logistics-center 等模块报错的根因来源。
    legacy_bridge_probe: dict = {"ok": False, "error": None, "traceback": None}
    try:
        wb_module = bridge.wb()
        legacy_bridge_probe = {"ok": True, "today_text": wb_module.today_text()}
    except Exception as exc:  # noqa: BLE001
        legacy_bridge_probe = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=6),
        }

    return {
        "mvp_root": str(settings.mvp_root),
        "mvp_root_exists": settings.mvp_root.is_dir(),
        "repo_root": str(settings.repo_root),
        "repo_root_exists": settings.repo_root.is_dir(),
        "modules": modules,
        "legacy_scripts": legacy_scripts,
        "legacy_bridge_probe": legacy_bridge_probe,
        "database": {
            "mode": get_db_mode(),
            "connected": check_db_connection(),
            "pg_host": settings.pg_host,
            "pg_database": settings.pg_database,
        },
        "auth_mode": settings.auth_mode,
        "cors_origins": settings.cors_origins,
        "secure_cookies": settings.secure_cookies,
        "trust_proxy_headers": settings.trust_proxy_headers,
        "vps_login_url": settings.vps_login_url,
    }


# ── 系统操作 ───────────────────────────────────────────────────────────────────

@router.post("/sync")
async def trigger_sync(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
):
    return run_full_sync(date or bridge.today_text())


@router.post("/sync-vps-sellout")
async def trigger_vps_sellout_sync(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """手动触发 VPS 手机 Sell-out + 激活率同步。"""
    date_text = date or bridge.today_text()
    count = sync_dealer_sales_from_vps(date_text)
    return {"ok": True, "date": date_text, "synced": count}


@router.post("/backup")
async def trigger_backup(_user: Annotated[User, Depends(require_role("admin"))] = None):
    path = backup_database()
    return {"ok": bool(path), "path": path}


@router.post("/run-daily-job")
async def run_daily(_user: Annotated[User, Depends(require_role("admin"))] = None):
    daily_sync_job()
    return {"ok": True}


# ── 用户管理 ───────────────────────────────────────────────────────────────────

class UserCreateBody(BaseModel):
    username: str
    password: str
    role: str = "sales"
    display_name: str = ""
    sales_name: str = ""
    dealer_id: str = ""       # dealer角色专用：绑定的门店store_id


class UserUpdateBody(BaseModel):
    display_name: str | None = None
    sales_name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    dealer_id: str | None = None  # dealer角色绑定门店


class ResetPasswordBody(BaseModel):
    new_password: str


@router.get("/users")
async def list_users(
    _user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
):
    users = session.exec(select(User).order_by(User.id)).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "display_name": u.display_name,
            "sales_name": u.sales_name,
            "dealer_id": getattr(u, "dealer_id", "") or "",
            "is_active": u.is_active,
            "must_change_password": getattr(u, "must_change_password", False),
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in users
    ]


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreateBody,
    current_user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
):
    from app.auth.security import hash_password as hp

    if body.role not in ROLE_LEVELS:
        raise HTTPException(status_code=400, detail=f"无效角色，可选：{list(ROLE_LEVELS)}")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    if session.exec(select(User).where(User.username == body.username)).first():
        raise HTTPException(status_code=409, detail="用户名已存在")
    new_user = User(
        username=body.username.strip(),
        hashed_password=hp(body.password),
        role=body.role,
        display_name=body.display_name.strip(),
        sales_name=body.sales_name.strip(),
        dealer_id=body.dealer_id.strip(),
        must_change_password=True,
        pwd_version=0,
    )
    session.add(new_user)
    session.commit()
    session.refresh(new_user)
    log_action(current_user.username, "create_user", resource=body.username)
    return {"ok": True, "id": new_user.id, "username": new_user.username}


@router.patch("/users/{username}")
async def update_user(
    username: str,
    body: UserUpdateBody,
    current_user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
):
    target = session.exec(select(User).where(User.username == username)).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    if body.role is not None:
        if body.role not in ROLE_LEVELS:
            raise HTTPException(status_code=400, detail=f"无效角色")
        target.role = body.role
    if body.display_name is not None:
        target.display_name = body.display_name.strip()
    if body.sales_name is not None:
        target.sales_name = body.sales_name.strip()
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.dealer_id is not None:
        target.dealer_id = body.dealer_id.strip()
    session.add(target)
    session.commit()
    log_action(current_user.username, "update_user", resource=username, detail=body.model_dump(exclude_none=True))
    return {"ok": True}


@router.post("/users/{username}/reset-password")
async def reset_password(
    username: str,
    body: ResetPasswordBody,
    current_user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
):
    from app.auth.security import hash_password as hp

    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="密码至少 8 位")
    target = session.exec(select(User).where(User.username == username)).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.hashed_password = hp(body.new_password)
    target.pwd_version = (getattr(target, "pwd_version", 0) or 0) + 1
    target.must_change_password = True
    session.add(target)
    session.commit()
    log_action(current_user.username, "reset_password", resource=username)
    return {"ok": True, "message": f"用户 {username} 密码已重置，下次登录须改密"}


@router.delete("/users/{username}")
async def deactivate_user(
    username: str,
    current_user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
):
    if username == current_user.username:
        raise HTTPException(status_code=400, detail="不能停用当前登录账号")
    target = session.exec(select(User).where(User.username == username)).first()
    if not target:
        raise HTTPException(status_code=404, detail="用户不存在")
    target.is_active = False
    session.add(target)
    session.commit()
    log_action(current_user.username, "deactivate_user", resource=username)
    return {"ok": True}


# ── 门店管理 ───────────────────────────────────────────────────────────────────

class StoreCreateBody(BaseModel):
    store_id: str
    name: str
    region: str = ""
    country: str = ""
    dealer_level: str = "L1"
    sales_owner: str = ""


class StoreUpdateBody(BaseModel):
    name: str | None = None
    region: str | None = None
    country: str | None = None
    dealer_level: str | None = None
    sales_owner: str | None = None
    is_active: bool | None = None
    sort_order: int | None = None


@router.get("/stores")
async def list_stores(
    _user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
    include_inactive: bool = Query(False),
):
    """列出所有门店（manager 及以上，含 sales_owner 等完整字段）。"""
    stmt = select(DealerStore).order_by(DealerStore.region, DealerStore.sort_order, DealerStore.store_id)
    if not include_inactive:
        stmt = stmt.where(DealerStore.is_active == True)
    stores = session.exec(stmt).all()
    return [
        {
            "store_id": s.store_id,
            "name": s.name,
            "region": s.region,
            "country": s.country,
            "dealer_level": getattr(s, "dealer_level", "L1") or "L1",
            "sales_owner": getattr(s, "sales_owner", "") or "",
            "is_active": s.is_active,
            "sort_order": s.sort_order,
        }
        for s in stores
    ]


@router.post("/stores", status_code=201)
async def create_store(
    body: StoreCreateBody,
    current_user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
):
    if not body.store_id.strip():
        raise HTTPException(status_code=422, detail="store_id 不能为空")
    if session.exec(select(DealerStore).where(DealerStore.store_id == body.store_id)).first():
        raise HTTPException(status_code=409, detail="门店 ID 已存在")
    session.add(DealerStore(
        store_id=body.store_id.strip(),
        name=body.name.strip(),
        region=body.region.strip(),
        country=body.country.strip(),
        dealer_level=body.dealer_level.strip() or "L1",
        sales_owner=body.sales_owner.strip(),
    ))
    session.commit()
    log_action(current_user.username, "create_store", resource=body.store_id)
    return {"ok": True}


@router.patch("/stores/{store_id}")
async def update_store(
    store_id: str,
    body: StoreUpdateBody,
    current_user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
):
    store = session.exec(select(DealerStore).where(DealerStore.store_id == store_id)).first()
    if not store:
        raise HTTPException(status_code=404, detail="门店不存在")
    if body.name is not None:
        store.name = body.name.strip()
    if body.region is not None:
        store.region = body.region.strip()
    if body.country is not None:
        store.country = body.country.strip()
    if body.dealer_level is not None:
        store.dealer_level = body.dealer_level.strip()
    if body.sales_owner is not None:
        store.sales_owner = body.sales_owner.strip()
    if body.is_active is not None:
        store.is_active = body.is_active
    if body.sort_order is not None:
        store.sort_order = body.sort_order
    session.add(store)
    session.commit()
    log_action(current_user.username, "update_store", resource=store_id,
               detail=body.model_dump(exclude_none=True))
    return {"ok": True}


# ── 月度目标 ───────────────────────────────────────────────────────────────────

class TargetUpsertBody(BaseModel):
    month: str                       # YYYY-MM
    dealer_id: str = ""              # 空 = 全局
    sell_out_target_yuan: float = 0.0
    visit_target: int = 0
    deal_target: int = 0
    add_rate_target: float = 0.35


@router.get("/targets")
async def list_targets(
    _user: Annotated[User, Depends(require_role("viewer"))],
    session: Annotated[Session, Depends(get_session)],
    month: str = Query(""),
):
    stmt = select(MonthlyTarget)
    if month:
        stmt = stmt.where(MonthlyTarget.month == month)
    rows = session.exec(stmt.order_by(MonthlyTarget.month.desc())).all()
    return [
        {
            "id": r.id,
            "month": r.month,
            "dealer_id": r.dealer_id,
            "sell_out_target_yuan": r.sell_out_target_yuan,
            "sell_out_target_wan": round(r.sell_out_target_yuan / 10000, 2),
            "visit_target": r.visit_target,
            "deal_target": r.deal_target,
            "add_rate_target": r.add_rate_target,
            "created_by": r.created_by,
        }
        for r in rows
    ]


@router.put("/targets")
async def upsert_target(
    body: TargetUpsertBody,
    current_user: Annotated[User, Depends(require_role("manager"))],
    session: Annotated[Session, Depends(get_session)],
):
    if not re.fullmatch(r"\d{4}-\d{2}", body.month):
        raise HTTPException(status_code=422, detail="month 格式应为 YYYY-MM")
    existing = session.exec(
        select(MonthlyTarget).where(
            MonthlyTarget.month == body.month,
            MonthlyTarget.dealer_id == body.dealer_id,
        )
    ).first()
    if existing:
        existing.sell_out_target_yuan = body.sell_out_target_yuan
        existing.visit_target = body.visit_target
        existing.deal_target = body.deal_target
        existing.add_rate_target = body.add_rate_target
        existing.updated_at = datetime.utcnow()
        existing.created_by = current_user.username
        session.add(existing)
    else:
        session.add(MonthlyTarget(
            month=body.month,
            dealer_id=body.dealer_id,
            sell_out_target_yuan=body.sell_out_target_yuan,
            visit_target=body.visit_target,
            deal_target=body.deal_target,
            add_rate_target=body.add_rate_target,
            created_by=current_user.username,
        ))
    session.commit()
    log_action(current_user.username, "upsert_target",
               resource=f"{body.month}:{body.dealer_id or 'global'}",
               detail={"sell_out_wan": round(body.sell_out_target_yuan / 10000, 2)})
    return {"ok": True}


# ── 审计日志 ───────────────────────────────────────────────────────────────────

@router.get("/audit-logs")
async def list_audit_logs(
    _user: Annotated[User, Depends(require_role("admin"))],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(200, le=1000),
    username: str = Query(""),
    action: str = Query(""),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if username:
        stmt = stmt.where(AuditLog.username == username)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    rows = session.exec(stmt).all()
    return [
        {
            "id": r.id,
            "username": r.username,
            "action": r.action,
            "resource": r.resource,
            "detail": r.detail,
            "ip": r.ip,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in rows
    ]
