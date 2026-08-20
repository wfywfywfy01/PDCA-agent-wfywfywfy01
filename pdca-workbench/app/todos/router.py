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
