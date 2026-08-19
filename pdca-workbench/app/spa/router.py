# -*- coding: utf-8 -*-
"""Vue3 SPA 托管（P1）：/app 下提供构建产物，未知路径回退 index.html。

渐进切换策略：新前端先挂在 /app 下与现有页面共存；各模块页面迁移完成后，
再把 / 重定向到 /app（经现有 PDCA_HOME_REDIRECT 配置）并退役旧页面路由。
"""
from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from app.config import get_settings

router = APIRouter(tags=["spa"])

_INDEX = "index.html"
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


def _dist() -> Path:
    return get_settings().spa_dist_dir


def _index_file() -> Path | None:
    index = _dist() / _INDEX
    return index if index.is_file() else None


def _not_built() -> HTMLResponse:
    html = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>前端未构建 · PDCA 工作台</title>
<style>body{font-family:system-ui,sans-serif;background:#0b0d13;color:#94a3b8;display:flex;
align-items:center;justify-content:center;min-height:100vh;margin:0}
.box{text-align:center;padding:48px}h1{color:#4e9ef5;font-size:24px}</style></head>
<body><div class="box"><h1>⚙️ 前端应用未构建</h1>
<p>本部署未包含 Vue3 前端产物（apps/web/dist 或镜像内 spa-dist）。<br>
开发环境请运行 <code>cd apps/web && npm install && npm run build</code>。</p></div></body></html>"""
    return HTMLResponse(html, status_code=200)


def _serve_index() -> FileResponse:
    return FileResponse(
        _index_file(),  # type: ignore[arg-type]  # 调用方已保证存在
        media_type="text/html; charset=utf-8",
        headers=_NO_CACHE,
    )


@router.get("/app", include_in_schema=False, response_model=None)
@router.get("/app/", include_in_schema=False, response_model=None)
async def spa_root():
    if not _index_file():
        return _not_built()
    return _serve_index()


@router.get("/app/{rel_path:path}", include_in_schema=False, response_model=None)
async def spa_path(rel_path: str):
    index = _index_file()
    if not index:
        return _not_built()
    if not rel_path or rel_path.endswith("/"):
        return _serve_index()
    dist = _dist().resolve()
    target = (dist / rel_path).resolve()
    if not str(target).startswith(str(dist) + "\\") and not str(target).startswith(str(dist) + "/"):
        return _serve_index()
    if not target.is_file():
        # SPA 客户端路由（/app/login 等）回退 index.html
        return _serve_index()
    media, _ = mimetypes.guess_type(str(target))
    headers = _NO_CACHE if (media or "").startswith("text/html") else None
    return FileResponse(target, media_type=media, headers=headers)
