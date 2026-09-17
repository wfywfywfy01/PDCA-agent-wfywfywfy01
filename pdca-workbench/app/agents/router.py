# -*- coding: utf-8 -*-
"""多智能体 API（第 12.3 节）：任务、运行、群状态、Outbox 审批、健康、统计。

权限：
- 读接口：manager 及以上（admin 全量；viewer 拒绝）；
- 审批/重试/执行写接口：仅 admin；
- 所有写操作写 audit_logs。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from loguru import logger
from sqlmodel import Session

from app.agents.flow_controller import all_slot_health_today
from app.agents.group_context import (
    ctob_group_configs,
    daily_report_group_config,
    group_state_summary,
    performance_group_configs,
)
from app.agents.outbox import (
    approve_outbox,
    list_outbox,
    reject_outbox,
    retry_outbox,
    send_due,
)
from app.agents.supervisor_service import (
    _tool_task_stats,
    department_summary_run,
    execute_run,
    list_runs,
    start_run,
)
from app.auth.deps import get_current_user, require_role
from app.auth.models import User
from app.audit import log_action
from app.database import get_session
from app.validation import require_iso_date

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")



def _run_dict(run) -> dict:
    return {
        "id": run.id,
        "run_key": run.run_key,
        "run_type": run.run_type,
        "status": run.status,
        "current_node": run.current_node,
        "requested_by": run.requested_by,
        "input_text": run.input_text[:500],
        "result_text": run.result_text[:2000],
        "error_code": run.error_code,
        "error_detail": run.error_detail[:500],
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }


@router.post("/tasks")
async def create_agent_task(
    payload: dict,
    user: Annotated[User, Depends(require_role("manager"))],
):
    """创建并立即执行一次主 Agent 任务（默认只返回结果，不推群）。"""
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text 不能为空")
    run = start_run(
        run_type="user_task",
        requested_by=user.username,
        input_text=text[:4000],
        source_type="api",
    )
    result = execute_run(run.id)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error") or "执行失败")
    log_action(user.username, "agent.task", f"run:{run.id}", {"text": text[:200]})
    return result


@router.get("/runs")
async def runs_list(
    limit: int = Query(50, ge=1, le=200),
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    return {"runs": list_runs(limit=limit)}


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: int,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    from app.agents.models import AgentRun
    from app.database import get_engine

    with Session(get_engine()) as session:
        row = session.get(AgentRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="运行不存在")
    return _run_dict(row)


@router.post("/runs/{run_id}/execute")
async def run_execute(
    run_id: int,
    user: Annotated[User, Depends(require_role("admin"))],
):
    result = execute_run(run_id)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail") or result.get("error"))
    log_action(user.username, "agent_run.execute", f"run:{run_id}")
    return result


@router.post("/department-summary")
async def department_summary(
    payload: dict,
    user: Annotated[User, Depends(require_role("manager"))],
):
    """生成部门总结（聚合 + 事实校验；有争议问题会写 waiting_approval）。"""
    day = require_iso_date(str(payload.get("date") or _today()))
    result = department_summary_run(day, user.username)
    log_action(user.username, "agent.department_summary", f"day:{day}")
    return result


@router.get("/groups")
async def groups_state(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """全部群实例状态（达标 5 群 + C转B 16 群 + 日报群）。"""
    day = _today()
    configs = performance_group_configs(day) + ctob_group_configs(day)
    report = daily_report_group_config(day)
    if report:
        configs.append(report)
    states = []
    for config in configs:
        try:
            states.append(group_state_summary(config))
        except Exception as exc:  # noqa: BLE001
            logger.warning("群状态读取失败 {}: {}", config.channel_id, exc)
            states.append({"channel_id": config.channel_id, "error": str(exc)[:200]})
    return {"groups": states, "count": len(states)}



@router.get("/groups/{channel_id}/state")
async def group_state(
    channel_id: str,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """单群状态（channel_id 隔离，不允许串群读取）。"""
    day = _today()
    configs = performance_group_configs(day) + ctob_group_configs(day)
    report = daily_report_group_config(day)
    if report:
        configs.append(report)
    for config in configs:
        if config.channel_id == channel_id:
            return group_state_summary(config)
    raise HTTPException(status_code=404, detail="群不在注册表中")


@router.get("/outbox")
async def outbox_list(
    approval_status: str = Query("", max_length=32),
    limit: int = Query(100, ge=1, le=300),
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    return {"items": list_outbox(approval_status=approval_status, limit=limit)}


@router.post("/outbox/{outbox_id}/approve")
async def outbox_approve(
    outbox_id: int,
    user: Annotated[User, Depends(require_role("admin"))],
):
    result = approve_outbox(outbox_id, user.username)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail"))
    log_action(user.username, "agent_outbox.approve", f"outbox:{outbox_id}")
    return result


@router.post("/outbox/{outbox_id}/reject")
async def outbox_reject(
    outbox_id: int,
    payload: dict,
    user: Annotated[User, Depends(require_role("admin"))],
):
    result = reject_outbox(outbox_id, user.username, str(payload.get("reason") or ""))
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail"))
    log_action(user.username, "agent_outbox.reject", f"outbox:{outbox_id}")
    return result


@router.post("/outbox/{outbox_id}/retry")
async def outbox_retry(
    outbox_id: int,
    user: Annotated[User, Depends(require_role("admin"))],
):
    result = retry_outbox(outbox_id, user.username)
    if not result.get("ok"):
        raise HTTPException(status_code=409, detail=result.get("detail"))
    log_action(user.username, "agent_outbox.retry", f"outbox:{outbox_id}")
    return result


@router.post("/outbox/send-due")
async def outbox_send_due(
    user: Annotated[User, Depends(require_role("admin"))],
):
    result = send_due()
    log_action(user.username, "agent_outbox.send_due", "", result)
    return result


@router.get("/stats")
async def stats(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """管理后台核心统计：每人待办数/闭环率 + 运行与审批概览。"""
    return {
        "task_stats": _tool_task_stats(),
        "pending_outbox": list_outbox(approval_status="pending", limit=50),
        "recent_runs": list_runs(limit=10),
        "slot_health": all_slot_health_today(_today()),
    }


@router.get("/health")
async def agent_health(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """Agent 子系统健康：开关、模型配置、Outbox 积压、档位健康摘要。"""
    from app.config import get_settings
    from app.database import get_db_mode

    settings = get_settings()
    slot_reports = all_slot_health_today(_today())
    problems = [item for item in slot_reports if not item.get("ok")]
    return {
        "enabled": settings.agent_enabled,
        "shadow_mode": settings.agent_shadow_mode,
        "outbox_enabled": settings.agent_outbox_enabled,
        "auto_template_push": settings.agent_auto_template_push,
        "task_write": settings.agent_task_write,
        "llm_draft": settings.agent_llm_draft,
        "qwen_configured": bool(settings.qwen_api_key),
        "qwen_model": settings.qwen_model,
        "asr_enabled": settings.asr_enabled,
        "healthcheck_enabled": settings.agent_healthcheck_enabled,
        "db_mode": get_db_mode(),
        "slot_problems": problems,
        "slot_problem_count": len(problems),
        "pending_outbox_count": len(list_outbox(approval_status="pending", limit=200)),
        "ok": not problems,
    }



