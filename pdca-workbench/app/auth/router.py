# -*- coding: utf-8 -*-
"""认证 API 路由（含登录限速、强制改密、token 版本号、VPS bootstrap）。"""
from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.odoo_login_map import should_refuse_odoo_sso_create
from app.auth.odoo_sso import parse_odoo_ticket, resolve_odoo_sso_secret
from app.auth.deps import ensure_portal_access, get_current_user
from app.auth.models import User
from app.auth.security import create_access_token, hash_password, revoke_token, verify_password
from app.auth.vps_identity import (
    ensure_vps_user,
    fetch_vps_me_payload,
    identity_from_headers,
    vps_display_name,
)
from app.audit import log_action
from app.config import get_settings
from app.database import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── 登录限速（内存热路径 + 数据库共享，5 次失败锁 15 分钟）─────────────────
# 内存 dict 保证单进程内零延迟；login_fail_records 表保证多 worker / 重启后
# 失败计数不丢失。数据库不可用时自动降级回纯内存实现。
_FAIL_WINDOW = 300
_MAX_FAILS = 5
_LOCKOUT_SEC = 900
_fail_log: dict[str, list[float]] = defaultdict(list)


def _db_fail_tools():
    """懒加载数据库工具，避免导入环；环境不支持时返回 None。"""
    try:
        from sqlalchemy import delete, func

        from app.auth.security_state import LoginFailRecord
        from app.database import get_engine
    except Exception:  # pragma: no cover
        return None
    return Session, LoginFailRecord, get_engine, delete, func


def _db_fail_stats(key: str, since: float) -> tuple[int, float | None]:
    """窗口内失败数与最早失败时间；数据库不可用返回 (0, None)。"""
    tools = _db_fail_tools()
    if not tools:
        return 0, None
    _, LoginFailRecord, get_engine, _, func = tools
    try:
        with Session(get_engine()) as session:
            row = session.exec(
                select(func.count(), func.min(LoginFailRecord.failed_at)).where(
                    LoginFailRecord.key == key,
                    LoginFailRecord.failed_at >= since,
                )
            ).one()
            return int(row[0] or 0), (float(row[1]) if row[1] is not None else None)
    except Exception:
        return 0, None


def _db_record_fail(key: str, now: float) -> None:
    tools = _db_fail_tools()
    if not tools:
        return
    _, LoginFailRecord, get_engine, delete, _ = tools
    try:
        with Session(get_engine()) as session:
            session.add(LoginFailRecord(key=key, failed_at=now))
            # 1/64 概率顺带清理过期记录，避免表无限增长
            if now % 64 < 1:
                session.exec(
                    delete(LoginFailRecord).where(
                        LoginFailRecord.failed_at < now - _LOCKOUT_SEC * 2
                    )
                )
            session.commit()
    except Exception:
        pass


def _db_clear_fail(key: str) -> None:
    tools = _db_fail_tools()
    if not tools:
        return
    _, LoginFailRecord, get_engine, delete, _ = tools
    try:
        with Session(get_engine()) as session:
            session.exec(delete(LoginFailRecord).where(LoginFailRecord.key == key))
            session.commit()
    except Exception:
        pass


def _client_ip(request: Request) -> str:
    """取客户端 IP：仅在请求来自已配置的可信代理时采信 X-Forwarded-For。"""
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    if not (
        settings.trust_proxy_headers
        and settings.trusted_proxy_ips
        and client_host in settings.trusted_proxy_ips
    ):
        return client_host
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return request.client.host if request.client else "unknown"


