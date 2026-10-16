# -*- coding: utf-8 -*-
"""配置 → 运行时（code / db 双源）。

- `code`：维持现状，群清单写死在 `app.duzhan.GROUPS` / `app.ctob.OWNERS`。
- `db`：读 `duzhan_agents` 里 **启用** 的子 Agent，一个子 Agent 一个群，
  按时区和档位合并注册调度，避免同档重复采集与并发推送。

这一层只做「翻译 + 注册」，不取数、不推送；真正发送仍走现有
`run_duzhan` / `run_ctob`（复用同一套渲染器）。
"""
from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.duzhan import TZ_SHANGHAI, DuzhanGroup, parse_hours
from app.duzhan_blocks import Block, as_str_list, normalize_time_slot, parse_blocks, split_time_slot
from app.models.duzhan_agent import DuzhanAgent

CONFIG_SOURCE_CODE = "code"
CONFIG_SOURCE_DB = "db"


def config_source() -> str:
    """当前配置来源：code | db（认不出来的值一律当 code，宁可维持现状）。"""
    try:
        from app.config import get_settings

        value = str(getattr(get_settings(), "duzhan_config_source", CONFIG_SOURCE_CODE) or "").strip().lower()
    except Exception:  # noqa: BLE001 — 配置没起来时按现状走
        value = ""
    return value if value in {CONFIG_SOURCE_CODE, CONFIG_SOURCE_DB} else CONFIG_SOURCE_CODE


def using_db() -> bool:
    return config_source() == CONFIG_SOURCE_DB


def load_enabled_agents() -> list[DuzhanAgent]:
    """读启用的子 Agent；库不可用时不抛异常，返回空并告警。"""
    try:
        from app.database import get_engine

        with Session(get_engine()) as session:
            statement = select(DuzhanAgent).where(DuzhanAgent.enabled == True).order_by(DuzhanAgent.id)  # noqa: E712
            return list(session.exec(statement).all())
    except Exception as exc:  # noqa: BLE001 — 配置表读不到不该拖垮整个调度
        logger.warning("读取督战官配置失败，本轮按空配置处理: {}", exc)
        return []


def _blocks(agent: DuzhanAgent) -> list[Block]:
    return parse_blocks(agent.blocks_json)


def _first(blocks: list[Block], kind: str) -> Optional[Block]:
    return next((block for block in blocks if block.type == kind), None)


def group_of(agent: DuzhanAgent) -> Optional[DuzhanGroup]:
    """子 Agent → 督战群（群名 / 群 ID / 语言 / 时区）。"""
    blocks = _blocks(agent)
    group = _first(blocks, "group")
    if group is None:
        return None
    channel_id = str(group.get("channel_id") or "").strip()
    if not channel_id:
        return None
    style = _first(blocks, "style")
    lang = str(style.get("lang") or "zh").strip() if style else "zh"
    from app.duzhan_admin.service import supported_channel_labels

    label = supported_channel_labels().get(channel_id)
    label = label or str(group.get("label") or "").strip() or agent.name
    from app.ctob import OWNERS as CTOB_OWNERS

    is_ctob = any(owner.channel_id == channel_id for owner in CTOB_OWNERS)
    tz_name = TZ_SHANGHAI if is_ctob else (str(agent.timezone or "").strip() or TZ_SHANGHAI)
    return DuzhanGroup(name=label, channel_id=channel_id, lang=lang, tz=tz_name)


def slots_of(agent: DuzhanAgent) -> list[int]:
    """兼容旧调用：返回配置时刻涉及的小时。"""
    hours: list[int] = []
    for slot in slot_times_of(agent):
        hour = int(slot[:2])
        if hour not in hours:
            hours.append(hour)
    return hours


def slot_times_of(agent: DuzhanAgent) -> list[str]:
    """返回去重后的规范 HH:MM 时刻，保留用户顺序。"""
    times = _first(_blocks(agent), "times")
    if times is None:
        return []
    slots: list[str] = []
    for raw in as_str_list(times.get("slots")):
        slot = normalize_time_slot(raw)
        if slot is not None and slot not in slots:
            slots.append(slot)
    return slots


def previous_slot_in(slots: list[str], current_slot: str) -> tuple[int, str] | None:
    """返回一组发送时刻里的上一档；首档回到前一天末档。"""
    slots = sorted(dict.fromkeys(slots))
    if current_slot not in slots or len(slots) < 2:
        return None
    index = slots.index(current_slot)
    return (0, slots[index - 1]) if index else (-1, slots[-1])


