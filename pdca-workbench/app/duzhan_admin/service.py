# -*- coding: utf-8 -*-
"""督战官子 Agent 配置服务层：解析、校验、结构试跑、从代码导入。

这一层**不取数、不推送**：试跑只把配置翻译成「运行时打算怎么做」。
真正按配置发送要等运行接管（调度从库注册）之后。
"""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger
from sqlmodel import Session, select

from app.duzhan_blocks import (
    CONDITION_KEYS,
    SOURCE_KEYS,
    Block,
    as_str_list,
    blocks_dict,
    dump_blocks,
    normalize_time_slot,
    parse_blocks,
    split_time_slot,
    validate_blocks,
)
from app.models.duzhan_agent import DuzhanAgent

RENDERER_DUZHAN = "duzhan.render_brief"
RENDERER_CTOB = "ctob.render_brief"

PREVIEW_NOTE = "结构试跑：只解析配置与校验，不取数、不发消息。"


def blocks_of(agent: DuzhanAgent) -> list[Block]:
    """读出积木列表（坏 JSON 按空配置处理）。"""
    return parse_blocks(agent.blocks_json)


def roster_by_group() -> dict[str, list[str]]:
    """达标群 → 完整待办、闭环和部门业绩名单。"""
    from app.duzhan_departments import DEPARTMENTS

    return {department.group: list(department.members) for department in DEPARTMENTS}


def department_rosters(*, task_only: bool = False) -> dict[str, list[str]]:
    """按真实群 ID 提供完整名单或仅追待办名单。"""
    from app.duzhan import GROUPS
    from app.duzhan_departments import department_for

    return {group.channel_id: list(department.task_only_members if task_only else department.members)
            for group in GROUPS if (department := department_for(group.name)) is not None}


def _department_members(blocks: list[Block], *, task_only: bool = False) -> list[str]:
    rosters = department_rosters(task_only=task_only)
    return next((rosters[str(block.get("channel_id"))] for block in blocks
                 if block.type == "group" and str(block.get("channel_id")) in rosters), [])


def roster_names() -> list[str]:
    """督战名单：达标群成员 + C转B 群主。

    C转B 群主只在 ctob.OWNERS 里，不在 duzhan_ledger 里；不并进来，导入的
    C转B 配置会全部被判「不在督战名单内」而无法启用。
    """
    names = [name for names in roster_by_group().values() for name in names]
    from app.ctob import OWNERS as CTOB_OWNERS

    for owner in CTOB_OWNERS:
        if owner.display and owner.display not in names:
            names.append(owner.display)
    return names


def supported_channel_labels() -> dict[str, str]:
    """channel_id → 固定业务群名；展示名不能改变取数归属。"""
    from app.ctob import OWNERS as CTOB_OWNERS
    from app.duzhan import GROUPS

    labels = {group.channel_id: group.name for group in GROUPS}
    labels.update({
        owner.channel_id: f"{owner.display}C转B跟进群"
        for owner in CTOB_OWNERS
    })
    return labels


def supported_channel_ids() -> list[str]:
    """当前已接入取数和闭环判断的达标群、C 转 B 群。"""
    return list(supported_channel_labels())


def strategy_ids() -> list[str]:
    """当前在查的策略 id（运行时文件优先）。"""
    try:
        from app.strategy_wa_brief import load_strategies

        return [item.id for item in load_strategies()[0]]
    except Exception as exc:  # noqa: BLE001 — 策略文件坏掉不该挡住配置页
        logger.warning("读取策略清单失败，跳过策略校验: {}", exc)
        return []


def owners_for(blocks: list[Block]) -> Optional[list[str]]:
    """按 channel_id 固定的业务群取名单；展示名不参与数据归属。"""
    table = roster_by_group()
    labels = supported_channel_labels()
    picked: list[str] = []
    for block in blocks:
        if block.type != "group":
            continue
        channel_id = str(block.get("channel_id") or "")
        label = labels.get(channel_id, str(block.get("label") or ""))
        picked.extend(table.get(label, []))
    picked = picked or roster_names()
    return picked or None


