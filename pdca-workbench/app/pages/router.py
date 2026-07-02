# -*- coding: utf-8 -*-
"""HTML 页面与静态模块托管。"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.auth.deps import get_current_user, require_role
from app.auth.models import User
from app.config import get_settings
from app.legacy import bridge
from app.pages.helpers import html_page, inject_vue_shell

router = APIRouter(tags=["pages"])


def _guess_media(path: Path) -> str:
    media, _ = mimetypes.guess_type(str(path))
    return media or "application/octet-stream"


def _serve_asset(resolver, rel_path: str) -> FileResponse:
    target = resolver(rel_path)
    if not target:
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type=_guess_media(target))


def _serve_skinned_html(path: Path, date_text: str, title: str, feature: str = "") -> HTMLResponse:
    if not path.is_file():
        return _unavailable(feature or title)
    try:
        html = bridge.skin_cockpit_html(path.read_text(encoding="utf-8"), date_text, title)
        return html_page(html)
    except Exception:
        return _unavailable(feature or title)


def _redirect_msg(path: str, date_text: str, message: str) -> RedirectResponse:
    return RedirectResponse(f"{path}?{urlencode({'date': date_text, 'message': message})}")


def _unavailable(feature: str = "") -> HTMLResponse:
    """Bridge/MVP 文件不可用时返回友好提示页，而不是 500。"""
    label = feature or "此功能"
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<title>功能不可用</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;background:#0b0d13;color:#94a3b8}}
.box{{text-align:center;padding:48px;max-width:480px}}
h1{{font-size:2rem;color:#4e9ef5;margin-bottom:.5rem}}
p{{line-height:1.7;margin:.5rem 0}}
a{{color:#4e9ef5;text-decoration:none}}</style></head>
<body><div class="box">
<h1>⚙️</h1>
<p><strong style="color:#e2e8f0">{label}</strong> 在当前部署环境中不可用。</p>
<p>This feature is not available in the current deployment.</p>
<p style="margin-top:1.5rem"><a href="/walkin-submit">← 返回录入页</a></p>
</div></body></html>"""
    return HTMLResponse(html, status_code=200)


def _safe_bridge_page(fn, *args, feature: str = "", **kwargs) -> HTMLResponse:
    """执行 bridge 渲染函数，失败时返回友好提示而非 500。"""
    try:
        return html_page(fn(*args, **kwargs))
    except Exception:
        return _unavailable(feature)


