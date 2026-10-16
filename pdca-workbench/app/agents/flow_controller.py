# -*- coding: utf-8 -*-
"""流程控制器：Cron 与 Agent 共用的确定性业务入口（第 8 节）。

定位：确定性服务，不是 LLM Agent。第一版封装现有函数，不改变三追文案：
  prepare_performance_slot -> prepare_duzhan（09:45 采集组表）
  push_performance_slot   -> run_duzhan（整点推送）
  run_ctob_evening        -> run_ctob（工作日北京 20:00）
  build_daily_report      -> daily_report.build_report（08:30 日报）
  check_slot_health       -> 每档整点后 5 分钟健康检查（P0）

所有入口写 slot.*/meeting.* 事件；单数据源失败继续组表并写“待确认”，
缺快照、推送失败绝不静默，调用现有 notify 告警。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from loguru import logger

from app.alerting import notify
from app.config import get_settings
from app.duzhan import (
    _slot_key,
    cron_timezones,
    groups_for_tz,
    load_prepared,
    parse_hours,
    prepare_duzhan,
    run_duzhan,
)
from app.duzhan_blocks import split_time_slot
from app.scheduler.run_ledger import claim_run, finish_run
from app.workday_calendar import is_workday


def _slot_text(hour: int, minute: int = 0) -> str:
    return f"{hour:02d}:{minute:02d}"


def _target_day(
    tz_name: str,
    now: datetime,
    day_offset: int = 0,
    *,
    hour: int | None = None,
    minute: int = 0,
    trigger_offset_minutes: int | None = None,
) -> str:
    local = now.astimezone(ZoneInfo(tz_name))
    if hour is not None and trigger_offset_minutes is not None:
        candidates = []
        for offset in (-1, 0, 1):
            target_day = local.date() + timedelta(days=offset)
            target = datetime(
                target_day.year, target_day.month, target_day.day, hour, minute,
                tzinfo=ZoneInfo(tz_name),
            )
            trigger = target + timedelta(minutes=trigger_offset_minutes)
            candidates.append((abs((trigger - local).total_seconds()), target_day))
        return min(candidates, key=lambda item: item[0])[1].isoformat()
    return (local.date() + timedelta(days=day_offset)).isoformat()


def _slot_bucket(tz_name: str, hour: int, day: str, minute: int = 0) -> str:
    token = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
    return f"{tz_name}:{token}:{day}"


def _slot_events_key(
    producer: str, event_type: str, tz_name: str, day: str, hour: int, minute: int = 0,
) -> str:
    token = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
    return f"{producer}:{event_type}:{tz_name}:{day}:{token}"


def prepare_performance_slot(
    tz_name: str,
    hour: int,
    now: datetime | None = None,
    *,
    minute: int = 0,
    day_offset: int = 0,
    trigger_offset_minutes: int | None = None,
    ledger_job: str = "duzhan_collect",
    channel_ids: list[str] | None = None,
) -> dict:
    """提前采集档位快照（P2 封装）：claim -> prepare_duzhan -> 事件 -> finish。

    `ledger_job` 按时区分档（db 源下同一时区、档位共用一次采集）；
    `channel_ids` 只组这些群的表。
    """
    from app.agents.events import write_event

    now = now or datetime.now(ZoneInfo(tz_name))
    day = _target_day(
        tz_name, now, day_offset, hour=hour, minute=minute,
        trigger_offset_minutes=trigger_offset_minutes,
    )
    if not is_workday(day):
        return {"tz": tz_name, "hour": hour, "minute": minute, "skipped": "weekend"}
    bucket = _slot_bucket(tz_name, hour, day, minute)
    if not claim_run(ledger_job, bucket):
        return {"tz": tz_name, "hour": hour, "minute": minute, "skipped": "already_claimed"}
    write_event("slot.collect_started", producer="flow_controller",
                event_key=_slot_events_key("flow_controller", "collect_started", tz_name, day, hour, minute),
                payload={"tz": tz_name, "hour": hour, "minute": minute, "day": day})
    try:
        payload = prepare_duzhan(
            tz_name, hour, now, minute=minute, day=day, channel_ids=channel_ids,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("督战官组表失败: {}", exc)
        finish_run(ledger_job, bucket, "failed", f"{type(exc).__name__}: {exc}")
        notify("督战官组表失败", f"{tz_name} {_slot_text(hour, minute)} {exc}"[:200])
        write_event("slot.collect_failed", producer="flow_controller",
                    event_key=_slot_events_key("flow_controller", "collect_failed", tz_name, day, hour, minute),
                    payload={"error": str(exc)[:300]})
        return {"tz": tz_name, "hour": hour, "minute": minute, "status": "failed", "error": str(exc)[:300]}
    write_event("slot.collect_completed", producer="flow_controller",
                event_key=_slot_events_key("flow_controller", "collect_completed", tz_name, day, hour, minute),
                payload={"groups": len(payload.get("messages") or {})})
    finish_run(ledger_job, bucket, "sent")
    payload["status"] = "ok"
    return payload


def push_performance_slot(
    tz_name: str,
    hour: int,
    now: datetime | None = None,
    *,
    minute: int = 0,
    day_offset: int = 0,
    trigger_offset_minutes: int | None = None,
    ledger_job: str = "duzhan",
    channel_ids: list[str] | None = None,
) -> dict:
    """整点推送（P2 封装）：claim -> run_duzhan -> 事件 -> finish；单群失败不阻断其他群。"""
    from app.agents.events import write_event

    now = now or datetime.now(ZoneInfo(tz_name))
    day = _target_day(
        tz_name, now, day_offset, hour=hour, minute=minute,
        trigger_offset_minutes=trigger_offset_minutes,
    )
    if not is_workday(day):
        return {"tz": tz_name, "hour": hour, "minute": minute, "skipped": "weekend"}
    bucket = _slot_bucket(tz_name, hour, day, minute)
    if not claim_run(ledger_job, bucket):
        return {"tz": tz_name, "hour": hour, "minute": minute, "skipped": "already_claimed"}
    write_event("slot.push_requested", producer="flow_controller",
                event_key=_slot_events_key("flow_controller", "push_requested", tz_name, day, hour, minute),
                payload={"tz": tz_name, "hour": hour, "minute": minute, "day": day})
    try:
        result = run_duzhan(
            tz_name, hour, now, minute=minute, day=day, channel_ids=channel_ids,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("督战官执行失败: {}", exc)
        finish_run(ledger_job, bucket, "failed", f"{type(exc).__name__}: {exc}")
        notify("督战官推送失败", f"{tz_name} {_slot_text(hour, minute)} {exc}"[:200])
        write_event("slot.push_failed", producer="flow_controller",
                    event_key=_slot_events_key("flow_controller", "push_failed", tz_name, day, hour, minute),
                    payload={"error": str(exc)[:300]})
        return {"tz": tz_name, "hour": hour, "minute": minute, "status": "failed", "error": str(exc)[:300]}
    failed = result.get("failed") or []
    sent = result.get("sent") or []
    # 对齐核心日报模式：部分失败 60 秒后整档重试一次（VPS 幂等键防重复推送）。
    if failed:
        logger.warning("督战官部分群失败，60 秒后重试一次: {} {} {}", tz_name, hour, failed)
        time.sleep(60)
        try:
            retry = run_duzhan(
                tz_name, hour, now, minute=minute, day=day, channel_ids=channel_ids,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("督战官重试失败: {}", exc)
            retry = {"sent": [], "failed": failed}
        retry_sent = retry.get("sent") or []
        retry_failed = retry.get("failed") or []
        sent = sorted(set(sent) | set(retry_sent))
        failed = retry_failed
    write_event("slot.push_succeeded" if not failed else "slot.push_failed",
                producer="flow_controller",
                event_key=_slot_events_key("flow_controller", "push_result", tz_name, day, hour, minute),
                payload={"sent": sent, "failed": failed})
    if failed:
        finish_run(ledger_job, bucket, "failed", ",".join(failed)[:512])
        notify("督战官部分群失败", f"{tz_name} {_slot_text(hour, minute)} {failed}")
        return {"tz": tz_name, "hour": hour, "minute": minute, "status": "partial", "sent": sent, "failed": failed}
    finish_run(ledger_job, bucket, "sent", ",".join(sent)[:512])
    return {"tz": tz_name, "hour": hour, "minute": minute, "status": "ok", "sent": sent}


def run_ctob_slot(
    hour: int = 20,
    day: str | None = None,
    now: datetime | None = None,
    *,
    minute: int = 0,
    day_offset: int = 0,
    trigger_offset_minutes: int | None = None,
    owners: tuple | None = None,
    ledger_job: str = "ctob",
) -> dict:
    """C转B 按档推送（P2 封装）：工作日北京 10:00 / 15:00 / 20:00，每档独立台账。

    `owners` 有值时只处理这些群；db 源下同一档位合并执行。
    """
    from app.ctob import TZ_SHANGHAI as _SH, run_ctob, slot_title

    now = now or datetime.now(ZoneInfo(_SH))
    day = day or _target_day(
        _SH, now, day_offset, hour=hour, minute=minute,
        trigger_offset_minutes=trigger_offset_minutes,
    )
    if not is_workday(day):
        return {"skipped": "weekend"}
    token = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
    bucket = f"{day}-{token}"
    if not claim_run(ledger_job, bucket):
        return {"skipped": "already_claimed"}
    try:
        result = run_ctob(day, now, hour=hour, minute=minute, owners=owners)
    except Exception as exc:  # noqa: BLE001
        logger.exception("C转B {}失败: {}", slot_title(hour, minute), exc)
        finish_run(ledger_job, bucket, "failed", f"{type(exc).__name__}: {exc}")
        notify(f"C转B{slot_title(hour, minute)}失败", str(exc)[:200])
        return {"status": "failed", "error": str(exc)[:300]}
    failed = result.get("failed") or []
    sent = result.get("sent") or []
    # 对齐核心日报模式：部分失败 60 秒后整档重试一次（幂等键 ctob-* 防重复推送）。
    if failed:
        logger.warning("C转B {}部分失败，60 秒后重试一次: {}", slot_title(hour, minute), failed)
        time.sleep(60)
        try:
            retry = run_ctob(day, now, hour=hour, minute=minute, owners=owners)
        except Exception as exc:  # noqa: BLE001
            logger.exception("C转B {}重试失败: {}", slot_title(hour, minute), exc)
            retry = {"sent": [], "failed": failed}
        sent = sorted(set(sent) | set(retry.get("sent") or []))
        failed = retry.get("failed") or []
    if failed:
        finish_run(ledger_job, bucket, "failed", ",".join(failed)[:512])
        notify(f"C转B{slot_title(hour, minute)}部分失败", str(failed))
        return {"status": "partial", "sent": sent, "failed": failed}
    finish_run(ledger_job, bucket, "sent", ",".join(sent)[:512])
    return {"status": "ok", "sent": sent}


def run_ctob_evening(day: str | None = None, now: datetime | None = None) -> dict:
    """C转B 晚追（20:00 档，兼容旧调用）。"""
    return run_ctob_slot(20, day, now)


def build_daily_report(day: str) -> str:
    """经营日报生成（P2 封装）。"""
    from app.daily_report import build_report

    return build_report(day)


def _scheduled_run_status(job_name: str, bucket: str) -> dict:
    """读取 run_ledger 中某次运行的凭证状态；不存在返回 {"found": False}。"""
    from sqlmodel import Session, select

    from app.database import get_engine
    from app.models.scheduled_job_run import ScheduledJobRun

    run_key = f"{job_name}:{bucket}"
    try:
        with Session(get_engine()) as session:
            row = session.exec(
                select(ScheduledJobRun).where(ScheduledJobRun.run_key == run_key)
            ).first()
    except Exception as exc:  # noqa: BLE001 — 健康检查自身降级，不能抛
        logger.warning("run_ledger 查询失败: {}", exc)
        return {"found": False, "error": str(exc)[:200]}
    if row is None:
        return {"found": False}
    return {
        "found": True,
        "status": row.status,
        "detail": row.detail,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def check_slot_health(
    tz_name: str,
    hour: int,
    day: str,
    *,
    minute: int = 0,
    now: datetime | None = None,
    expect_push: bool = True,
    alert: bool = True,
) -> dict:
    """P0 档位健康检查：collect run / slot 快照 / push run 三项凭证。

    检查：
    1. duzhan_collect:{tz}:{hour}:{day} 是否 sent；
    2. 快照文件是否存在、JSON 可解析、prepared_at 属于当天该档、群数量正确；
    3. duzhan:{tz}:{hour}:{day} 推送凭证是否存在且 sent。
    缺失/失败时返回问题清单；alert=True 才调用 notify（后台展示传 False）。
    只读检查，绝不补发、不推真实群、不修改三追文案。
    """
    problems: list[dict] = []
    from app.duzhan_admin import runtime

    slot_text = _slot_text(hour, minute)
    bucket = _slot_bucket(tz_name, hour, day, minute)
    db_source = runtime.using_db()
    if db_source:
        channels = [group.channel_id for agent, group in runtime.duzhan_agents()
                    if group.tz == tz_name and slot_text in runtime.slot_times_of(agent)]
        slot = (load_prepared(tz_name, hour, day, _slot_key(channels), minute)
                if minute else load_prepared(tz_name, hour, day, _slot_key(channels)))
        expected_groups = len(channels)
        collect_job, push_job = f"duzhan_collect:db:{tz_name}", f"duzhan_push:db:{tz_name}"
    else:
        slot = load_prepared(tz_name, hour, day, minute=minute) if minute else load_prepared(tz_name, hour, day)
        expected_groups = len(groups_for_tz(tz_name))
        collect_job, push_job = "duzhan_collect", "duzhan"

    collect = _scheduled_run_status(collect_job, bucket)
    if db_source and minute == 0 and not collect.get("found"):
        legacy_collect = _scheduled_run_status("duzhan_collect", bucket)
        if legacy_collect.get("found"):
            from app.duzhan import GROUPS

            collect = legacy_collect
            slot = load_prepared(tz_name, hour, day)
            expected_groups = sum(group.tz == tz_name for group in GROUPS)
    if not collect.get("found"):
        problems.append({"step": "collect_run", "detail": "未找到 duzhan_collect 运行凭证"})
    elif collect.get("status") != "sent":
        problems.append({"step": "collect_run", "detail": f"状态 {collect.get('status')} "
                         f"{collect.get('detail') or ''}"[:200]})

    if slot is None:
        problems.append({"step": "slot_snapshot", "detail": "快照文件缺失"})
    else:
        prepared = slot.get("prepared_at") or ""
        slot_day = (slot.get("day") or "")
        slot_hour = slot.get("hour")
        slot_minute = int(slot.get("minute") or 0)
        if slot_day != day or slot_hour != hour or slot_minute != minute:
            problems.append({
                "step": "slot_snapshot",
                "detail": f"快照属于 {slot_day} {int(slot_hour or 0):02d}:{slot_minute:02d}，与检查档不符",
            })
        elif not prepared:
            problems.append({"step": "slot_snapshot", "detail": "prepared_at 缺失"})
        else:
            try:
                parsed = datetime.fromisoformat(prepared)
                local = parsed.astimezone(ZoneInfo(tz_name))
                target = datetime.strptime(
                    f"{day}T{hour:02d}:{minute:02d}:00", "%Y-%m-%dT%H:%M:%S",
                ).replace(tzinfo=ZoneInfo(tz_name))
                lead_minutes = (target - local).total_seconds() / 60
                if not 0 <= lead_minutes <= 60:
                    problems.append({"step": "slot_snapshot", "detail": f"prepared_at={prepared} 不属于当天该档"})
            except (ValueError, TypeError):
                problems.append({"step": "slot_snapshot", "detail": f"prepared_at 不可解析: {prepared[:40]}"})
        groups = len(slot.get("messages") or {})
        if groups != expected_groups:
            problems.append({"step": "slot_snapshot", "detail": f"群消息 {groups} != 预期 {expected_groups}"})

    if expect_push:
        push = _scheduled_run_status(push_job, bucket)
        if db_source and minute == 0 and not push.get("found"):
            legacy_push = _scheduled_run_status("duzhan", bucket)
            if legacy_push.get("found"):
                push = legacy_push
        if not push.get("found"):
            problems.append({"step": "push_run", "detail": "未找到 duzhan 推送凭证"})
        elif push.get("status") != "sent":
            problems.append({"step": "push_run", "detail": f"状态 {push.get('status')} "
                         f"{push.get('detail') or ''}"[:200]})

    report = {
        "date": day,
        "timezone": tz_name,
        "hour": slot_text,
        "slot": slot_text,
        "ok": not problems,
        "problems": problems,
        "suggested_action": "人工核对调度器与机器人配置，必要时手动补跑该档" if problems else "",
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
    }
    if problems:
        detail = "; ".join(f"{p['step']}:{p['detail']}" for p in problems)[:280]
        if alert:
            notify("督战档位健康检查失败", f"{tz_name} {slot_text} {day} → {detail}")
        logger.error("slot health FAILED {} {} {}: {}", tz_name, slot_text, day, detail)
    else:
        logger.info("slot health OK {} {} {}", tz_name, slot_text, day)
    return report


def check_ctob_slot_health(
    hour: int,
    day: str,
    *,
    minute: int = 0,
    now: datetime | None = None,
    alert: bool = True,
) -> dict:
    """检查 DB 配置的 C 转 B 档位运行凭证和群快照。"""
    from app.ctob import TZ_SHANGHAI, load_snapshot

    token = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
    slot_text = _slot_text(hour, minute)
    expected_channels = set(_ctob_health_channels(hour, minute))
    problems: list[dict] = []
    run = _scheduled_run_status("ctob:db", f"{day}-{token}")
    if not run.get("found"):
        problems.append({"step": "ctob_run", "detail": "未找到 C转B 运行凭证"})
    elif run.get("status") != "sent":
        problems.append({
            "step": "ctob_run",
            "detail": f"状态 {run.get('status')} {run.get('detail') or ''}"[:200],
        })
    actual_channels = set(load_snapshot(day, hour, minute))
    if actual_channels != expected_channels:
        problems.append({
            "step": "ctob_snapshot",
            "detail": f"群快照 {len(actual_channels)} != 预期 {len(expected_channels)}",
        })
    report = {
        "date": day,
        "timezone": TZ_SHANGHAI,
        "hour": slot_text,
        "slot": slot_text,
        "ok": not problems,
        "problems": problems,
        "suggested_action": "人工核对 C转B 调度与机器人配置，必要时手动补跑该档" if problems else "",
        "checked_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds"),
    }
    if problems:
        detail = "; ".join(f"{item['step']}:{item['detail']}" for item in problems)[:280]
        if alert:
            notify("C转B 档位健康检查失败", f"{slot_text} {day} → {detail}")
        logger.error("ctob slot health FAILED {} {}: {}", slot_text, day, detail)
    else:
        logger.info("ctob slot health OK {} {}", slot_text, day)
    return report


def _health_hours(tz_name: str, default_slots: list[str]) -> list[int]:
    from app.duzhan_admin import runtime

    if runtime.using_db():
        return sorted({hour for agent, group in runtime.duzhan_agents()
                       if group.tz == tz_name for hour in runtime.slots_of(agent)})
    return parse_hours(default_slots)


def _health_slots(tz_name: str, default_slots: list[str]) -> list[str]:
    from app.duzhan_admin import runtime

    if runtime.using_db():
        return sorted({slot for agent, group in runtime.duzhan_agents()
                       if group.tz == tz_name for slot in runtime.slot_times_of(agent)})
    return [f"{hour:02d}:00" for hour in _health_hours(tz_name, default_slots)]


def _health_channels(tz_name: str, hour: int, minute: int = 0) -> list[str]:
    from app.duzhan_admin import runtime

    if runtime.using_db():
        slot = _slot_text(hour, minute)
        return sorted({group.channel_id for agent, group in runtime.duzhan_agents()
                       if group.tz == tz_name and slot in runtime.slot_times_of(agent)})
    return sorted({group.channel_id for group in groups_for_tz(tz_name)})


def _ctob_health_slots() -> list[str]:
    from app.duzhan_admin import runtime

    if not runtime.using_db():
        return []
    return sorted({
        slot
        for agent, _owner in runtime.follow_agents()
        for slot in runtime.slot_times_of(agent)
    })


def _ctob_health_channels(hour: int, minute: int = 0) -> list[str]:
    from app.duzhan_admin import runtime

    slot = _slot_text(hour, minute)
    return sorted({
        owner.channel_id
        for agent, owner in runtime.follow_agents()
        if slot in runtime.slot_times_of(agent)
    })


def _health_targets(settings) -> list[tuple[str, str, str]]:
    """返回（类型、时区、HH:MM），让 C 转 B 与督战群分别留健康凭证。"""
    from app.duzhan_admin import runtime

    targets: list[tuple[str, str, str]] = []
    if bool(getattr(settings, "duzhan_enabled", True)):
        for tz_name in cron_timezones():
            targets.extend(
                ("duzhan", tz_name, slot)
                for slot in _health_slots(tz_name, settings.duzhan_times)
            )
    if runtime.using_db() and bool(getattr(settings, "ctob_enabled", False)):
        targets.extend(("ctob", "Asia/Shanghai", slot) for slot in _ctob_health_slots())
    return targets


def scoped_slot_health(reports: list[dict], allowed_channels: set[str] | None) -> list[dict]:
    """Do not expose a shared-slot aggregate as a scoped group's own health."""
    if allowed_channels is None:
        return reports
    visible = []
    for report in reports:
        channels = set(report.get("channel_ids") or [])
        if not channels.intersection(allowed_channels):
            continue
        if channels.issubset(allowed_channels):
            visible.append(report)
        else:
            visible.append({
                "date": report["date"], "timezone": report["timezone"],
                "hour": report["hour"], "slot": report.get("slot") or report["hour"],
                "ok": None, "state": "partial", "problems": [],
                "suggested_action": "档位含无权群，无法单独判定本群健康",
                "checked_at": report["checked_at"],
            })
    return visible