def previous_slot_of(agent: DuzhanAgent, current_slot: str) -> tuple[int, str] | None:
    """返回同一 Agent 的上一发送时刻；首档回到前一天末档。"""
    return previous_slot_in(slot_times_of(agent), current_slot)


def conditions_allow(agent: DuzhanAgent, day: str, ledger: dict | None) -> bool:
    """发送前检查条件块；数据不可用时不把它当成「没有数据」。"""
    from app.ctob import OWNERS as CTOB_OWNERS
    from app.duzhan_ledger import people_for
    from app.workday_calendar import day_kind

    group = group_of(agent)
    if group is None:
        return False
    is_ctob = any(owner.channel_id == group.channel_id for owner in CTOB_OWNERS)
    kind = day_kind(day)
    observed_keys = (
        "mtd_wan", "wa_reached", "intent_count", "mto_count", "vps_im_sent",
        "daily_report", "vemory", "collections", "evidence", "perf_slip", "perf_intent",
    )

    def observed(row: dict) -> bool:
        return any(
            value is not None and (bool(value) if isinstance(value, (str, list, dict)) else True)
            for value in (row.get(field) for field in observed_keys)
        )

    for block in _blocks(agent):
        if block.type != "condition":
            continue
        key = str(block.get("key") or "")
        expected = block.get("value") is True
        if key == "workday":
            actual = kind in {"workday", "makeup"}
        elif key == "holiday":
            actual = kind == "long_holiday"
        elif key == "has_data":
            if not expected or not isinstance(ledger, dict) or ledger.get("_collection_failed"):
                return False
            if is_ctob:
                actual = bool(ledger.get("chats")) or bool((ledger.get("cohort") or {}).get("rows")) or any(
                    (ledger.get("summary") or {}).get(key) is not None
                    for key in ("reached", "replied", "outbound", "inbound", "new", "complete")
                ) or any(
                    (ledger.get("cohort") or {}).get(key) is not None
                    for key in ("new", "chatted", "replied", "intent")
                )
            else:
                actual = any(observed(row) for row in people_for(group.name, ledger))
        else:
            return False
        if actual != expected:
            return False
    return True


def conditions_allow_channel(channel_id: str, day: str, ledger: dict | None) -> bool:
    """按启用的群配置检查发送条件。找不到配置时不发送。"""
    for agent in load_enabled_agents():
        group = group_of(agent)
        if group and group.channel_id == channel_id:
            return conditions_allow(agent, day, ledger)
    return False


def _follow_owners_by_channel() -> dict:
    from app.ctob import OWNERS as FOLLOW_OWNERS

    return {owner.channel_id: owner for owner in FOLLOW_OWNERS}


def duzhan_agents() -> list[tuple[DuzhanAgent, DuzhanGroup]]:
    """启用、合法、且不是跟进群的子 Agent。"""
    follow_channels = set(_follow_owners_by_channel())
    picked: list[tuple[DuzhanAgent, DuzhanGroup]] = []
    for agent in load_enabled_agents():
        group = group_of(agent)
        if group is None:
            logger.warning("子 Agent #{} {} 缺少可用的 group 块，跳过注册", agent.id, agent.name)
            continue
        if group.channel_id in follow_channels:
            continue
        if not slot_times_of(agent):
            logger.warning("子 Agent #{} {} 没有可用发送时间，跳过注册", agent.id, agent.name)
            continue
        picked.append((agent, group))
    return picked


def groups_for_tz(tz_name: str) -> list[DuzhanGroup]:
    """db 源：该时区下所有启用子 Agent 的群。"""
    return [group for _agent, group in duzhan_agents() if group.tz == tz_name]


def cron_timezones() -> list[str]:
    seen: list[str] = []
    for _agent, group in duzhan_agents():
        if group.tz not in seen:
            seen.append(group.tz)
    return seen


def follow_agents() -> list[tuple[DuzhanAgent, object]]:
    """启用且指向跟进群（C转B）的子 Agent，配对现有的跟进群负责人。"""
    by_channel = _follow_owners_by_channel()
    picked: list[tuple[DuzhanAgent, object]] = []
    for agent in load_enabled_agents():
        group = group_of(agent)
        if group is None:
            continue
        owner = by_channel.get(group.channel_id)
        if owner is None:
            continue
        if not slot_times_of(agent):
            logger.warning("跟进群子 Agent #{} {} 没有可用档位，跳过注册", agent.id, agent.name)
            continue
        picked.append((agent, owner))
    return picked


