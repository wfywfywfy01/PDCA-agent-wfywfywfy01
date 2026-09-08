# -*- coding: utf-8 -*-
"""待办模块的统一行级权限；只接受管理员显式配置的 owner/team 映射。"""
from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.scope import normalize_scope_key, visible_owner_keys
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.todos.owners import split_owners


def allowed_owner_keys(user: User | None, session: Session) -> set[str] | None:
    """None 表示管理员全量；空集合表示 fail-closed。"""
    if user is None or user.role == "admin":
        return None
    return {
        normalize_scope_key(value)
        for value in (visible_owner_keys(user, session) or [])
        if normalize_scope_key(value)
    }


def owner_allowed(owner: str, allowed: set[str] | None) -> bool:
    if allowed is None:
        return True
    parts = {
        normalize_scope_key(part)
        for part in split_owners(owner)
        if normalize_scope_key(part)
    }
    return bool(parts) and parts.issubset(allowed)


def task_allowed(task: PdcaTask, allowed: set[str] | None) -> bool:
    return owner_allowed(task.owner, allowed)


def project_allowed(
    project: TodoProject,
    session: Session,
    allowed: set[str] | None,
    tasks: list[PdcaTask] | None = None,
) -> bool:
    if allowed is None:
        return True
    project_tasks = (
        [task for task in tasks if task.project_id == project.id]
        if tasks is not None
        else list(session.exec(
            select(PdcaTask).where(PdcaTask.project_id == project.id)
        ).all())
    )
    if project_tasks:
        # 混合团队项目整体对主管隐藏，避免通过项目元数据侧漏。
        return all(task_allowed(task, allowed) for task in project_tasks)
    return owner_allowed(project.coordinator, allowed)


def require_task(task: PdcaTask | None, allowed: set[str] | None) -> PdcaTask:
    if task is None or not task_allowed(task, allowed):
        raise HTTPException(status_code=404, detail="待办不存在")
    return task


def require_project(
    project: TodoProject | None,
    session: Session,
    allowed: set[str] | None,
) -> TodoProject:
    if project is None or not project_allowed(project, session, allowed):
        raise HTTPException(status_code=404, detail="项目不存在")
    return project
