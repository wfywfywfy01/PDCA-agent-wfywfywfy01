# -*- coding: utf-8 -*-
"""海外渠道日报群总结（每天 08:00，前 24 小时，总分结构）。

结构：大部门（海外事业部）→ 小部门（各小组/群）→ 个人明细 → 明日预告 → 卡点。
口径与三追一致：到账（系统已录单）/ 水单（已付款未到账）/ 意向（明确意向额）；
读不出写“待确认”，绝不用 0 冒充。推送复用日报群机器人身份（todos.service）。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from loguru import logger

from app.config import get_settings
from app.duzhan_ledger import RATE_CNY, TODAY_SLOGAN, collect_ledger

TZ_SHANGHAI = "Asia/Shanghai"


def _wan(value: float | None, digits: int = 1) -> str:
    """金额（万）；None → 待确认。"""
    if value is None:
        return "待确认"
    return f"{round(float(value), digits):g} 万"


def _clip(text: str, limit: int) -> str:
    """单行摘要截断：保留信息密度，去掉换行。"""
    flat = " ".join(str(text or "").split())
    if len(flat) <= limit:
        return flat
    return flat[: limit - 1] + "…"


def _red_text(item: dict) -> str:
    """红榜一行：没出单就别写 0 万，写“本月未出单”。"""
    money = float(item.get("mtd_wan") or 0)
    money_text = f"累计{money:g}万" if money > 0 else "本月未出单"
    score = item.get("score")
    score_text = f"{round(float(score))} 分｜" if score is not None else ""
    return f"@{item.get('display')} {score_text}{money_text}"


def _hours_text(people: list[dict]) -> str:
    """合计工时；任何一人没出数就写待确认，不用 0 冒充。"""
    if not people:
        return "待确认"
    values = [p.get("hours_minutes") for p in people]
    if any(v is None for v in values):
        return "待确认"
    return f"{sum(float(v) for v in values) / 60:.1f}h"


def _bucket_text(count: int, total: float) -> str:
    """水单/意向笔数：一笔都没有时写“未检索到”，避免当成 0 元结论。"""
    if count <= 0:
        return "未检索到"
    return f"{count} 笔（{_wan(total)}）"


def _amounts(items: list[dict]) -> str:
    """水单/意向明细：金额 + 原文摘要；没检索到就直说。"""
    if not items:
        return "未检索到"
    parts: list[str] = []
    for item in items[:3]:
        money = item.get("amount_text") or "金额待确认"
        snippet = (item.get("snippet") or "").strip()
        parts.append(f"{money}（{snippet[:40]}）" if snippet else str(money))
    return "；".join(parts)


def _target_line(month_target: float | None, mtd: float | None, day: str) -> str:
    """大部门/小部门目标行：滚动日目标 + 累计应达 + 领先/落后。"""
    from app.duzhan_ledger import daily_target_progress

    progress = daily_target_progress(month_target, mtd, day)
    if progress.get("daily_target") is None:
        return f"月目标 待确认｜累计 {_wan(mtd)}"
    text = (
        f"月目标 {_wan(month_target)}｜日目标 {progress['daily_target']:g} 万/天"
        f"（第 {progress['days_elapsed']}/{progress['days_in_month']} 天，累计应达 {_wan(progress['rolling_target']) }）"
    )
    if progress.get("gap") is not None:
        lead = "领先" if progress["ahead"] else "落后"
        text += f"｜累计到账 {_wan(mtd)}（{lead} {abs(progress['gap']):g} 万）"
    return text


def _prev_day(day: str) -> str:
    """数据日 = 推送日前一天；日期非法时原样返回。"""
    try:
        return (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return day


def _window_text(day: str, ledger_day: str) -> str:
    """前 24 小时窗口：数据日 08:00 → 推送日 08:00。"""
    try:
        end = datetime.strptime(day, "%Y-%m-%d").replace(hour=8, tzinfo=ZoneInfo(TZ_SHANGHAI))
    except ValueError:
        return f"窗口待确认｜数据日 {ledger_day}"
    start = end - timedelta(hours=24)
    return (
        f"窗口：{start.strftime('%m-%d %H:%M')} → {end.strftime('%m-%d %H:%M')}"
        f"（北京时间）｜数据日 {ledger_day}"
    )


def build_digest(
    day: str,
    ledger: dict | None = None,
    *,
    ledger_day: str | None = None,
) -> str:
    """生成海外日报群总结文本（总分结构）。

    day = 推送日（调度器给当天 08:00）；ledger_day = 数据日，默认前一天，
    用来覆盖「前 24 小时」（数据日 08:00 → 推送日 08:00）。到账是系统已录单
    的本月累计，读不到的人计入「未出数」，不用 0 冒充。
    """
    ledger_day = ledger_day or _prev_day(day)
    ledger = ledger or collect_ledger(ledger_day)
    people = ledger.get("people") or []
    department_target = _department_target(ledger_day)
    arrived_values = [p.get("perf_arrived_wan") for p in people]
    known_arrived = [float(v) for v in arrived_values if v is not None]
    arrived = sum(known_arrived) if known_arrived else None
    missing_arrived = sum(1 for v in arrived_values if v is None)
    slip_total = sum(
        float(item.get("wan") or 0)
        for p in people for item in (p.get("perf_slip") or [])
    )
    intent_total = sum(
        float(item.get("wan") or 0)
        for p in people for item in (p.get("perf_intent") or [])
    )
    slip_count = sum(len(p.get("perf_slip") or []) for p in people)
    intent_count = sum(len(p.get("perf_intent") or []) for p in people)
    mto_done = sum(1 for p in people if (p.get("mto_count") or 0) >= 4)
    lines: list[str] = []
    missing_text = f"（{missing_arrived} 人未出数）" if missing_arrived else ""
    lines.append(f"【海外渠道日报｜{day} 08:00】")
    lines.append(_window_text(day, ledger_day))
    lines.append("")
    lines.append("一、大部门（海外事业部）")
    lines.append(f"   • {_target_line(department_target, arrived, ledger_day)}")
    lines.append(
        f"   • 三口径：到账 {_wan(arrived)}{missing_text}"
        f"｜水单 {_bucket_text(slip_count, slip_total)}"
        f"｜意向 {_bucket_text(intent_count, intent_total)}"
    )
    if people:
        lines.append(
            f"   • MTO：4 款达标 {mto_done}/{len(people)} 人"
            f"｜工时合计 {_hours_text(people)}｜战役 {TODAY_SLOGAN}"
        )
    else:
        lines.append(f"   • MTO / 工时：待确认（未取到人员台账）｜战役 {TODAY_SLOGAN}")
    red = ledger.get("red") or []
    black = ledger.get("black") or []
    if red:
        lines.append(
            "   • 红榜（过程完成度）："
            + " / ".join(_red_text(item) for item in red[:3])
        )
    if black:
        lines.append(
            "   • 黑榜（待改进）："
            + " / ".join(
                f"@{item.get('display')} {_clip(str(item.get('reason') or '待补充'), 40)}"
                for item in black[:3]
            )
        )
    lines.append("")
    lines.append("二、小部门（各小组/群）")
    for group_name in _group_order(people):
        members = [p for p in people if _group_of(p) == group_name]
        if not members:
            continue
        group_target = _group_target(members, ledger_day)
        group_mtd = sum(float(m.get('mtd_wan') or 0) for m in members if m.get('mtd_wan') is not None)
        group_mtd = group_mtd if any(m.get('mtd_wan') is not None for m in members) else None
        group_slip = [i for m in members for i in (m.get('perf_slip') or [])]
        group_intent = [i for m in members for i in (m.get('perf_intent') or [])]
        mto_ok = sum(1 for m in members if (m.get('mto_count') or 0) >= 4)
        member_text = " / ".join(str(m.get('display') or '未署名') for m in members)
        lines.append(f"   • {group_name}（{member_text}）")
        lines.append(f"     - {_target_line(group_target, group_mtd, ledger_day)}")
        lines.append(f"     - 水单：{_amounts(group_slip)}｜意向：{_amounts(group_intent)}")
        lines.append(
            f"     - MTO 4 款达标 {mto_ok}/{len(members)} 人"
            f"｜工时合计 {_hours_text(members)}"
        )
    lines.append("")
    lines.append("三、个人明细")
    for person in sorted(people, key=lambda item: -(float(item.get('mtd_wan') or 0))):
        display = person.get('display') or '未署名'
        mtd = person.get('mtd_wan')
        daily = person.get('daily_target_wan')
        gap = person.get('target_gap_wan')
        wa = person.get('wa_reached')
        wa_text = '待确认' if wa is None else f"{wa} 户"
        mto = person.get('mto_count')
        mto_text = '待确认' if mto is None else f"{mto}/4"
        hours = '待确认' if person.get('hours_minutes') is None else f"{float(person['hours_minutes']) / 60:.1f}h"
        report = person.get('daily_report') or {}
        report_text = '已交' if report else '未见日报'
        slip = _amounts(person.get('perf_slip') or [])
        intent = _amounts(person.get('perf_intent') or [])
        lead = ''
        if gap is not None:
            lead = f"｜{'领先' if person.get('target_ahead') else '落后'} {abs(gap):g} 万"
        daily_text = f"{daily:g} 万" if daily is not None else "待确认"
        lines.append(f"   • {display}：累计到账 {_wan(mtd)}{lead}｜日目标 {daily_text}")
        lines.append(f"     水单 {slip}｜意向 {intent}｜MTO {mto_text}｜WhatsApp {wa_text}｜工时 {hours}｜{report_text}")
    lines.append("")
    lines.append("四、明日预告（未闭环 → 第一动作）")
    carried = 0
    for person in people:
        titles = [
            _clip(str(i.get('title') or ''), 60)
            for i in (person.get('collections') or [])
            if str(i.get('status') or '') != 'done'
        ]
        titles = [t for t in titles if t][:2]
        if not titles:
            continue
        carried += 1
        lines.append(f"   • {person.get('display') or '未署名'}：{'；'.join(titles)}")
    if not carried:
        lines.append("   • 未检索到未闭环事项（缺数据不等于没做，待群里确认）")
    lines.append("")
    lines.append("五、卡点与需拍板")
    blockers: list[str] = []
    for person in people:
        hits = [
            _clip(str(item), 70)
            for item in (person.get("blockers") or [])
            if _is_blocker(str(item))
        ]
        if hits:
            blockers.append(f"{person.get('display') or '未署名'}：{'；'.join(hits[:2])}")
    if blockers:
        lines.extend(f"   • {item}" for item in blockers[:8])
    else:
        lines.append("   • 未见卡点上报（日常计划类内容不计入本节）")
    lines.append("")
    lines.append("数据口径：到账=系统已录单；水单=客户已付款未到账；意向=明确意向金额；读不出写待确认。")
    return chr(10).join(lines)


def _group_of(person: dict) -> str:
    """台账行的组名；缺字段归入「未分组」。"""
    return str((person or {}).get("group") or "未分组")


_BLOCKER_HINTS = (
    "卡点", "阻塞", "受阻", "障碍", "风险", "缺口", "延期", "延迟", "暂停",
    "不同意", "未收到", "未回款", "等回复", "等客户", "迟迟", "放弃",
)
# 日常计划/安排类原话即使含“未回复”等字样，也不算卡点（新人组晨夕会模板常见）。
_PLAN_HINTS = ("今日计划", "明日计划", "工作计划", "工作安排", "今日安排", "晨夕会")


def _is_blocker(text: str) -> bool:
    """只有像卡点的原话才进「卡点与需拍板」，避免把今日计划当卡点。"""
    if not text:
        return False
    if any(hint in text for hint in _PLAN_HINTS):
        return False
    return any(hint in text for hint in _BLOCKER_HINTS)


def _group_order(people: list[dict]) -> list[str]:
    """小部门顺序：按三追注册表顺序，未知组排最后。"""
    from app.duzhan import GROUPS

    known = [g.name for g in GROUPS]
    seen = [_group_of(p) for p in people]
    ordered = [name for name in known if name in seen]
    ordered += [name for name in dict.fromkeys(seen) if name not in ordered]
    return ordered


def _target_month(day: str) -> dict:
    """目标文件里当月那一块；读不到返回空字典（一律待确认，不猜）。"""
    import json

    from app.duzhan_ledger import TARGETS_FILE

    try:
        payload = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    month = payload.get(day[:7]) or {}
    return month if isinstance(month, dict) else {}


def _target_entries(day: str) -> list[dict]:
    """目标文件当月明细（个人目标 + 带 members 的小组目标）。"""
    entries = _target_month(day).get("entries") or []
    return [item for item in entries if isinstance(item, dict)]


def _department_target(day: str) -> float | None:
    """部门月度目标：目标文件 department_target_wan；缺失返回 None（待确认）。"""
    value = _target_month(day).get("department_target_wan")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _group_target(members: list[dict], day: str) -> float | None:
    """小组月目标：先把个人目标加总；个人目标都缺时用文件里带 members 的组目标。"""
    known = [float(m["target_wan"]) for m in members if m.get("target_wan") is not None]
    if known:
        return sum(known)
    names = {str(m.get("display") or "") for m in members}
    for entry in _target_entries(day):
        entry_members = {str(item) for item in (entry.get("members") or [])}
        if entry_members and entry_members & names:
            try:
                return float(entry.get("target_wan") or 0)
            except (TypeError, ValueError):
                return None
    return None
def push_digest(
    day: str | None = None,
    *,
    dry_run: bool = False,
    body: str | None = None,
) -> dict:
    """生成并推送海外日报群总结（每天 08:00，前 24 小时）。

    目标群 = 海外日报群（PDCA_TODO_GROUP_CHANNEL_ID，与 Agent 群实例同源）。
    返回 {day, ledger_day, sent, via, reason, chars}；dry_run 只生成不发送，
    便于上线前用真实台账预览。推送失败不静默，调用方据此告警。
    """
    from app.todos.service import send_group_text

    day = day or datetime.now(ZoneInfo(TZ_SHANGHAI)).date().isoformat()
    ledger_day = _prev_day(day)
    body = body or build_digest(day, ledger_day=ledger_day)
    result = {
        "day": day,
        "ledger_day": ledger_day,
        "sent": False,
        "via": "",
        "reason": "",
        "chars": len(body),
    }
    if dry_run:
        result["reason"] = "dry_run"
        return {**result, "preview": body}
    channel_id = get_settings().todo_group_channel_id
    if not channel_id:
        result["reason"] = "未配置 PDCA_TODO_GROUP_CHANNEL_ID"
        return result
    ok, reason, via = send_group_text(
        channel_id,
        body,
        f"pdca-daily-digest-{day}",
        bot_name="海外日报",
    )
    result.update({"sent": ok, "via": via, "reason": reason})
    return result


def render_previous_day(day: str) -> str:
    """只渲染不推送（管理后台/自检用），台账取数据日。"""
    return build_digest(day, ledger_day=_prev_day(day))
