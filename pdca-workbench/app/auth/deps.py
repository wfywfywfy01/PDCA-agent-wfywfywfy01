# -*- coding: utf-8 -*-
"""认证依赖注入与角色校验。"""
from __future__ import annotations

import asyncio
from typing import Annotated, Callable

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session, select

from app.auth.models import ROLE_LEVELS, User
from app.auth.security import decode_token
from app.auth.vps_identity import (
    ensure_vps_user,
    fetch_vps_me_payload,
    identity_from_headers,
)
from app.config import get_settings
from app.database import get_session

bearer_scheme = HTTPBearer(auto_error=False)


def _role_level(role: str) -> int:
    return ROLE_LEVELS.get(role, -1)


async def _user_from_jwt(
    session: Session,
    token: str | None,
) -> User | None:
    if not token:
        return None
    payload = decode_token(token)
    if not payload or "sub" not in payload:
        return None
    username = payload["sub"]
    user = session.exec(select(User).where(User.username == username)).first()
    if not user or not user.is_active:
        return None
    token_pwd_v = payload.get("pwd_v", 0)
    user_pwd_v = getattr(user, "pwd_version", 0) or 0
    if token_pwd_v != user_pwd_v:
        return None
    return user


async def _user_from_proxy_headers(session: Session, request: Request) -> User | None:
    """反向代理注入 Header → 本地用户。"""
    settings = get_settings()
    if not settings.trust_proxy_headers:
        return None
    headers = {k.lower(): v for k, v in request.headers.items()}
    identity = identity_from_headers(headers)
    if not identity:
        return None
    return await asyncio.to_thread(ensure_vps_user, session, identity)


async def _user_from_vps(session: Session) -> User | None:
    """通过 vertu odoo me 解析当前 VPS 登录用户（服务端会话）。"""
    vps = await asyncio.to_thread(fetch_vps_me_payload)
    if not vps:
        return None
    return await asyncio.to_thread(ensure_vps_user, session, vps)


async def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    pdca_token: Annotated[str | None, Cookie()] = None,
) -> User:
    """
    解析当前用户，优先级：
    1. 反向代理 Header（多用户生产）
    2. JWT Cookie / Bearer（local / hybrid）
    3. 服务端 vertu odoo me（vps / hybrid 兜底）
    """
    settings = get_settings()
    mode = settings.auth_mode
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif pdca_token:
        token = pdca_token

    # 1) 代理 Header（所有模式均可，需显式开启）
    proxy_user = await _user_from_proxy_headers(session, request)
    if proxy_user:
        return proxy_user

    # 2) JWT
    if mode in ("hybrid", "local"):
        user = await _user_from_jwt(session, token)
        if user:
            return user
        if mode == "local":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")

    # 3) 服务端 vertu 会话
    if mode in ("vps", "hybrid"):
        user = await _user_from_vps(session)
        if user:
            return user

    if mode == "vps":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未检测到 VPS 登录，请先在 VPS/Odoo 完成登录（vertu login）",
        )
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")


def require_role(min_role: str) -> Callable:
    """返回要求最低角色的依赖。"""

    async def _checker(user: Annotated[User, Depends(get_current_user)]) -> User:
        if _role_level(user.role) < _role_level(min_role):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _checker


def can_write(user: User) -> bool:
    return _role_level(user.role) >= _role_level("sales")


def can_manage(user: User) -> bool:
    return _role_level(user.role) >= _role_level("manager")


def is_admin(user: User) -> bool:
    return user.role == "admin"
