# -*- coding: utf-8 -*-
"""主 Agent 服务：任务运行生命周期与工具白名单（第 7 节 / 12.3 节）。

agent_runs 一行 = 一个根运行；节点顺序 receive->classify->load_context->
plan->validate_plan->dispatch->aggregate->fact_check->approval_gate->
persist_result->complete。所有工具调用走白名单；模型不可用不影响定时任务。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlmodel import Session, select

from app.audit import log_action
from app.config import get_settings
from app.database import get_engine
from app.agents.events import write_event
from app.agents.models import AgentRun
from app.agents.supervisor_graph import (
    build_department_summary,
    classify_intent,
    decision_with_llm,
    fact_check_summary,
)

# 工具白名单：只有这里声明的动作可被派发（prompt 注入无法扩权）。
_ALLOWED_ACTIONS = {
    "collect": "flow_controller",
    "draft_summary": "supervisor",
    "query_tasks": "group_agent",
    "group_followup": "group_agent",
    "task_stats": "supervisor",
    "group_state": "supervisor",
    "slot_health": "supervisor",
    "outbox_list": "supervisor",
    "ask_user": "supervisor",
    "noop": "supervisor",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_run_key(prefix: str = "run") -> str:
    """全局唯一运行键。"""
    return f"{prefix}:{utcnow().strftime('%Y%m%d')}:{uuid.uuid4().hex[:16]}"


def start_run(
    *,
    run_type: str,
    requested_by: str,
    input_text: str = "",
    input_json: str = "",
    source_type: str = "api",
    source_ref: str = "",
) -> AgentRun:
    """创建 agent_runs 根运行并写 task.received 事件。"""
    now = utcnow()
    run = AgentRun(
        run_key=new_run_key(run_type),
        thread_id=f"supervisor:{run_type}:{utcnow().strftime('%Y%m%d%H%M%S')}",
        run_type=run_type,
        source_type=source_type,
        source_ref=source_ref[:256],
        requested_by=requested_by[:128],
        input_text=input_text,
        input_json=input_json,
        status="queued",
        created_at=now,
        updated_at=now,
    )
    with Session(get_engine()) as session:
        session.add(run)
        session.commit()
        session.refresh(run)
    write_event(
        "task.received",
        producer="supervisor",
        run_id=run.id,
        event_key=f"supervisor:received:{run.id}",
        payload={"run_type": run_type, "requested_by": requested_by},
    )
    return run



def _set_run(
    run_id: int,
    *,
    status: str | None = None,
    current_node: str | None = None,
    result_text: str | None = None,
    result_json: str | None = None,
    error_code: str = "",
    error_detail: str = "",
) -> None:
    """更新运行状态（不抛异常，失败只记日志）。"""
    try:
        with Session(get_engine()) as session:
            row = session.get(AgentRun, run_id)
            if row is None:
                return
            if status is not None:
                row.status = status[:32]
            if current_node is not None:
                row.current_node = current_node[:64]
            if result_text is not None:
                row.result_text = result_text
            if result_json is not None:
                row.result_json = result_json
            if error_code:
                row.error_code = error_code[:64]
            if error_detail:
                row.error_detail = error_detail
            if status in ("succeeded", "failed", "cancelled"):
                row.finished_at = utcnow()
            elif status == "running" and row.started_at is None:
                row.started_at = utcnow()
            row.updated_at = utcnow()
            session.add(row)
            session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("更新运行状态失败 run={}: {}", run_id, exc)


def _tool_task_stats(target: str = "all") -> dict:
    """工具：每人待办统计（谁有多少待办、闭环没有）。"""
    from sqlmodel import Session as DbSession

    from app.models.pdca_task import PdcaTask

    with DbSession(get_engine()) as session:
        rows = session.exec(select(PdcaTask).order_by(PdcaTask.id)).all()
    by_owner: dict[str, dict] = {}
    for row in rows:
        owner = (row.owner or "").strip() or "未指定"
        bucket = by_owner.setdefault(
            owner,
            {"open": 0, "done": 0, "blocked": 0, "verified": 0, "unverified": 0, "total": 0},
        )
        bucket["total"] += 1
        status = str(row.status or "")
        if status in ("done", "completed", "complete"):
            bucket["done"] += 1
        else:
            bucket["open"] += 1
        if row.blocked_reason:
            bucket["blocked"] += 1
        verification = row.verification_status or "unverified"
        if verification == "verified":
            bucket["verified"] += 1
        else:
            bucket["unverified"] += 1
    stats = []
    for owner, bucket in by_owner.items():
        bucket["owner"] = owner
        bucket["closure_rate"] = round(bucket["done"] / bucket["total"], 4) if bucket["total"] else 0.0
        stats.append(bucket)
    stats.sort(key=lambda item: (-item["open"], item["owner"]))
    return {"owners": stats, "total_tasks": len(rows)}


def _tool_group_state(target: str = "all") -> dict:
    """工具：全部群实例状态快照。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    from app.agents.group_context import (
        ctob_group_configs,
        daily_report_group_config,
        group_state_summary,
        performance_group_configs,
    )

    day = _dt.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    configs = performance_group_configs(day) + ctob_group_configs(day)
    report = daily_report_group_config(day)
    if report:
        configs.append(report)
    states = []
    for config in configs:
        try:
            states.append(group_state_summary(config))
        except Exception as exc:  # noqa: BLE001
            states.append({"channel_id": config.channel_id, "error": str(exc)[:200]})
    return {"groups": states, "count": len(states)}


