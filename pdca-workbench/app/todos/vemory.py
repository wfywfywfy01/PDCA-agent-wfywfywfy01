# -*- coding: utf-8 -*-
"""Vemory 会议待办 OpenAPI 同步 —— pdca_tasks 的事实源。

POST {PDCA_VEMORY_OPENAPI_URL}/openapi/getUserMeetingTodos
Header X-API-Key: $VEMORY_OPENAPI_KEY

按 PDCA_VEMORY_TODO_USERS 名单逐人查询最近 7 天会议待办，以 Vemory 待办 ID
为主键 upsert 进 pdca_tasks（source="vemory"）：

- status=1（已完成）→ 库内 status="done"；status=0 → "pending"（Vemory 为准）
- deadline 有值 → task_date=deadline；否则 task_date=meeting_date
- owner = 被查询人员姓名（催办对象，与 todo-tracker 语义一致；speaker 仅是
  会上发言人线索，不能直接当执行人）
- 7 天窗口内之前同步过、本次未再出现的 Vemory 待办 → 视为已删除，置 done
  （接口只返回未删除待办；窗口外的不动，避免把窗口滚动误判为删除）

密钥未配置或名单为空时安全跳过（fail-closed，不产生任何数据变化）。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.todos.projects import ensure_projects, match_project
from app.todos.sop import classify_todo

_TZ = ZoneInfo("Asia/Shanghai")
_WINDOW_DAYS = 6  # 起始 = 今天-6 天（含今天共 7 天，接口限制 7×24h）


def load_vemory_users(raw: str = "") -> list[dict]:
    """解析人员名单 JSON：裸数组或 {"people": [...]}。"""
    raw = raw or get_settings().vemory_todo_users_json
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("PDCA_VEMORY_TODO_USERS 不是合法 JSON，跳过 Vemory 待办同步")
        return []
    if isinstance(payload, dict) and isinstance(payload.get("people"), list):
        payload = payload["people"]
    if not isinstance(payload, list):
        return []
    return [
        item
        for item in payload
        if isinstance(item, dict)
        and item.get("name")
        and (item.get("vemoryUserId") or item.get("user_id"))
    ]


def _window() -> tuple[str, str]:
    now = datetime.now(_TZ)
    start = (now - timedelta(days=_WINDOW_DAYS)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")
    return f"{start} 00:00:00", f"{end} 23:59:59"


def fetch_vemory_todos(
    user: dict,
    api_key: str,
    url: str,
    start_time: str,
    end_time: str,
) -> list[dict]:
    """调用 OpenAPI，返回展平的待办列表（每条含 _meeting 上下文）。失败抛异常。"""
    user_id = int(user.get("vemoryUserId") or user.get("user_id") or 0)
    response = httpx.post(
        f"{url}/openapi/getUserMeetingTodos",
        json={
            "user_id": user_id,
            "start_time": start_time,
            "end_time": end_time,
            "timezone": "Asia/Shanghai",
        },
        headers={"X-API-Key": api_key, "Content-Type": "application/json"},
        timeout=30.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}")
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        # httpx 对非法 JSON 抛 json.JSONDecodeError（ValueError 子类），一并兜住
        raise RuntimeError("响应不是 JSON")
    # 接入方必须同时判断 HTTP 状态与响应体 status（业务失败可能以 HTTP 200 返回）
    if body.get("status") != 0:
        raise RuntimeError(str(body.get("err_code") or body.get("message") or "业务失败"))
    meetings = ((body.get("data") or {}).get("meetings")) or []
    flat: list[dict] = []
    for meeting in meetings:
        if not isinstance(meeting, dict):
            continue
        for todo in meeting.get("todos") or []:
            if not isinstance(todo, dict):
                continue
            flat.append({**todo, "_meeting": meeting})
    return flat


def _meeting_date_ms(meeting: dict, fallback: str) -> str:
    """start_record_time 为 Unix 毫秒时间戳，转 Asia/Shanghai 日期。"""
    ts = meeting.get("start_record_time")
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts / 1000.0, tz=_TZ).strftime("%Y-%m-%d")
    return fallback


def _external_id(todo: dict, user_id: int) -> str:
    """待办 ID 缺失时用 人员+文本+会议 计算短哈希兜底（与 todo-tracker 一致）。"""
    tid = todo.get("id")
    if isinstance(tid, int) and tid > 0:
        return f"vemory:{tid}"
    meeting = todo.get("_meeting") or {}
    raw = f"{user_id}|{todo.get('content') or ''}|{meeting.get('meeting_id') or ''}"
    return "vemory-hash:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def sync_vemory_todos(today: str | None = None) -> dict:
    """以 Vemory OpenAPI 为准，把会议待办同步进 pdca_tasks。"""
    settings = get_settings()
    api_key = os.environ.get("VEMORY_OPENAPI_KEY", "").strip()
    users = load_vemory_users()
    if not api_key:
        logger.warning("VEMORY_OPENAPI_KEY 未配置，跳过 Vemory 待办同步")
        return {"status": "skipped", "reason": "no_api_key"}
    if not users:
        logger.warning("PDCA_VEMORY_TODO_USERS 名单为空，跳过 Vemory 待办同步")
        return {"status": "skipped", "reason": "no_users"}

    today = today or datetime.now(_TZ).strftime("%Y-%m-%d")
    start_time, end_time = _window()
    window_start = start_time[:10]

    seen: set[str] = set()
    upserted = 0
    done_flipped = 0
    errors: list[str] = []

    with Session(get_engine()) as session:
        _project_by_key, project_by_id = ensure_projects(session)
        existing_rows = session.exec(
            select(PdcaTask).where(
                PdcaTask.source == "vemory",
                PdcaTask.external_todo_id != "",
            ),
        ).all()
        existing_map: dict[str, PdcaTask] = {row.external_todo_id: row for row in existing_rows}

        for user in users:
            name = str(user.get("name") or "").strip()
            user_id = int(user.get("vemoryUserId") or user.get("user_id") or 0)
            try:
                todos = fetch_vemory_todos(
                    user, api_key, settings.vemory_openapi_url, start_time, end_time
                )
            except Exception as exc:  # noqa: BLE001 — 单人失败不阻断其他人
                errors.append(f"{name}: {exc}")
                continue
            for todo in todos:
                meeting = todo.get("_meeting") or {}
                ext_id = _external_id(todo, user_id)
                seen.add(ext_id)
                meeting_date = _meeting_date_ms(meeting, today)
                deadline = str(todo.get("deadline") or "").strip()
                title = str(todo.get("content") or "").strip()
                if not title:
                    continue
                status = "done" if int(todo.get("status") or 0) != 0 else "pending"
                # 岗位 SOP 收敛：执行人 = 分类器结果，定不了回退会议参与人本人
                converged = classify_todo(
                    title=title,
                    meeting_name=str(meeting.get("meeting_name") or ""),
                    speaker=str(todo.get("speaker") or "").strip(),
                    participant=name,
                )
                owner = converged["executor"] or name
                # 项目（事项）收敛：标题命中项目规则 → 挂 project_id
                project_rule = match_project(title)
                project_id = None
                if project_rule and project_rule["key"] in _project_by_key:
                    project_id = _project_by_key[project_rule["key"]].id
                row = existing_map.get(ext_id)
                if row is None:
                    row = PdcaTask(
                        task_date=deadline or meeting_date,
                        title=title,
                        owner=owner,
                        status=status,
                        source="vemory",
                        external_todo_id=ext_id,
                        meeting_name=str(meeting.get("meeting_name") or "").strip(),
                        meeting_date=meeting_date,
                        position=converged["position"],
                        origin_owner=name,
                        project_id=project_id,
                    )
                    session.add(row)
                    existing_map[ext_id] = row
                else:
                    # Vemory 为准：状态/截止/标题/会议信息以接口覆盖
                    if row.status != status:
                        if status == "done":
                            done_flipped += 1
                        row.status = status
                    row.task_date = deadline or meeting_date
                    row.title = title
                    # 手工修正过的执行人不被重算覆盖（owner_locked）
                    if not getattr(row, "owner_locked", False):
                        row.owner = owner
                    row.meeting_name = str(meeting.get("meeting_name") or "").strip()
                    row.meeting_date = meeting_date
                    row.position = converged["position"]
                    row.origin_owner = name
                    row.project_id = project_id
                    row.updated_at = datetime.utcnow()
                    session.add(row)
                upserted += 1

        # 删除检测：窗口内之前同步过、本次未再出现的 Vemory 待办 → 置 done
        deleted_closed = 0
        for ext_id, row in existing_map.items():
            if ext_id in seen:
                continue
            if not row.meeting_date or row.meeting_date < window_start:
                # 会议已滑出 7 天窗口：无法区分「已删除」与「窗口滚动」，保持原状
                continue
            if row.status == "done":
                continue
            row.status = "done"
            row.updated_at = datetime.utcnow()
            session.add(row)
            deleted_closed += 1

        session.commit()

    result = {
        "status": "ok",
        "date": today,
        "users": len(users),
        "upserted": upserted,
        "done_flipped": done_flipped,
        "deleted_closed": deleted_closed,
        "errors": errors,
    }
    logger.info("Vemory 待办同步完成: {}", result)
    return result
