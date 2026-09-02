# -*- coding: utf-8 -*-
"""待办催办（提醒跟进）与项目（事项）管理 API。

- GET  /api/todos/remind/candidates   预览：今天会被催到的人和任务（dry-run，按项目分组）
- POST /api/todos/remind              立即催办：VPS IM 私聊本人（manual 轮，忽略频控）
- GET/POST/PATCH /api/todos/projects  项目列表 / 手工新建 / 改名与协调人
- PATCH /api/todos/projects/{id}/status  项目状态（新建/跟进中/阻塞/待验收/已闭环）
- POST /api/todos/projects/{id}/merge    项目合并（待办并入目标项目，源项目闭环）
- GET  /api/todos/tasks                  待办列表（unassigned=散单 / project_id 筛选）
- PATCH /api/todos/tasks/{id}            待办转挂项目 / 摘出为散单
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


class ProjectUpdateRequest(BaseModel):
    status: Optional[str] = None
    name: Optional[str] = None
    coordinator: Optional[str] = None


class ProjectCreateRequest(BaseModel):
    name: str
    coordinator: str = ""


class ProjectMergeRequest(BaseModel):
    target_id: int


class TaskProjectRequest(BaseModel):
    project_id: Optional[int] = None  # None = 摘出为散单


@router.get("/api/todos/projects")
async def list_projects(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """项目（事项）列表：含类型与各项目未完成待办数。"""
    import json as _json

    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask
    from app.models.todo_project import TodoProject
    from app.todos.projects import ensure_projects

    with Session(get_engine()) as session:
        ensure_projects(session)
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
            "kind": row.kind or "keyword",
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


@router.patch("/api/todos/projects/{project_id}")
async def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """更新项目：改名 / 协调人 / 状态（可选字段，仅更新传入项）。"""
    from datetime import datetime

    from fastapi import HTTPException
    from sqlmodel import Session

    from app.database import get_engine
    from app.models.todo_project import PROJECT_STATUSES, TodoProject

    with Session(get_engine()) as session:
        row = session.get(TodoProject, project_id)
        if row is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        if payload.status is not None:
            status = payload.status.strip()
            if status not in PROJECT_STATUSES:
                raise HTTPException(status_code=422, detail="非法状态")
            row.status = status
        if payload.name is not None:
            name = payload.name.strip()
            if not name:
                raise HTTPException(status_code=422, detail="项目名不能为空")
            row.name = name[:256]
        if payload.coordinator is not None:
            row.coordinator = (payload.coordinator or "").strip()[:128]
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
    log_action(
        username=user.username,
        action="todo_project_update",
        resource=row.key,
        detail={
            "name": payload.name,
            "coordinator": payload.coordinator,
            "status": payload.status,
        },
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "id": row.id, "name": row.name, "status": row.status}


@router.post("/api/todos/projects")
async def create_project(
    payload: ProjectCreateRequest,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """手工创建业务项目（kind=manual）；待办可经 PATCH /api/todos/tasks/{id} 转挂。"""
    import hashlib
    import time

    from fastapi import HTTPException
    from sqlmodel import Session

    from app.database import get_engine
    from app.models.todo_project import TodoProject

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="项目名不能为空")
    key = "man:" + hashlib.sha1(
        (name + str(int(time.time()))).encode("utf-8")
    ).hexdigest()[:12]
    coordinator = (payload.coordinator or "").strip()[:128]
    with Session(get_engine()) as session:
        row = TodoProject(
            key=key,
            name=name[:256],
            kind="manual",
            status="新建",
            executors="[]",
            coordinator=coordinator,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        project_id = row.id
    log_action(
        username=user.username,
        action="todo_project_create",
        resource=key,
        detail={"name": name, "coordinator": coordinator},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "id": project_id, "key": key, "name": name}


@router.post("/api/todos/projects/{project_id}/merge")
async def merge_project(
    project_id: int,
    payload: ProjectMergeRequest,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """把源项目全部待办并入目标项目，源项目置「已闭环」不再催办。"""
    from datetime import datetime

    from fastapi import HTTPException
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask
    from app.models.todo_project import TodoProject
    from app.todos.projects import refresh_meeting_project_members

    if payload.target_id == project_id:
        raise HTTPException(status_code=422, detail="目标项目不能是源项目自身")
    with Session(get_engine()) as session:
        source = session.get(TodoProject, project_id)
        target = session.get(TodoProject, payload.target_id)
        if source is None or target is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        moved = 0
        for task in session.exec(
            select(PdcaTask).where(PdcaTask.project_id == project_id)
        ).all():
            task.project_id = target.id
            task.updated_at = datetime.utcnow()
            session.add(task)
            moved += 1
        source.status = "已闭环"
        source.updated_at = datetime.utcnow()
        session.add(source)
        session.commit()
        refresh_meeting_project_members(session)
        session.commit()
    log_action(
        username=user.username,
        action="todo_project_merge",
        resource=source.key,
        detail={"target_id": target.id, "target": target.name, "moved": moved},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "moved": moved, "target_id": target.id, "target": target.name}


@router.patch("/api/todos/tasks/{task_id}")
async def reassign_task_project(
    task_id: int,
    payload: TaskProjectRequest,
    request: Request,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """把待办转挂到指定项目；project_id=null 摘出为散单（走个人催办）。"""
    from datetime import datetime

    from fastapi import HTTPException
    from sqlmodel import Session

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask
    from app.models.todo_project import TodoProject
    from app.todos.projects import refresh_meeting_project_members

    with Session(get_engine()) as session:
        row = session.get(PdcaTask, task_id)
        if row is None:
            raise HTTPException(status_code=404, detail="待办不存在")
        if payload.project_id is not None:
            project = session.get(TodoProject, payload.project_id)
            if project is None:
                raise HTTPException(status_code=422, detail="项目不存在")
            if project.status == "已闭环":
                project.status = "跟进中"
                project.updated_at = datetime.utcnow()
                session.add(project)
            row.project_id = project.id
        else:
            row.project_id = None
        row.updated_at = datetime.utcnow()
        session.add(row)
        session.commit()
        refresh_meeting_project_members(session)
        session.commit()
    log_action(
        username=user.username,
        action="todo_task_project",
        resource=str(task_id),
        detail={"project_id": row.project_id},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "task_id": task_id, "project_id": row.project_id}


@router.get("/api/todos/tasks")
async def list_tasks(
    project_id: Optional[int] = None,
    unassigned: bool = False,
    open_only: bool = True,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """待办列表：按项目筛选（unassigned=true 取散单），open_only 只取未完成。

    供管理面板做待办转挂（PATCH /api/todos/tasks/{id}）与摘出。
    """
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask

    with Session(get_engine()) as session:
        query = select(PdcaTask)
        if unassigned:
            query = query.where(PdcaTask.project_id.is_(None))
        elif project_id is not None:
            query = query.where(PdcaTask.project_id == project_id)
        rows = list(session.exec(query.order_by(PdcaTask.task_date.asc())).all())
    if open_only:
        rows = [row for row in rows if not _status_is_done(row.status)]
    return [
        {
            "id": row.id,
            "task_date": row.task_date,
            "title": row.title,
            "owner": row.owner,
            "status": row.status,
            "source": row.source,
            "meeting_name": row.meeting_name,
            "project_id": row.project_id,
        }
        for row in rows
    ]


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