def validate_agent(
    agent: DuzhanAgent,
    *,
    owners: Optional[list[str]] = None,
    strategies: Optional[list[str]] = None,
) -> list[str]:
    """校验一个子 Agent 的配置，返回错误列表（不抛异常）。"""
    blocks = blocks_of(agent)
    errors = validate_blocks(
        blocks,
        owners=owners_for(blocks) if owners is None else owners,
        strategies=strategy_ids() if strategies is None else strategies,
    )
    members = _department_members(blocks)
    selected = _people_of(blocks)
    if members and selected and set(selected) != set(members):
        errors.append(f"按部门汇总需覆盖完整部门名单：{'、'.join(members)}；请使用全体部门成员或留空")
    from app.ctob import OWNERS as CTOB_OWNERS

    ctob_channels = {owner.channel_id for owner in CTOB_OWNERS}
    is_ctob = any(block.type == "group" and block.get("channel_id") in ctob_channels for block in blocks)
    if is_ctob:
        if any(block.type == "rule" and block.get("when") == "missing_report" for block in blocks):
            errors.append("C转B 跟进群没有日报字段，不能使用「未交日报」动作条件")
        if (agent.timezone or "Asia/Shanghai").strip() != "Asia/Shanghai":
            errors.append("C转B 跟进群仅支持 Asia/Shanghai 时区")
    supported = set(supported_channel_ids())
    for block in blocks:
        channel_id = str(block.get("channel_id") or "") if block.type == "group" else ""
        if channel_id and channel_id not in supported:
            errors.append("目标群尚未接入闭环采集，请选择系统已接入的督战群")
    return errors


def _slots_of(blocks: list[Block]) -> list[str]:
    times = next((block for block in blocks if block.type == "times"), None)
    return as_str_list(times.get("slots")) if times else []


def _people_of(blocks: list[Block]) -> list[str]:
    people = next((block for block in blocks if block.type == "people"), None)
    return as_str_list(people.get("names")) if people else []


def _style_of(blocks: list[Block]) -> dict:
    style = next((block for block in blocks if block.type == "style"), None)
    return {
        "lang": str(style.get("lang") or "zh") if style else "zh",
        "title": str(style.get("title") or "") if style else "",
        "footer": str(style.get("footer") or "") if style else "",
    }


def renderer_for(blocks: list[Block]) -> str:
    """这份配置会走哪个渲染器：群在 C转B 名单里走 ctob，否则走达标群。"""
    from app.ctob import OWNERS as CTOB_OWNERS

    ctob_channels = {owner.channel_id for owner in CTOB_OWNERS}
    for block in blocks:
        if block.type == "group" and str(block.get("channel_id") or "") in ctob_channels:
            return RENDERER_CTOB
    return RENDERER_DUZHAN


def resolve_spec(agent: DuzhanAgent) -> dict:
    """配置 → 运行时结构（不含任何实时数据）。"""
    blocks = blocks_of(agent)
    style = _style_of(blocks)
    rules: list[dict] = []
    for block in blocks:
        if block.type != "rule":
            continue
        mode = str(block.get("mode") or "text")
        rules.append(
            {
                "mode": mode,
                "when": str(block.get("when") or "always"),
                "text": str(block.get("text") or "") if mode == "text" else "",
                "prompt": str(block.get("prompt") or "") if mode == "ai" else "",
            }
        )
    renderer = renderer_for(blocks)
    members = _department_members(blocks)
    timezone_name = "Asia/Shanghai" if renderer == RENDERER_CTOB else (agent.timezone or "Asia/Shanghai")
    return {
        "id": agent.id,
        "name": agent.name,
        "enabled": bool(agent.enabled),
        "timezone": timezone_name,
        "groups": [
            {"channel_id": str(block.get("channel_id") or ""), "label": str(block.get("label") or "")}
            for block in blocks
            if block.type == "group"
        ],
        "slots": _slots_of(blocks),
        "people": members or _people_of(blocks),
        "task_only_people": _department_members(blocks, task_only=True),
        "department_report": bool(members),
        "sources": [str(block.get("key") or "") for block in blocks if block.type == "source"],
        "rules": rules,
        "conditions": [
            {"key": str(block.get("key") or ""), "value": block.get("value") is True}
            for block in blocks
            if block.type == "condition"
        ],
        "recipients": [
            {"kind": str(block.get("kind") or ""), "id": str(block.get("id") or "")}
            for block in blocks
            if block.type == "recipient"
        ],
        "strategies": [
            {"id": str(block.get("id") or ""), "until": str(block.get("until") or "")}
            for block in blocks
            if block.type == "strategy"
        ],
        "lang": style["lang"],
        "title": style["title"],
        "footer": style["footer"],
        "renderer": renderer,
    }


