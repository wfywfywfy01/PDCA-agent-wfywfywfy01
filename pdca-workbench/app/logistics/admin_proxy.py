# -*- coding: utf-8 -*-
"""同源挂载独立物流运营台。

物流追踪服务保留自己的 SQLite、会话和审计；PDCA 只做经过登录和角色检查的
反向代理。这样运营台可以放在 PDCA 域名下，但两个服务仍能独立发布和回滚。
"""
from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse

from app.auth.deps import get_current_user
from app.auth.models import ROLE_LEVELS, User
from app.config import get_settings

router = APIRouter(prefix="/logistics-admin", tags=["logistics-admin"])
_PREFIX = "/logistics-admin"
_DROP_RESPONSE_HEADERS = {
    "connection",
    "content-length",
    "keep-alive",
    "location",
    "transfer-encoding",
    "x-frame-options",
}
_ROOT_ATTRIBUTE = re.compile(
    r"((?:href|action|formaction|src)\s*=\s*[\"'])/(?!/|logistics-admin(?:/|[\"']))",
    flags=re.IGNORECASE,
)


def _upstream_base() -> str:
    return str(getattr(get_settings(), "logistics_admin_upstream", "") or "").rstrip("/")


def _upstream_origin(base: str) -> str:
    parsed = urlsplit(base)
    return f"{parsed.scheme}://{parsed.netloc}"


def _target_path(path: str) -> str:
    """把代理路径还原为运营台根路径，并拒绝路径穿越。"""
    parts = [part for part in path.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(status_code=400, detail="物流运营台路径无效")
    return "/" + "/".join(parts) if parts else "/"


def _required_role(path: str, method: str) -> str:
    """映射 PDCA 角色到运营台操作级别。"""
    if path in {"/login", "/logout"}:
        return "viewer"
    if path == "/users" or path.startswith("/api/users"):
        return "admin"
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        return "manager"
    return "viewer"


def _check_role(user: User, path: str, method: str) -> None:
    if user.role == "dealer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="经销商账号不能进入物流运营台")
    required = _required_role(path, method)
    if ROLE_LEVELS.get(user.role, -1) < ROLE_LEVELS.get(required, 0):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="物流运营台权限不足")


def _rewrite_location(value: str) -> str:
    if value.startswith(_PREFIX) or not value.startswith("/"):
        return value
    return _PREFIX + value


def _rewrite_set_cookie(value: str) -> str:
    # 登录 CSRF cookie 只需覆盖代理登录页；会话 cookie 也限制在运营台前缀。
    value = re.sub(r"(?i)(^|;\s*)Path=/login(?=;|$)", r"\1Path=/logistics-admin/login", value)
    return re.sub(r"(?i)(^|;\s*)Path=/(?=;|$)", r"\1Path=/logistics-admin", value)


def _rewrite_html(body: bytes, content_type: str) -> bytes:
    if "text/html" not in content_type.lower():
        return body
    text = body.decode("utf-8", errors="replace")
    text = _ROOT_ATTRIBUTE.sub(r"\1/logistics-admin/", text)
    marker = "</nav>"
    if marker in text and "/app/logistics" not in text:
        text = text.replace(
            marker,
            '<a href="/app/logistics" class="sidenav__item">返回 PDCA 物流中心</a></nav>',
            1,
        )
    return text.encode("utf-8")


def _request_headers(request: Request, origin: str) -> dict[str, str]:
    allowed = {
        "accept",
        "accept-language",
        "content-type",
        "cookie",
        "user-agent",
        "x-csrf-token",
    }
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() in allowed
    }
    raw_cookie = request.headers.get("cookie", "")
    if raw_cookie:
        # 不把 PDCA JWT、知识库重认证等本站 cookie 发送给独立物流服务。
        headers.pop("cookie", None)
        cookies = []
        for item in raw_cookie.split(";"):
            name, separator, value = item.strip().partition("=")
            if separator and name in {"logistics_session", "logistics_login_csrf"}:
                cookies.append(f"{name}={value}")
        if cookies:
            headers["Cookie"] = "; ".join(cookies)
    # httpx 自动解压响应；要求上游返回明文，避免把已解压 body 与原始
    # Content-Encoding 一起转发后让浏览器再次解压。
    headers["Accept-Encoding"] = "identity"
    # 运营台的登录 CSRF 校验要求 Origin 与 Host 同源；这里的请求由 PDCA
    # 服务端发起，所以将浏览器的 PDCA 来源转换为固定上游来源。
    if request.headers.get("origin"):
        headers["Origin"] = origin
    if request.headers.get("referer"):
        headers["Referer"] = origin + "/login"
    return headers


def _response_headers(upstream: httpx.Response, content_type: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in upstream.headers.items():
        if key.lower() == "x-frame-options":
            headers["X-Frame-Options"] = "SAMEORIGIN"
            continue
        if key.lower() in _DROP_RESPONSE_HEADERS or key.lower() == "set-cookie":
            continue
        if key.lower() == "content-type":
            headers[key] = content_type
        else:
            headers[key] = value
    return headers


@router.api_route(
    "/{path:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def proxy_logistics_admin(
    path: str,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    base = _upstream_base()
    if not base:
        raise HTTPException(status_code=503, detail="物流运营台尚未配置，请联系管理员")
    target_path = _target_path(path)
    _check_role(user, target_path, request.method)
    query = request.url.query
    target_url = f"{base}{target_path}" + (f"?{query}" if query else "")
    origin = _upstream_origin(base)
    body = await request.body() if request.method not in {"GET", "HEAD"} else None
    timeout = float(getattr(get_settings(), "logistics_admin_timeout_seconds", 15.0))
    client = httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False)
    try:
        upstream_request = client.build_request(
            request.method,
            target_url,
            headers=_request_headers(request, origin),
            content=body,
        )
        upstream = await client.send(upstream_request, stream=True)
    except (httpx.HTTPError, ValueError) as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="物流运营台暂不可达") from exc

    content_type = upstream.headers.get("content-type", "")
    response_headers = _response_headers(upstream, content_type)
    location = upstream.headers.get("location")
    if location:
        response_headers["Location"] = _rewrite_location(location)

    async def body_iterator():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    if "text/html" in content_type.lower():
        # HTML 页面很小，先读完后重写绝对根路径；静态证据文件继续流式传输。
        try:
            content = _rewrite_html(await upstream.aread(), content_type)
        finally:
            await upstream.aclose()
            await client.aclose()
        response = Response(content, status_code=upstream.status_code, headers=response_headers)
        for cookie in upstream.headers.get_list("set-cookie"):
            response.headers.append("set-cookie", _rewrite_set_cookie(cookie))
        return response

    response = StreamingResponse(
        body_iterator(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=None,
    )
    for cookie in upstream.headers.get_list("set-cookie"):
        response.headers.append("set-cookie", _rewrite_set_cookie(cookie))
    return response
