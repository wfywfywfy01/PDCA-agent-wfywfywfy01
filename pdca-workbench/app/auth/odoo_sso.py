# -*- coding: utf-8 -*-
"""Odoo iframe 免登：短时 HMAC 票据签发/校验。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.config import get_settings

_TICKET_TTL_SECONDS = 120
_BLOCKED_LOGINS = {"public", "__system__", "portaltemplateuser"}


def resolve_odoo_sso_secret() -> str:
    """优先环境变量，其次 data/odoo_sso_secret，都没有则关闭 SSO。"""
    settings = get_settings()
    env_secret = (getattr(settings, "odoo_sso_secret", "") or "").strip()
    if env_secret:
        return env_secret
    path = settings.data_dir / "odoo_sso_secret"
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    except OSError:
        pass
    return ""


def issue_odoo_ticket(
    *,
    login: str,
    uid: int,
    name: str,
    job_title: str = "",
    department_name: str = "",
    secret: str,
    ttl: int = _TICKET_TTL_SECONDS,
) -> str:
    """签发 `body.hex_hmac` 票据。"""
    payload = {
        "login": str(login).strip(),
        "uid": int(uid),
        "name": str(name or "").strip(),
        "job_title": str(job_title or "").strip(),
        "department_name": str(department_name or "").strip(),
        "exp": int(time.time()) + int(ttl),
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_odoo_ticket(ticket: str, secret: str) -> dict[str, Any] | None:
    """校验签名与过期时间。非法返回 None。"""
    normalized = (ticket or "").strip()
    if "." not in normalized or len(normalized) > 2048:
        return None
    body, _, sig = normalized.partition(".")
    if not body or not sig:
        return None
    expect = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(body + pad).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        exp = int(payload.get("exp") or 0)
        uid = int(payload.get("uid") or 0)
    except (TypeError, ValueError):
        return None
    login = str(payload.get("login") or "").strip()
    if exp < int(time.time()) or uid <= 0 or not login:
        return None
    if login.lower() in _BLOCKED_LOGINS:
        return None
    payload["login"] = login
    payload["uid"] = uid
    payload["name"] = str(payload.get("name") or login).strip()
    payload["job_title"] = str(payload.get("job_title") or "").strip()
    payload["department_name"] = str(payload.get("department_name") or "").strip()
    return payload