def _slot_grace_ends(
    local: datetime, hour: int, minute: int, delay_minutes: int, *, day: str | None = None,
) -> datetime:
    target_day = local.date() if day is None else datetime.fromisoformat(day).date()
    return datetime(
        target_day.year, target_day.month, target_day.day, hour, minute,
        tzinfo=local.tzinfo,
    ) + timedelta(
        minutes=max(0, delay_minutes)
    )


def run_health_checks_for(now: datetime | None = None) -> list[dict]:
    """每 5 分钟扫描：补扫当天已过宽限期的档位。

    补扫语义：调度器/容器在整点前后重启也不会漏检——当天任何已到点的
    档位都会在下一个 5 分钟 tick 被检查。每个（时区, 日期, 档位）只告警
    一次（slot.health_checked 事件幂等去重）。只检查工作日档位。
    """
    from app.agents.events import write_event

    settings = get_settings()
    reports: list[dict] = []
    for kind, tz_name, slot in _health_targets(settings):
        try:
            zone = ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001
            continue
        local = (now or datetime.now(zone)).astimezone(zone)
        clock = split_time_slot(slot)
        if clock is None:
            continue
        hour, minute = clock
        today = local.date()
        previous = today - timedelta(days=1)
        slot_days = [today]
        previous_grace = _slot_grace_ends(
            local, hour, minute, settings.agent_healthcheck_delay_minutes,
            day=previous.isoformat(),
        )
        # 午夜后的短时重启窗口也交给 health_checked 事件去重。这样晚档
        # 尚无检查事件时会补扫，同时不会在次日白天重新翻查全部旧档。
        if local - previous_grace <= timedelta(hours=6):
            slot_days.insert(0, previous)
        for slot_day in slot_days:
            day = slot_day.isoformat()
            if not is_workday(day) or local < _slot_grace_ends(
                local, hour, minute, settings.agent_healthcheck_delay_minutes, day=day,
            ):
                continue  # 非推送日，或宽限期内推送可能尚未完成
            token = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
            kind_key = "" if kind == "duzhan" else f":{kind}"
            event_key = f"flow_controller:health_checked{kind_key}:{tz_name}:{day}:{token}"
            if not write_event("slot.health_checked", producer="flow_controller",
                               event_key=event_key,
                               payload={"kind": kind, "tz": tz_name, "day": day,
                                        "hour": hour, "minute": minute}):
                continue  # 本档今天已检查并告警过
            if kind == "ctob":
                reports.append(check_ctob_slot_health(
                    hour, day, minute=minute, now=local, alert=True,
                ))
            else:
                reports.append(check_slot_health(
                    tz_name, hour, day, minute=minute, now=local, alert=True,
                ))
    return reports