def _summary_lines(
    spec: dict, day: Optional[str], hour: Optional[int], slot: Optional[str] = None,
) -> list[str]:
    """把结构翻成给人看的一行行说明（配置页「试跑」直接展示这些）。"""
    lines: list[str] = []
    for group in spec["groups"]:
        label = group["label"] or "(未命名群)"
        lines.append(f"发送到：{label}（{group['channel_id'] or '缺 channel_id'}）")
    slots = list(spec["slots"])
    if slot is not None:
        picked = [item for item in slots if item == slot]
        slots = picked or slots
    elif hour is not None:
        picked = [slot for slot in slots if slot.split(":")[0].lstrip("0") == str(hour)]
        slots = picked or slots
    lines.append(f"档位：{'、'.join(slots) or '未配置'}（{spec['timezone']}）")
    if day:
        lines.append(f"试跑日期：{day}")
    prefix = "部门成员（当前督战，每时段合并一条）" if spec["department_report"] else "覆盖人员"
    lines.append(f"{prefix}：{'、'.join(spec['people']) if spec['people'] else '该群全员（未限定）'}")
    if spec["task_only_people"]:
        lines.append("仅追待办与闭环（业绩计入部门，不追MTO等销售专项）：" + "、".join(spec["task_only_people"]))
    lines.append(
        "数据源："
        + (" → ".join(SOURCE_KEYS.get(key, key) for key in spec["sources"]) if spec["sources"] else "未配置")
    )
    for rule in spec["rules"]:
        body = rule["text"] or f"AI 生成：{rule['prompt']}"
        lines.append(f"规则（{rule['when']}）：{body}")
    for condition in spec["conditions"]:
        key = CONDITION_KEYS.get(condition["key"], condition["key"])
        lines.append(f"触发条件：{key} = {'是' if condition['value'] else '否'}")
    for recipient in spec["recipients"]:
        lines.append(f"额外收件人：{recipient['kind']} {recipient['id']}")
    for strategy in spec["strategies"]:
        tail = f"（到 {strategy['until']}）" if strategy["until"] else ""
        lines.append(f"策略核查：{strategy['id']}{tail}")
    lines.append(f"渲染器：{spec['renderer']}")
    return lines


def preview_agent(
    agent: DuzhanAgent, *, day: Optional[str] = None, hour: Optional[int] = None,
    slot: Optional[str] = None,
) -> dict:
    """结构试跑：配置能解析成什么、有没有错、到点会怎么发。"""
    spec = resolve_spec(agent)
    errors = validate_agent(agent)
    return {
        "agent": {"id": agent.id, "name": agent.name, "enabled": bool(agent.enabled)},
        "day": day,
        "hour": hour,
        "slot": slot,
        "errors": errors,
        "spec": spec,
        "summary": _summary_lines(spec, day, hour, slot),
        "note": PREVIEW_NOTE,
    }


def _pick_slot(
    agent: DuzhanAgent, slot: Optional[str], hour: Optional[int], now,
) -> tuple[str, int, int]:
    """选指定时刻；未指定时取最近已到点时刻，否则取第一档。"""
    from app.duzhan_admin import runtime

    slots = runtime.slot_times_of(agent) or ["10:00", "15:00", "20:00"]
    requested = normalize_time_slot(slot) if slot else None
    if requested not in slots:
        requested = next((item for item in slots if hour is not None and int(item[:2]) == hour), None)
    if requested is None:
        current = now.strftime("%H:%M")
        passed = [item for item in slots if item <= current]
        requested = passed[-1] if passed else slots[0]
    clock = split_time_slot(requested)
    if clock is None:
        return "10:00", 10, 0
    return requested, clock[0], clock[1]


