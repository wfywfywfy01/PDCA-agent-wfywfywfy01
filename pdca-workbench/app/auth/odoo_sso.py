# -*- coding: utf-8 -*-
"""Odoo iframe 免登：短时 HMAC 票据签发/校验。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any

import httpx
from loguru import logger

from app.config import get_settings

_SESSION_ID_RE = re.compile(r"^[0-9a-f]{20,64}$")

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


def identity_from_odoo_session(session_id: str, claimed_uid: str | int | None = None) -> dict[str, Any] | None:
    """用 Odoo `session_id` 向 admin 验身。不把 URL 里的 user_id 当身份。

    @param session_id Odoo cookie/query 中的 session_id（40 位 hex）
    @param claimed_uid 可选；若带了且与 Odoo uid 不一致则拒绝
    @returns 与 HMAC 票据同形的 identity，失败返回 None
    """
    token = (session_id or "").strip().lower()
    if not _SESSION_ID_RE.fullmatch(token):
        return None
    url = f"{get_settings().odoo_base_url}/web/session/get_session_info"
    try:
        response = httpx.post(
            url,
            json={"jsonrpc": "2.0", "method": "call", "params": {}, "id": 1},
            headers={"Cookie": f"session_id={token}", "Content-Type": "application/json"},
            timeout=8.0,
        )
        payload = response.json()
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Odoo session 校验失败: {}", type(exc).__name__)
        return None
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return None
    try:
        uid = int(result.get("uid") or 0)
    except (TypeError, ValueError):
        return None
    login = str(result.get("username") or result.get("login") or "").strip()
    if uid <= 0 or not login or login.lower() in _BLOCKED_LOGINS:
        return None
    if claimed_uid not in (None, ""):
        try:
            if int(claimed_uid) != uid:
                return None
        except (TypeError, ValueError):
            return None
    return {
        "login": login,
        "uid": uid,
        "name": str(result.get("name") or login).strip(),
        "job_title": "",
        "department_name": "",
    }