def _tool_slot_health(target: str = "all") -> dict:
    """工具：当日全部档位健康状态（只读，不告警侧查）。"""
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo

    from app.agents.flow_controller import all_slot_health_today

    day = _dt.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    return {"day": day, "reports": all_slot_health_today(day)}


def _tool_outbox_list(target: str = "pending") -> dict:
    """工具：Outbox 列表。"""
    from app.agents.outbox import list_outbox

    return {"items": list_outbox(approval_status=target if target != "all" else "", limit=50)}


_TOOLS = {
    "task_stats": _tool_task_stats,
    "group_state": _tool_group_state,
    "slot_health": _tool_slot_health,
    "outbox_list": _tool_outbox_list,
}


def execute_run(run_id: int) -> dict:
    """执行一次根运行：确定性路由优先，LLM 决策兜底，最后过事实校验。"""
    with Session(get_engine()) as session:
        run = session.get(AgentRun, run_id)
    if run is None:
        return {"ok": False, "detail": "运行不存在"}
    if run.status not in ("queued", "failed"):
        return {"ok": False, "detail": f"状态 {run.status} 不允许执行"}
    _set_run(run_id, status="running", current_node="classify")
    write_event("task.planned", producer="supervisor", run_id=run_id,
                event_key=f"supervisor:planned:{run_id}")
    try:
        decision = classify_intent(run.input_text) or decision_with_llm(run.input_text)
        _set_run(run_id, current_node="validate_plan")
        # 意图收敛到规范值（模型自由文本意图 → 规范枚举），便于状态与审计。
        from app.agents.supervisor_graph import normalize_intent

        decision.intent = normalize_intent(decision.intent, run.input_text)
        actions = [
            action for action in decision.actions
            if action.action_type in _ALLOWED_ACTIONS
        ]
        if decision.intent == "risky_action" and not decision.approval_required:
            decision.approval_required = True
        results: dict[str, object] = {"decision": decision.model_dump()}
        _set_run(run_id, current_node="dispatch")
        for action in actions:
            tool = _TOOLS.get(action.action_type)
            if tool is not None:
                try:
                    results[action.action_type] = tool(action.target)
                except Exception as exc:  # noqa: BLE001 — 单工具失败写待确认
                    results[action.action_type] = {"error": str(exc)[:200], "status": "待确认"}
            elif action.action_type == "collect":
                from app.agents.group_service import run_group_slot

                results["collect"] = {
                    "performance": run_group_slot(group_type="performance", hour=10),
                }
            elif action.action_type == "draft_summary":
                from datetime import datetime as _dt
                from zoneinfo import ZoneInfo

                day = _dt.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
                summary = build_department_summary(day)
                results["draft_summary"] = summary
                problems = fact_check_summary(summary["summary_draft"])
                if problems:
                    results["fact_check"] = problems
                    results["fact_check_passed"] = False
                else:
                    results["fact_check"] = []
                    results["fact_check_passed"] = True
        # LLM 路径默认只读工具：查询类意图即使没给出白名单动作，也返回真实数据；
        # 部门总结意图兜底生成总结 + 事实校验。两者均只读，不产生任何外发。
        if decision.intent == "known_readonly_query" and not actions:
            for tool_name in ("task_stats", "group_state", "slot_health"):
                try:
                    results[tool_name] = _TOOLS[tool_name]("all")
                except Exception as exc:  # noqa: BLE001
                    results[tool_name] = {"error": str(exc)[:200], "status": "待确认"}
        if decision.intent == "department_summary" and "draft_summary" not in results:
            from datetime import datetime as _dt
            from zoneinfo import ZoneInfo

            day = _dt.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            summary = build_department_summary(day)
            results["draft_summary"] = summary
            problems = fact_check_summary(summary["summary_draft"])
            results["fact_check"] = problems
            results["fact_check_passed"] = not problems
        _set_run(run_id, current_node="aggregate")
        if decision.intent in ("risky_action",) and decision.approval_required:
            status = "waiting_approval"
        else:
            status = "succeeded"
        write_event("task.dispatched", producer="supervisor", run_id=run_id,
                    event_key=f"supervisor:dispatched:{run_id}",
                    payload={"intent": decision.intent,
                             "actions": [a.action_type for a in actions]})
        _set_run(
            run_id,
            status=status,
            current_node="complete",
            result_text=decision.summary[:4000],
            result_json=json.dumps(results, ensure_ascii=False)[:65536],
        )
        log_action(run.requested_by, "agent_run.executed", f"run:{run_id}",
                   {"intent": decision.intent, "status": status})
        return {"ok": True, "run_id": run_id, "status": status,
                "intent": decision.intent, "results": results}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Supervisor 运行失败 run={}: {}", run_id, exc)
        _set_run(run_id, status="failed", error_code=type(exc).__name__,
                 error_detail=str(exc)[:2000])
        write_event("task.blocked", producer="supervisor", run_id=run_id,
                    event_key=f"supervisor:failed:{run_id}",
                    payload={"error": str(exc)[:300]})
        return {"ok": False, "run_id": run_id, "status": "failed", "error": str(exc)[:300]}