@router.get("/")
async def home(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    index = settings.home_dashboard_dir / "index.html"
    if not index.is_file():
        # MVP 目录未部署，降级到录入页
        return RedirectResponse("/walkin-submit")
    return html_page(index.read_text(encoding="utf-8"))


@router.get("/login")
async def login_page():
    settings = get_settings()
    login = settings.frontend_dir / "login.html"
    if login.is_file():
        return FileResponse(login, media_type="text/html; charset=utf-8")
    return HTMLResponse("<p>login.html 缺失</p>")


@router.get("/home-classic")
async def home_classic(
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_home, date or bridge.today_text(), message, feature="经营看板")


@router.get("/questionnaire")
async def questionnaire(
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_questionnaire, date or bridge.today_text(), message, feature="问卷")


@router.get("/todos")
async def todos_page(
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_todos, date or bridge.today_text(), message, feature="待办中心")


@router.get("/logistics")
async def logistics(
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    try:
        html = bridge.render_logistics(date or bridge.today_text(), message)
        html = html.replace(
            "录入物流单号</h2>",
            '录入物流单号</h2><p style="margin:6px 0 0"><a href="/logistics-center/?date='
            + (date or bridge.today_text())
            + '">查看物流进展看板 →</a></p>',
            1,
        )
        if user.role == "sales":
            sales_label = getattr(user, "sales_name", "") or user.display_name
            html = html.replace(
                '<label>销售<input name="salesperson"',
                f'<label>销售<input name="salesperson" value="{sales_label}" readonly',
                1,
            )
        return html_page(html)
    except Exception:
        return _unavailable("物流录入")


@router.get("/im-unread")
async def im_unread(
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_im_unread, date or bridge.today_text(), message, feature="IM 未读")


@router.get("/customer-mgmt")
async def customer_mgmt(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    try:
        date_text = date or bridge.today_text()
        err = bridge.ensure_customer_server()
        if err:
            return _redirect_msg("/", date_text, err)
        return html_page(bridge.render_customer_mgmt_frame(date_text))
    except Exception:
        return _unavailable("客户管理")


@router.get("/agent-soul")
async def agent_soul(
    agent: str = Query(""),
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_agent_soul, date or bridge.today_text(), agent, message, feature="Agent 管理")


@router.get("/agent-edit")
async def agent_edit(
    agent: str = Query(""),
    file: str = Query("SOUL.md"),
    date: str | None = None,
    message: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_agent_edit, date or bridge.today_text(), agent, file, message, feature="Agent 编辑")


@router.get("/view-path")
async def view_path(
    path: str = Query(""),
    date: str | None = None,
    from_url: str = Query("", alias="from"),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    return _safe_bridge_page(bridge.render_view_path, date or bridge.today_text(), path, from_url, feature="文件查看")


@router.get("/open")
async def open_target(
    target: str = Query(""),
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    date_text = date or bridge.today_text()
    file_path = bridge.latest_output_file(date_text, target)
    if file_path and file_path.is_file():
        return RedirectResponse(f"/api/files/download?path={quote(str(file_path))}")
    return _redirect_msg("/", date_text, "文件还不存在，请先运行今日 PDCA。")


@router.get("/open-path")
async def open_path_route(
    path: str = Query(""),
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    date_text = date or bridge.today_text()
    try:
        resolved = Path(path).resolve()
        if resolved.is_file():
            return RedirectResponse(f"/api/files/download?path={quote(str(resolved))}")
    except OSError:
        pass
    return _redirect_msg("/", date_text, "文件还不存在。")


@router.get("/open-im-channel")
async def open_im_channel(
    channel_id: str = Query(""),
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    date_text = date or bridge.today_text()
    msg = bridge.open_im_channel(channel_id)
    return _redirect_msg("/im-unread", date_text, msg)


@router.get("/dashboard")
async def dashboard(
    date: str | None = None,
    start: str = Query(""),
    end: str = Query(""),
    user: Annotated[User, Depends(get_current_user)] = None,
):
    try:
        date_text = date or bridge.today_text()
        if start and end:
            date_text = end
            code, stdout, stderr = bridge.run_pdca(date_text, push=False, start_date=start)
            if code != 0:
                return _redirect_msg("/", date_text, "区间看板生成失败")
        dash = bridge.output_dir(date_text) / "dashboard.html"
        if not dash.is_file():
            code, stdout, stderr = bridge.run_pdca(date_text, push=False)
            if code != 0:
                return _redirect_msg("/", date_text, "看板生成失败")
        if not dash.is_file():
            return _redirect_msg("/", date_text, "暂无看板")
        html = inject_vue_shell(bridge.skin_dashboard_html(dash.read_text(encoding="utf-8"), date_text))
        return HTMLResponse(html)
    except Exception:
        return _unavailable("经营看板（需要 vertu 数据服务）")


@router.get("/dashboard-theme.css")
async def dashboard_theme_css():
    settings = get_settings()
    path = settings.home_dashboard_dir / "workbench-unified.css"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="text/css; charset=utf-8")


@router.get("/workbench-cockpit-shell.css")
async def cockpit_shell_css():
    settings = get_settings()
    path = settings.home_dashboard_dir / "workbench-cockpit-shell.css"
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(path, media_type="text/css; charset=utf-8")


def _serve_module(index: Path, date_text: str, title: str, feature: str) -> HTMLResponse:
    """通用模块页面加载，文件不存在时返回友好提示。"""
    if not index.is_file():
        return _unavailable(feature)
    try:
        html = bridge.skin_cockpit_html(index.read_text(encoding="utf-8"), date_text, title)
        return html_page(html)
    except Exception:
        return _unavailable(feature)


@router.get("/walkin-cockpit")
@router.get("/walkin-cockpit/")
async def walkin_index(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    return _serve_module(
        settings.walkin_cockpit_dir / "index.html",
        date or bridge.today_text(),
        "客流分析台", "客流分析台",
    )


@router.get("/walkin-cockpit/{rel_path:path}")
async def walkin_assets(
    rel_path: str,
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    if rel_path.endswith(".html"):
        settings = get_settings()
        path = settings.walkin_cockpit_dir / unquote(rel_path)
        if path.is_file():
            return _serve_module(path, date or bridge.today_text(), "客流分析台", "客流分析台")
    try:
        return _serve_asset(bridge.resolve_walkin_asset, rel_path)
    except Exception:
        raise HTTPException(status_code=404)


@router.get("/meeting-center")
@router.get("/meeting-center/")
async def meeting_index(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    return _serve_module(
        settings.meeting_center_dir / "index.html",
        date or bridge.today_text(),
        "会议中心", "会议中心",
    )


@router.get("/meeting-center/{rel_path:path}")
async def meeting_assets(
    rel_path: str,
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    try:
        return _serve_asset(bridge.resolve_meeting_center_asset, rel_path)
    except Exception:
        raise HTTPException(status_code=404)


@router.get("/online-cockpit")
@router.get("/online-cockpit/")
@router.get("/online-cockpit/{rel_path:path}")
async def online_redirect(date: str | None = None):
    q = f"?date={date}" if date else ""
    return RedirectResponse(f"/walkin-cockpit/{q}#oi-merged")


@router.get("/logistics-center")
@router.get("/logistics-center/")
async def logistics_center_index(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    return _serve_module(
        settings.logistics_center_dir / "index.html",
        date or bridge.today_text(),
        "物流进展", "物流中心",
    )


@router.get("/logistics-center/{rel_path:path}")
async def logistics_center_assets(
    rel_path: str,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    target = (settings.logistics_center_dir / unquote(rel_path)).resolve()
    root = settings.logistics_center_dir.resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type=_guess_media(target))


@router.get("/onboarding-center")
@router.get("/onboarding-center/")
async def onboarding_center_index(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    return _serve_module(
        settings.onboarding_center_dir / "index.html",
        date or bridge.today_text(),
        "新人培训", "入职中心",
    )


@router.get("/onboarding-center/{rel_path:path}")
async def onboarding_center_assets(
    rel_path: str,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    target = (settings.onboarding_center_dir / unquote(rel_path)).resolve()
    root = settings.onboarding_center_dir.resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type=_guess_media(target))


@router.get("/signalseller-center")
@router.get("/signalseller-center/")
async def signalseller_center_index(
    date: str | None = None,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    return _serve_module(
        settings.signalseller_center_dir / "index.html",
        date or bridge.today_text(),
        "获客指挥", "获客指挥中心",
    )


@router.get("/signalseller-center/{rel_path:path}")
async def signalseller_center_assets(
    rel_path: str,
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    target = (settings.signalseller_center_dir / unquote(rel_path)).resolve()
    root = settings.signalseller_center_dir.resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type=_guess_media(target))


@router.get("/shared/{rel_path:path}")
async def shared_assets(rel_path: str):
    settings = get_settings()
    target = (settings.frontend_dir / "shared" / unquote(rel_path)).resolve()
    root = (settings.frontend_dir / "shared").resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target, media_type=_guess_media(target))


@router.get("/admin-panel")
@router.get("/admin-panel/")
async def admin_panel_page(
    user: Annotated[User, Depends(require_role("admin"))],
):
    settings = get_settings()
    html_path = settings.frontend_dir / "admin_panel.html"
    if not html_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(html_path, media_type="text/html; charset=utf-8")


@router.get("/dealer-sellin")
@router.get("/dealer-sellin/")
async def dealer_sellin_page(
    user: Annotated[User, Depends(get_current_user)] = None,
):
    settings = get_settings()
    html_path = settings.frontend_dir / "dealer_sellin.html"
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="dealer_sellin.html 缺失")
    return FileResponse(html_path, media_type="text/html; charset=utf-8")


@router.get("/walkin-submit")
@router.get("/walkin-submit/")
async def walkin_submit_page(
    user: Annotated[User, Depends(get_current_user)] = None,
):
    """门店五件套录入页面（支持 ?store=STORE_ID 预设门店）。"""
    settings = get_settings()
    html_path = settings.frontend_dir / "walkin_submit.html"
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="walkin_submit.html 缺失")
    return FileResponse(html_path, media_type="text/html; charset=utf-8")


@router.get("/store-five-kit")
@router.get("/store-five-kit/")
async def store_five_kit_page(
    user: Annotated[User, Depends(get_current_user)] = None,
):
    """各门店五件套数据展示页面。"""
    settings = get_settings()
    html_path = settings.frontend_dir / "store_five_kit.html"
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="store_five_kit.html 缺失")
    return FileResponse(html_path, media_type="text/html; charset=utf-8")