def register_agent_jobs(
    scheduler, *, duzhan_enabled: bool = True, ctob_enabled: bool = True,
) -> list[dict]:
    """db 源：同一时区、同一档位合并采集和推送，返回群注册清单。"""
    from zoneinfo import ZoneInfo

    from app.config import get_settings
    from app.duzhan import collect_clock
    from app.scheduler.jobs import ctob_job, duzhan_collect_job, duzhan_job

    lead = int(getattr(get_settings(), "duzhan_lead_minutes", 15) or 15)
    registered: list[dict] = []
    duzhan_slots: dict[tuple[str, str], list[str]] = {}

    if duzhan_enabled:
        for agent, group in duzhan_agents():
            slots = slot_times_of(agent)
            for slot in slots:
                duzhan_slots.setdefault((group.tz, slot), []).append(group.channel_id)
            registered.append(
                {
                    "kind": "duzhan",
                    "agent_id": agent.id,
                    "name": agent.name,
                    "channel_id": group.channel_id,
                    "timezone": group.tz,
                    "slots": slots,
                }
            )

    for (tz_name, slot), channel_ids in duzhan_slots.items():
        clock = split_time_slot(slot)
        if clock is None:  # 已由 slot_times_of 过滤，防御性保护
            continue
        hour, minute = clock
        zone = ZoneInfo(tz_name)
        slug = tz_name.lower().replace("/", "_")
        slot_slug = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
        collect_hour, collect_minute = collect_clock(hour, lead, minute)
        backup_hour, backup_minute = collect_clock(hour, -30, minute)
        scheduler.add_job(
            duzhan_collect_job,
            args=[tz_name, hour],
            kwargs={
                "minute": minute,
                "trigger_offset_minutes": -lead,
                "ledger_job": f"duzhan_collect:db:{tz_name}",
                "channel_ids": channel_ids,
            },
            trigger="cron",
            hour=collect_hour,
            minute=collect_minute,
            day_of_week="mon-sun",
            timezone=zone,
            id=f"duzhan_collect_{slug}_{slot_slug}",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        push_kwargs = {
            "minute": minute,
            "ledger_job": f"duzhan_push:db:{tz_name}",
            "channel_ids": channel_ids,
        }
        for job_id, job_hour, job_minute, trigger_offset in (
            (f"duzhan_{slug}_{slot_slug}", hour, minute, 0),
            (f"duzhan_backup_{slug}_{slot_slug}", backup_hour, backup_minute, 30),
        ):
            scheduler.add_job(
                duzhan_job,
                args=[tz_name, hour],
                kwargs={**push_kwargs, "trigger_offset_minutes": trigger_offset},
                trigger="cron",
                hour=job_hour,
                minute=job_minute,
                day_of_week="mon-sun",
                timezone=zone,
                id=job_id,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )

    follow_slots: dict[str, list[object]] = {}
    if ctob_enabled:
        for agent, owner in follow_agents():
            slots = slot_times_of(agent)
            for slot in slots:
                follow_slots.setdefault(slot, []).append(owner)
            registered.append(
                {
                    "kind": "follow",
                    "agent_id": agent.id,
                    "name": agent.name,
                    "channel_id": owner.channel_id,
                    "timezone": TZ_SHANGHAI,
                    "slots": slots,
                }
            )

    for slot, owners in follow_slots.items():
        clock = split_time_slot(slot)
        if clock is None:
            continue
        hour, minute = clock
        slot_slug = f"{hour:02d}" if minute == 0 else f"{hour:02d}{minute:02d}"
        backup_hour, backup_minute = collect_clock(hour, -30, minute)
        kwargs = {"minute": minute, "owners": tuple(owners), "ledger_job": "ctob:db"}
        for job_id, job_hour, job_minute, trigger_offset in (
            (f"ctob_db_{slot_slug}", hour, minute, 0),
            (f"ctob_db_backup_{slot_slug}", backup_hour, backup_minute, 30),
        ):
            scheduler.add_job(
                ctob_job,
                args=[hour],
                kwargs={**kwargs, "trigger_offset_minutes": trigger_offset},
                trigger="cron",
                hour=job_hour,
                minute=job_minute,
                day_of_week="mon-sun",
                timezone=ZoneInfo(TZ_SHANGHAI),
                id=job_id,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=3600,
            )

    if not registered:
        logger.warning(
            "督战官配置源=db，但库里没有可注册的启用子 Agent：本次不会注册任何督战推送。"
            "若不是本意，请检查配置页，或把 PDCA_DUZHAN_CONFIG_SOURCE 切回 code。"
        )
    for row in registered:
        logger.info(
            "督战官注册【{}】{} → {}（{}，档位 {}）",
            row["kind"], row["name"], row["channel_id"], row["timezone"], row["slots"],
        )
    return registered