def department_summary_run(day: str, requested_by: str) -> dict:
    """部门总结根运行：聚合 + 事实校验 + 落库。"""
    run = start_run(
        run_type="department_summary",
        requested_by=requested_by,
        input_text=f"生成 {day} 海外渠道部门总结",
        source_type="api",
    )
    _set_run(run.id, status="running", current_node="aggregate")
    try:
        summary = build_department_summary(day)
        problems = fact_check_summary(summary["summary_draft"])
        passed = not problems
        _set_run(
            run.id,
            status="succeeded" if passed else "waiting_approval",
            current_node="complete",
            result_text=summary["summary_draft"],
            result_json=json.dumps(
                {"summary": summary, "fact_check": problems, "passed": passed},
                ensure_ascii=False,
            )[:65536],
        )
        return {"ok": True, "run_id": run.id, "passed": passed, "problems": problems,
                "summary_draft": summary["summary_draft"]}
    except Exception as exc:  # noqa: BLE001
        _set_run(run.id, status="failed", error_code=type(exc).__name__,
                 error_detail=str(exc)[:2000])
        return {"ok": False, "run_id": run.id, "error": str(exc)[:300]}


def list_runs(limit: int = 50) -> list[dict]:
    """运行列表（后台展示，倒序）。"""
    with Session(get_engine()) as session:
        rows = session.exec(
            select(AgentRun).order_by(AgentRun.id.desc()).limit(min(limit, 200))
        ).all()
    return [
        {
            "id": row.id,
            "run_key": row.run_key,
            "run_type": row.run_type,
            "status": row.status,
            "requested_by": row.requested_by,
            "input_text": row.input_text[:200],
            "result_text": row.result_text[:400],
            "current_node": row.current_node,
            "error_detail": row.error_detail[:200],
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in rows
    ]



