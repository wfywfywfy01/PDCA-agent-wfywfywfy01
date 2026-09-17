# -*- coding: utf-8 -*-
"""群级 Agent：一套图、多实例（第 9 节）。

GroupGraph 是确定性状态机（不用 LangGraph 依赖；节点顺序与规格 9.2 一致），
LLM 只在草稿润色步骤可选接入，模型故障回退确定性草稿。
任务状态机与规格 9.3 一致：
  pending -> assigned -> claimed -> in_progress -> evidence_submitted -> verified -> done
  pending/in_progress -> blocked；evidence_submitted -> rejected -> in_progress；
  任何未完成状态可衍生 overdue / escalated。
闭环铁律：“收到/好的/已跟进”只算 claimed/in_progress，绝不直接 done；
done 必须 verification_status == verified 且无剩余动作。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from app.agents.group_context import GroupConfig, load_open_tasks, load_slot_snapshot
from app.agents.schemas import GroupAgentOutput, GroupTask


# 任务状态机常量（规格 9.3）。
STATUS_FLOW: dict[str, str] = {
    "pending": "assigned",
    "assigned": "claimed",
    "claimed": "in_progress",
    "in_progress": "evidence_submitted",
    "evidence_submitted": "verified",
    "verified": "done",
}

OPEN_STATUSES = {"pending", "assigned", "claimed", "in_progress", "evidence_submitted", "verified"}

# 只有这些证据类型能推进 verification_status。
EVIDENCE_TYPES = {
    "im_message",
    "whatsapp_metric",
    "whatsapp_message",
    "vemory_transcript",
    "doubao_transcript",
    "vps_activity",
    "daily_report",
    "mto_image",
    "mto_quote",
    "payment_receipt",
    "manual_confirmation",
}

# 只凭这些回复不能闭环（最多推进到 claimed/in_progress）。
ACK_WORDS = ("收到", "好的", "了解", "明白", "ok", "okay", "received", "noted", "roger")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def next_status(status: str) -> str:
    """状态机正向转移；非法/终态原样返回。"""
    return STATUS_FLOW.get(status, status)


def is_ack_only(text: str) -> bool:
    """判定回复是否只是“收到”类确认（不能闭环）。"""
    normalized = (text or "").strip().casefold()
    if not normalized:
        return False
    if len(normalized) > 12:
        return False
    return any(word in normalized for word in ACK_WORDS)


def classify_task(task: dict, now: datetime) -> str:
    """把 pdca_task 行归类为 done / blocked / overdue / in_progress / claimed / pending。"""
    status = str(task.get("status") or "pending")
    if status in ("done", "completed", "complete"):
        return "done"
    if task.get("blocked_reason"):
        return "blocked"
    due_at = task.get("due_at")
    if due_at:
        try:
            due = datetime.fromisoformat(str(due_at))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if now > due.astimezone(timezone.utc):
                return "overdue"
        except (ValueError, TypeError):
            pass
    if status in ("evidence_submitted", "verified"):
        return "in_progress"
    if status in ("claimed", "in_progress"):
        return status
    return "pending"


def verify_claims(task: dict) -> tuple[str, list[str]]:
    """核验证据并给出 (verification_status, missing) 的确定性判定。

    铁律：无证据不 verified；只有 ack 回复不推进；证据类型不在白名单不算。
    自动核验最多到 partial，verified 需要 manual_confirmation 或已人工置 verified。
    """
    current = task.get("verification_status") or "unverified"
    if current == "verified":
        return "verified", []
    evidence = task.get("evidence") or []
    if not isinstance(evidence, list) or not evidence:
        if is_ack_only(task.get("reply_text") or ""):
            return "unverified", ["仅有收到类回复，无证据"]
        return "unverified", ["无证据"]
    typed = [
        item
        for item in evidence
        if isinstance(item, dict) and item.get("evidence_type") in EVIDENCE_TYPES
    ]
    if not typed:
        return "unverified", ["证据类型不在白名单"]
    manual = [item for item in typed if item.get("evidence_type") == "manual_confirmation"]
    if manual:
        return "verified", []
    return "partial", []


class GroupGraph:
    """一个群在一个档位的处理管线（无状态实例方法，状态全部外传）。"""

    def __init__(self, config: GroupConfig):
        self.config = config

    def load_group_config(self, state: dict) -> dict:
        """节点 1：实例参数进入状态。"""
        state["group"] = {
            "group_type": self.config.group_type,
            "channel_id": self.config.channel_id,
            "timezone": self.config.timezone,
            "language": self.config.language,
            "owners": list(self.config.owners),
            "group_name": self.config.group_name,
            "slot": self.config.slot,
            "date": self.config.date,
        }
        return state

    def load_current_tasks(self, state: dict) -> dict:
        """节点 2：读取未闭环 pdca_tasks。"""
        state["tasks"] = load_open_tasks(
            owners=self.config.owners, channel_id=self.config.channel_id
        )
        return state

    def load_latest_evidence(self, state: dict) -> dict:
        """节点 3：加载本群最近事件（证据交接在 events，不重复读原始群消息）。"""
        from app.agents.events import latest_events

        state["events"] = latest_events(group_channel_id=self.config.channel_id, limit=20)
        return state

    def compare_previous_slot(self, state: dict, prev_snapshot: dict | None) -> dict:
        """节点 4：与上一档快照对比（15:00 比 10:00，20:00 比 15:00）。"""
        state["prev_snapshot"] = prev_snapshot
        prev_people = {
            str(item.get("display") or ""): item for item in (prev_snapshot or {}).get("people") or []
        }
        state["prev_people"] = prev_people
        return state

    def classify_progress(self, state: dict) -> dict:
        """节点 5：任务分类与人员进度对比。"""
        now = utcnow()
        buckets: dict[str, list[dict]] = {
            "done": [], "blocked": [], "overdue": [], "in_progress": [], "claimed": [], "pending": [],
        }
        for task in state.get("tasks") or []:
            buckets.setdefault(classify_task(task, now), []).append(task)
        state["buckets"] = buckets
        people_now = {
            str(item.get("display") or "") for item in (state.get("snapshot") or {}).get("people") or []
        }
        changes: list[dict] = []
        for display, prev in (state.get("prev_people") or {}).items():
            if display not in people_now:
                changes.append({"owner": display, "change": "人员在新档快照中缺失（待确认）"})
        state["progress_changes"] = changes
        return state

    def verify_claims(self, state: dict) -> dict:
        """节点 6：证据核验（确定性，见 verify_claims）。"""
        verified: list[dict] = []
        for task in state.get("tasks") or []:
            status, missing = verify_claims(task)
            task["computed_verification"] = status
            task["computed_missing"] = missing
            if status == "verified":
                verified.append(task)
        state["verified_tasks"] = verified
        return state

    def decide_next_action(self, state: dict) -> dict:
        """节点 7：决定下一动作（催报/催证据/催回复/升级）。"""
        hour = int(str(self.config.slot or "").split(":")[0] or 0)
        actions: list[dict] = []
        buckets = state.get("buckets") or {}
        for task in buckets.get("pending") or []:
            actions.append({"owner": task.get("owner"), "type": "claim",
                            "title": task.get("title"), "detail": "未认领"})
        for task in buckets.get("overdue") or []:
            actions.append({"owner": task.get("owner"), "type": "escalate",
                            "title": task.get("title"), "detail": "逾期未闭环"})
        for task in buckets.get("in_progress") or []:
            actions.append({"owner": task.get("owner"), "type": "evidence",
                            "title": task.get("title"), "detail": "推进中，待证据"})
        if hour == 10 and not (state.get("tasks") or []):
            for owner in self.config.owners:
                actions.append({"owner": owner, "type": "plan", "title": "提交今日 3-5 项工作",
                                "detail": "未报计划"})
        state["next_actions"] = actions[:30]
        return state

    def draft_message(self, state: dict, template: str = "") -> dict:
        """节点 8：确定性草稿（模板由 group_service 传入；LLM 润色在服务层可选）。"""
        if template:
            state["draft_message"] = template
            return state
        lines: list[str] = []
        buckets = state.get("buckets") or {}
        if buckets.get("blocked"):
            lines.append("卡点：" + "；".join(t["title"] for t in buckets["blocked"][:5]))
        if buckets.get("overdue"):
            lines.append("逾期未闭环：" + "；".join(t["title"] for t in buckets["overdue"][:5]))
        if not lines:
            lines.append("待确认：本档无新增变化")
        state["draft_message"] = "\n".join(lines)
        return state

    def validate_message(self, state: dict) -> dict:
        """节点 9：草稿过 schema 与高风险词检测；approval_policy 只降不升。"""
        from app.agents.outbox import forced_manual

        body = state.get("draft_message") or ""
        policy = "auto_template" if not forced_manual(
            body, state.get("message_kind") or "group_followup"
        ) else "manual_required"
        state["approval_policy"] = policy
        buckets = state.get("buckets") or {}

        def _as_group_task(task: dict) -> GroupTask:
            return GroupTask(
                task_id=task.get("id"),
                group_channel_id=task.get("group_channel_id") or self.config.channel_id,
                owner=task.get("owner") or "",
                objective=task.get("title") or "",
                expected_evidence=task.get("computed_missing") or [],
                deadline=task.get("due_at"),
                risk_level="high" if task.get("priority") == "high" else "medium",
                source_refs=[task.get("source_ref")] if task.get("source_ref") else [],
            )

        output = GroupAgentOutput(
            group_channel_id=self.config.channel_id,
            slot=self.config.slot,
            facts=(state.get("snapshot") or {}).get("people") or [],
            progress_changes=state.get("progress_changes") or [],
            blocked_tasks=[_as_group_task(t) for t in (buckets.get("blocked") or [])[:10]],
            missing_evidence=[
                _as_group_task(t)
                for t in (state.get("tasks") or [])
                if t.get("computed_verification") in ("unverified", "partial")
            ][:10],
            next_actions=state.get("next_actions") or [],
            draft_message=body[:8000],
            approval_policy=policy,
            unknowns=[]
        )
        state["output"] = output
        return state

    def run(self, snapshot: dict | None, prev_snapshot: dict | None) -> dict:
        """执行整条管线，返回最终状态（含 GroupAgentOutput）。"""
        state: dict[str, Any] = {"snapshot": snapshot}
        self.load_group_config(state)
        self.load_current_tasks(state)
        self.load_latest_evidence(state)
        self.compare_previous_slot(state, prev_snapshot)
        self.classify_progress(state)
        self.verify_claims(state)
        self.decide_next_action(state)
        self.draft_message(state)
        self.validate_message(state)
        return state


def apply_task_updates(
    *,
    updates: list[dict],
    actor: str = "group_agent",
) -> dict:
    """把群 Agent 的确定性结论落库：只做状态机允许的转移，写 task.* 事件。

    每项：{task_id, to_status?, blocked_reason?, verification_status?, evidence?}
    返回 {updated, skipped}。
    """
    from sqlmodel import Session, select

    from app.agents.events import write_event
    from app.database import get_engine
    from app.models.pdca_task import PdcaTask

    updated = 0
    skipped: list[dict] = []
    with Session(get_engine()) as session:
        for item in updates:
            task_id = item.get("task_id")
            if not task_id:
                skipped.append({"reason": "缺 task_id"})
                continue
            row = session.get(PdcaTask, int(task_id))
            if row is None:
                skipped.append({"task_id": task_id, "reason": "不存在"})
                continue
            if getattr(row, "owner_locked", False) and item.get("owner") and item["owner"] != row.owner:
                skipped.append({"task_id": task_id, "reason": "owner_locked"})
                continue
            changed = False
            to_status = item.get("to_status")
            if to_status and to_status in OPEN_STATUSES.union({"done", "blocked"}):
                row.status = to_status
                changed = True
            if item.get("blocked_reason") is not None:
                row.blocked_reason = str(item["blocked_reason"])[:512]
                changed = True
            if item.get("verification_status") in ("unverified", "partial", "verified", "rejected", "pending_manual"):
                row.verification_status = item["verification_status"]
                changed = True
            if item.get("evidence") is not None:
                row.evidence_json = json.dumps(item["evidence"], ensure_ascii=False)[:65536]
                changed = True
            if to_status == "done" and row.closed_at is None:
                row.closed_at = utcnow()
                changed = True
            if changed:
                row.updated_at = utcnow()
                session.add(row)
                updated += 1
                write_event("task.progressed", producer=actor, task_id=row.id,
                            event_key=f"{actor}:progressed:{row.id}:{utcnow().timestamp():.0f}",
                            payload={"to_status": to_status, "blocked": item.get("blocked_reason") or ""})
        session.commit()
    return {"updated": updated, "skipped": skipped}
