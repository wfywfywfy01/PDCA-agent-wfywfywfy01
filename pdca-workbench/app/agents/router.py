# -*- coding: utf-8 -*-
"""多智能体 API（第 12.3 节）：任务、运行、群状态、Outbox 审批、健康、统计。

权限：
- 读接口：manager 及以上（admin 全量；viewer 拒绝）；
- 审批/重试/执行写接口：仅 admin；
- 所有写操作写 audit_logs。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from sqlmodel import Session

from app.agents.flow_controller import all_slot_health_today, run_health_checks_for
from app.agents.group_context import (
    ctob_group_configs,
    daily_report_group_config,
    group_state_summary,
    performance_group_configs,
)
from app.agents.group_service import list_drafts, run_group_instance
from app.agents.mto_vision_service import review_owner_detail
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
from app.auth.deps import require_role
from app.auth.models import User
from app.auth.scope import DataScope, normalize_scope_key, resolve_data_scope
from app.audit import log_action
from app.validation import require_iso_date

router = APIRouter(prefix="/api/agents", tags=["agents"])


def _today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")


def _scope(user: User) -> DataScope:
    from app.database import get_engine

    with Session(get_engine()) as session:
        return resolve_data_scope(user, session)


def _all_group_configs(day: str):
    configs = performance_group_configs(day) + ctob_group_configs(day)
    report = daily_report_group_config(day)
    if report:
        configs.append(report)
    return configs


def _visible_group_configs(user: User, day: str):
    scope = _scope(user)
    configs = _all_group_configs(day)
    if scope.unrestricted:
        return configs
    owners = {normalize_scope_key(value) for value in scope.owner_keys}
    return [
        config for config in configs
        if config.owners and all(normalize_scope_key(owner) in owners for owner in config.owners)
    ]


def _allowed_owners(user: User) -> set[str] | None:
    scope = _scope(user)
    return None if scope.unrestricted else set(scope.owner_keys)



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
    result = execute_run(run.id, allowed_owners=_allowed_owners(user))
    if not result.get("ok"):
        status_code = 403 if result.get("error_code") == "forbidden" else 502
        raise HTTPException(status_code=status_code, detail=result.get("error") or "执行失败")
    log_action(user.username, "agent.task", f"run:{run.id}", {"text": text[:200]})
    return result


@router.get("/runs")
async def runs_list(
    limit: int = Query(50, ge=1, le=200),
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    requested_by = "" if _scope(user).unrestricted else user.username
    return {"runs": list_runs(limit=limit, requested_by=requested_by)}


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: int,
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    from app.agents.models import AgentRun
    from app.database import get_engine

    with Session(get_engine()) as session:
        row = session.get(AgentRun, run_id)
    if row is None or (not _scope(user).unrestricted and row.requested_by != user.username):
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
    user: Annotated[User, Depends(require_role("admin"))],
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
    configs = _visible_group_configs(user, day)
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
    configs = _visible_group_configs(user, day)
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
    channels = {config.channel_id for config in _visible_group_configs(user, _today())}
    allowed_channels = None if _scope(user).unrestricted else channels
    return {"items": list_outbox(
        approval_status=approval_status, limit=limit,
        allowed_channel_ids=allowed_channels,
    )}


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
    scope = _scope(user)
    owners = None if scope.unrestricted else set(scope.owner_keys)
    channels = {config.channel_id for config in _visible_group_configs(user, _today())}
    allowed_channels = None if scope.unrestricted else channels
    slot_health = all_slot_health_today(_today())
    if allowed_channels is not None:
        slot_health = [
            row for row in slot_health if row.get("channel_id") in allowed_channels
        ]
    return {
        "task_stats": _tool_task_stats(allowed_owners=owners),
        "pending_outbox": list_outbox(
            approval_status="pending", limit=50,
            allowed_channel_ids=allowed_channels,
        ),
        "recent_runs": list_runs(
            limit=10, requested_by="" if scope.unrestricted else user.username
        ),
        "slot_health": slot_health,
    }


@router.get("/health")
async def agent_health(
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """Agent 子系统健康：开关、模型配置、Outbox 积压、档位健康摘要。"""
    from app.config import get_settings
    from app.database import get_db_mode

    settings = get_settings()
    scope = _scope(user)
    channels = {config.channel_id for config in _visible_group_configs(user, _today())}
    allowed_channels = None if scope.unrestricted else channels
    slot_reports = all_slot_health_today(_today())
    if allowed_channels is not None:
        slot_reports = [
            row for row in slot_reports if row.get("channel_id") in allowed_channels
        ]
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
        "pending_outbox_count": len(list_outbox(
            approval_status="pending", limit=200,
            allowed_channel_ids=allowed_channels,
        )),
        "ok": not problems,
    }


@router.get("/drafts")
async def drafts_list(
    day: str = Query("", max_length=10),
    channel_id: str = Query("", max_length=64),
    limit: int = Query(100, ge=1, le=300),
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """群 Agent 草稿列表（影子与正式都可见）。"""
    if day:
        day = require_iso_date(day)
    channels = {config.channel_id for config in _visible_group_configs(user, day or _today())}
    allowed_channels = None if _scope(user).unrestricted else channels
    if channel_id and allowed_channels is not None and channel_id not in allowed_channels:
        raise HTTPException(status_code=404, detail="群不在授权范围内")
    return {"items": list_drafts(
        day=day, channel_id=channel_id, limit=limit,
        allowed_channel_ids=allowed_channels,
    )}


@router.post("/groups/{channel_id}/run")
async def group_shadow_run(
    channel_id: str,
    payload: dict,
    user: Annotated[User, Depends(require_role("admin"))],
):
    """手动试跑单群影子草稿（只生成草稿，绝不推群、不写任务）。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    day = str(payload.get("day") or "")
    if day:
        day = require_iso_date(day)
    try:
        hour = int(payload.get("hour") or 20)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="hour 必须是整数")
    if hour not in (10, 15, 20):
        raise HTTPException(status_code=422, detail="hour 只支持 10/15/20")
    configs = performance_group_configs(day or _today()) + ctob_group_configs(day or _today())
    report = daily_report_group_config(day or _today())
    if report:
        configs.append(report)
    config = next((item for item in configs if item.channel_id == channel_id), None)
    if config is None:
        raise HTTPException(status_code=404, detail="群不在注册表中")
    if not day:
        day = _dt.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d")
    result = run_group_instance(config, hour=hour, day=day, shadow=True)
    log_action(user.username, "agent_group.shadow_run", channel_id, {"day": day, "hour": hour})
    return {"ok": True, **result}


