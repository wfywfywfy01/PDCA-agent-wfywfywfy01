# -*- coding: utf-8 -*-
"""签发短时 HMAC 票据并跳转到 PDCA。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote, urlencode

from odoo import http
from odoo.http import request

PDCA_BASE = "https://pdca-workbench.vertu.cn"


class PdcaEmbedController(http.Controller):
    @http.route("/pdca/embed", type="http", auth="user", sitemap=False)
    def embed(self, next="/", **_kw):
        """iframe 入口：已登录则带票据跳 PDCA，未登录由 Odoo 先出登录页。"""
        user = request.env.user
        secret = (
            request.env["ir.config_parameter"].sudo().get_param("pdca.sso_secret") or ""
        ).strip()
        next_path = next if isinstance(next, str) and next.startswith("/") and not next.startswith("//") else "/"
        if not secret or user._is_public():
            return request.redirect(f"{PDCA_BASE}/login?next={quote(next_path)}")

        job = ""
        dept = ""
        employee = getattr(user, "employee_id", False)
        if employee:
            job = employee.job_id.name or ""
            dept = employee.department_id.name or ""

        payload = json.dumps(
            {
                "login": user.login,
                "uid": user.id,
                "name": user.name or user.login,
                "job_title": job,
                "department_name": dept,
                "exp": int(time.time()) + 120,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        body = base64.urlsafe_b64encode(payload.encode("utf-8")).rstrip(b"=").decode("ascii")
        sig = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
        query = urlencode({"ticket": f"{body}.{sig}", "next": next_path})
        return request.redirect(f"{PDCA_BASE}/api/auth/odoo-sso?{query}")
