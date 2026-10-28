# -*- coding: utf-8 -*-
"""小黑屋群任务采集、持久化、证据核对与定时提醒编排。

真实消息统一委托 ``app.heiwu`` 的专用机器人发送入口。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_DUE_TIME = time(23, 59, 59)

_COLLECTIVE_RE = re.compile(r"(?:@\s*所有人|全员|所有人|每个人|请大家|大家请|各位销售小伙伴)")
_ASSIGNMENT_RE = re.compile(r"(?:作业|任务|提交|完成|制作|录制|复盘|打卡)")
_REMINDER_RE = re.compile(r"(?:催(?:一下)?|还没交|尚未交|未提交|没提交|抓紧提交)")
_ANNOUNCEMENT_RE = re.compile(r"(?:奖励规则|红包|奖金|罚款|处罚|财务奖励)")
_NAMED_ASSIGNMENT_RE = re.compile(
    r"(?:跟进|回访|整理|发送|联系|确认|交付|提交|完成|制作|录制|复盘|打卡|处理|核对|准备)"
)
_DATE_RANGE_RE = re.compile(
    r"(?P<m1>\d{1,2})\s*(?:月|[./-])\s*(?P<d1>\d{1,2})\s*日?\s*"
    r"(?:-|—|–|~|～|至|到)\s*"
    r"(?:(?P<m2>\d{1,2})\s*(?:月|[./-])\s*)?(?P<d2>\d{1,2})\s*日?"
)
_SINGLE_DATE_RE = re.compile(r"(?P<m>\d{1,2})\s*(?:月|[./])\s*(?P<d>\d{1,2})\s*日?")
_CLOCK_RE = re.compile(r"(?P<h>\d{1,2})\s*[:：]\s*(?P<m>\d{2})")
_DAILY_RE = re.compile(r"(?:每日|每天)")
_SUPPORT_JOB_RE = re.compile(r"数据分析")


def _message_time(message: dict, tz: ZoneInfo) -> datetime | None:
    raw = str(message.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(tz)


def _date_window(text: str, created: datetime, tz: ZoneInfo) -> tuple[date, datetime | None]:
    """返回任务开始日和 UTC 截止时间；长期任务没有截止时间。"""
    if re.search(r"(?:长期|持续)", text) and not _DAILY_RE.search(text):
        return created.date(), None
    matched = _DATE_RANGE_RE.search(text)
    if matched:
        start_month = int(matched.group("m1"))
        end_month = int(matched.group("m2") or start_month)
        start = date(created.year, start_month, int(matched.group("d1")))
        end_year = created.year + int(end_month < start_month)
        end = date(end_year, end_month, int(matched.group("d2")))
    else:
        single = _SINGLE_DATE_RE.search(text)
        if single:
            start = end = date(created.year, int(single.group("m")), int(single.group("d")))
        elif "明天" in text:
            start = end = created.date() + timedelta(days=1)
        else:
            start = end = created.date()
    clock = next(
        (
            matched
            for matched in _CLOCK_RE.finditer(text)
            if re.search(r"(?:截止|截至|最晚|不晚于)\s*$", text[:matched.start()])
            or re.match(r"\s*(?:前|之前|截止)", text[matched.end():])
        ),
        None,
    )
    due_time = DEFAULT_DUE_TIME
    if clock:
        hour, minute = int(clock.group("h")), int(clock.group("m"))
        if hour > 23 or minute > 59:
            raise ValueError("invalid explicit task deadline")
        due_time = time(hour, minute)
    due_local = datetime.combine(end, due_time, tzinfo=tz)
    return start, due_local.astimezone(timezone.utc)


@dataclass(frozen=True)
class TaskPolicy:
    """Explicit scope for generic groups; None retains legacy 小黑屋 policy."""
    excluded_user_ids: tuple[int, ...] = ()
    excluded_names: tuple[str, ...] = ()
    exclude_admins: bool = True
    exclude_support: bool = True


def _owner_excluded(user_id: int | str | None, *names: str, policy: TaskPolicy | None = None) -> bool:
    if policy is None:
        from app.config import get_settings
        settings = get_settings()
        policy = TaskPolicy(
            excluded_user_ids=tuple(getattr(settings, "heiwu_task_excluded_user_ids", ())),
            excluded_names=tuple(getattr(settings, "heiwu_task_excluded_names", ())),
        )
    excluded_ids = {str(value) for value in policy.excluded_user_ids}
    excluded_names = {str(value).strip().lstrip("@").strip().casefold()
                      for value in policy.excluded_names if str(value).strip()}
    return bool(str(user_id or "").strip() in excluded_ids or any(
        str(name or "").strip().lstrip("@").strip().casefold() in excluded_names for name in names))


def active_group_members(members: list[dict], publisher_user_id: int | str, *, policy: TaskPolicy | None = None) -> list[dict]:
    """把群成员规范成真实用户；排除机器人、退群用户、发布管理员和无名用户。"""
    publisher = str(publisher_user_id)
    result: list[dict] = []
    seen_ids: set[str] = set()
    for raw in members or []:
        if not isinstance(raw, dict) or str(raw.get("member_type") or "") != "user":
            continue
        if (policy is None or policy.exclude_admins) and str(raw.get("role") or "").strip().casefold() in {"owner", "admin"}:
            continue
        if (policy is None or policy.exclude_support) and _SUPPORT_JOB_RE.search(str(raw.get("job_title") or "")):
            continue
        user_id = str(raw.get("user_id") or "").strip()
        if not user_id or user_id == publisher or raw.get("removed_at") or user_id in seen_ids:
            continue
        name = str(
            raw.get("employee_name")
            or raw.get("nickname")
            or raw.get("remark")
            or raw.get("login")
            or ""
        ).strip()
        if not name:
            continue
        if _owner_excluded(user_id, name, policy=policy):
            continue
        seen_ids.add(user_id)
        result.append({"user_id": user_id, "name": name, "raw": raw})
    return result


def _member_aliases(member: dict) -> set[str]:
    raw = member.get("raw") or {}
    values = {
        member.get("name"),
        raw.get("employee_name"),
        raw.get("nickname"),
        raw.get("remark"),
        raw.get("login"),
    }
    return {str(value).strip().lstrip("@").strip() for value in values if str(value or "").strip()}


def _resolve_member(label: str, members: list[dict]) -> dict | None:
    wanted = str(label or "").strip().lstrip("@").strip()
    matched = [member for member in members if wanted in _member_aliases(member)]
    return matched[0] if len(matched) == 1 else None


def _collective_title(body: str) -> str:
    """Keep the business task while dropping roster/date/submission boilerplate."""
    text = re.split(
        r"[，,；;。]\s*(?=(?:请大家|大家请|各位销售小伙伴|每人|每个|要求|完成并|完成后|并提交))",
        body,
        maxsplit=1,
    )[0]
    text = re.sub(r"@\s*所有人", " ", text)
    text = _DATE_RANGE_RE.sub(" ", text)
    text = _SINGLE_DATE_RE.sub(" ", text)
    text = _COLLECTIVE_RE.sub(" ", text)
    text = re.sub(
        r"^\s*(?:从|在|于)?\s*(?:本次|今日|今天)?\s*(?:的)?"
        r"(?:作业|任务)(?:内容|主题)?\s*(?:是|为|[:：])?\s*",
        "",
        text,
    )
    text = re.sub(r"^\s*(?:在|于)?\s*(?:完成|制作|录制|进行|做)\s*", "", text)
    text = re.sub(r"\s*(?:完成后|并)?提交(?:到|至)?群内.*$", "", text)
    concise = text.strip(" \t\r\n，,。；;：:-")
    return (concise or re.sub(r"\s+", " ", body).strip())[:120]


def _task_dict(
    *,
    member: dict,
    title: str,
    message: dict,
    created: datetime,
    tz: ZoneInfo,
    slot: int,
    schedule_text: str | None = None,
) -> dict:
    schedule = schedule_text or title
    start_date, due_at = _date_window(schedule, created, tz)
    return {
        "owner": member["name"],
        "owner_user_id": member["user_id"],
        "title": title[:512],
        "start_date": start_date.isoformat(),
        "due_at": due_at,
        "source_message_id": str(message.get("id") or ""),
        "source_updated_at": str(message.get("updated_at") or message.get("created_at") or ""),
        "source_slot": slot,
        "recurring_daily": bool(_DAILY_RE.search(schedule)),
    }


def parse_assignment_message(
    message: dict,
    members: list[dict],
    *,
    publisher_user_id: int | str,
    timezone_name: str = "Asia/Shanghai",
    policy: TaskPolicy | None = None,
) -> list[dict]:
    """把管理员一条任务通知解析为逐人任务；不是可信派单则返回空列表。"""
    if not isinstance(message, dict):
        return []
    if str(message.get("sender_user_id") or "") != str(publisher_user_id):
        return []
    if message.get("revoked_at") or str(message.get("message_type") or "") == "recall":
        return []
    message_id = str(message.get("id") or "").strip()
    raw_body = str(message.get("body") or "")
    body = re.sub(r"\s+", " ", raw_body).strip()
    if not message_id or not body:
        return []
    if _REMINDER_RE.search(body) or _ANNOUNCEMENT_RE.search(body):
        return []
    tz = ZoneInfo(timezone_name)
    created = _message_time(message, tz)
    if created is None:
        return []
    roster = active_group_members(members, publisher_user_id, policy=policy)
    if _COLLECTIVE_RE.search(body):
        if not _ASSIGNMENT_RE.search(body):
            return []
        title = _collective_title(body)
        try:
            return [
                _task_dict(
                    member=member, title=title, schedule_text=body,
                    message=message, created=created, tz=tz, slot=0,
                )
                for member in roster
            ]
        except ValueError:
            return []

    from app.meeting_todos_fetch import parse_items

    parsed = parse_items(raw_body)
    result: list[dict] = []
    owner_slots: dict[str, int] = {}
    for item in parsed:
        title = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        member = _resolve_member(str(item.get("who") or ""), roster)
        if member is None or not title or not _NAMED_ASSIGNMENT_RE.search(title):
            continue
        slot = owner_slots.get(member["user_id"], 0)
        owner_slots[member["user_id"]] = slot + 1
        try:
            result.append(
                _task_dict(member=member, title=title, message=message, created=created, tz=tz, slot=slot)
            )
        except ValueError:
            continue
    return result


SOURCE = "heiwu_group_task"


def _source_ref(channel_id: str, task: dict) -> str:
    message_key = hashlib.sha256(
        (channel_id + "\0" + task["source_message_id"]).encode("utf-8")
    ).hexdigest()[:32]
    return f"heiwu-task:{message_key}:{task['owner_user_id']}:{task.get('source_slot', 0)}"


def _assignment_evidence(task: dict) -> list[dict]:
    return [
        {
            "evidence_type": "assignment_notice",
            **({"publisher_user_id": str(task["publisher_user_id"])} if task.get("publisher_user_id") else {}),
            "message_id": task["source_message_id"],
            "owner_user_id": task["owner_user_id"],
            "source_updated_at": task["source_updated_at"],
            "start_date": task["start_date"],
            "due_at": task["due_at"].isoformat() if task["due_at"] else None,
            "recurring_daily": bool(task.get("recurring_daily")),
        }
    ]


def _assignment_record(evidence_json: str) -> dict:
    try:
        evidence = json.loads(evidence_json or "[]")
    except (TypeError, ValueError):
        return {}
    return next(
        (
            item for item in evidence
            if isinstance(item, dict) and item.get("evidence_type") == "assignment_notice"
        ),
        {},
    ) if isinstance(evidence, list) else {}


def _source_message_id(row) -> str:
    try:
        evidence = json.loads(row.evidence_json or "[]")
    except (TypeError, ValueError):
        return ""
    for item in evidence if isinstance(evidence, list) else []:
        if isinstance(item, dict) and item.get("evidence_type") == "assignment_notice":
            return str(item.get("message_id") or "")
    return ""


def _same_instant(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left.astimezone(timezone.utc) == right.astimezone(timezone.utc)


def _title_key(value: str) -> str:
    return re.sub(r"[\s，。,:：；;@]+", "", str(value or "")).casefold()


def _cancel_row(row, *, reason: str, evidence_type: str, now: datetime) -> bool:
    if row.status in {"done", "complete", "completed"} and row.verification_status == "rejected":
        return False
    try:
        evidence = json.loads(row.evidence_json or "[]")
    except (TypeError, ValueError):
        evidence = []
    if not isinstance(evidence, list):
        evidence = []
    evidence.append({"evidence_type": evidence_type, "recorded_at": now.isoformat()})
    row.status = "complete"
    row.verification_status = "rejected"
    row.blocked_reason = reason
    row.closed_at = now
    row.updated_at = now
    row.evidence_json = json.dumps(evidence, ensure_ascii=False)
    return True


def _exclude_row(row, *, now: datetime, policy: TaskPolicy | None = None) -> bool:
    """停止排除人员的未关闭任务，保留交付证据和催办历史。"""
    owner_id = _assignment_record(row.evidence_json).get("owner_user_id")
    if not _owner_excluded(owner_id, row.owner, policy=policy) or row.status in {"done", "complete", "completed"}:
        return False
    evidence = _evidence_items(row)
    evidence.append({"evidence_type": "owner_exclusion", "recorded_at": now.isoformat()})
    row.status = "complete"
    row.verification_status = "excluded"
    row.blocked_reason = "人员在排除名单内，不参与群任务跟进" if policy is not None else "人员在排除名单内，不参与小黑屋任务跟进"
    row.closed_at = now
    row.updated_at = now
    row.evidence_json = json.dumps(evidence, ensure_ascii=False)
    return True


def sync_assignment_messages(
    messages: list[dict],
    members: list[dict],
    *,
    channel_id: str,
    publisher_user_id: int | str,
    timezone_name: str = "Asia/Shanghai",
    policy: TaskPolicy | None = None,
) -> dict:
    """把管理员消息幂等同步到 PdcaTask；编辑、改派和撤回会收敛旧任务。"""
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask

    result = {"created": 0, "updated": 0, "cancelled": 0, "ignored": 0}
    now = datetime.now(timezone.utc)
    with Session(get_engine()) as session:
        rows = list(
            session.exec(
                select(PdcaTask).where(
                    PdcaTask.source == SOURCE,
                    PdcaTask.group_channel_id == channel_id,
                )
            ).all()
        )
        by_ref = {row.source_ref: row for row in rows}
        by_message: dict[str, list] = {}
        for row in rows:
            if _exclude_row(row, now=now, policy=policy):
                session.add(row)
                result["cancelled"] += 1
            by_message.setdefault(_source_message_id(row), []).append(row)

        for message in messages or []:
            if not isinstance(message, dict):
                result["ignored"] += 1
                continue
            message_id = str(message.get("id") or "").strip()
            if (
                not message_id
                or str(message.get("sender_user_id") or "") != str(publisher_user_id)
            ):
                result["ignored"] += 1
                continue
            desired = parse_assignment_message(
                message,
                members,
                publisher_user_id=publisher_user_id,
                timezone_name=timezone_name,
                policy=policy,
            )
            current_rows = by_message.get(message_id, [])
            revoked = bool(message.get("revoked_at")) or str(message.get("message_type") or "") == "recall"
            if not desired and not current_rows:
                result["ignored"] += int(not revoked)
                continue

            desired_refs: set[str] = set()
            for task in desired:
                if policy is not None:
                    task["publisher_user_id"] = str(publisher_user_id)
                ref = _source_ref(channel_id, task)
                desired_refs.add(ref)
                row = by_ref.get(ref)
                evidence_json = json.dumps(_assignment_evidence(task), ensure_ascii=False)
                if row is None:
                    duplicate = next(
                        (
                            existing for existing in rows
                            if existing.status not in {"done", "complete", "completed"}
                            and (
                                existing.owner == task["owner"] if policy is None else
                                str(_assignment_record(existing.evidence_json).get("owner_user_id") or "") == str(task["owner_user_id"])
                                and str(_assignment_record(existing.evidence_json).get("publisher_user_id") or "") == str(task["publisher_user_id"])
                            )
                            and existing.task_date == task["start_date"]
                            and _title_key(existing.title) == _title_key(task["title"])
                            and _same_instant(existing.due_at, task["due_at"])
                        ),
                        None,
                    )
                    if duplicate is not None:
                        continue
                    row = PdcaTask(
                        task_date=task["start_date"],
                        title=task["title"],
                        owner=task["owner"],
                        status="pending",
                        source=SOURCE,
                        group_channel_id=channel_id,
                        source_ref=ref,
                        due_at=task["due_at"],
                        evidence_json=evidence_json,
                        verification_status="unverified",
                        updated_at=now,
                    )
                    session.add(row)
                    rows.append(row)
                    by_ref[ref] = row
                    by_message.setdefault(message_id, []).append(row)
                    result["created"] += 1
                    continue
                material_change = (
                    row.task_date != task["start_date"]
                    or row.title != task["title"]
                    or row.owner != task["owner"]
                    or not _same_instant(row.due_at, task["due_at"])
                    or _assignment_record(row.evidence_json) != _assignment_evidence(task)[0]
                )
                was_cancelled = row.status in {"done", "complete", "completed"} and row.verification_status == "rejected"
                was_excluded = policy is not None and row.verification_status == "excluded"
                if was_excluded and not material_change:
                    row.status = "pending"
                    row.verification_status = "unverified"
                    row.blocked_reason = ""
                    row.closed_at = None
                    row.updated_at = now
                    session.add(row)
                    result["updated"] += 1
                    continue
                if not material_change and not was_cancelled:
                    continue
                row.task_date = task["start_date"]
                row.title = task["title"]
                row.owner = task["owner"]
                row.due_at = task["due_at"]
                row.evidence_json = evidence_json
                row.status = "pending"
                row.verification_status = "unverified"
                row.blocked_reason = ""
                row.closed_at = None
                row.last_reminded_at = None
                row.last_reminded_round = ""
                row.updated_at = now
                session.add(row)
                result["updated"] += 1

            for row in current_rows:
                if row.source_ref in desired_refs:
                    continue
                if _owner_excluded(_assignment_record(row.evidence_json).get("owner_user_id"), row.owner, policy=policy):
                    continue
                if _cancel_row(
                    row,
                    reason="源任务已撤回" if revoked else "源任务已改派或删除",
                    evidence_type="source_withdrawal" if revoked else "source_reassignment",
                    now=now,
                ):
                    session.add(row)
                    result["cancelled"] += 1
        session.commit()
    return result


def _aware_utc(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _task_period(task: dict, tz: ZoneInfo) -> tuple[datetime, datetime | None]:
    try:
        start_day = date.fromisoformat(str(task.get("start_date") or task.get("task_date") or ""))
    except ValueError:
        start_day = datetime.now(tz).date()
    start = datetime.combine(start_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    return start, _aware_utc(task.get("due_at"))


def _dates_overlap(text: str, created: datetime, task_start: datetime, task_due: datetime | None, tz: ZoneInfo) -> bool:
    if not (_DATE_RANGE_RE.search(text) or _SINGLE_DATE_RE.search(text)):
        return False
    evidence_start_day, evidence_due = _date_window(text, created.astimezone(tz), tz)
    evidence_start = datetime.combine(evidence_start_day, time.min, tzinfo=tz).astimezone(timezone.utc)
    evidence_end = evidence_due or evidence_start
    task_end = task_due or datetime.max.replace(tzinfo=timezone.utc)
    return evidence_start <= task_end and evidence_end >= task_start


def _unreadable(message: dict) -> bool:
    bad = {"unreadable", "failed", "error", "download_failed", "ocr_failed"}
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    values = {str(value).casefold() for value in metadata.values() if isinstance(value, (str, int))}
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        attachment_meta = attachment.get("metadata")
        if isinstance(attachment_meta, dict):
            values.update(str(value).casefold() for value in attachment_meta.values() if isinstance(value, (str, int)))
    return bool(values & bad)


def _message_revoked(message: dict) -> bool:
    return bool(message.get("revoked_at")) or str(message.get("message_type") or "").casefold() == "recall"


def _attachment_kind(message: dict) -> str:
    attachments = [item for item in (message.get("attachments") or []) if isinstance(item, dict)]
    message_type = str(message.get("message_type") or "").casefold()
    readable_types: set[str] = set()
    declared_media = False
    for item in attachments:
        attachment_type = str(item.get("attachment_type") or message_type or "").casefold()
        if attachment_type in {"image", "video"}:
            declared_media = True
            if str(item.get("url") or item.get("storage_key") or "").strip():
                readable_types.add(attachment_type)
    if "video" in readable_types:
        return "video"
    if "image" in readable_types:
        return "image"
    if declared_media:
        return "unknown"
    if attachments:
        return "unsupported"
    if message_type in {"image", "video"}:
        return "unknown"
    return "none"


def _has_quoted_media(message: dict) -> bool:
    snapshot = message.get("quote_snapshot")
    if not isinstance(snapshot, dict):
        return False
    if str(snapshot.get("message_type") or "").casefold() in {"image", "video"}:
        return True
    candidates = list(snapshot.get("attachments") or [])
    for key in ("attachment", "image", "video"):
        value = snapshot.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    return any(
        isinstance(item, dict)
        and (
            str(item.get("attachment_type") or "").casefold() in {"image", "video"}
            or str(item.get("mime_type") or "").casefold().startswith(("image/", "video/"))
        )
        for item in candidates
    )


def evaluate_task_evidence(
    task: dict,
    messages: list[dict],
    *,
    history_complete: bool,
    history_start: datetime | str | None = None,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> dict:
    """判断一项任务为 submitted / missing / pending / progress。

    只在历史明确完整且已到截止时返回 missing；媒体无法读取或附件类型不支持时
    返回 pending，避免把“无法核验”写成“未提交”。
    """
    from app.todos.evidence import has_followup

    tz = ZoneInfo(timezone_name)
    current = _aware_utc(now or datetime.now(timezone.utc))
    assert current is not None
    task_start, task_due = _task_period(task, tz)
    if task.get("recurring_daily") or _DAILY_RE.search(str(task.get("title") or "")):
        return {"state": "pending", "message_ids": [], "reason": "每日重复任务需人工核对"}
    owner_user_id = str(task.get("owner_user_id") or "")
    source_message_id = str(task.get("source_message_id") or "")
    relevant: list[tuple[datetime, dict]] = []
    for message in messages or []:
        if not isinstance(message, dict) or str(message.get("sender_user_id") or "") != owner_user_id:
            continue
        if _message_revoked(message):
            continue
        created_local = _message_time(message, tz)
        if created_local is None:
            continue
        created = created_local.astimezone(timezone.utc)
        if task_start <= created <= current:
            relevant.append((created, message))
    relevant.sort(key=lambda pair: pair[0])
    pending_ids: list[str] = []
    for created, message in relevant:
        kind = _attachment_kind(message)
        quoted_media = _has_quoted_media(message)
        if kind == "none" and not quoted_media and str(message.get("message_type") or "") == "text":
            continue
        context_parts = [str(message.get("body") or "")]
        for other_created, other in relevant:
            if other is message or str(other.get("message_type") or "") != "text":
                continue
            if abs((other_created - created).total_seconds()) <= 10 * 60:
                context_parts.append(str(other.get("body") or ""))
        context = "\n".join(part.strip() for part in context_parts if part.strip())
        direct = str(message.get("parent_message_id") or message.get("quote_message_id") or "") == source_message_id
        content_matched = direct or has_followup(str(task.get("title") or ""), context)
        date_matched = _dates_overlap(context, created, task_start, task_due, tz)
        candidate = content_matched or date_matched or not context
        message_id = str(message.get("id") or "")
        if quoted_media:
            if candidate:
                pending_ids.append(message_id)
            continue
        if _unreadable(message) or kind in {"unsupported", "unknown"}:
            if candidate:
                pending_ids.append(message_id)
            continue
        requires_video = "视频" in str(task.get("title") or "")
        if requires_video and kind == "image":
            if candidate:
                pending_ids.append(message_id)
            continue
        if kind in {"image", "video"} and content_matched:
            return {
                "state": "submitted",
                "message_ids": [message_id] if message_id else [],
                "reason": "已找到与任务关联的媒体证据",
            }
        if kind in {"image", "video"} and candidate:
            pending_ids.append(message_id)

    # 文字可直接作为非视频类交付，但“已交/任务标题”短回复不能闭环。
    text_claim_ids: list[str] = []
    if "视频" not in str(task.get("title") or ""):
        for _, message in relevant:
            if str(message.get("message_type") or "") != "text":
                continue
            body = str(message.get("body") or "").strip()
            direct = str(message.get("parent_message_id") or message.get("quote_message_id") or "") == source_message_id
            if len(body) >= 80 and (direct or has_followup(str(task.get("title") or ""), body)):
                message_id = str(message.get("id") or "")
                return {
                    "state": "submitted",
                    "message_ids": [message_id] if message_id else [],
                    "reason": "已找到与任务关联的正文证据",
                }
            if direct or has_followup(str(task.get("title") or ""), body) or re.search(r"(?:已交|已提交|交了)", body):
                message_id = str(message.get("id") or "")
                if message_id:
                    text_claim_ids.append(message_id)
    else:
        for _, message in relevant:
            if str(message.get("message_type") or "") != "text":
                continue
            body = str(message.get("body") or "").strip()
            direct = str(message.get("parent_message_id") or message.get("quote_message_id") or "") == source_message_id
            if direct or has_followup(str(task.get("title") or ""), body) or re.search(r"(?:已交|已提交|交了)", body):
                message_id = str(message.get("id") or "")
                if message_id:
                    text_claim_ids.append(message_id)
    if pending_ids:
        return {"state": "pending", "message_ids": [item for item in pending_ids if item], "reason": "附件待人工确认"}
    if text_claim_ids:
        return {"state": "pending", "message_ids": text_claim_ids, "reason": "只有提交说明，未找到交付证据"}
    if not history_complete:
        return {"state": "pending", "message_ids": [], "reason": "群消息采集不完整，待确认"}
    coverage_start = _aware_utc(history_start)
    if coverage_start is not None and task_start < coverage_start:
        return {"state": "pending", "message_ids": [], "reason": "消息窗口未覆盖任务开始时间，待确认"}
    if task_due is None or current < task_due:
        return {"state": "progress", "message_ids": [], "reason": "任务仍在执行期"}
    return {"state": "missing", "message_ids": [], "reason": "完整消息范围内未找到提交证据"}


def _task_from_row(row) -> dict:
    try:
        evidence = json.loads(row.evidence_json or "[]")
    except (TypeError, ValueError):
        evidence = []
    assignment = next(
        (
            item
            for item in evidence if isinstance(evidence, list) and isinstance(item, dict)
            if item.get("evidence_type") == "assignment_notice"
        ),
        {},
    )
    return {
        "id": row.id,
        "owner": row.owner,
        "owner_user_id": str(assignment.get("owner_user_id") or ""),
        "publisher_user_id": str(assignment.get("publisher_user_id") or ""),
        "title": row.title,
        "start_date": str(assignment.get("start_date") or row.task_date),
        "due_at": row.due_at,
        "source_message_id": str(assignment.get("message_id") or ""),
        "recurring_daily": bool(assignment.get("recurring_daily")),
        "status": row.status,
        "last_reminded_at": row.last_reminded_at,
        "last_reminded_round": row.last_reminded_round,
    }


def _evidence_items(row) -> list[dict]:
    try:
        evidence = json.loads(row.evidence_json or "[]")
    except (TypeError, ValueError):
        return []
    return [item for item in evidence if isinstance(item, dict)] if isinstance(evidence, list) else []


def _stored_evidence_ids(row) -> set[str]:
    return {
        str(item.get("message_id") or "")
        for item in _evidence_items(row)
        if item.get("evidence_type") == "im_message" and str(item.get("message_id") or "")
    }


def reconcile_task_evidence(
    messages: list[dict],
    *,
    channel_id: str,
    history_complete: bool,
    history_start: datetime | str | None = None,
    now: datetime | None = None,
    timezone_name: str = "Asia/Shanghai",
    policy: TaskPolicy | None = None,
) -> dict[str, list[dict]]:
    """核对本群未闭环任务并持久化证据状态；不负责发送。"""
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask

    current = _aware_utc(now or datetime.now(timezone.utc))
    assert current is not None
    result: dict[str, list[dict]] = {
        "submitted": [], "missing": [], "pending": [], "progress": [],
    }
    with Session(get_engine()) as session:
        rows = list(
            session.exec(
                select(PdcaTask).where(
                    PdcaTask.source == SOURCE,
                    PdcaTask.group_channel_id == channel_id,
                    ~PdcaTask.status.in_(["done", "complete", "completed"]),
                )
            ).all()
        )
        for row in rows:
            if _exclude_row(row, now=current, policy=policy):
                session.add(row)
                continue
            task = _task_from_row(row)
            decision = evaluate_task_evidence(
                task,
                messages,
                history_complete=history_complete,
                history_start=history_start,
                now=current,
                timezone_name=timezone_name,
            )
            stored_ids = _stored_evidence_ids(row)
            messages_by_id = {
                str(message.get("id") or ""): message
                for message in messages
                if isinstance(message, dict) and str(message.get("id") or "")
            }
            present_stored = {
                message_id: messages_by_id[message_id]
                for message_id in stored_ids
                if message_id in messages_by_id
            }
            invalid_stored_ids: set[str] = set()
            if row.status == "evidence_submitted" and decision["state"] != "submitted":
                if stored_ids and not present_stored:
                    task_start, _task_due = _task_period(task, ZoneInfo(timezone_name))
                    coverage_start = _aware_utc(history_start)
                    if not (
                        history_complete
                        and coverage_start is not None
                        and task_start is not None
                        and coverage_start <= task_start
                    ):
                        decision = {
                            "state": "submitted",
                            "message_ids": sorted(stored_ids),
                            "reason": "已提交证据不在本次消息窗口内",
                        }
                    else:
                        invalid_stored_ids = set(stored_ids)
                elif present_stored:
                    invalid_stored_ids = set(present_stored)
                if (
                    present_stored
                    and decision["state"] == "pending"
                    and decision["reason"] == "只有提交说明，未找到交付证据"
                    and history_complete
                    and _task_period(task, ZoneInfo(timezone_name))[1] is not None
                    and current >= _task_period(task, ZoneInfo(timezone_name))[1]
                ):
                    decision = {
                        "state": "missing",
                        "message_ids": [],
                        "reason": "原交付证据已撤回或失效",
                    }
            state = decision["state"]
            task["evidence_state"] = state
            task["evidence_reason"] = decision["reason"]
            task["evidence_message_ids"] = decision["message_ids"]
            result[state].append(task)
            changed = False
            if state == "submitted":
                evidence = _evidence_items(row)
                known = {
                    str(item.get("message_id") or "")
                    for item in evidence if isinstance(item, dict)
                }
                for message_id in decision["message_ids"]:
                    if message_id and message_id not in known:
                        evidence.append({
                            "evidence_type": "im_message",
                            "message_id": message_id,
                            "recorded_at": current.isoformat(),
                        })
                row.evidence_json = json.dumps(evidence, ensure_ascii=False)
                row.status = "evidence_submitted"
                row.verification_status = "partial"
                row.blocked_reason = ""
                changed = True
            else:
                if invalid_stored_ids:
                    evidence = [
                        item for item in _evidence_items(row)
                        if not (
                            item.get("evidence_type") == "im_message"
                            and str(item.get("message_id") or "") in invalid_stored_ids
                        )
                    ]
                    row.evidence_json = json.dumps(evidence, ensure_ascii=False)
                    changed = True
                if row.status == "evidence_submitted":
                    row.status = "pending"
                    changed = True
            if state == "pending":
                if row.verification_status != "pending_manual" or row.blocked_reason != decision["reason"]:
                    row.verification_status = "pending_manual"
                    row.blocked_reason = decision["reason"][:512]
                    changed = True
            else:
                if state != "submitted" and (row.verification_status != "unverified" or row.blocked_reason):
                    row.verification_status = "unverified"
                    row.blocked_reason = ""
                    changed = True
            if changed:
                row.updated_at = current
                session.add(row)
        session.commit()
    return result


def fetch_group_members(channel_id: str) -> dict:
    """读取目标群完整成员；取不到目标群时明确返回 complete=False。"""
    from app.vertu.client import run_vertu_sync_json

    try:
        payload = run_vertu_sync_json(["im", "+channels", "--limit", "200"], timeout=90.0)
    except Exception as exc:  # noqa: BLE001 - 边界统一转成待确认
        return {"members": [], "complete": False, "error": type(exc).__name__}
    channels = payload.get("channels") if isinstance(payload, dict) else payload
    if not isinstance(channels, list):
        return {"members": [], "complete": False, "error": "invalid_channels_payload"}
    channel = next(
        (item for item in channels if isinstance(item, dict) and str(item.get("id") or "") == channel_id),
        None,
    )
    if channel is None or not isinstance(channel.get("members"), list):
        return {"members": [], "complete": False, "error": "channel_not_found"}
    return {"members": channel["members"], "complete": True, "error": ""}


def fetch_group_history(channel_id: str, *, now: datetime, lookback_days: int) -> dict:
    """读取任务与证据窗口；命中页上限时按不完整处理，不据此判未交。"""
    from app.vertu.client import run_vertu_sync_json

    current = _aware_utc(now)
    assert current is not None
    start = current - timedelta(days=max(1, int(lookback_days)))
    limit = 200
    base_args = [
        "im", "+history", "--channel-id", channel_id,
        "--date-from", start.isoformat().replace("+00:00", "Z"),
        "--date-to", current.isoformat().replace("+00:00", "Z"),
        "--limit", str(limit),
    ]
    rows: list[dict] = []
    seen_pages: set[tuple[str, ...]] = set()
    offset = 0
    for _page in range(100):
        args = [*base_args]
        if offset:
            args += ["--offset", str(offset)]
        try:
            payload = run_vertu_sync_json(args, timeout=90.0)
        except Exception as exc:  # noqa: BLE001 - 边界统一转成待确认
            return {
                "messages": rows, "complete": False,
                "error": type(exc).__name__, "coverage_start": start,
            }
        messages = payload.get("messages") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("ok") is False or not isinstance(messages, list):
            return {
                "messages": rows, "complete": False,
                "error": "invalid_history_payload", "coverage_start": start,
            }
        page_rows = [item for item in messages if isinstance(item, dict)]
        signature = tuple(str(item.get("id") or "") for item in page_rows)
        if messages and signature in seen_pages:
            return {
                "messages": rows, "complete": False,
                "error": "history_pagination_stalled", "coverage_start": start,
            }
        seen_pages.add(signature)
        rows.extend(page_rows)
        if len(messages) < limit:
            return {
                "messages": rows, "complete": True, "error": "",
                "coverage_start": start,
            }
        offset += len(messages)
    return {
        "messages": rows, "complete": False,
        "error": "history_page_limit", "coverage_start": start,
    }


def _started(task: dict, current: datetime, tz: ZoneInfo) -> bool:
    try:
        start_day = date.fromisoformat(str(task.get("start_date") or ""))
    except ValueError:
        return False
    return start_day <= current.astimezone(tz).date()


def _reminded_today(task: dict, round_name: str, current: datetime, tz: ZoneInfo, reminder_round: str | None = None) -> bool:
    if str(task.get("last_reminded_round") or "") != (reminder_round or f"heiwu-{round_name}"):
        return False
    reminded = _aware_utc(task.get("last_reminded_at"))
    return bool(reminded and reminded.astimezone(tz).date() == current.astimezone(tz).date())


def _task_label(task: dict, state: str, current: datetime, tz: ZoneInfo, round_name: str) -> str:
    due = _aware_utc(task.get("due_at"))
    today = current.astimezone(tz).date()
    if state == "pending":
        return "证据待人工确认"
    if round_name == "evening":
        if state == "missing":
            return "已过截止时间，未找到交付证据"
        if due is not None and due.astimezone(tz).date() == today:
            return "今晚截止，尚未见交付，请截止前补交"
        return "执行期内，请回报当前进度"
    if due is None:
        return "长期任务"
    due_day = due.astimezone(tz).date()
    if due_day < today:
        return "已逾期"
    if due_day == today:
        return "今天 " + due.astimezone(tz).strftime("%H:%M") + " 核对"
    return "进行中，截止 " + due_day.strftime("%m-%d")


def _build_body(owner: str, tasks: list[tuple[dict, str]], current: datetime, tz: ZoneInfo, round_name: str) -> str:
    heading = "早间任务提醒" if round_name == "morning" else "晚间任务核对"
    lines = [f"@{owner}｜{heading}"]
    for task, state in tasks:
        label = _task_label(task, state, current, tz, round_name)
        lines.append(f"- [{label}] {task['title']}")
    if round_name == "evening" and any(state == "progress" for _, state in tasks):
        lines.append("多日任务无需每天重交，回复当前进度即可。")
    return "\n".join(lines)


def _mark_reminded(task_ids: list[int], *, round_name: str, current: datetime, reminder_round: str | None = None) -> None:
    from sqlmodel import Session

    from app.database import get_engine
    from app.models.pdca_task import PdcaTask

    with Session(get_engine()) as session:
        for task_id in task_ids:
            row = session.get(PdcaTask, task_id)
            if row is None:
                continue
            row.last_reminded_at = current
            row.last_reminded_round = reminder_round or f"heiwu-{round_name}"
            row.remind_count = int(row.remind_count or 0) + 1
            row.updated_at = current
            session.add(row)
        session.commit()


def _round_groups(decisions: dict[str, list[dict]], *, round_name: str, current: datetime, tz: ZoneInfo, policy: TaskPolicy | None = None, reminder_round: str | None = None) -> list[dict]:
    grouped: dict[str, dict] = {}
    states = ("missing", "progress", "pending") if round_name == "morning" else ("missing", "progress")
    for state in states:
        for task in decisions[state]:
            if not _started(task, current, tz) or _reminded_today(task, round_name, current, tz, reminder_round):
                continue
            owner_id = str(task.get("owner_user_id") or "")
            if not owner_id or _owner_excluded(owner_id, task.get("owner", ""), policy=policy):
                continue
            group = grouped.setdefault(owner_id, {"owner_user_id": owner_id, "owner": task["owner"], "tasks": []})
            group["tasks"].append((task, state))
    return list(grouped.values())


def run_round(round_name: str, *, now: datetime | None = None, dry_run: bool = False) -> dict:
    """运行 morning/evening 一轮；采集失败时不发送、不写已提醒。"""
    if round_name not in {"morning", "evening"}:
        raise ValueError("round_name must be morning or evening")

    from app.config import get_settings
    from app.heiwu import _reply, channel_id, configured
    from app.scheduler.run_ledger import claim_run, finish_run

    settings = get_settings()
    publisher_ids = tuple(getattr(settings, "heiwu_task_publisher_user_ids", ()) or ())
    if not getattr(settings, "heiwu_tasks_enabled", False):
        return {"skipped": "disabled"}
    if not publisher_ids:
        return {"skipped": "publisher_not_configured"}
    current = _aware_utc(now or datetime.now(timezone.utc))
    assert current is not None
    tz = LOCAL_TZ
    day = current.astimezone(tz).date().isoformat()
    group_channel_id = channel_id()
    job_name = f"heiwu_tasks_{round_name}"
    if not dry_run and not claim_run(job_name, day):
        return {"skipped": "already_claimed"}

    try:
        history = fetch_group_history(
            group_channel_id,
            now=current,
            lookback_days=int(getattr(settings, "heiwu_task_lookback_days", 21) or 21),
        )
        roster = fetch_group_members(group_channel_id)
        messages = history["messages"]
        if dry_run:
            member_rows = roster["members"] if roster["complete"] else []
            excluded = {str(item) for item in publisher_ids}
            member_rows = [
                item for item in member_rows
                if str(item.get("user_id") or "") not in excluded
            ]
            previews = []
            if history["complete"] and roster["complete"]:
                for publisher_id in publisher_ids:
                    for message in messages:
                        previews.extend(parse_assignment_message(
                            message, member_rows, publisher_user_id=publisher_id
                        ))
            return {
                "dry_run": True,
                "history_complete": history["complete"],
                "roster_complete": roster["complete"],
                "tasks": len(previews),
                "reminded": 0,
            }

        if not history["complete"] or not roster["complete"]:
            decisions = reconcile_task_evidence(
                messages,
                channel_id=group_channel_id,
                history_complete=False,
                history_start=history.get("coverage_start"),
                now=current,
            )
            error = history["error"] or roster["error"] or "source_incomplete"
            finish_run(job_name, day, "failed", error)
            return {
                "tasks": sum(len(items) for items in decisions.values()),
                "submitted": len(decisions["submitted"]),
                "pending": len(decisions["pending"]),
                "reminded": 0,
                "failed": error,
            }

        all_publishers = {str(item) for item in publisher_ids}
        member_rows = [
            item for item in roster["members"]
            if str(item.get("user_id") or "") not in all_publishers
        ]
        sync_result = {"created": 0, "updated": 0, "cancelled": 0, "ignored": 0}
        for publisher_id in publisher_ids:
            publisher_messages = [
                message for message in messages
                if str(message.get("sender_user_id") or "") == str(publisher_id)
            ]
            partial = sync_assignment_messages(
                publisher_messages,
                member_rows,
                channel_id=group_channel_id,
                publisher_user_id=publisher_id,
            )
            for key in sync_result:
                sync_result[key] += partial[key]
        decisions = reconcile_task_evidence(
            messages,
            channel_id=group_channel_id,
            history_complete=True,
            history_start=history.get("coverage_start"),
            now=current,
        )
        groups = _round_groups(decisions, round_name=round_name, current=current, tz=tz)
        if groups and not configured():
            finish_run(job_name, day, "failed", "bot_not_configured")
            return {
                "tasks": sum(len(items) for items in decisions.values()),
                "submitted": len(decisions["submitted"]),
                "pending": len(decisions["pending"]),
                "reminded": 0,
                "failed": "bot_not_configured",
            }

        reminded = 0
        failures: list[str] = []
        for group in groups:
            body = _build_body(group["owner"], group["tasks"], current, tz, round_name)
            task_ids = [int(task["id"]) for task, _ in group["tasks"]]
            digest = hashlib.sha256(",".join(str(item) for item in sorted(task_ids)).encode()).hexdigest()[:12]
            key = f"heiwu-task-{round_name}-{day}-{group['owner_user_id']}-{digest}"
            if "?" in body or "\ufffd" in body or body.encode("utf-8").decode("utf-8") != body:
                failures.append(f"unsafe_text:{group['owner_user_id']}")
                continue
            parent = str(group["tasks"][0][0].get("source_message_id") or "")
            try:
                sent = bool(_reply(body, parent, key))
            except Exception as exc:  # noqa: BLE001 - 单人失败不能提前写提醒游标
                failures.append(f"{group['owner_user_id']}:{type(exc).__name__}")
                continue
            if not sent:
                failures.append(f"send_failed:{group['owner_user_id']}")
                continue
            _mark_reminded(task_ids, round_name=round_name, current=current)
            reminded += len(task_ids)

        if failures:
            finish_run(job_name, day, "failed", ";".join(failures)[:512])
        else:
            finish_run(job_name, day, "sent", f"reminded={reminded}")
        return {
            "tasks": sum(len(items) for items in decisions.values()),
            "submitted": len(decisions["submitted"]),
            "pending": len(decisions["pending"]),
            "reminded": reminded,
            "failed": failures,
            "sync": sync_result,
        }
    except Exception as exc:  # noqa: BLE001 - scheduler 入口必须收尾 run ledger
        if not dry_run:
            finish_run(job_name, day, "failed", type(exc).__name__)
        return {"tasks": 0, "submitted": 0, "pending": 0, "reminded": 0, "failed": type(exc).__name__}
