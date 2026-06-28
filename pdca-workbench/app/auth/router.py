# -*- coding: utf-8 -*-
"""认证 API 路由（含登录限速、强制改密、token 版本号）。"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.security import create_access_token, hash_password, verify_password
from app.audit import log_action
from app.config import get_settings
from app.database import get_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ── 登录限速（内存，5 次失败锁 15 分钟）──────────────────────────────────────
_FAIL_WINDOW = 300       # 5 分钟内
_MAX_FAILS   = 5
_LOCKOUT_SEC = 900       # 锁定 15 分钟

# {key: [(timestamp, ...), ...]}
_fail_log: dict[str, list[float]] = defaultdict(list)


def _rate_limit_key(request: Request, username: str) -> str:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "unknown")
    return f"{ip}:{username}"


def _check_rate_limit(key: str) -> None:
    now = time.time()
    times = _fail_log[key]
    # 清理超出窗口的记录
    _fail_log[key] = [t for t in times if now - t < _FAIL_WINDOW]
    if len(_fail_log[key]) >= _MAX_FAILS:
        wait = int(_LOCKOUT_SEC - (now - _fail_log[key][0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"登录失败次数过多，请 {max(wait//60,1)} 分钟后再试",
        )


def _record_fail(key: str) -> None:
    _fail_log[key].append(time.time())


def _clear_fail(key: str) -> None:
    _fail_log.pop(key, None)


# ── 请求体 ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    username: str
    role: str
    display_name: str
    sales_name: str = ""
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ── 端点 ──────────────────────────────────────────────────────────────────────

@router.get("/config")
async def auth_config():
    """公开：前端判断 local / vps / hybrid 认证模式。"""
    settings = get_settings()
    return {
        "auth_mode": settings.auth_mode,
        "vps_login_url": settings.vps_login_url,
    }


@router.get("/vps-check")
async def vps_check():
    """公开：探测 vertu odoo me 是否可用（不写入本地用户）。"""
    import asyncio

    from app.auth.vps_identity import fetch_vps_me_payload, vps_profile

    vps = await asyncio.to_thread(fetch_vps_me_payload)
    if not vps:
        return {"ok": False, "detail": "未检测到 VPS 登录，请先 vertu login / 登录 Odoo"}
    return {"ok": True, "profile": vps_profile(vps)}


@router.post("/vps-bootstrap")
async def vps_bootstrap(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
):
    """
    VPS/hybrid 模式下签发 pdca_token Cookie，避免页面与 API 鉴权不一致。

    需已通过 vertu odoo me 或本地 JWT 完成 get_current_user。
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
    log_action(user.username, "login", ip=request.client.host if request.client else "")
    settings = get_settings()
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
            must_change_password=must_change,
        ),
    }


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("pdca_token")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    import asyncio

    from app.auth.vps_identity import fetch_vps_me_payload, vps_display_name, vps_profile
    from app.config import get_settings

    settings = get_settings()
    display = user.display_name
    if settings.auth_mode in ("vps", "hybrid"):
        vps = await asyncio.to_thread(fetch_vps_me_payload)
        if vps:
            prof = vps_profile(vps)
            display = prof.get("display_name") or vps_display_name(vps)
    return UserOut(
        username=user.username,
        role=user.role,
        display_name=display,
        sales_name=getattr(user, "sales_name", "") or "",
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
    """修改密码：验旧密 → 更新 + 递增 pwd_version（令旧 token 失效）+ 签发新 token。"""
    if not verify_password(body.old_password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 8 位")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")

    user.hashed_password = hash_password(body.new_password)
    user.pwd_version = (getattr(user, "pwd_version", 0) or 0) + 1
    user.must_change_password = False
    session.add(user)
    session.commit()
    session.refresh(user)

    # 签发包含新 pwd_version 的 token，让前端无缝续期
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
    log_action(user.username, "change_password", ip=request.client.host if request.client else "")
    return {"ok": True, "message": "密码已修改", "access_token": new_token}
