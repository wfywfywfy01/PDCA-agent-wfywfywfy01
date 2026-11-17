"""Daily real-GTM overdue summaries using the existing supervisor bot and ledger."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.config import get_settings
from app.duzhan_admin.acquisition_models import AcquisitionQueueEnvelope, supervision_connection
from app.scheduler.run_ledger import claim_run, finish_run
from app.vps_im_push import push_duzhan_message

TZ = ZoneInfo("Asia/Shanghai")


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_user_id: int = Field(gt=0, strict=True)
    vps_user_id: int = Field(gt=0, strict=True)
    channel_id: UUID
    dispatch_message_id: UUID


def verified_recipients(targets: list[Target]) -> set[int]:
    """Verify the exact sender and current recipient membership; no fallback bot."""
    import os
    from app import heiwu_tasks
    from app.duzhan_admin.group_tasks import _payload_rows
    from app.vertu.client import run_vertu_sync_json

    app_id = os.environ.get("PDCA_DUZHAN_BOT_APP_ID", "").strip()
    if not app_id or not os.environ.get("PDCA_DUZHAN_BOT_APP_SECRET", "").strip():
        return set()
    bots = _payload_rows(run_vertu_sync_json(["im", "+bot-channels"], timeout=30), "channels")
    groups = _payload_rows(run_vertu_sync_json(["im", "+channels", "--limit", "200"], timeout=30), "channels")
    joined = {str(row.get("channel_id")) for row in bots
              if (row.get("app_id") or row.get("bot_app_id")) == app_id and row.get("channel_type") == "group"}
    groups = {str(row.get("id")): row for row in groups}
    result = set()
    for target in targets:
        channel = str(target.channel_id)
        members = groups.get(channel, {}).get("members")
        if channel not in joined or not isinstance(members, list):
            continue
        active = heiwu_tasks.active_group_members(members, 0,
            policy=heiwu_tasks.TaskPolicy(exclude_admins=False, exclude_support=False))
        if str(target.vps_user_id) in {str(row["user_id"]) for row in active}:
            result.add(target.owner_user_id)
    return result


def read_tasks(settings, current: datetime):
    url, token = supervision_connection(settings)
    rows, seen, blocked = [], set(), set()
    total = None
    with httpx.Client(timeout=10, follow_redirects=False, trust_env=False) as client:
        for offset in range(0, 5000, 100):
            response = client.get(url, headers={"Authorization": f"Bearer {token}"}, params={
                "source_limit": 100, "source_offset": offset, "reply_limit": 1, "reply_offset": 0})
            response.raise_for_status()
            queue = AcquisitionQueueEnvelope.model_validate_json(response.content).data
            page, replies = queue.source_tasks, queue.owner_pending_replies
            if queue.environment != "real" or page is None or replies is None:
                raise ValueError("real_complete_queue_required")
            for stamp in (queue.as_of, page.as_of, replies.as_of):
                if stamp is None or not -timedelta(seconds=60) <= current-stamp <= timedelta(minutes=5):
                    raise ValueError("stale_or_future_queue")
            if page.offset != offset or page.limit != 100 or (total is not None and total != page.total):
                raise ValueError("inconsistent_pagination")
            if sum(owner.pending + owner.received for owner in replies.by_owner) != replies.total:
                raise ValueError("incomplete_pending_owners")
            total = page.total
            # Owner-level unresolved replies must not be treated as silence.
            blocked.update(owner.owner_user_id for owner in replies.by_owner if owner.pending or owner.received)
            for row in page.items:
                if row.task_id in seen:
                    raise ValueError("duplicate_pagination")
                seen.add(row.task_id)
                rows.append(row)
            if not page.has_more:
                if len(rows) != total:
                    raise ValueError("incomplete_queue")
                return rows, blocked
            if len(page.items) != 100:
                raise ValueError("incomplete_page")
    raise ValueError("queue_limit_exceeded")


def eligible(row, current: datetime) -> bool:
    return bool(row.status == "pending" and row.overdue is True
                and row.next_due_at is not None and row.next_due_at <= current
                and not row.stored_outreach_hold and row.outreach_hold_status != "held"
                and not row.pending_reply and not row.reply_processing
                and not row.pending_reply_count and not row.processing_reply_count
                and not row.pending_replies and not row.pending_replies_truncated)


def body_for(rows, settings, current: datetime) -> str:
    # ponytail: eight task references per owner; the workbench retains the full list.
    lines = [f"【线索逾期跟进提醒】{current.astimezone(TZ):%m月%d日}",
             f"{rows[0].owner_name or '负责人'}，系统记录 {len(rows)} 条线索任务超过截止时间。"]
    for row in rows[:8]:
        action = " ".join((row.next_action or "待补充下一步").split())[:80]
        lines.append(f"线索 #{row.task_id}｜截止 {row.next_due_at.astimezone(TZ):%m-%d %H:%M}｜下一步：{action}")
    if len(rows) > 8:
        lines.append(f"其余 {len(rows)-8} 条请在工作台查看。")
    lines.extend(["请引用线索分发机器人的原派单回复，每条注明线索编号、实际进度、下一步和截止时间。",
                  "如已处理，请回写事实；需暂停或调整期限，请注明原因。本提醒不代表客户已通过触达核验。",
                  settings.acquisition_supervision_url + "/#followup"])
    body = "\n".join(lines)
    if "?" in body or "\ufffd" in body or body.encode("utf-8").decode("utf-8") != body:
        raise ValueError("invalid_message_text")
    return body


def poll_due(*, now: datetime | None = None) -> dict:
    settings = get_settings()
    result = {"sent": 0, "failed": 0, "eligible_tasks": 0}
    if (not getattr(settings, "acquisition_chase_enabled", False)
            or not settings.scheduler_enabled or settings.environment != "production"
            or getattr(settings, "remote_db_from_host", False)):
        return dict(result, skipped="disabled")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return dict(result, skipped="timezone_required")
    if not 9 <= current.astimezone(TZ).hour < 19:
        return dict(result, skipped="outside_work_hours")
    try:
        targets = TypeAdapter(list[Target]).validate_json(settings.acquisition_chase_targets)
        if not 1 <= len(targets) <= 30 or len({t.owner_user_id for t in targets}) != len(targets):
            raise ValueError("invalid_targets")
        rows, blocked = read_tasks(settings, current)
        owners = {target.owner_user_id for target in targets}
        candidates = [row for row in rows if row.owner_user_id in owners-blocked and eligible(row, current)]
        result["eligible_tasks"] = len(candidates)
        if not candidates:
            return result
        verified = verified_recipients(targets)
        day = current.astimezone(TZ).date().isoformat()
        for target in targets:
            selected = [row for row in candidates if row.owner_user_id == target.owner_user_id]
            if not selected:
                continue
            if target.owner_user_id not in verified:
                result["failed"] += 1
                continue
            body = body_for(selected, settings, current)
            job = f"gtm_chase:{target.owner_user_id}"
            if not claim_run(job, day):
                continue
            key = f"{job}:{day}"  # Stable even if task text or group mapping changes during retry.
            ok = push_duzhan_message(body, str(target.channel_id),
                                    parent_message_id=str(target.dispatch_message_id), idempotency_key=key)
            # An uncertain HTTP result must not repeatedly chase the same person today.
            finish_run(job, day, "sent" if ok else "uncertain",
                       f"group={target.channel_id};tasks={len(selected)};key={key};utf8=ok")
            result["sent" if ok else "failed"] += 1
        return result
    except Exception as exc:
        return dict(result, failed=result["failed"]+1, error=type(exc).__name__)
