# -*- coding: utf-8 -*-
"""VPS / vertu odoo me 身份解析与本地用户映射。"""
from __future__ import annotations

import secrets
import time
from typing import Any

from loguru import logger
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.security import hash_password
from app.legacy import bridge

_VPS_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_CACHE_SECONDS = 120


def fetch_vps_me_payload() -> dict | None:
    """
    读取 vertu `odoo me` 当前登录用户。

    @returns Odoo 用户 dict，失败返回 None
    """
    now = time.time()
    cached = _VPS_CACHE.get("payload")
    if cached and now - float(_VPS_CACHE.get("ts") or 0) < _CACHE_SECONDS:
        return cached
    try:
        result = bridge.wb().fetch_vps_identity()
        if result.get("ok") and result.get("user"):
            _VPS_CACHE["ts"] = now
            _VPS_CACHE["payload"] = result["user"]
            return result["user"]
    except Exception as exc:
        logger.warning("VPS odoo me 失败: {}", exc)
    return None


def _nested(row: dict, *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if val not in (None, ""):
            return str(val).strip()
    return ""


def infer_pdca_role(vps: dict) -> str:
    """
    从 VPS 用户信息推断 PDCA 角色。

    @param vps odoo me 返回体
    """
    groups = " ".join(
        str(vps.get(k) or "")
        for k in ("groups", "group_names", "roles", "role")
    ).lower()
    job = _nested(vps, "job_title", "role", "title").lower()
    dept = _nested(vps, "department_name", "department", "dept_name").lower()
    login = _nested(vps, "login").lower()

    if any(k in groups for k in ("admin", "settings")) or vps.get("is_admin") in (True, 1, "1"):
        return "admin"
    if "manager" in groups or "主管" in job or "总监" in job or "中台" in job:
        return "manager"
    if "经销商" in dept or "销售" in job or "dealer" in groups:
        return "sales"
    if login in {"admin", "root"}:
        return "admin"
    return "manager"


def vps_display_name(vps: dict) -> str:
    """@returns 真实姓名"""
    return _nested(vps, "employee_name", "name", "display_name", "login") or "VPS 用户"


def vps_username(vps: dict) -> str:
    """@returns 本地 users.username（优先 Odoo login）"""
    login = _nested(vps, "login")
    if login:
        return login
    uid = vps.get("user_id") or vps.get("id")
    if uid:
        return f"vps-{uid}"
    return f"vps-{secrets.token_hex(4)}"


def ensure_vps_user(session: Session, vps: dict) -> User:
    """
    将 VPS 用户同步到本地 users 表（仅用于权限与展示，密码随机）。

    @param session SQLModel session
    @param vps odoo me payload
    """
    username = vps_username(vps)
    name = vps_display_name(vps)
    role = infer_pdca_role(vps)
    sales_name = name if role == "sales" else ""

    user = session.exec(select(User).where(User.username == username)).first()
    if not user:
        user = User(
            username=username,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            role=role,
            display_name=name,
            sales_name=sales_name,
            must_change_password=False,
            is_active=True,
        )
    else:
        user.display_name = name
        user.role = role
        user.sales_name = sales_name or user.sales_name
        user.is_active = True

    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def vps_profile(vps: dict) -> dict:
    """@returns 前端展示用 profile"""
    name = vps_display_name(vps)
    job = _nested(vps, "job_title", "role", "title") or _nested(vps, "department_name", "department")
    return {
        "username": vps_username(vps),
        "display_name": name,
        "sales_name": name,
        "role": infer_pdca_role(vps),
        "job_title": job,
        "vps_user_id": vps.get("user_id") or vps.get("id"),
        "login": vps.get("login"),
    }
