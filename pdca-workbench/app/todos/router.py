# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）API。

- GET  /api/todos/remind/candidates  预览：今天会被催到的人和任务（dry-run）
- POST /api/todos/remind             立即催办：VPS IM 私聊本人（manual 轮，忽略频控）
"""
from __future__ import annotations

import asyncio
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.audit import log_action
from app.auth.deps import require_role
from app.auth.models import User
from app.statuses import is_done as _status_is_done
from app.todos.service import run_todo_reminders

router = APIRouter(tags=["todos"])


class RemindRequest(BaseModel):
    dry_run: bool = False


@router.get("/api/todos/remind/candidates")
async def remind_candidates(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """预览待催清单：不发送、不改库（owner 匹配仍会查 IM 组织）。"""
    return await asyncio.to_thread(
        run_todo_reminders,
        None,
        "manual",
        True,
        True,
    )


@router.post("/api/todos/remind")
async def remind_now(
    request: Request,
    payload: Optional[RemindRequest] = None,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """立即催办：manual 轮次、忽略当日频控。dry_run=true 只预览。"""
    dry_run = bool(payload and payload.dry_run)
    result = await asyncio.to_thread(
        run_todo_reminders,
        None,
        "manual",
        True,
        dry_run,
    )
    client_ip = request.client.host if request.client else ""
    log_action(
        username=user.username,
        action="todo_remind",
        resource=result["date"],
        detail={
            "dry_run": dry_run,
            "pending": result.get("pending_tasks"),
            "sent": len(result.get("sent") or []),
            "skipped": len(result.get("skipped_owners") or []),
            "failed": len(result.get("failed") or []),
        },
        ip=client_ip,
    )
    return result

class ProjectStatusRequest(BaseModel):
    status: str


@router.get("/api/todos/projects")
async def list_projects(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """项目（事项）列表：含各项目未完成待办数。"""
    import json as _json

    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask
    from app.models.todo_project import TodoProject
    from app.todos.projects import ensure_projects

    with Session(get_engine()) as session:
        by_key, _ = ensure_projects(session)
        rows = list(session.exec(select(TodoProject)).all())
        open_counts: dict = {}
        for row in session.exec(
            select(PdcaTask).where(PdcaTask.project_id.is_not(None))
        ).all():
            if not _status_is_done(row.status):
                open_counts[row.project_id] = open_counts.get(row.project_id, 0) + 1
    return [
        {
            "id": row.id,
            "key": row.key,
            "name": row.name,
            "status": row.status,
            "executors": _json.loads(row.executors or "[]"),
            "coordinator": row.coordinator,
            "open_tasks": open_counts.get(row.id, 0),
            "remind_count": row.remind_count or 0,
            "last_reminded_round": row.last_reminded_round or "",
        }
        for row in sorted(rows, key=lambda r: -(open_counts.get(r.id, 0)))
    ]


@router.patch("/api/todos/projects/{project_id}/status")
async def update_project_status(
    project_id: int,
    payload: ProjectStatusRequest,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """更新项目状态（新建/跟进中/阻塞/待验收/已闭环）。已闭环不再催办。"""
    from datetime import datetime

    from sqlmodel import Session

    from app.database import get_engine
    from app.models.todo_project import PROJECT_STATUSES, TodoProject

    status = payload.status.strip()
    if status not in PROJECT_STATUSES:
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="非法状态")
    with Session(get_engine()) as session:
        row = session.get(TodoProject, project_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="项目不存在")
        row.status = status
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    log_action(
        username=user.username,
        action="todo_project_status",
        resource=row.key,
        detail={"status": status},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "id": row.id, "status": status}

@router.get("/api/todos/replies")
async def list_replies(
    limit: int = 100,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """回复采集记录：unreviewed 在前，供人工确认。"""
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.im_replies import TodoReply

    with Session(get_engine()) as session:
        rows = list(
            session.exec(
                select(TodoReply).order_by(TodoReply.at.desc()).limit(min(limit, 500))
            ).all()
        )
    return [
        {
            "id": row.id,
            "person": row.person,
            "text": row.text,
            "at": row.at.isoformat() if row.at else "",
            "signal": row.signal,
            "status": row.status,
            "target_task_id": row.target_task_id,
            "target_project_id": row.target_project_id,
        }
        for row in rows
    ]


class ReplyActionRequest(BaseModel):
    pass


@router.post("/api/todos/replies/{reply_id}/apply-all")
async def apply_reply_all(
    reply_id: int,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """人工确认：把该人最近一次催办消息里的全部未完成待办标记完成。"""
    from datetime import datetime

    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.im_replies import ImRemindSend, TodoReply
    from app.models.pdca_task import PdcaTask

    with Session(get_engine()) as session:
        row = session.get(TodoReply, reply_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="回复不存在")
        send = session.exec(
            select(ImRemindSend)
            .where(ImRemindSend.person == row.person)
            .order_by(ImRemindSend.sent_at.desc())
        ).first()
        count = 0
        if send is not None:
            import json as _json

            task_ids = _json.loads(send.item_task_ids or "[]")
            tasks = list(
                session.exec(
                    select(PdcaTask).where(PdcaTask.id.in_([int(t) for t in task_ids]))
                ).all()
            )
            now = datetime.utcnow()
            for task in tasks:
                task.status = "done"
                task.reply_text = row.text[:1024]
                task.replied_at = now
                session.add(task)
                count += 1
        row.status = "applied"
        session.add(row)
        session.commit()
    log_action(
        username=user.username,
        action="todo_reply_apply_all",
        resource=row.person,
        detail={"reply_id": reply_id, "tasks": count},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "tasks_closed": count}


@router.post("/api/todos/replies/{reply_id}/ignore")
async def ignore_reply(
    reply_id: int,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """人工确认：忽略该回复。"""
    from sqlmodel import Session

    from app.database import get_engine
    from app.models.im_replies import TodoReply

    with Session(get_engine()) as session:
        row = session.get(TodoReply, reply_id)
        if row is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="回复不存在")
        row.status = "ignored"
        session.add(row)
        session.commit()
    log_action(
        username=user.username,
        action="todo_reply_ignore",
        resource=row.person,
        detail={"reply_id": reply_id},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True}