def _with_preview_agent(rows: list[tuple], agent: DuzhanAgent, target: object) -> list[tuple]:
    """试跑始终按当前卡片解析，即使它尚未启用。"""
    channel_id = getattr(target, "channel_id", "")
    return [
        (row, item) for row, item in rows
        if getattr(item, "channel_id", "") != channel_id
    ] + [(agent, target)]


def render_preview(
    agent: DuzhanAgent, *, day: Optional[str] = None, hour: Optional[int] = None,
    slot: Optional[str] = None,
) -> dict:
    """用已保存卡片和已有快照台账试跑；不取数、不发送。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app import ctob as ctob_module
    from app import duzhan as duzhan_module
    from app.duzhan_admin import ai_rules, runtime
    from app.duzhan_ledger import empty_ledger
    from app.workday_calendar import is_workday

    group = runtime.group_of(agent)
    if group is None:
        return {
            "mode": "render", "ok": False, "error": "配置里没有可用的 group 块",
            "day": day, "hour": hour, "slot": slot,
        }

    tz_name = group.tz
    now = datetime.now(ZoneInfo(tz_name))
    day = day or now.strftime("%Y-%m-%d")
    slot, hour, minute = _pick_slot(agent, slot, hour, now)
    render_time = datetime.strptime(day, "%Y-%m-%d").replace(
        hour=hour, minute=minute, tzinfo=ZoneInfo(tz_name),
    )

    owner = next((item for item in ctob_module.OWNERS if item.channel_id == group.channel_id), None)

    if owner is not None:
        # 跟进群：快照在 app.ctob 那边，按群存
        collected = ctob_module.load_snapshot(day, hour, minute) or {}
        data = collected.get(group.channel_id) or {"summary": {}, "chats": [], "cohort": {}}
        active_follow = _with_preview_agent(
            runtime.follow_agents() if runtime.using_db() else [], agent, owner,
        )
        prev_data = ctob_module._previous_snapshot_for_owner(  # noqa: SLF001
            day, hour, minute, group.channel_id, active_follow,
        )
        previous_slot = ctob_module._previous_slot_label(  # noqa: SLF001
            prev_data, configured=True,
        )
        override = ai_rules.focus_for_agent(
            agent, group, hour, day, data, minute=minute, preview=True,
        )
        body = ctob_module.render_brief(
            owner, day, data["summary"], data["chats"], data["cohort"],
            hour=hour, prev=prev_data, minute=minute,
            previous_slot=previous_slot, focus_override=override,
        )
        source = "snapshot" if group.channel_id in collected else "empty_ledger"
        renderer = "ctob.render_brief"
        message_count = 1
        condition_data = data
    else:
        # 达标群：只复用台账，始终用当前卡片重渲染，避免展示旧快照里的旧规则。
        active = _with_preview_agent(
            runtime.duzhan_agents() if runtime.using_db() else [], agent, group,
        )

        def slot_key_for(slot_value: str) -> str:
            channels = [item.channel_id for row, item in active
                        if item.tz == tz_name and slot_value in runtime.slot_times_of(row)]
            return (duzhan_module._slot_key(channels) if group.channel_id in channels
                    else group.channel_id[:8])

        slot_key = slot_key_for(slot)
        if minute:
            snapshot = duzhan_module.load_prepared(
                tz_name, hour, day, slot_key, minute,
            ) or duzhan_module.load_prepared(tz_name, hour, day, minute=minute)
        else:
            snapshot = duzhan_module.load_prepared(
                tz_name, hour, day, slot_key,
            ) or duzhan_module.load_prepared(tz_name, hour, day)
        ledger = snapshot.get("ledger") if isinstance(snapshot, dict) else None
        prev = duzhan_module._previous_prepared_for_group(  # noqa: SLF001
            tz_name, day, hour, minute, group.channel_id, active,
        )
        prev_ledger = prev.get("ledger") if isinstance(prev, dict) else None
        previous_slot = duzhan_module._previous_slot_label(  # noqa: SLF001
            prev, configured=True,
        )
        use_ledger, source = (ledger, "snapshot_ledger") if isinstance(ledger, dict) else (empty_ledger(day), "empty_ledger")
        override = ai_rules.focus_for_agent(
            agent, group, hour, day, use_ledger, minute=minute, preview=True,
        )
        parts = duzhan_module.render_person_briefs(
            group, hour, render_time, use_ledger, prev_ledger,
            minute=minute, previous_slot=previous_slot, focus_override=override,
        )
        body = "\n\n────────\n\n".join(str(part.get("text") or "") for part in parts)
        message_count = len(parts)
        condition_data = use_ledger if isinstance(ledger, dict) else None
        renderer = "duzhan.render_brief"

    send_allowed = is_workday(day) and runtime.conditions_allow(agent, day, condition_data)
    notes = {
        "snapshot": "按本档跟进快照和当前卡片渲染。",
        "snapshot_ledger": "按本档快照台账和当前卡片重新渲染；每条以横线分隔。",
        "empty_ledger": "本档尚无快照；按空台账和当前卡片渲染，数字显示待确认。",
    }
    return {
        "mode": "render",
        "ok": True,
        "agent": {"id": agent.id, "name": agent.name, "enabled": bool(agent.enabled)},
        "day": day,
        "hour": hour,
        "slot": slot,
        "timezone": tz_name,
        "channel_id": group.channel_id,
        "group": group.name,
        "renderer": renderer,
        "source": source,
        "send_allowed": send_allowed,
        "send_reason": "非督战推送日" if not is_workday(day) else ("发送条件未满足" if not send_allowed else "卡片条件满足"),
        "message_count": message_count,
        "chars": len(body),
        "body": body,
        "note": notes.get(source, ""),
    }


def agent_out(agent: DuzhanAgent) -> dict:
    """接口返回体：配置 + 当前错误（前端据此禁掉「启用」）。"""
    blocks = blocks_of(agent)
    return {
        "id": agent.id,
        "name": agent.name,
        "enabled": bool(agent.enabled),
        "timezone": agent.timezone,
        "note": agent.note,
        "blocks": blocks_dict(blocks),
        "errors": validate_agent(agent),
        "renderer": renderer_for(blocks),
        "updated_at": agent.updated_at.isoformat() if agent.updated_at else "",
    }


def _seed_blocks(
    *,
    channel_id: str,
    label: str,
    lang: str,
    slots: list[str],
    people: list[str],
    sources: list[str],
) -> dict:
    blocks: list[dict] = [
        {"type": "group", "channel_id": channel_id, "label": label},
        {"type": "times", "slots": slots},
    ]
    if people:
        blocks.append({"type": "people", "names": people})
    for key in sources:
        blocks.append({"type": "source", "key": key})
    blocks.append({"type": "style", "lang": lang, "title": label})
    return {"blocks": blocks}


#: 达标群现有取数节：业绩 / MTO 报价图 / VPS 留痕 / 日报 / 会议
DUZHAN_SEED_SOURCES = ["wa_summary", "mto_ocr", "im_trace", "daily_report", "vemory"]
#: C转B 群现有取数节：WhatsApp 日汇总
CTOB_SEED_SOURCES = ["wa_summary"]


def configure_departments(session: Session, *, apply: bool = False) -> list[dict]:
    """Preview/apply one atomic cohort update; preserve card rules, slots and enabled state."""
    import json
    from datetime import datetime, timezone
    from app.duzhan import GROUPS
    from app.duzhan_departments import department_for

    cards = list(session.exec(select(DuzhanAgent).with_for_update()).all())
    plans = []
    for group in GROUPS:
        department = department_for(group.name)
        matching = [card for card in cards if any(
            block.type == "group" and block.get("channel_id") == group.channel_id
            for block in blocks_of(card)
        )]
        if len(matching) != 1:
            raise ValueError(f"{department.name} 必须恰有一张现有群配置，当前 {len(matching)} 张")
        card = matching[0]
        name = f"{department.name}督战官"
        if any(other.id != card.id and other.name == name for other in cards):
            raise ValueError(f"配置名称已被其他群使用：{name}")
        payload = json.loads(card.blocks_json)
        people = next((block for block in payload["blocks"] if block.get("type") == "people"), None)
        if people is None:
            payload["blocks"].insert(2, {"type": "people", "names": list(department.members)})
        else:
            people["names"] = list(department.members)
        blocks_json = json.dumps(payload, ensure_ascii=False)
        candidate = card.model_copy(update={"name": name, "blocks_json": blocks_json})
        errors = validate_agent(candidate)
        if errors:
            raise ValueError(f"{department.name} 配置校验失败：{'；'.join(errors)}")
        if card.name != name or json.loads(card.blocks_json) != payload:
            plans.append((card, name, blocks_json, department))
    result = [{"id": card.id, "before": card.name, "after": name,
               "members": list(department.members), "enabled": card.enabled}
              for card, name, _blocks, department in plans]
    if apply:
        for card, name, blocks_json, _department in plans:
            card.name, card.blocks_json = name, blocks_json
            card.updated_at = datetime.now(timezone.utc)
            session.add(card)
        session.commit()
    return result


def seed_from_code(session: Session) -> dict:
    """把现在硬编码的群导成配置；一律 **默认停用**，避免导入即双跑。"""
    from app.config import get_settings
    from app.ctob import OWNERS as CTOB_OWNERS
    from app.duzhan import GROUPS
    from app.duzhan_departments import department_for

    settings = get_settings()
    duzhan_slots = list(getattr(settings, "duzhan_times", None) or ["10:00", "15:00", "20:00"])
    ctob_slots = list(getattr(settings, "ctob_times", None) or duzhan_slots)
    groups = roster_by_group()

    plans: list[dict[str, Any]] = []
    for group in GROUPS:
        plans.append(
            {
                "name": f"{department_for(group.name).name}督战官",
                "timezone": group.tz,
                "blocks": _seed_blocks(
                    channel_id=group.channel_id,
                    label=group.name,
                    lang=group.lang,
                    slots=duzhan_slots,
                    people=groups.get(group.name, []),
                    sources=DUZHAN_SEED_SOURCES,
                ),
            }
        )
    for owner in CTOB_OWNERS:
        plans.append(
            {
                "name": f"{owner.display}C转B跟进群督战官",
                "timezone": "Asia/Shanghai",
                "blocks": _seed_blocks(
                    channel_id=owner.channel_id,
                    label=f"{owner.display}C转B跟进群",
                    lang="zh",
                    slots=ctob_slots,
                    people=[owner.display],
                    sources=CTOB_SEED_SOURCES,
                ),
            }
        )

    existing_rows = list(session.exec(select(DuzhanAgent)).all())
    existing = {row.name for row in existing_rows}
    existing_channels = {str(block.get("channel_id") or "") for row in existing_rows
                         for block in blocks_of(row) if block.type == "group"}
    created: list[DuzhanAgent] = []
    skipped: list[str] = []
    for plan in plans:
        channel = next(block["channel_id"] for block in plan["blocks"]["blocks"] if block["type"] == "group")
        if plan["name"] in existing or channel in existing_channels:
            skipped.append(plan["name"])
            continue
        row = DuzhanAgent(
            name=plan["name"],
            enabled=False,
            timezone=plan["timezone"],
            blocks_json=dump_blocks(parse_blocks(plan["blocks"])),
            note="从代码导入（默认停用，核对后再启用）",
        )
        session.add(row)
        created.append(row)
    session.commit()
    for row in created:
        session.refresh(row)
    logger.info("从代码导入督战官配置：新增 {}，跳过 {}", len(created), len(skipped))
    return {"created": [agent_out(row) for row in created], "skipped": skipped}
