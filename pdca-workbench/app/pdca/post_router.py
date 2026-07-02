# -*- coding: utf-8 -*-
"""Legacy 表单 POST 路由迁移。"""
from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.deps import require_role
from app.auth.models import User
from app.legacy import bridge
from app.models import writes as db_writes
from app.models.sync import sync_daily_reports
from app.pages.helpers import html_page
from app.pdca.legacy_form import form_to_legacy

router = APIRouter(tags=["pdca-forms"])


def _redirect(path: str, date_text: str, message: str = "") -> RedirectResponse:
    qs = urlencode({"date": date_text, "message": message})
    return RedirectResponse(f"{path}?{qs}", status_code=303)


@router.post("/questionnaire")
async def post_questionnaire(
    request: Request,
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("sales"))] = None,
):
    date_text = date or bridge.today_text()
    form = form_to_legacy(await request.form())
    bridge.save_questionnaire(date_text, form)
    qpath = bridge.questionnaire_path(date_text)
    content = qpath.read_text(encoding="utf-8") if qpath.is_file() else ""
    db_writes.upsert_daily_report(
        date_text,
        "questionnaire",
        f"{date_text}_questionnaire",
        content,
        str(qpath),
    )
    return _redirect("/questionnaire", date_text, "问卷已保存。")


@router.post("/todos")
async def post_todos(
    request: Request,
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("sales"))] = None,
):
    date_text = date or bridge.today_text()
    form = form_to_legacy(await request.form())
    bridge.append_todo(date_text, form)
    db_writes.insert_pdca_task(
        task_date=date_text,
        title=(form.get("title", [""])[0] or "").strip(),
        owner=(form.get("owner", [""])[0] or "").strip(),
        status=(form.get("status", ["pending"])[0] or "pending"),
        priority=(form.get("priority", ["MEDIUM"])[0] or "normal"),
        source="workbench",
    )
    return _redirect("/todos", date_text, "代办已保存。")


@router.post("/logistics")
async def post_logistics(
    request: Request,
    date: str | None = None,
    user: Annotated[User, Depends(require_role("sales"))] = None,
):
    date_text = date or bridge.today_text()
    form = form_to_legacy(await request.form())
    if user.role == "sales" and not (form.get("salesperson", [""])[0] or "").strip():
        sales_label = getattr(user, "sales_name", "") or user.display_name or user.username
        form["salesperson"] = [sales_label]
    bridge.append_logistics(date_text, form)
    from app.logistics.service import canonical_sales_name

    db_writes.upsert_logistics_shipment(
        date_text,
        form,
        canonical_sales_name((form.get("salesperson", [""])[0] or "").strip()),
    )
    return _redirect("/logistics-center/", date_text, "物流单号已保存。")


@router.post("/run")
async def post_run(
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
):
    date_text = date or bridge.today_text()
    code, stdout, stderr = bridge.run_pdca(date_text, push=False)
    if code == 0:
        sync_daily_reports(date_text)
    message = "运行成功，结果已刷新。" if code == 0 else f"运行失败：{(stderr or stdout)[:200]}"
    return _redirect("/", date_text, message[:300])


@router.post("/pdca-task")
async def post_pdca_task(
    request: Request,
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("sales"))] = None,
):
    form = form_to_legacy(await request.form())
    task_date = (form.get("date", [date or bridge.today_text()])[0] or bridge.today_text())
    try:
        message = bridge.save_pdca_task_update(form)
        db_writes.update_pdca_task_from_form(
            task_date=task_date,
            title=(form.get("title", [""])[0] or "").strip(),
            status=(form.get("status", [""])[0] or "").strip(),
            vps_todo_id=(form.get("todo_id", [""])[0] or "").strip(),
        )
    except Exception as exc:
        message = f"保存失败：{exc}"
    return _redirect("/", task_date, message[:300])


@router.post("/hermes-chat")
async def post_hermes_chat(
    request: Request,
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("manager"))] = None,
):
    date_text = date or bridge.today_text()
    form = form_to_legacy(await request.form())
    query_text = (form.get("query", [""])[0] or "").strip()
    result = bridge.run_hermes_chat(query_text)
    html = bridge.render_home(date_text, hermes_result=result)
    return html_page(html)


@router.post("/agent-soul")
async def post_agent_soul(
    request: Request,
    agent: str = Query(""),
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("admin"))] = None,
):
    date_text = date or bridge.today_text()
    agent_obj = bridge.agent_by_key(agent)
    if not agent_obj:
        return _redirect("/", date_text, "未知 Agent。")
    form = form_to_legacy(await request.form())
    bridge.write_text(bridge.ensure_agent_soul(agent_obj), form.get("content", [""])[0])
    qs = urlencode({"date": date_text, "agent": agent, "message": "SOUL.md 已保存。"})
    return RedirectResponse(f"/agent-soul?{qs}", status_code=303)


@router.post("/agent-core-file")
async def post_agent_core_file(
    request: Request,
    agent: str = Query(""),
    file: str = Query("SOUL.md"),
    date: str | None = None,
    _user: Annotated[User, Depends(require_role("admin"))] = None,
):
    date_text = date or bridge.today_text()
    agent_obj = bridge.agent_by_key(agent)
    if not agent_obj or file not in bridge.agent_core_files():
        return _redirect("/", date_text, "未知 Agent 或文件。")
    form = form_to_legacy(await request.form())
    bridge.write_text(bridge.ensure_agent_core_file(agent_obj, file), form.get("content", [""])[0])
    qs = urlencode({
        "date": date_text,
        "agent": agent,
        "file": file,
        "message": f"{file} 已保存。",
    })
    return RedirectResponse(f"/agent-edit?{qs}", status_code=303)


@router.post("/agent-skill")
async def post_agent_skill(
    agent: str = Query(""),
    date: str | None = None,
    skill: UploadFile = File(...),
    _user: Annotated[User, Depends(require_role("admin"))] = None,
):
    date_text = date or bridge.today_text()
    try:
        if not skill.filename:
            raise ValueError("没有收到 skill 文件。")
        content = await skill.read()
        target = bridge.install_skill_to_agent(agent, skill.filename, content)
        msg = f"Skill 已安装：{target}"
    except Exception as exc:
        msg = f"Skill 安装失败：{exc}"
    qs = urlencode({"date": date_text, "agent": agent, "message": msg})
    return RedirectResponse(f"/agent-edit?{qs}", status_code=303)
