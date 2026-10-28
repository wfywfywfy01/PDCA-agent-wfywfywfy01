"""Configurable VPS group tasks, using the existing evidence and delivery safeguards.

This mode never consumes sales/MTO data or the legacy 小黑屋 personnel policy.
The server's fixed supervisor bot is the only sender; previews never fetch or send.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app import heiwu_tasks
from app.duzhan_blocks import parse_blocks, time_slot_stage
from app.models.duzhan_agent import DuzhanAgent
from app.models.pdca_task import PdcaTask


def policy_of(agent: DuzhanAgent):
    return next((block for block in parse_blocks(agent.blocks_json) if block.type == "task_policy"), None)


def owner_policy(agent: DuzhanAgent) -> heiwu_tasks.TaskPolicy:
    policy = policy_of(agent)
    return heiwu_tasks.TaskPolicy(
        excluded_user_ids=tuple(policy.get("excluded_user_ids", [])) if policy else (),
        exclude_admins=False, exclude_support=False,
    )


def reserved_reason(channel_id: str) -> str:
    from app.duzhan_admin.service import supported_channel_ids
    from app.heiwu import channel_id as heiwu_channel_id

    if channel_id == heiwu_channel_id():
        return "该群已有小黑屋专用任务跟进，请在原配置维护，避免重复催办"
    if channel_id in supported_channel_ids():
        return "该群已有销售督战规则，请使用原业务模式"
    return ""


def validate_config(agent: DuzhanAgent) -> list[str]:
    from app.duzhan_admin.runtime import group_of

    group = group_of(agent)
    errors = []
    if group and (reason := reserved_reason(group.channel_id)):
        errors.append(reason)
    for block in parse_blocks(agent.blocks_json):
        if block.type not in {"group", "times", "task_policy", "style", "condition"}:
            errors.append(f"群任务模式不支持 {block.type} 配置；只核对指定发布人的任务与证据")
        if block.type == "condition" and block.get("key") not in {"workday", "holiday"}:
            errors.append("群任务模式仅支持工作日或长假提醒条件")
        if block.type == "style" and any(block.get(key) for key in ("title", "footer")):
            errors.append("群任务提醒使用统一标题，暂不支持自定义标题或页脚")
        if block.type == "style" and block.get("lang", "zh") != "zh":
            errors.append("群任务模式目前使用中文提醒")
    return errors


def _payload_rows(payload, key: str) -> list[dict]:
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise ValueError("source_unavailable")
    rows = payload.get(key, payload.get("items")) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("invalid_source_payload")
    return [row for row in rows if isinstance(row, dict)]


def group_options() -> dict:
    """Only expose groups joined by the fixed bot; unavailable rosters stay explicit."""
    import os
    from app.vertu.client import run_vertu_sync_json

    # Same source as push_duzhan_message; never verify one bot and send as another.
    bot_id = os.environ.get("PDCA_DUZHAN_BOT_APP_ID", "").strip()
    configured = bool(bot_id and os.environ.get("PDCA_DUZHAN_BOT_APP_SECRET", "").strip())
    result = {"items": [], "bot_app_id": bot_id, "configured": configured, "error": ""}
    if not configured:
        result["error"] = "督战机器人尚未配置，请联系系统管理员完成接入"
        return result
    try:
        bot_rows = _payload_rows(run_vertu_sync_json(["im", "+bot-channels"], timeout=45.0), "channels")
    except Exception:
        result["error"] = "暂时无法核实督战机器人所在群，请稍后重试"
        return result
    try:
        rows = _payload_rows(run_vertu_sync_json(["im", "+channels", "--limit", "200"], timeout=45.0), "channels")
        by_channel = {str(row.get("id") or ""): row for row in rows}
    except Exception:
        by_channel = {}
        result["error"] = "暂时无法读取群成员，相关群不能启用"
    seen: set[str] = set()
    for row in bot_rows:
        channel_id = str(row.get("channel_id") or "")
        if (row.get("app_id") or row.get("bot_app_id")) != bot_id or row.get("channel_type") != "group":
            continue
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        raw_members = by_channel.get(channel_id, {}).get("members")
        complete = isinstance(raw_members, list)
        members = heiwu_tasks.active_group_members(
            raw_members if complete else [], 0,
            policy=heiwu_tasks.TaskPolicy(exclude_admins=False, exclude_support=False),
        )
        reason = reserved_reason(channel_id) or ("暂时无法读取完整群成员，请刷新或核对群权限" if not complete else "")
        if not reason and not members:
            reason = "未读取到可选成员，暂时不能启用"
        result["items"].append({
            "channel_id": channel_id, "label": str(row.get("channel_name") or channel_id),
            "bot_joined": True, "available": not bool(reason), "reason": reason,
            "members": [{"user_id": int(member["user_id"]), "name": member["name"],
                         "role": str(member["raw"].get("role") or "member")}
                        for member in members if str(member["user_id"]).isdigit() and int(member["user_id"]) > 0],
        })
    return result


def connection_errors(agent: DuzhanAgent) -> list[str]:
    from app.duzhan_admin.runtime import group_of

    group = group_of(agent)
    policy = policy_of(agent)
    if group is None or policy is None:
        return ["目标群或任务发布人未配置"]
    directory = group_options()
    if not directory["configured"]:
        return [directory.get("error") or "督战机器人尚未配置"]
    item = next((row for row in directory["items"] if row["channel_id"] == group.channel_id), None)
    if item is None:
        return [directory.get("error") or "督战机器人尚未加入该群，或当前接入身份无权读取该群"]
    if not item["available"]:
        return [item["reason"]]
    member_ids = {row["user_id"] for row in item["members"]}
    if any(value not in member_ids for value in policy.get("publisher_user_ids", [])):
        return ["任务发布人已不在当前群成员名单，请重新选择"]
    if any(value not in member_ids for value in policy.get("excluded_user_ids", [])):
        return ["排除人员已不在当前群成员名单，请重新选择"]
    return []


def _round(slot: str) -> str:
    return "evening" if time_slot_stage(slot) == 20 else "morning"


def _load_card(agent_id: int) -> DuzhanAgent | None:
    from app.database import get_engine
    with Session(get_engine()) as session:
        return session.get(DuzhanAgent, agent_id)


def _active(agent: DuzhanAgent) -> bool:
    latest = _load_card(agent.id)
    return bool(latest and latest.enabled and latest.blocks_json == agent.blocks_json and latest.timezone == agent.timezone)


def _groups(agent, decisions, slot, current):
    return heiwu_tasks._round_groups(
        decisions, round_name=_round(slot), current=current, tz=ZoneInfo(agent.timezone),
        policy=owner_policy(agent), reminder_round=f"group-task:{slot}",
    )


def _body(group, slot, current, tz):
    body = heiwu_tasks._build_body(group["owner"], group["tasks"], current, tz, _round(slot))
    if time_slot_stage(slot) == 15:
        body = body.replace("早间任务提醒", "午间进度提醒")
    return body


def run_card(agent_id: int, slot: str, *, now: datetime | None = None) -> dict:
    """One persisted card/slot. Recheck identity and live state before real delivery."""
    from app.duzhan_admin import runtime, service
    from app.scheduler.run_ledger import claim_run, finish_run
    from app.vps_im_push import push_duzhan_message

    agent = _load_card(agent_id)
    if agent is None or not agent.enabled or policy_of(agent) is None:
        return {"skipped": "disabled"}
    errors = service.validate_agent(agent)
    if errors or slot not in runtime.slot_times_of(agent):
        return {"failed": "invalid_config", "reminded": 0}
    current = heiwu_tasks._aware_utc(now or datetime.now(timezone.utc))
    tz = ZoneInfo(agent.timezone)
    day = current.astimezone(tz).date().isoformat()
    group = runtime.group_of(agent)
    if not runtime.conditions_allow(agent, day, None):
        return {"skipped": "conditions"}
    job_name = f"group_tasks:{group.channel_id}:{slot}"
    if not claim_run(job_name, day):
        return {"skipped": "already_claimed"}
    try:
        errors = connection_errors(agent)
        if errors:
            finish_run(job_name, day, "failed", errors[0])
            return {"failed": errors[0], "reminded": 0}
        history = heiwu_tasks.fetch_group_history(group.channel_id, now=current, lookback_days=21)
        roster = heiwu_tasks.fetch_group_members(group.channel_id)
        policy = owner_policy(agent)
        if not history["complete"] or not roster["complete"]:
            heiwu_tasks.reconcile_task_evidence(
                history["messages"], channel_id=group.channel_id, history_complete=False,
                history_start=history.get("coverage_start"), now=current,
                timezone_name=agent.timezone, policy=policy,
            )
            error = history.get("error") or roster.get("error") or "source_incomplete"
            finish_run(job_name, day, "failed", error)
            return {"failed": error, "reminded": 0}
        if not _active(agent):
            finish_run(job_name, day, "failed", "configuration_changed")
            return {"skipped": "configuration_changed", "reminded": 0}
        publisher_ids = policy_of(agent).get("publisher_user_ids", [])
        members = [row for row in roster["members"] if str(row.get("user_id")) not in {str(value) for value in publisher_ids}]
        eligible = {row["user_id"] for row in heiwu_tasks.active_group_members(members, 0, policy=policy)}
        for publisher_id in publisher_ids:
            heiwu_tasks.sync_assignment_messages(
                history["messages"], members, channel_id=group.channel_id, publisher_user_id=publisher_id,
                timezone_name=agent.timezone, policy=policy,
            )
        decisions = heiwu_tasks.reconcile_task_evidence(
            history["messages"], channel_id=group.channel_id, history_complete=True,
            history_start=history.get("coverage_start"), now=current,
            timezone_name=agent.timezone, policy=policy,
        )
        # Changing designated publishers must not keep chasing old publishers' tasks.
        trusted_publishers = {str(value) for value in publisher_ids}
        decisions = {state: [task for task in tasks if task.get("publisher_user_id") in trusted_publishers]
                     for state, tasks in decisions.items()}
        reminded, failures = 0, []
        for owner in _groups(agent, decisions, slot, current):
            if owner["owner_user_id"] not in eligible:
                continue
            if not _active(agent):
                failures.append("configuration_changed")
                break
            body = _body(owner, slot, current, tz)
            if "?" in body or "\ufffd" in body or body.encode("utf-8").decode("utf-8") != body:
                failures.append("invalid_message_text")
                continue
            # Stable for the owner/slot even if a source edit changes the task set during a retry.
            key = f"group-task:{group.channel_id}:{day}:{slot}:{owner['owner_user_id']}"
            if push_duzhan_message(body, group.channel_id, idempotency_key=key):
                task_ids = [int(task["id"]) for task, _ in owner["tasks"]]
                heiwu_tasks._mark_reminded(task_ids, round_name=_round(slot), current=current, reminder_round=f"group-task:{slot}")
                reminded += len(task_ids)
            else:
                failures.append("send_failed")
        finish_run(job_name, day, "failed" if failures else "sent", ";".join(failures) if failures else f"reminded={reminded}")
        return {"reminded": reminded, "submitted": len(decisions["submitted"]), "pending": len(decisions["pending"]), "failed": failures}
    except Exception as exc:
        finish_run(job_name, day, "failed", type(exc).__name__)
        return {"failed": type(exc).__name__, "reminded": 0}


def poll_due(*, now: datetime | None = None) -> list[dict]:
    """Minute polling makes new times and pauses effective without scheduler restart."""
    from app.config import get_settings
    from app.duzhan_admin.runtime import load_enabled_agents, slot_times_of

    if not getattr(get_settings(), "scheduler_enabled", False):
        return []
    current = heiwu_tasks._aware_utc(now or datetime.now(timezone.utc))
    results = []
    for agent in load_enabled_agents():
        if policy_of(agent) is None:
            continue
        local = current.astimezone(ZoneInfo(agent.timezone))
        minute = local.hour * 60 + local.minute
        for slot in slot_times_of(agent):
            hour, minutes = map(int, slot.split(":"))
            if 0 <= minute - (hour * 60 + minutes) < 5:
                results.append(run_card(agent.id, slot, now=current))
    return results


def render_preview(agent: DuzhanAgent, *, day: str | None = None, hour: int | None = None, slot: str | None = None) -> dict:
    """Read stored tasks only. No collection claim, mutation, model call, or message."""
    from app.database import get_engine
    from app.duzhan_admin import runtime, service

    errors = service.validate_agent(agent)
    if errors:
        return {"mode": "render", "ok": False, "error": "；".join(errors)}
    tz = ZoneInfo(agent.timezone)
    current = datetime.now(tz)
    day = day or current.date().isoformat()
    slot, hour, minute = service._pick_slot(agent, slot, hour, current)
    current = datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=tz)
    group = runtime.group_of(agent)
    with Session(get_engine()) as session:
        rows = list(session.exec(select(PdcaTask).where(
            PdcaTask.source == heiwu_tasks.SOURCE, PdcaTask.group_channel_id == group.channel_id,
            ~PdcaTask.status.in_(["done", "complete", "completed"]),
        )).all())
    policy = owner_policy(agent)
    publishers = {str(value) for value in policy_of(agent).get("publisher_user_ids", [])}
    lines = []
    for row in rows:
        task = heiwu_tasks._task_from_row(row)
        if str(heiwu_tasks._assignment_record(row.evidence_json).get("publisher_user_id") or "") not in publishers:
            continue
        if task["owner_user_id"] in publishers or heiwu_tasks._owner_excluded(task["owner_user_id"], row.owner, policy=policy):
            continue
        if not heiwu_tasks._started(task, current, tz):
            continue
        state = "已找到提交证据，待验收" if row.status == "evidence_submitted" else "待确认"
        lines.append(f"- {row.owner}｜{row.title}｜{state}")
    body = "\n".join(lines) if lines else "暂无已采集任务。启用后将按设定时间读取指定发布人的群任务，并核对实际交付证据。"
    return {"mode": "render", "ok": True, "agent": {"id": agent.id, "name": agent.name, "enabled": agent.enabled},
            "day": day, "hour": hour, "slot": slot, "timezone": agent.timezone,
            "channel_id": group.channel_id, "group": group.name, "renderer": "group_tasks",
            "source": "task_ledger", "body": body, "chars": len(body), "message_count": 0,
            "send_allowed": False, "send_reason": "预览不发送消息", "task_count": len(lines),
            "note": "只读现有任务台账，未重新采集群消息。没有提交证据的事项标待确认；真实检查只在消息采集完整后判定未交。"}