def _rate_limit_key(request: Request, username: str) -> str:
    return f"{_client_ip(request)}:{username}"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    times = _fail_log[key]
    _fail_log[key] = [t for t in times if now - t < _FAIL_WINDOW]
    db_count, db_oldest = _db_fail_stats(key, now - _FAIL_WINDOW)
    fail_count = len(_fail_log[key]) + db_count
    if fail_count >= _MAX_FAILS:
        oldest_candidates = []
        if _fail_log[key]:
            oldest_candidates.append(_fail_log[key][0])
        if db_oldest is not None:
            oldest_candidates.append(db_oldest)
        oldest = min(oldest_candidates) if oldest_candidates else now
        wait = int(_LOCKOUT_SEC - (now - oldest))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {max(wait // 60, 1)} 分钟后再试",
        )


def _record_fail(key: str) -> None:
    now = time.time()
    _fail_log[key].append(now)
    _db_record_fail(key, now)


def _clear_fail(key: str) -> None:
    _fail_log.pop(key, None)
    _db_clear_fail(key)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    username: str
    role: str
    display_name: str
    sales_name: str = ""
    owner_key: str = ""
    team_key: str = ""
    data_scope: str = ""
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.get("/config")
async def auth_config():
    """公开：前端判断 local / vps / hybrid 认证模式。"""
    settings = get_settings()
    return {
        "auth_mode": settings.auth_mode,
        "vps_login_url": settings.vps_login_url,
        "trust_proxy_headers": settings.trust_proxy_headers,
        "default_next": "/",
    }


@router.get("/vps-check")
async def vps_check(request: Request):
    """
    探测 VPS 身份是否可用（不写入本地用户）。

    仅返回是否可用与脱敏姓名，不暴露 login / role 细节。
    """
    settings = get_settings()
    proxy_client_host = request.client.host if request.client else None
    if (
        settings.trust_proxy_headers
        and settings.trusted_proxy_ips
        and proxy_client_host in settings.trusted_proxy_ips
    ):
        headers = {k.lower(): v for k, v in request.headers.items()}
        identity = identity_from_headers(headers)
        if identity:
            return {
                "ok": True,
                "source": "proxy-header",
                "profile": {"display_name": vps_display_name(identity)},
            }

    # A server-side vertu-cli session identifies the host, not the remote
    # browser. Public multi-user SSO must use trusted proxy headers.
    client_host = request.client.host if request.client else None
    if client_host not in {"127.0.0.1", "::1"}:
        return {
            "ok": False,
            "detail": "未检测到与当前访问者绑定的 VPS 身份，请使用本地账号或由管理员配置单点登录",
        }

    vps = await asyncio.to_thread(fetch_vps_me_payload)
    if not vps:
        return {"ok": False, "detail": "未检测到 Vertu 身份，请联系管理员检查 vertu-cli 服务凭据"}
    return {
        "ok": True,
        "source": "vertu-cli-hr-me",
        "profile": {"display_name": vps_display_name(vps)},
    }


def _safe_next_path(raw: str | None) -> str:
    value = (raw or "/").strip() or "/"
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _set_pdca_cookie(response: Response, token: str, *, framed: bool = False) -> None:
    settings = get_settings()
    samesite = "none" if framed else "lax"
    secure = bool(settings.secure_cookies or samesite == "none")
    response.set_cookie(
        key="pdca_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=settings.access_token_expire_minutes * 60,
    )


@router.get("/odoo-sso")
async def odoo_sso(
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
    ticket: str = "",
    next: str = "/",
):
    """消费 Odoo 短时票据，签发 pdca_token 后跳回业务页（供 iframe 免登）。"""
    secret = resolve_odoo_sso_secret()
    payload = parse_odoo_ticket(ticket, secret) if secret else None
    next_path = _safe_next_path(next)
    if not payload:
        return RedirectResponse(f"/login?next={next_path}", status_code=302)
    if should_refuse_odoo_sso_create(payload["login"]):
        return RedirectResponse(f"/login?next={next_path}", status_code=302)

    identity = {
        "login": payload["login"],
        "name": payload["name"],
        "employee_name": payload["name"],
        "display_name": payload["name"],
        "job_title": payload.get("job_title") or "",
        "department_name": payload.get("department_name") or "",
        "user_id": payload["uid"],
        "_source": "odoo-sso",
    }
    user = await asyncio.to_thread(ensure_vps_user, session, identity)
    ensure_portal_access(user)
    log_action(user.username, "odoo_sso", ip=_client_ip(request))
    pwd_v = getattr(user, "pwd_version", 0) or 0
    settings = get_settings()
    token = create_access_token(
        {"sub": user.username, "role": user.role, "pwd_v": pwd_v},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    redirect = RedirectResponse(next_path, status_code=302)
    _set_pdca_cookie(redirect, token, framed=True)
    return redirect


@router.post("/vps-bootstrap")
async def vps_bootstrap(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
):
    """
    VPS/hybrid 模式下签发 pdca_token Cookie，避免页面与 API 鉴权不一致。
    """
    settings = get_settings()
    if settings.auth_mode not in ("vps", "hybrid"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前非 VPS 认证模式")
    pwd_v = getattr(user, "pwd_version", 0) or 0
    token = create_access_token(
        {"sub": user.username, "role": user.role, "pwd_v": pwd_v},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    response.set_cookie(
        key="pdca_token",
        value=token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    return {
        "ok": True,
        "access_token": token,
        "user": UserOut(
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            sales_name=getattr(user, "sales_name", "") or "",
            owner_key=getattr(user, "owner_key", "") or "",
            team_key=getattr(user, "team_key", "") or "",
            data_scope=getattr(user, "data_scope", "") or "",
            must_change_password=False,
        ),
    }


@router.post("/login")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Annotated[Session, Depends(get_session)],
):
    """登录并设置 httpOnly Cookie。"""
    settings = get_settings()
    if settings.auth_mode == "vps":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="当前为 VPS 单点登录模式，请使用 VPS/Odoo 账号登录，无需本地账号",
        )
    key = _rate_limit_key(request, body.username)
    _check_rate_limit(key)

    user = session.exec(select(User).where(User.username == body.username)).first()
    if not user or not verify_password(body.password, user.hashed_password):
        _record_fail(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已停用")

    _clear_fail(key)
    ensure_portal_access(user)
    log_action(user.username, "login", ip=_client_ip(request))
    pwd_v = getattr(user, "pwd_version", 0) or 0
    token = create_access_token(
        {"sub": user.username, "role": user.role, "pwd_v": pwd_v},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    response.set_cookie(
        key="pdca_token",
        value=token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    must_change = getattr(user, "must_change_password", False)
    return {
        "access_token": token,
        "token_type": "bearer",
        "must_change_password": must_change,
        "user": UserOut(
            username=user.username,
            role=user.role,
            display_name=user.display_name,
            sales_name=getattr(user, "sales_name", "") or "",
            owner_key=getattr(user, "owner_key", "") or "",
            team_key=getattr(user, "team_key", "") or "",
            data_scope=getattr(user, "data_scope", "") or "",
            must_change_password=must_change,
        ),
    }


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    pdca_token: Annotated[str | None, Cookie()] = None,
):
    settings = get_settings()

    token = pdca_token
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            token = auth[len("Bearer ") :]
    if token:
        revoke_token(token)

    response.delete_cookie(
        "pdca_token",
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return UserOut(
        username=user.username,
        role=user.role,
        display_name=user.display_name,
        sales_name=getattr(user, "sales_name", "") or "",
        owner_key=getattr(user, "owner_key", "") or "",
        team_key=getattr(user, "team_key", "") or "",
        data_scope=getattr(user, "data_scope", "") or "",
        must_change_password=getattr(user, "must_change_password", False),
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    """修改密码：验旧密 → 更新 + 递增 pwd_version + 签发新 token。"""
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if len(body.new_password) < 12:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 12 位")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")

    user.hashed_password = hash_password(body.new_password)
    user.pwd_version = (getattr(user, "pwd_version", 0) or 0) + 1
    user.must_change_password = False
    session.add(user)
    session.commit()
    session.refresh(user)

    settings = get_settings()
    new_token = create_access_token(
        {"sub": user.username, "role": user.role, "pwd_v": user.pwd_version},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    response.set_cookie(
        key="pdca_token",
        value=new_token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
    )
    log_action(user.username, "change_password", ip=_client_ip(request))
    return {"ok": True, "message": "密码已修改", "access_token": new_token}