def all_slot_health_today(day: str, *, now: datetime | None = None) -> list[dict]:
    """给定日期全部时区/档位的健康状态（供后台展示，不告警）。"""
    settings = get_settings()
    reports = []
    for kind, tz_name, slot in _health_targets(settings):
        try:
            zone = ZoneInfo(tz_name)
        except Exception:  # noqa: BLE001 - invalid legacy timezone must not break the health page
            continue
        local = (now or datetime.now(zone)).astimezone(zone)
        local_day = local.strftime("%Y-%m-%d")
        clock = split_time_slot(slot)
        if clock is None:
            continue
        hour, minute = clock
        channels = (
            _ctob_health_channels(hour, minute)
            if kind == "ctob"
            else _health_channels(tz_name, hour, minute)
        )
        if day > local_day or (day == local_day and local < _slot_grace_ends(
            local, hour, minute, settings.agent_healthcheck_delay_minutes,
        )):
            reports.append({
                "date": day, "timezone": tz_name, "hour": slot, "slot": slot,
                "kind": kind, "ok": None, "state": "pending", "problems": [],
                "channel_ids": channels, "suggested_action": "",
                "checked_at": local.isoformat(timespec="seconds"),
            })
            continue
        if kind == "ctob":
            report = check_ctob_slot_health(
                hour, day, minute=minute, now=local, alert=False,
            )
        else:
            report = check_slot_health(
                tz_name, hour, day, minute=minute, now=local, expect_push=True, alert=False,
            )
        report["kind"] = kind
        report["state"] = "passed" if report["ok"] else "failed"
        report["channel_ids"] = channels
        reports.append(report)
    return reports
