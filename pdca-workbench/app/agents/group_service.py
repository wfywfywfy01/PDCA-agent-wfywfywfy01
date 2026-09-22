# -*- coding: utf-8 -*-
"""群 Agent 服务：一个档位内为每个群实例跑 GroupGraph（第 9 节）。

开关：
  PDCA_AGENT_ENABLED=0          整体关闭（部署默认）
  PDCA_AGENT_SHADOW_MODE=1      影子模式：只生成草稿与结论，不写 pdca_tasks、
                                不建 Outbox、绝不推群（部署默认）
  PDCA_AGENT_TASK_WRITE=0       非影子下是否允许把结论写回 pdca_tasks
  PDCA_AGENT_LLM_DRAFT=0        是否用本地 Qwen 润色草稿（默认确定性模板）
单群失败不阻断其他群；模型失败回退确定性草稿。
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from app.agents.events import write_event
from app.agents.group_context import GroupConfig, load_slot_snapshot
from app.agents.group_graph import GroupGraph, apply_task_updates
from app.config import get_settings

def _polish_draft(draft: str, config: GroupConfig) -> str:
    """用文本模型（DeepSeek flash，见 PDCA_SUPERVISOR_*）润色草稿。

    模型路由约定（2026-09-17 拍板）：图像/OCR 走本地 Qwen（mto_ocr），
    其他文本任务走 DeepSeek flash；失败/未配置返回原文，不阻断确定性链路。
    """
    try:
        from app.agents.llm_client import QwenUnavailable, supervisor_client
        from app.agents.prompts import load_group

        client = supervisor_client()
        reply = client.chat(
            [
                {"role": "system", "content": load_group()},
                {
                    "role": "user",
                    "content": "请润色以下群催办草稿，保持事实与语气一致，不改动数字：\n" + draft[:4000],
                },
            ],
            max_tokens=4096,  # deepseek-flash 推理模型：reasoning 占预算，需足够大否则草稿为空
            temperature=0.2,
        )
        polished = (reply.get("content") or "").strip()
        return polished[:8000] if polished else draft
    except QwenUnavailable as exc:
        logger.warning("群草稿润色失败，回退确定性草稿: {}", exc)
        return draft
    except Exception as exc:  # noqa: BLE001
        logger.warning("群草稿润色异常，回退确定性草稿: {}", exc)
        return draft


def _draft_template(state: dict, config: GroupConfig) -> str:
    """确定性草稿模板（不改三追文案；这是 Agent 侧催办草稿）。"""
    buckets = state.get("buckets") or {}
    head = {
        "10:00": "今日任务（请确认或补充）：",
        "15:00": "本档相对 10:00 的变化：",
        "20:00": "今日兑现核验：",
    }.get(config.slot, "催办：")
    lines = [head]
    for task in (buckets.get("pending") or [])[:5]:
        owner = task.get("owner") or "未指定"
        lines.append("- 待认领：" + str(task.get("title")) + "（" + owner + "）")
    for task in (buckets.get("overdue") or [])[:5]:
        owner = task.get("owner") or "未指定"
        lines.append("- 逾期：" + str(task.get("title")) + "（" + owner + "）")
    for task in (buckets.get("blocked") or [])[:5]:
        reason = task.get("blocked_reason") or "待补充"
        lines.append("- 卡点：" + str(task.get("title")) + "｜" + reason)
    verified = [
        t for t in (state.get("tasks") or []) if t.get("computed_verification") == "verified"
    ]
    if verified:
        lines.append("- 已有证据闭环 " + str(len(verified)) + " 项")
    if len(lines) == 1:
        lines.append("- 本档无新增变化（待确认）")
    return "\n".join(lines)


def persist_draft(
    *,
    config: GroupConfig,
    day: str,
    slot: str,
    body: str,
    approval_policy: str,
    shadow: bool,
    run_id: int | None = None,
) -> int:
    """把群草稿落库（影子与正式都落）；同 channel/day/slot 重跑覆盖。"""
    from sqlmodel import Session, select

    from app.agents.models import AgentDraft
    from app.database import get_engine

    draft_key = f"{config.channel_id}:{day}:{slot}"
    with Session(get_engine()) as session:
        row = session.exec(
            select(AgentDraft).where(AgentDraft.draft_key == draft_key)
        ).first()
        if row is None:
            row = AgentDraft(
                draft_key=draft_key,
                run_id=run_id,
                channel_id=config.channel_id,
                group_name=config.group_name,
                group_type=config.group_type,
                day=day,
                slot=slot,
                body=body,
                approval_policy=approval_policy,
                shadow=shadow,
            )
            session.add(row)
        else:
            row.body = body
            row.approval_policy = approval_policy
            row.shadow = shadow
            if run_id is not None:
                row.run_id = run_id
            row.updated_at = datetime.now(timezone.utc)
            session.add(row)
        session.commit()
        session.refresh(row)
        return row.id or 0


def list_drafts(
    *, day: str = "", channel_id: str = "", limit: int = 100,
    allowed_channel_ids: set[str] | None = None,
) -> list[dict]:
    """后台草稿列表（倒序）。"""
    from sqlmodel import Session, select

    from app.agents.models import AgentDraft
    from app.database import get_engine

    statement = select(AgentDraft).order_by(AgentDraft.id.desc()).limit(min(limit, 300))
    if day:
        statement = statement.where(AgentDraft.day == day)
    if channel_id:
        statement = statement.where(AgentDraft.channel_id == channel_id)
    if allowed_channel_ids is not None:
        statement = statement.where(AgentDraft.channel_id.in_(sorted(allowed_channel_ids)))
    with Session(get_engine()) as session:
        rows = session.exec(statement).all()
    return [
        {
            "id": row.id,
            "draft_key": row.draft_key,
            "channel_id": row.channel_id,
            "group_name": row.group_name,
            "group_type": row.group_type,
            "day": row.day,
            "slot": row.slot,
            "body": row.body[:6000],
            "approval_policy": row.approval_policy,
            "shadow": row.shadow,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


def run_group_instance(
    config: GroupConfig,
    *,
    hour: int,
    day: str,
    shadow: bool | None = None,
) -> dict:
    """跑一个群实例：读快照 -> GroupGraph -> 草稿 -> 影子/外发分流。"""
    settings = get_settings()
    if shadow is None:
        shadow = settings.agent_shadow_mode
    prev_hour = hour - 5 if hour in (15, 20) else None
    snapshot = load_slot_snapshot(config.timezone, day, hour)
    prev_snapshot = (
        load_slot_snapshot(config.timezone, day, prev_hour) if prev_hour else None
    )
    slot_text = f"{hour:02d}:00"
    run_config = GroupConfig(
        group_type=config.group_type,
        channel_id=config.channel_id,
        timezone=config.timezone,
        language=config.language,
        owners=config.owners,
        slot=slot_text,
        date=day,
        group_name=config.group_name,
    )
    graph = GroupGraph(run_config)
    state = graph.run(snapshot, prev_snapshot)
    state["draft_message"] = _draft_template(state, run_config)
    if settings.agent_llm_draft:
        state["draft_message"] = _polish_draft(state["draft_message"], run_config)
    graph.validate_message(state)
    output = state["output"]
    result = {
        "group_channel_id": config.channel_id,
        "group_name": config.group_name,
        "slot": slot_text,
        "shadow": shadow,
        "draft_message": output.draft_message,
        "approval_policy": output.approval_policy,
        "blocked_tasks": [item.model_dump() for item in output.blocked_tasks],
        "missing_evidence": [item.model_dump() for item in output.missing_evidence],
        "next_actions": output.next_actions,
        "has_snapshot": snapshot is not None,
    }
    try:
        result["draft_id"] = persist_draft(
            config=run_config,
            day=day,
            slot=slot_text,
            body=output.draft_message,
            approval_policy=output.approval_policy,
            shadow=shadow,
        )
    except Exception as exc:  # noqa: BLE001 — 草稿落库失败不阻断主流程
        logger.warning("草稿落库失败 {}: {}", run_config.channel_id, exc)
    write_event(
        "slot.draft_created",
        producer="group_agent",
        group_channel_id=config.channel_id,
        event_key=f"group_agent:draft:{config.channel_id}:{day}:{hour:02d}",
        payload={"shadow": shadow, "slot": slot_text},
    )
    if shadow:
        result["mode"] = "shadow_draft_only"
        return result
    # 非影子：草稿一律走 Outbox 审批（auto_template 只在开关允许时直接发）。
    from app.agents.outbox import create_outbox
    from app.duzhan import _idempotency_key

    outbox_row = create_outbox(
        # producer="agent"：与整点确定性三追推送的键区分开，避免服务端去重丢消息
        idempotency_key=_idempotency_key(
            config.timezone, day, hour, config.channel_id, producer="agent"
        ),
        channel_id=config.channel_id,
        body=output.draft_message,
        message_kind="group_followup",
        approval_policy=output.approval_policy,
    )
    result["outbox_created"] = bool(outbox_row)
    if settings.agent_task_write:
        updates = []
        for task in state.get("tasks") or []:
            computed = task.get("computed_verification")
            status = task.get("status")
            if computed == "verified" and status != "done":
                updates.append(
                    {
                        "task_id": task["id"],
                        "to_status": "done",
                        "verification_status": "verified",
                    }
                )
            elif computed == "partial" and status in ("in_progress", "claimed"):
                updates.append(
                    {
                        "task_id": task["id"],
                        "to_status": "evidence_submitted",
                        "verification_status": "partial",
                    }
                )
        if updates:
            result["task_updates"] = apply_task_updates(updates=updates)
        else:
            result["task_updates"] = {"updated": 0, "skipped": []}
    else:
        result["task_updates"] = {
            "updated": 0,
            "skipped": [],
            "reason": "PDCA_AGENT_TASK_WRITE=0",
        }
    result["mode"] = "live"
    return result


def run_group_slot(
    *,
    group_type: str = "performance",
    hour: int = 10,
    day: str = "",
) -> list[dict]:
    """跑指定群类型在某个档位的全部实例；单群异常不阻断其他群。"""
    settings = get_settings()
    if not settings.agent_enabled:
        return [{"skipped": "PDCA_AGENT_ENABLED=0"}]
    from app.agents.group_context import (
        ctob_group_configs,
        daily_report_group_config,
        performance_group_configs,
    )

    if not day:
        day = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    if group_type == "performance":
        configs = performance_group_configs(day)
    elif group_type == "ctob":
        configs = ctob_group_configs(day)
    elif group_type == "daily_report":
        item = daily_report_group_config(day)
        configs = [item] if item else []
    else:
        configs = []
    results: list[dict] = []
    for config in configs:
        try:
            results.append(run_group_instance(config, hour=hour, day=day))
        except Exception as exc:  # noqa: BLE001 — 单群故障不阻断其他群
            logger.exception("群 Agent 实例失败 {}: {}", config.channel_id, exc)
            results.append(
                {
                    "group_channel_id": config.channel_id,
                    "status": "failed",
                    "error": str(exc)[:300],
                }
            )
    return results