@router.post("/groups/all-run")
async def all_groups_shadow_run(
    payload: dict,
    user: Annotated[User, Depends(require_role("admin"))],
):
    """手动试跑全部群影子草稿（最近档；只出草稿，绝不推群、不写任务）。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    try:
        hour = int(payload.get("hour") or 20)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="hour 必须是整数")
    if hour not in (10, 15, 20):
        raise HTTPException(status_code=422, detail="hour 只支持 10/15/20")
    day = str(payload.get("day") or "")
    if day:
        day = require_iso_date(day)
    configs = performance_group_configs(day or _today()) + ctob_group_configs(day or _today())
    report = daily_report_group_config(day or _today())
    if report:
        configs.append(report)
    generated = 0
    failures: list[dict] = []
    for config in configs:
        try:
            group_day = day or _dt.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d")
            run_group_instance(config, hour=hour, day=group_day, shadow=True)
            generated += 1
        except Exception as exc:  # noqa: BLE001 — 单群失败不阻断其他群
            failures.append({"channel_id": config.channel_id, "error": str(exc)[:200]})
    log_action(user.username, "agent_group.shadow_run_all", "", {"hour": hour, "generated": generated})
    return {"ok": True, "generated": generated, "failed": len(failures), "failures": failures}


@router.get("/mto")
async def mto_detail(
    owner: str = Query(..., max_length=64, description="负责人姓名，如 于冰"),
    day: str = Query("", max_length=10),
    force: bool = Query(False, description="忽略 1 小时缓存，重新下载+OCR"),
    user: Annotated[User, Depends(require_role("manager"))] = None,
):
    """MTO 明细核对：每张图一行（文件/机型/报价/达标/交期/客户）+ 当日汇总。

    口径：单款报价 ≥30 万（汇率 7.1）算达标；读不出写“待确认”，不编造金额。
    """
    day = require_iso_date(day or _today())
    owners = _allowed_owners(user)
    if owners is not None and normalize_scope_key(owner) not in {
        normalize_scope_key(value) for value in owners
    }:
        raise HTTPException(status_code=404, detail="负责人不在授权范围内")
    result = review_owner_detail(owner, day, force=force)
    if result.get("error"):
        raise HTTPException(status_code=409, detail=result["error"])
    return result


@router.post("/mto/cleanup")
async def mto_cleanup(
    user: Annotated[User, Depends(require_role("admin"))],
):
    """手动触发 MTO 图片下载残留清理（默认每日 03:30 自动执行）。"""
    from app.config import get_settings
    from app.mto_ocr import cleanup_temp_files

    settings = get_settings()
    result = cleanup_temp_files(getattr(settings, "mto_temp_max_age_hours", 24.0))
    log_action(user.username, "mto.cleanup", "", result)
    return {"ok": True, **result}


@router.post("/health-check")
async def trigger_health_check(
    user: Annotated[User, Depends(require_role("admin"))],
):
    """手动触发一次档位健康检查（补扫当天已过档位；只读，不补发）。"""
    try:
        reports = run_health_checks_for()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"健康检查执行失败: {exc}") from exc
    log_action(user.username, "agent_slot.health_check", "", {"reports": len(reports)})
    return {"ok": True, "reports": reports}



