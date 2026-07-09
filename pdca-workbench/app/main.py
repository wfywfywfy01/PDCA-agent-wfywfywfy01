# -*- coding: utf-8 -*-
"""FastAPI 应用入口。"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from loguru import logger

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.auth.seed import seed_users
from app.config import get_settings
from app.dashboard.router import router as dashboard_router
from app.database import bootstrap_database, get_db_mode
from app.logging_setup import setup_logging
from app.logistics.router import router as logistics_router
from app.pages.router import router as pages_router
from app.files.router import router as files_router
from app.pdca.post_router import router as pdca_post_router
from app.pdca.router import router as pdca_router
from app.scheduler.jobs import start_scheduler, stop_scheduler
from app.export.router import router as export_router
from app.walkin.router import router as walkin_router

PUBLIC_PATHS = {
    "/login",
    "/api/auth/login",
    "/api/auth/config",
    "/api/auth/vps-check",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
    "/dashboard-theme.css",
    "/workbench-cockpit-shell.css",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭生命周期。"""
    setup_logging()
    settings = get_settings()
    os.environ["VERTU_COMMAND"] = settings.vertu_command
    if "dev-secret" in settings.secret_key or "change" in settings.secret_key.lower():
        logger.warning("⚠️  PDCA_SECRET_KEY 使用开发占位符，生产环境请在 .env 中设置强密钥！")
    mode = bootstrap_database()
    seed_users()
    from app.models.store_seed import seed_stores
    seed_stores()
    start_scheduler()
    logger.info(
        "PDCA 工作台已启动 {}:{} db_mode={} MVP={} auth_mode={}",
        settings.host,
        settings.port,
        mode,
        settings.mvp_root,
        settings.auth_mode,
    )
    yield
    stop_scheduler()
    logger.info("PDCA 工作台已关闭")


app = FastAPI(
    title="PDCA 工作台",
    description="经销商 PDCA 本地多角色生产环境（PostgreSQL）",
    version="1.0.0",
    lifespan=lifespan,
)

_settings0 = get_settings()
_cors_origins = _settings0.cors_origins or ["*"]
# credentials + "*" 浏览器会拒；有显式白名单时才开 credentials
_cors_credentials = bool(_settings0.cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_redirect_middleware(request: Request, call_next):
    """未登录访问页面时跳转登录（API 返回 401）。"""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/shared/"):
        return await call_next(request)
    if path.startswith("/api/") and path != "/api/auth/login":
        return await call_next(request)
    if path.startswith("/walkin-cockpit/") and not path.endswith(".html"):
        return await call_next(request)
    if path.startswith("/meeting-center/") and "." in path.split("/")[-1]:
        return await call_next(request)

    settings = get_settings()
    # vps/hybrid：页面放行，由路由 Depends(get_current_user) 鉴权
    if settings.auth_mode in ("vps", "hybrid"):
        return await call_next(request)

    token = request.cookies.get("pdca_token")
    auth = request.headers.get("authorization", "")
    if not token and not auth.startswith("Bearer "):
        if path.startswith("/api/"):
            return JSONResponse({"detail": "未登录"}, status_code=401)
        if not path.startswith(("/login",)):
            return RedirectResponse(f"/login?next={path}")
    return await call_next(request)


_404_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>页面不存在 · PDCA 工作台</title>
<style>body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f1f5f9}
.box{text-align:center;padding:48px;background:#fff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08)}
h1{font-size:48px;margin:0;color:#2563eb}p{color:#64748b}a{color:#2563eb}</style>
</head><body><div class="box"><h1>404</h1><p>页面不存在</p><a href="/">返回首页</a></div></body></html>"""

_500_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>服务异常 · PDCA 工作台</title>
<style>body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#f1f5f9}
.box{text-align:center;padding:48px;background:#fff;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08)}
h1{font-size:48px;margin:0;color:#dc2626}p{color:#64748b}a{color:#2563eb}</style>
</head><body><div class="box"><h1>500</h1><p>服务内部错误，请稍后重试或联系管理员。</p><a href="/">返回首页</a></div></body></html>"""


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    if exc.status_code == 404:
        return HTMLResponse(_404_HTML, status_code=404)
    if exc.status_code in (401, 403):
        next_path = request.url.path
        return RedirectResponse(f"/login?next={next_path}")
    return HTMLResponse(_500_HTML, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse({"detail": "请求参数有误", "errors": exc.errors()}, status_code=422)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常 {} {}: {}", request.method, request.url.path, exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "服务内部错误"}, status_code=500)
    return HTMLResponse(_500_HTML, status_code=500)


app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(walkin_router)
app.include_router(logistics_router)
app.include_router(pdca_router)
app.include_router(pdca_post_router)
app.include_router(files_router)
app.include_router(admin_router)
app.include_router(export_router)
app.include_router(pages_router)


@app.get("/health")
async def health():
    """健康检查（含数据库连通性）。"""
    mode = get_db_mode()
    db_ok = mode in ("postgresql", "sqlite", "sqlite-fallback")
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "pdca-workbench",
        "database": mode,
        "database_connected": db_ok,
    }
