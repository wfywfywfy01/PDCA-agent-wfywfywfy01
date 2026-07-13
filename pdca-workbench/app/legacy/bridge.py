# -*- coding: utf-8 -*-
"""
桥接 data_role_pdca_mvp/scripts/pdca_workbench.py 业务函数。

第一阶段不重写业务逻辑，直接复用现有实现。
"""
from __future__ import annotations

import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


@lru_cache
def _ensure_legacy_import() -> Any:
    """加载遗留 pdca_workbench 模块。"""
    settings = get_settings()
    scripts = settings.scripts_dir
    repo_scripts = settings.repo_root / "scripts"
    for path in (str(scripts), str(repo_scripts)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import pdca_workbench as wb  # noqa: WPS433

    return wb


def wb():
    """获取遗留模块单例。"""
    return _ensure_legacy_import()


def today_text() -> str:
    """今日日期文本；遗留模块加载失败时退化为本机日期，避免各页面直接 500。"""
    try:
        return wb().today_text()
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")


def api_dashboard_overview(date_text: str, period: str = "day", session_user: dict | None = None) -> dict:
    return wb().api_dashboard_overview(date_text, period, session_user=session_user)


def api_customer_center_summary(session_user: dict | None = None) -> list:
    return wb().api_customer_center_summary(session_user=session_user)


def api_task_center_summary(date_text: str | None = None) -> list:
    return wb().api_task_center_summary(date_text)


def api_task_center_panel(date_text: str | None = None) -> dict:
    return wb().api_task_center_panel(date_text)


def api_meeting_center_summary(date_text: str | None = None, end_date: str | None = None) -> list:
    return wb().api_meeting_center_summary(date_text, end_date)


def api_meeting_center_meetings(
    date_text: str,
    person_phone: str = "",
    person_name: str = "",
    end_date: str = "",
) -> dict:
    return wb().api_meeting_center_meetings(date_text, person_phone, person_name, end_date)


def api_meeting_center_people() -> dict:
    return wb().api_meeting_center_people()


def api_meeting_center_dispatch(body: dict, date_text: str) -> dict:
    return wb().api_meeting_center_dispatch(body, date_text)


def build_walkin_payload(month: str, date_text: str) -> dict:
    mod = wb()
    if mod.build_walkin_api_payload is None:
        raise RuntimeError("workbench_data module missing")
    return mod.build_walkin_api_payload(month, date_text)


def build_online_channel_payload(date_text: str) -> dict:
    mod = wb()
    if mod.build_online_channel_payload is None:
        raise RuntimeError("workbench_data module missing")
    return mod.build_online_channel_payload(date_text)


def skin_cockpit_html(html: str, date_text: str, page_title: str = "经销商驾驶舱") -> str:
    return wb().skin_cockpit_html(html, date_text, page_title)


def skin_dashboard_html(html: str, date_text: str) -> str:
    return wb().skin_dashboard_html(html, date_text)


def output_dir(date_text: str) -> Path:
    return wb().output_dir(date_text)


def render_questionnaire(date_text: str, message: str = "") -> str:
    return wb().render_questionnaire(date_text, message)


def render_todos(date_text: str, message: str = "") -> str:
    return wb().render_todos(date_text, message)


def render_logistics(date_text: str, message: str = "") -> str:
    return wb().render_logistics(date_text, message)


def render_im_unread(date_text: str, message: str = "") -> str:
    return wb().render_im_unread(date_text, message)


def render_customer_mgmt_frame(date_text: str) -> str:
    return wb().render_customer_mgmt_frame(date_text)


def run_pdca(date_text: str, push: bool = False, start_date: str = "") -> tuple:
    return wb().run_pdca(date_text, push=push, start_date=start_date)


def resolve_walkin_asset(rel_path: str) -> Path | None:
    return wb().resolve_walkin_asset(rel_path)


def resolve_meeting_center_asset(rel_path: str) -> Path | None:
    return wb().resolve_meeting_center_asset(rel_path)


def resolve_home_dashboard_asset(rel_path: str) -> Path | None:
    return wb().resolve_home_dashboard_asset(rel_path)


def save_questionnaire(date_text: str, form: dict) -> None:
    wb().save_questionnaire(date_text, form)


def append_todo(date_text: str, form: dict) -> None:
    wb().append_todo(date_text, form)


def append_logistics(date_text: str, form: dict) -> None:
    wb().append_logistics(date_text, form)


def save_pdca_task_update(form: dict) -> str:
    return wb().save_pdca_task_update(form)


def run_hermes_chat(query: str) -> dict:
    return wb().run_hermes_chat(query)


def render_home(date_text: str, message: str = "", hermes_result=None) -> str:
    return wb().render_home(date_text, message, hermes_result=hermes_result)


def render_agent_soul(date_text: str, agent_key: str, message: str = "") -> str:
    return wb().render_agent_soul(date_text, agent_key, message)


def render_agent_edit(
    date_text: str,
    agent_key: str,
    active_file: str = "SOUL.md",
    message: str = "",
) -> str:
    return wb().render_agent_edit(date_text, agent_key, active_file, message)


def render_view_path(date_text: str, path_text: str, back_url: str = "") -> str:
    return wb().render_view_path(date_text, path_text, back_url)


def open_target(date_text: str, target: str) -> str:
    return wb().open_target(date_text, target)


def open_path(path_text: str) -> str:
    return wb().open_path(path_text)


def open_im_channel(channel_id: str) -> str:
    return wb().open_im_channel(channel_id)


def ensure_customer_server() -> str:
    return wb().ensure_customer_server()


def agent_by_key(key: str):
    return wb().agent_by_key(key)


def ensure_agent_soul(agent):
    return wb().ensure_agent_soul(agent)


def ensure_agent_core_file(agent, filename: str):
    return wb().ensure_agent_core_file(agent, filename)


def write_text(path: Path, content: str) -> None:
    wb().write_text(path, content)


def install_skill_to_agent(agent_key: str, filename: str, content_bytes: bytes) -> str:
    return wb().install_skill_to_agent(agent_key, filename, content_bytes)


def api_dealer_sellin_summary(month: str | None = None) -> dict:
    """从 data_raw 读取经销商进货（sell-in）汇总数据。"""
    import json
    from datetime import date, timedelta

    settings = get_settings()
    data_raw = settings.repo_root / "data_raw"

    if not month:
        month = date.today().strftime("%Y-%m")

    def _load_file(path: Path) -> list:
        try:
            data = json.loads(path.read_bytes().decode("utf-8-sig"))
            return (
                data.get("result", {})
                .get("execution", {})
                .get("result", {})
                .get("customer_summary", [])
            )
        except Exception:
            return []

    def _latest_file_for_month(mo: str) -> Path | None:
        candidates = sorted(
            [f for f in data_raw.glob(f"dealer_sales_month_to_date_{mo}-*.json") if "params" not in f.name],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            candidates = sorted(
                [f for f in data_raw.glob(f"dealer_sales_month_to_date_{mo}.json") if "params" not in f.name],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        return candidates[0] if candidates else None

    main_file = _latest_file_for_month(month)
    if not main_file:
        return {"month": month, "total_wan": 0.0, "dealers": [], "has_data": False, "trend": []}

    customers = _load_file(main_file)
    dealers = []
    total = 0.0
    for c in customers:
        perf = float(c.get("performance") or 0)
        total += perf
        dealers.append({
            "name": c.get("partner_name", ""),
            "wan": round(perf / 10000, 2),
            "quantity": int(c.get("quantity") or 0),
        })
    dealers.sort(key=lambda x: x["wan"], reverse=True)
    for i, d in enumerate(dealers):
        d["rank"] = i + 1

    # 最近 6 个月趋势
    trend = []
    y, m = map(int, month.split("-"))
    for i in range(5, -1, -1):
        mm, yy = m - i, y
        while mm <= 0:
            mm += 12
            yy -= 1
        mo = f"{yy:04d}-{mm:02d}"
        f2 = _latest_file_for_month(mo)
        mo_total = 0.0
        if f2:
            for c in _load_file(f2):
                mo_total += float(c.get("performance") or 0)
        trend.append({"month": mo, "wan": round(mo_total / 10000, 2)})

    return {
        "month": month,
        "total_wan": round(total / 10000, 2),
        "dealers": dealers,
        "has_data": len(dealers) > 0,
        "trend": trend,
        "source_file": main_file.name,
    }


def agent_core_files() -> list[str]:
    return list(wb().AGENT_CORE_FILES)


def latest_output_file(date_text: str, target: str) -> Path | None:
    return wb().latest_output_file(date_text, target)


def questionnaire_path(date_text: str) -> Path:
    return wb().questionnaire_path(date_text)


def todo_path(date_text: str) -> Path:
    return wb().todo_path(date_text)
