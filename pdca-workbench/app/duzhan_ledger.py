# -*- coding: utf-8 -*-
"""督战官台账：vertu-cli 回款 + AINativeSales WhatsApp/意向 + 红黑榜。

对标催收机器人：台账是唯一数据源，模板只读台账。Vemory 等接口到再填。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from app.alerting import notify
from app.config import get_settings
from app.daily_report_template import check_template, looks_like_report

TODAY_SLOGAN = "1300万战役"  # 部门月目标口号（1228 万 ≈ 1300 万），只作口号展示
RATE_CNY = 7.1  # USD→CNY 折算（与 mto_ocr 一致）
TARGETS_FILE = Path(__file__).with_name("monthly_sales_targets.json")
DUZHAN_BOT_ID = "459fdf45-3882-404c-b5e8-570fe9680ecf"
_PAYLOAD_RE = re.compile(
    r'<script id="payload" type="application/json">(.*?)</script>',
    re.S,
)


@dataclass(frozen=True)
class Owner:
    """达标群里一个按人取数的主体。"""

    group: str
    display: str
    cli_name: str = ""
    target_name: str = ""
    employee_id: int | None = None
    department_id: int | None = None
    dept_l2: str = ""
    im_user_id: int | None = None
    vemory_user_id: int | None = None
    vps_names: tuple[str, ...] = ()
    follow_channel_id: str = ""
    # 新人 100 万是新部合计，不拆到个人，target_wan 留空。
    target_wan: float | None = None


# 老板 2026-10-10 拍板：按「谁追谁」把人放到对应达标群，各追各的、对应到人：
#   杨晶晶群：杨晶晶 / 何海文 / 王宇彤
#   viki 群：Viki(尤文静) / 江旭(Sana) / 张月馨
#   Lina 群：Lina(DEH) / Safae
#   Q4五百万群：刘春梅 / 邓琳莹（新人小组群停推，5 个人全部分流）
# 老板 2026-09-18 拍板：江旭就是 Sana，要加；吴楠、杨成凤、张倩不加。
OWNERS: tuple[Owner, ...] = (
    Owner(
        "于冰业绩达标群",
        "于冰",
        cli_name="于冰",
        target_name="于冰",
        employee_id=45,
        im_user_id=13063,
        vemory_user_id=41,
        target_wan=200,
    ),
    Owner(
        "杨晶晶业绩达标群",
        "杨晶晶",
        cli_name="杨晶晶",
        target_name="杨晶晶",
        employee_id=47,
        im_user_id=13122,
        vemory_user_id=69,
        target_wan=333,
    ),
    Owner(
        "杨晶晶业绩达标群",
        "何海文",
        cli_name="何海文",
        target_name="何海文",
        employee_id=238,
        im_user_id=14113,
        vemory_user_id=109,
        target_wan=95,
    ),
    Owner(
        "杨晶晶业绩达标群",
        "王宇彤",
        cli_name="王宇彤",
        employee_id=278,
        im_user_id=14344,
        vemory_user_id=121,
        follow_channel_id="792c8c09-4c4f-4162-b0cb-45f6d009b504",
    ),
    Owner(
        "viki业绩达标群",
        "Viki",
        cli_name="尤文静",
        target_name="尤文静",
        employee_id=216,
        im_user_id=13551,
        vemory_user_id=80,
        vps_names=("尤文静",),
        target_wan=100,
    ),
    Owner(
        "viki业绩达标群",
        "江旭",
        cli_name="江旭",
        employee_id=388,
        im_user_id=14549,
        vps_names=("江旭", "Sana"),
        # Sana客户跟进群（老板 2026-09-18 确认江旭=Sana）
        follow_channel_id="d038caa8-3bd3-432b-b91a-9bf58180e855",
    ),
    Owner(
        "viki业绩达标群",
        "张月馨",
        cli_name="张月馨",
        employee_id=559,
        # ponytail: 月馨群仅 14660 回飞书表；组织搜索无名。错了再改。
        im_user_id=14660,
        follow_channel_id="743227fa-07cc-4bfd-be74-9242aaa56e71",
    ),
    Owner(
        "Lina业绩达标群",
        "Lina",
        cli_name="DEHDAHOUMAIMA",
        target_name="Lina",
        employee_id=171,
        im_user_id=13050,
        vps_names=("DEHDAHOUMAIMA", "丽娜"),
        target_wan=400,
    ),
    Owner(
        "Lina业绩达标群",
        "Safae",
        cli_name="Safae Ben M'hamed",
        employee_id=305,
        im_user_id=14460,
        vps_names=("Safae Ben M'hamed", "Safae"),
        follow_channel_id="8cf4b40b-0e60-4819-9120-a22f3c808a00",
    ),
    Owner(
        "Lina业绩达标群",
        "冯磊",
        cli_name="冯磊-1",
        im_user_id=12545,
    ),
    Owner(
        # 老板 2026-10-10：Q4 五百万专项群，和邓琳莹一起追
        "Q4五百万",
        "刘春梅",
        cli_name="刘春梅",
        target_name="刘春梅",
        im_user_id=12564,
        vps_names=("刘春梅",),
        # 老板 2026-10-10：10 月给刘春梅 100 万（从「其他（待拆解）」里挪，总额仍是 1525 万）
        target_wan=100,
    ),
    Owner(
        "Q4五百万",
        "付汪阳",
        cli_name="付汪阳",
        im_user_id=13365,
    ),
    Owner(
        "Q4五百万",
        "邓琳莹",
        cli_name="邓琳莹",
        employee_id=36,
        im_user_id=14247,
        follow_channel_id="8bb5ae97-3ffb-42e7-869d-c5cef358510a",
    ),
)


@dataclass
class PersonRow:
    """一个人/小组当日台账行。None = 未出数，禁止当成 0。"""

    group: str
    display: str
    target_wan: float | None = None
    mtd_wan: float | None = None
    wa_reached: int | None = None
    wa_lower_bound: bool = False
    intent_count: int | None = None
    mto_count: int | None = None
    mto_names: list[str] = field(default_factory=list)
    mto_quotes: list[dict] = field(default_factory=list)
    mto_daily_goal: int = 4
    mto_min_wan: float = 30
    hours_minutes: float | None = None
    hours_band: str = ""
    hours_window: str = ""
    hours_parts: dict = field(default_factory=dict)
    vps_im_sent: int | None = None
    vps_agent_calls: int | None = None
    vps_turns: int | None = None
    vps_daily: bool = False
    vps_first: str = ""
    vps_last: str = ""
    vemory: list[dict] = field(default_factory=list)
    vemory_ok: bool = True
    daily_report: dict = field(default_factory=dict)
    # 日报群取数是否成功：失败时必须写「待确认」，不能渲染成「未见日报」并据此扣分。
    daily_report_ok: bool = True
    # None also covers historical snapshots without collection provenance.
    history_ok: bool | None = None
    # 第 8 节「今日早会待办」正文（按群分流，空串表示当天没有、不出这一节）
    meeting_todos: str = ""
    collections: list[dict] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    # 滚动日目标（月目标 ÷ 当月天数 × 已过天数）；Nove 为 None 时渲染“待确认”。
    daily_target_wan: float | None = None
    rolling_target_wan: float | None = None
    # 月目标来源：file（用户维护的目标文件）/ group（组目标摊到人）/ hardcoded / none
    target_source: str = ""
    days_elapsed: int | None = None
    days_in_month: int | None = None
    target_gap_wan: float | None = None
    target_ahead: bool | None = None
    # 小组目标背景值：新人小组 100 万按人头平均分后，这里留小组总额与组名。
    group_target_wan: float | None = None
    group_target_name: str = ""
    # 业绩三关键词：到账（系统已录单）/ 水单（已付款未到账）/ 意向（明确意向金额）
    perf_arrived_wan: float | None = None
    perf_slip: list[dict] = field(default_factory=list)
    perf_intent: list[dict] = field(default_factory=list)
    score: float = 0.0
    gaps: list[str] = field(default_factory=list)


def empty_ledger(day: str) -> dict:
    """空台账，渲染侧全部打待确认。"""
    return {
        "day": day,
        "today_target": TODAY_SLOGAN,
        "people": [],
        "red": [],
        "black": [],
        "rewards": [],
        "penalties": [],
        "vemory_status": "ok",
    }


def _blank(lang: str = "zh") -> str:
    return "pending" if lang == "en" else "待确认"


def wan_text(value: float | None, lang: str = "zh") -> str:
    """金额转万；空值待确认。"""
    if value is None:
        return _blank(lang)
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return text or "0"


def count_text(value: int | None, *, lower_bound: bool = False, lang: str = "zh") -> str:
    """户数；空值待确认。不完整时标已同步下限。"""
    if value is None:
        return _blank(lang)
    suffix = ""
    if lower_bound:
        suffix = " (synced lower bound)" if lang == "en" else "（已同步下限）"
    return f"{value}{suffix}"


STANDARD_DAY_MIN = 480.0
CAP_MIN_PER_CHAT = 25.0
CAP_MIN_WA = 240.0  # WhatsApp 最多 4h
MIN_MTO = 10.0
MIN_COLLECT = 15.0
CAP_MTO = 30.0  # MTO 整天最多半小时
CAP_COLLECT = 120.0
CAP_MEETING = 180.0
MIN_VPS_TURN = 6.0  # Agent 一轮（Standard提问或 OpenCode 调用）按 6 分钟
CAP_VPS = 150.0
MIN_CHAT = 8.0


def _parse_dt(text: object) -> datetime | None:
    if isinstance(text, (int, float)):
        ts = float(text)
        if ts <= 0:
            return None
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts)
        except (OSError, OverflowError, ValueError):
            return None
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return _parse_dt(int(raw))
    raw = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw[:26])
    except ValueError:
        return None


def meeting_minutes(item: dict) -> float:
    """Vemory 实际时长。优先 duration；否则起止相减。没有记 0。"""
    for key in ("duration_minutes", "duration_min"):
        value = item.get(key)
        if isinstance(value, (int, float)) and value > 0:
            # 工作台偶发把秒写进 duration_minutes（如快速会议 450）。
            return float(value) / 60.0 if value > 240 else float(value)
    seconds = item.get("duration_seconds")
    if isinstance(seconds, (int, float)) and seconds > 0:
        return float(seconds) / 60.0
    duration = item.get("duration")
    if isinstance(duration, (int, float)) and duration > 0:
        # ponytail: >10h 当秒；常见录音秒数。
        return float(duration) / 60.0 if duration > 600 else float(duration)
    start = _parse_dt(item.get("start_time") or item.get("start_record_time"))
    end = _parse_dt(item.get("end_time") or item.get("end_record_time"))
    if start and end:
        delta = (end - start).total_seconds() / 60.0
        if delta > 0:
            return delta
    return 0.0


def chat_minutes(outbound: int, inbound: int) -> float:
    """单户估算分钟。有来往至少 8 分钟；发 1.2 + 收 1.0；单户封顶 25。"""
    if outbound <= 0 and inbound <= 0:
        return 0.0
    raw = max(MIN_CHAT, outbound * 1.2 + inbound * 1.0)
    return min(raw, CAP_MIN_PER_CHAT)


def workdays_this_week(day: str) -> int:
    """本周一到检查日的工作日数，用来把周累计轮次摊成日均。周末按 5。"""
    try:
        weekday = datetime.strptime(day, "%Y-%m-%d").weekday()
    except ValueError:
        return 1
    if weekday >= 5:
        return 5
    return weekday + 1


def vps_minutes(row: dict) -> float:
    """VPS 工时：Standard提问 + OpenCode/Harness 当轮数。周报摊到已过工作日。"""
    turns = row.get("vps_turns")
    if turns is None:
        return 0.0
    days = max(int(row.get("vps_weekdays") or 1), 1)
    daily_rounds = float(turns) / days
    return min(daily_rounds * MIN_VPS_TURN, CAP_VPS)


def estimate_hours(chats: list[dict], person: dict | None = None) -> dict:
    """经销商工时：只加有记录的块，对照标准 8h。不把空窗当工时。"""
    wa_raw = sum(
        chat_minutes(int(item.get("outbound") or 0), int(item.get("inbound") or 0))
        for item in chats
    )
    wa = min(wa_raw, CAP_MIN_WA)
    lasts = [str(item.get("last") or "") for item in chats if item.get("last")]
    window = f"{min(lasts)}–{max(lasts)}" if lasts else ""
    row = person or {}
    mto_n = int(row.get("mto_count") or 0) if row.get("mto_count") is not None else 0
    quotes = [item for item in (row.get("mto_quotes") or []) if isinstance(item, dict)]
    if quotes:
        mto_n = max(mto_n, sum(1 for item in quotes if item.get("raw_ok") or item.get("qualifies")))
    collect_n = len(row.get("collections") or [])
    meetings = row.get("vemory") or [] if row.get("vemory_ok") is not False else []
    meeting_n = len(meetings)
    mto = min(mto_n * MIN_MTO, CAP_MTO) if row.get("mto_count") is not None else 0.0
    collect = min(collect_n * MIN_COLLECT, CAP_COLLECT)
    meeting_raw = sum(meeting_minutes(item) for item in meetings if isinstance(item, dict))
    meeting = min(meeting_raw, CAP_MEETING)
    vps = vps_minutes(row)
    covered = wa + mto + collect + meeting + vps
    # 一条证据都没有时，工时是「没出数」而不是「0 小时」（老板口径：不用 0 冒充）
    no_evidence = (
        chats == []
        and row.get("mto_count") is None
        and not collect_n
        and meeting_n == 0
        and row.get("vps_turns") is None
    )
    minutes = None if no_evidence else min(covered, STANDARD_DAY_MIN)
    gap = max(STANDARD_DAY_MIN - covered, 0.0)
    hours = None if minutes is None else round(minutes / 60.0, 2)
    std = round(STANDARD_DAY_MIN / 60.0, 1)
    ratio = covered / STANDARD_DAY_MIN if STANDARD_DAY_MIN else 0
    if no_evidence:
        band = "待确认"
    elif ratio >= 0.85:
        band = "近满勤"
    elif ratio >= 0.5:
        band = "半日+"
    elif covered >= 30:
        band = "浅"
    else:
        band = "证据不足"
    parts = {
        "wa": round(wa, 1),
        "mto": round(mto, 1),
        "collect": round(collect, 1),
        "meeting": round(meeting, 1),
        "vps": round(vps, 1),
        "gap": round(gap, 1),
        "std": STANDARD_DAY_MIN,
    }
    return {
        "minutes": None if minutes is None else round(minutes, 1),
        "hours": hours,
        "band": band,
        "window": window,
        "parts": parts,
        "std_hours": std,
    }


def parse_wa_hour_chats(payload: dict | None) -> list[dict]:
    """conversations.customers 明细，供工时。经销商全量 WhatsApp。"""
    chats: list[dict] = []
    for row in (payload or {}).get("rows") or []:
        if not isinstance(row, dict) or row.get("row_type") != "detail":
            continue
        chats.append(
            {
                "outbound": int(row.get("outbound_message_count") or 0),
                "inbound": int(row.get("inbound_message_count") or 0),
                "last": str(row.get("last_message_time") or "")[11:16],
            }
        )
    return chats


def hours_text(person: dict | None, lang: str = "zh") -> str:
    """督战官文案：对照 8h + 分项证据。未出数待确认。"""
    if not person or person.get("hours_minutes") is None:
        return _blank(lang)
    minutes = float(person.get("hours_minutes") or 0)
    hours = round(minutes / 60.0, 2)
    band = str(person.get("hours_band") or "")
    parts = person.get("hours_parts") or {}
    gap_h = round(float(parts.get("gap") or 0) / 60.0, 2)
    wa_h = round(float(parts.get("wa") or 0) / 60.0, 2)
    mto_h = round(float(parts.get("mto") or 0) / 60.0, 2)
    col_h = round(float(parts.get("collect") or 0) / 60.0, 2)
    meet_h = round(float(parts.get("meeting") or 0) / 60.0, 2)
    vps_h = round(float(parts.get("vps") or 0) / 60.0, 2)
    window = str(person.get("hours_window") or "")
    if lang == "en":
        extra = f"; WA window {window} (span≠hours)" if window else ""
        return (
            f"{hours}h / 8h std | {band} | WA {wa_h}h + MTO {mto_h}h + "
            f"collections {col_h}h + meetings {meet_h}h + VPS {vps_h}h | gap {gap_h}h{extra}"
        )
    extra = f"；WA窗口 {window}（跨度≠工时）" if window else ""
    return (
        f"{hours}h / 标准8h｜{band}｜WA {wa_h}h + MTO {mto_h}h + "
        f"催收跟进 {col_h}h + 会议 {meet_h}h + VPS {vps_h}h｜缺口 {gap_h}h{extra}"
    )


def daily_target_progress(
    month_target_wan: float | None,
    mtd_wan: float | None,
    day: str,
) -> dict:
    """滚动日目标：日目标 = 月目标 ÷ 当月天数；累计应达 = 日目标 × 当月已过天数。

    返回（单位：万，None 表示该口径缺数据，绝不拿 0 冒充）：
      month_target / days_in_month / days_elapsed / daily_target /
      rolling_target（累计应达）/ mtd（累计回款）/ gap（正=领先，负=落后）/ ahead
    规范：TODAY_SLOGAN（如“1300万战役”）是部门月目标口号，不能当“今日目标”展示。
    """
    import calendar

    out: dict = {
        "month_target": month_target_wan,
        "days_in_month": None,
        "days_elapsed": None,
        "daily_target": None,
        "rolling_target": None,
        "mtd": mtd_wan,
        "gap": None,
        "ahead": None,
    }
    try:
        year, month, day_of_month = (int(part) for part in day.split("-")[:3])
        days_in_month = calendar.monthrange(year, month)[1]
        days_elapsed = min(max(day_of_month, 1), days_in_month)
    except (ValueError, TypeError):
        return out
    out["days_in_month"] = days_in_month
    out["days_elapsed"] = days_elapsed
    if month_target_wan is not None and days_in_month:
        daily = round(float(month_target_wan) / days_in_month, 2)
        out["daily_target"] = daily
        out["rolling_target"] = round(daily * days_elapsed, 1)
    if out["rolling_target"] is not None and mtd_wan is not None:
        gap = round(float(mtd_wan) - out["rolling_target"], 1)
        out["gap"] = gap
        out["ahead"] = gap >= 0
    return out


def daily_target_text(progress: dict, lang: str = "zh") -> str:
    """把滚动日目标渲染成一行；缺数据写“待确认”。"""
    if not progress or progress.get("daily_target") is None:
        return "pending" if lang == "en" else "待确认"
    # 天数缺（手工构造的台账）时不写 None/None，只留累计应达
    has_days = (
        progress.get("days_elapsed") is not None
        and progress.get("days_in_month") is not None
    )
    if lang == "en":
        text = f"{progress['daily_target']} wan/day"
        if has_days:
            text += f" (day {progress['days_elapsed']}/{progress['days_in_month']}"
            text += f", cumulative due {progress['rolling_target']} wan)"
        elif progress.get("rolling_target") is not None:
            text += f" (cumulative due {progress['rolling_target']} wan)"
        if progress.get("gap") is not None:
            lead = "ahead" if progress["ahead"] else "behind"
            text += f" | {lead} {abs(progress['gap'])} wan"
        return text
    text = f"{progress['daily_target']} 万/天"
    if has_days:
        text += (
            f"（第 {progress['days_elapsed']}/{progress['days_in_month']} 天"
            f"，累计应达 {progress['rolling_target']} 万）"
        )
    elif progress.get("rolling_target") is not None:
        text += f"（累计应达 {progress['rolling_target']} 万）"
    if progress.get("gap") is not None:
        lead = "领先" if progress["ahead"] else "落后"
        text += f"｜{lead} {abs(progress['gap'])} 万"
    return text


# 业绩三关键词：到账（已录单）/ 水单（已付款未到账）/ 意向（明确意向金额）
_PERF_KEYWORDS = {
    "arrived": ("到账", "已录单", "已回款", "货款已到"),
    "slip": ("水单",),
    "intent": ("意向",),
}
# 这些是机器人自己的模板回显或明确否定，不能当成客户水单/意向
_PERF_NOISE_RE = re.compile(
    r"晚追|早追|中追|无\s*VPS\s*留痕|无Vemory|Vemory\s*录音链接|"
    r"水单\s*[（(]\s*无\s*[)）]|意向\s*[（(]\s*无\s*[)）]|"
    r"无s*水单|没有水单|没有s*意向|无意向|暂无意向|无明确意向|"
    r"请补：|回复格式|本档动作",
)
_PERF_AMOUNT_RE = re.compile(
    r"(?:USD|usd|\$|美金|美元)\s*([\d,]+(?:\.\d+)?)|"
    r"([\d,]+(?:\.\d+)?)\s*(?:USD|usd|\$|美金|美元)|"
    r"([\d,]+(?:\.\d+)?)\s*([Ww万])|"
    r"([\d,]+(?:\.\d+)?)\s*(?:万?RMB|人民币|元)"
)


def parse_performance_buckets(
    messages: list | None,
    sender_id: int | None,
    *,
    arrived_wan: float | None = None,
) -> dict:
    """按关键词把当天业绩拆成三桶，金额只在原文可解析时给出。

    - arrived（到账）：以系统已录单回款为准（arrived_wan，来自 OKR/vertu-cli）；
      群内“到账/已录单”原文作为佐证列在 mentions；
    - slip（水单）：客户已付款、尚未到账，一定会到 —— 群消息含“水单”的行；
    - intent（意向）：明确的意向金额 —— 群消息含“意向”的行。
    每条 {amount_text, wan, usd, snippet, source}；解析不出的金额写空、不编造。
    """
    buckets: dict = {
        "arrived": {"wan": arrived_wan, "source": "系统已录单回款", "mentions": []},
        "slip": [],
        "intent": [],
    }
    if not sender_id:
        return buckets
    for msg in messages or []:
        if (
            not isinstance(msg, dict)
            or msg.get("revoked_at")
            or str(msg.get("message_type") or "").lower() == "recall"
        ):
            continue
        if msg.get("sender_user_id") != sender_id:
            continue
        if str(msg.get("message_type") or "") not in {"text", "", "link"}:
            continue
        body = _msg_body(msg).strip()
        if len(body) < 3:
            continue
        created = str(msg.get("created_at") or "")[:10]
        for line in re.split(r"[\n；;]+", body):
            text = line.strip()
            if len(text) < 2:
                continue
            if _PERF_NOISE_RE.search(text):
                continue
            for bucket, keywords in (
                ("arrived", _PERF_KEYWORDS["arrived"]),
                ("slip", _PERF_KEYWORDS["slip"]),
                ("intent", _PERF_KEYWORDS["intent"]),
            ):
                if not any(keyword in text for keyword in keywords):
                    continue
                amount = _perf_amount(text)
                item = {
                    "amount_text": amount["text"],
                    "wan": amount["wan"],
                    "usd": amount["usd"],
                    "snippet": re.sub(r"\s+", " ", text)[:160],
                    "source": ("im:" + created) if created else "im",
                }
                if bucket == "arrived":
                    buckets["arrived"]["mentions"].append(item)
                elif len(buckets[bucket]) < 10:
                    buckets[bucket].append(item)
                break
    return buckets


def as_int(value: object, default: int = 0) -> int:
    """宽松取整：外部卡片可能给「100%」「已完成」这类值，坏值按 default，绝不抛异常。

    日报卡片的 metadata 由 IM 侧写入、不在本仓控制，采集是关键路径，不能因为一个
    非数字 progress 就让整轮采集（三个整点推送）全部失败。
    """
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if text.endswith("%"):
        text = text[:-1].strip()
    try:
        return int(float(text))
    except (TypeError, ValueError):
        logger.warning("无法解析的整数值，按 {} 处理: {!r}", default, value)
        return default


def as_float(value: object, default: float = 0.0) -> float:
    """宽松取浮点：同上，坏值按 default，绝不抛异常。"""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").rstrip("%")
    try:
        return float(text)
    except (TypeError, ValueError):
        logger.warning("无法解析的数值，按 {} 处理: {!r}", default, value)
        return default


def num_text(value: float) -> str:
    """金额显示：整数不带小数点，大数不用科学计数法（format(x, "g") 会把 2000000 写成 2e+06）。"""
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}".replace(",", "")
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _perf_amount(text: str) -> dict:
    """从一行文字抠金额：USD 优先，其次 x万 / x元 / xRMB；读不出留空。"""
    match = _PERF_AMOUNT_RE.search(text or "")
    if not match:
        return {"text": "", "wan": None, "usd": None}
    if match.group(1) or match.group(2):
        raw = (match.group(1) or match.group(2) or "").replace(",", "")
        try:
            usd = float(raw)
        except ValueError:
            return {"text": "", "wan": None, "usd": None}
        return {"text": "$" + num_text(usd), "wan": round(usd * RATE_CNY / 10000, 1), "usd": usd}
    if match.group(3):
        try:
            wan = float(match.group(3).replace(",", ""))
        except ValueError:
            return {"text": "", "wan": None, "usd": None}
        return {"text": num_text(wan) + "万", "wan": wan, "usd": None}
    if match.group(5):
        try:
            yuan = float(match.group(5).replace(",", ""))
        except ValueError:
            return {"text": "", "wan": None, "usd": None}
        return {"text": num_text(yuan) + "元", "wan": round(yuan / 10000, 2), "usd": None}
    return {"text": "", "wan": None, "usd": None}


def image_performance_facts(quotes: list[dict], day: str) -> tuple[list[dict], list[dict], list[str]]:
    """把同次图片 OCR 的业绩事实列为待核证据；绝不叠加正式已录单业绩。"""
    from app.mto_ocr import quote_document_type

    slips: list[dict] = []
    intents: list[dict] = []
    pending: list[str] = []
    for quote in quotes or []:
        if not isinstance(quote, dict):
            continue
        document_type = quote_document_type(quote)
        basis = str(quote.get("performance_basis") or "unknown")
        visible = re.sub(r"\s+", " ", str(quote.get("visible_text") or "")).strip()[:160]
        amount = quote.get("performance_amount")
        currency = str(quote.get("performance_currency") or "")
        amount_text = ""
        if (
            isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and math.isfinite(amount)
            and amount >= 0
            and currency
        ):
            amount_text = ("$" + num_text(amount)) if currency == "USD" else f"{num_text(amount)} {currency}"
        else:
            amount = None
        source_message_id = str(quote.get("source_message_id") or "")
        source_attachment_id = str(quote.get("source_attachment_id") or "")
        source_ref = source_message_id or source_attachment_id
        item = {
            "amount_text": amount_text,
            "wan": quote.get("performance_wan"),
            "usd": amount if currency == "USD" else None,
            "snippet": "图片识别待核：" + (visible or "业务凭证"),
            "source": f"im-image:{day}" + (f":{source_ref}" if source_ref else ""),
            "source_message_id": source_message_id,
            "source_attachment_id": source_attachment_id,
            "document_type": document_type,
            "performance_basis": basis,
            "review_status": "pending",
        }
        # 纯金额不足以证明水单/意向；必须有明确类型、业务阶段和可见原文。
        if document_type == "payment_receipt" and basis == "paid_not_received" and visible:
            slips.append(item)
        elif basis == "intent" and visible:
            intents.append(item)
        elif document_type in {"payment_receipt", "sales_report"} or basis in {
            "paid_not_received", "received", "booked_sales", "intent"
        }:
            label = "付款/水单" if document_type == "payment_receipt" else "业绩"
            pending.append(f"群图片{label}证据待核（未计入系统已录单业绩）")
    return slips[:10], intents[:10], pending[:6]


def pending_group_image_count(messages: list | None, sender_id: int | None, quotes: list[dict]) -> int:
    """未完成 OCR 或仍无法分类的图片数；用于显式保留待核证据。"""
    from app.mto_ocr import quote_document_type

    total, _ = parse_mto_images(messages, sender_id)
    accounted = 0
    for quote in quotes or []:
        if not isinstance(quote, dict):
            continue
        document_type = quote_document_type(quote)
        if document_type in {"payment_receipt", "sales_report", "other"}:
            accounted += 1
        elif document_type == "mto_quote" and quote.get("raw_ok") and quote.get("wan") is not None:
            accounted += 1
    return max(total - accounted, 0)


def target_entries(day: str) -> list[dict]:
    """目标文件里当月的 entries；结构非法时返回空表并告警。

    这张表由用户每月手写维护，格式错一点点都不能让采集整轮失败：
    collect_ledger 第 2 行就读它，抛异常会让三个整点全部变「待确认」，
    证据 HTML / 日报作业也会直接 failed。
    """
    month = day[:7]
    try:
        payload = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("月度目标文件读取失败（{}）：{}", TARGETS_FILE, exc)
        return []
    if not isinstance(payload, dict):
        logger.warning("月度目标文件顶层必须是对象，已忽略：{}", TARGETS_FILE)
        return []
    plan = payload.get(month)
    if plan is None:
        return []
    if not isinstance(plan, dict):
        logger.warning("月度目标 {} 的值必须是对象，已忽略", month)
        return []
    entries = plan.get("entries") or []
    if not isinstance(entries, list):
        logger.warning("月度目标 {} 的 entries 必须是数组，已忽略", month)
        return []
    clean: list[dict] = []
    for item in entries:
        if not isinstance(item, dict):
            logger.warning("月度目标 {} 里有非对象条目，已跳过：{!r}", month, item)
            continue
        clean.append(item)
    return clean


def load_month_targets(day: str) -> dict[str, float]:
    """本地月度目标（万）；0 / 负数 / 非数字都按「未配置」处理，不静默当成有效目标。"""
    out: dict[str, float] = {}
    for item in target_entries(day):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        value = as_float(item.get("target_wan"), default=-1.0)
        if value <= 0:
            logger.warning(
                "月度目标 {} 的 target_wan 非法（{!r}），按未配置处理",
                name,
                item.get("target_wan"),
            )
            continue
        out[name] = value
    return out


def resolve_month_target(
    owner: Owner, day: str, monthly_targets: dict[str, float]
) -> tuple[float | None, str]:
    """单人月目标与来源：file / group / hardcoded / none。

    单一来源原则：app/monthly_sales_targets.json 是月度目标的唯一权威来源（用户
    每月更新），文件命中就直接用；文件没有的条目按「组目标摊到人」再按 OWNERS 里
    硬编码的历史目标兜底，并且必须告警（见 warn_target_fallback），不能静默用旧数。
    文件名按 display 匹配，display 是英文名的人用 target_name 兜一层（如 Viki←尤文静）。
    """
    for key in (owner.display, owner.target_name):
        if key and key in monthly_targets:
            return monthly_targets[key], "file"
    split = split_group_target_of(owner.display, day)
    if split:
        return split[0], "group"
    if owner.target_wan is not None:
        return owner.target_wan, "hardcoded"
    return None, "none"


def month_target_scope(day: str, monthly_targets: dict[str, float]) -> tuple[bool, list[str]]:
    """当月目标文件覆盖情况：返回 (是否覆盖到人, 文件没覆盖、只能兜底的人)。"""
    from app.duzhan_departments import is_task_only

    tracked = [item for item in OWNERS if (item.target_wan or item.group)
               and not is_task_only(item.group, item.display)]
    if not monthly_targets:
        return False, [item.display for item in tracked]
    missing = [
        item.display
        for item in tracked
        if resolve_month_target(item, day, monthly_targets)[1] not in ("file", "group")
    ]
    return (not missing), missing


_TARGET_WARNED: set[str] = set()


def warn_target_fallback(day: str, monthly_targets: dict[str, float]) -> list[str]:
    """当月目标文件缺人时告警（同一个月只发一次），返回兜底名单。"""
    covered, missing = month_target_scope(day, monthly_targets)
    month = day[:7]
    if covered and not missing:
        return []
    if month in _TARGET_WARNED:
        return missing
    names = "、".join(missing) if missing else "（当月条目整体缺失）"
    logger.warning("月度目标文件未覆盖 {}，以下人员回退硬编码目标: {}", month, names)
    try:
        notify(
            "月度目标未更新",
            f"{month} 的月度目标没有在 app/monthly_sales_targets.json 里配置完整，"
            f"以下人员暂时回退到硬编码目标：{names}。请更新目标文件后重新采集。",
        )
    except Exception as exc:  # noqa: BLE001 — 告警失败不影响采集
        # 只有发出去才记「本月已告警」：否则一次 notify 异常会让当月彻底静默。
        logger.warning("月度目标兜底告警发送失败（下轮会重试）: {}", exc)
        return missing
    _TARGET_WARNED.add(month)
    return missing


def _group_entry_of(display: str, day: str) -> tuple[dict, list[str]] | None:
    """按目标文件的成员名单回查小组条目，返回 (条目, 名单里的人)。

    老板 2026-10-10 重新分组后，「按达标群推断谁属于哪个小组」不再成立：
    新部的人被分到 Q4五百万 / Lina / 杨晶晶 / viki 四个群里，继续按群推断
    会把这几个群的其他人（例如刘春梅）也算进新部，分母也会变成群人数。
    现在以**目标文件的 members 名单**为准：谁在名单里就摊给谁，分母就是名单人数。
    江旭（Sana）按老板 2026-09-18 的口径列进新部名单，数字与此前一致（100/5=20 万）。
    """
    month = day[:7]
    try:
        payload = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = (payload.get(month) or {}).get("entries") or []
    for item in entries:
        members = [str(name) for name in (item.get("members") or []) if name]
        if display in members:
            return item, members
    return None


def group_target_of(display: str, day: str) -> tuple[float, str] | None:
    """按人头找不到月目标时，回查目标文件里带 members 的小组目标。

    返回 (组目标万, 小组名)；找不到返回 None。
    """
    found = _group_entry_of(display, day)
    if not found:
        return None
    entry, _members = found
    try:
        return float(entry.get("target_wan") or 0), str(entry.get("name") or "")
    except (TypeError, ValueError):
        return None


def split_group_target_of(display: str, day: str) -> tuple[float, str, int] | None:
    """小组目标按人头平均分：返回 (每人月目标万, 小组名, 人数)。

    老板 2026-09-18 拍板：新人小组 100 万给新人平均分（分母只算实际
    纳入跟踪的人，目标文件里列了但没跟踪的人不摊）。
    """
    found = _group_entry_of(display, day)
    if not found:
        return None
    entry, counted = found
    if not counted:
        return None
    try:
        total = float(entry.get("target_wan") or 0)
    except (TypeError, ValueError):
        return None
    return round(total / len(counted), 2), str(entry.get("name") or ""), len(counted)


def parse_wa_reached(payload: dict | None) -> tuple[int | None, bool]:
    """conversations.reach_summary → (触达户数, 是否下限)。未覆盖返回 None。"""
    if not isinstance(payload, dict):
        return None, False
    rows = payload.get("rows") or []
    row = next((item for item in rows if isinstance(item, dict) and item.get("row_type") == "summary"), None)
    if not row:
        return None, False
    wa = ((row.get("platform_metrics") or {}).get("whatsapp") or {})
    if wa.get("included") is False:
        return None, False
    value = wa.get("reached_customer_count", row.get("reached_customer_count"))
    if value is None:
        return None, False
    freshness = row.get("data_freshness") or {}
    lower = bool(
        freshness.get("overall_status") == "partial"
        or payload.get("total_is_exact") is False
        or payload.get("is_complete") is False
    )
    return int(value), lower


def parse_intent_count(payload: dict | None) -> int | None:
    """sales.operation_summary 当日新增明确意向。"""
    if not isinstance(payload, dict):
        return None
    rows = payload.get("rows") or []
    row = next((item for item in rows if isinstance(item, dict)), None)
    if not row:
        return None
    metrics = row.get("private_operation_metrics") or {}
    value = metrics.get("new_intent_customer_count")
    if value is None:
        return None
    return int(value)


def iter_mto_image_attachments(messages: list | None, sender_id: int | None = None):
    """遍历本人发送或引用的图片附件，并按附件身份去重。"""
    seen: set[tuple] = set()
    for msg_index, msg in enumerate(messages or []):
        if not isinstance(msg, dict) or msg.get("revoked_at"):
            continue
        if str(msg.get("sender_bot_id") or "") == DUZHAN_BOT_ID:
            continue
        if sender_id is not None and msg.get("sender_user_id") != sender_id:
            continue
        nodes = [msg]
        snapshot = msg.get("quote_snapshot")
        if isinstance(snapshot, dict):
            nodes.append(snapshot)
        for node_index, node in enumerate(nodes):
            if node.get("revoked_at") or str(node.get("message_type") or "").lower() == "recall":
                continue
            if str(node.get("sender_bot_id") or "") == DUZHAN_BOT_ID:
                continue
            node_sender = node.get("sender_user_id")
            if node is not msg and sender_id is not None and node_sender is not None and node_sender != sender_id:
                continue
            attachments = [item for item in (node.get("attachments") or []) if isinstance(item, dict)]
            for key in ("attachment", "image"):
                item = node.get(key)
                if isinstance(item, dict):
                    attachments.append(item)
            for att_index, att in enumerate(attachments):
                attachment_type = str(att.get("attachment_type") or "").lower()
                mime_type = str(att.get("mime_type") or "").lower()
                if attachment_type != "image" and not mime_type.startswith("image/"):
                    continue
                identity = next(
                    (
                        (key, str(att[key]))
                        for key in ("sha256", "storage_key", "id", "url")
                        if att.get(key)
                    ),
                    None,
                )
                if identity is None:
                    identity = ("position", msg_index, node_index, att_index)
                if identity in seen:
                    continue
                seen.add(identity)
                enriched = dict(att)
                if not enriched.get("message_id"):
                    enriched["message_id"] = node.get("id") or msg.get("id") or ""
                yield enriched


def parse_mto_images(messages: list | None, sender_id: int | None = None) -> tuple[int, list[str]]:
    """群历史里非机器人、未撤回的图片。给了 sender_id 则只计本人。"""
    names = [str(att.get("name") or "image") for att in iter_mto_image_attachments(messages, sender_id)]
    return len(names), names


_ITEM_RE = re.compile(
    r"(?m)^\s*(?:订单\s*)?(\d+)\s*[\.．、:：]\s*(.+?)(?=^\s*(?:订单\s*)?\d+\s*[\.．、:：]|\Z)",
    re.S,
)
_AMOUNT_RE = re.compile(
    r"(?:USD|usd|\$|美金|美元)\s*([\d,]+(?:\.\d+)?)|"
    r"([\d,]+(?:\.\d+)?)\s*(?:USD|usd|\$|美金|美元)|"
    r"([\d,]+(?:\.\d+)?)\s*([Ww](?![A-Za-z0-9])|万)"
)
_TASK_EVIDENCE_AMOUNT_RE = re.compile(
    r"(?:USD|RMB|CNY|GBP|EUR|US\$|[$¥￥€£]|美金|美元|人民币)"
    r"\s*[\d,]+(?:\.\d+)?\s*(?:[Ww](?![A-Za-z0-9])|万)?|"
    r"[\d,]+(?:\.\d+)?\s*(?:[Ww](?![A-Za-z0-9])|万)?\s*(?:USD|RMB|CNY|GBP|EUR|US\$|[$¥￥€£]|"
    r"美金|美元|人民币|元|(?:[Ww](?![A-Za-z0-9])|万)(?:\s*(?:RMB|CNY|人民币|元))?)",
    re.I,
)
_ORDER_RE = re.compile(r"XSD-[A-Z0-9-]+", re.I)
_ENGLISH_ENTITY_NAME_RE = re.compile(
    r"\b(Customer|Client|customer|client)\s+("
    r"[A-Z][A-Za-z'’-]*|"
    r"(?:will|may)(?=\s+(?:invoice|order|balance|deposit|payment|account|"
    r"contract|task|profile|is|are|was|were|has|had)\b))",
)
_BLOCK_HINTS = (
    "未回复",
    "约不上",
    "无法登陆",
    "物流",
    "系统问题",
    "合同",
    "mix-up",
    "price mix",
    "退信",
    "undeliver",
)
_URL_RE = re.compile(r"https?://[^\s<>）)]+")
_RELATIVE_DEADLINE_RE = re.compile(
    r"\b(?:in|within)\s+\d+\s+(?:(?:working|business)\s+)?(?:days?|weeks?)\b",
    re.I,
)
_ABSOLUTE_DEADLINE_RE = re.compile(
    r"\b(?:(?:on|by)\s+(?:tomorrow|tonight|next\s+(?:week|month)|"
    r"(?:next|this)\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"(?:the\s+)?end\s+of\s+(?:day|week|month)|eod|"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"(?:,?\s+\d{4})?)|(?:next|this)\s+"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day)\b|"
    r"\bat\s+(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:am|pm))?\b",
    re.I,
)
_HISTORICAL_TIME_RE = re.compile(
    r"\b(?:(?:(?:as\s+of|through|until|up\s+to)\s+)?yesterday|before\s+today|"
    r"previously|earlier)\b",
    re.I,
)
_UNCONFIRMED_STATE_RE = re.compile(
    r"待[^，。；;！？!?\n]{1,8}(?:确认|核实)|"
    r"待确认|等待确认|有待确认|待核实|等待核实|尚未确认|还未确认|"
    r"还没(?:有)?(?:确认|核实)|未经确认|"
    r"未确认|尚未核实|还未核实|未经核实|无法确认|不能确认|无法核实|不能核实|"
    r"没有证据(?:证明|表明)?|"
    r"\b(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:was|were)\s+(?:still\s+)?"
    r"(?:pending|needed|required)(?:\s+(?:yesterday|previously|earlier|before\s+today))?"
    r"(?:[,;:\n]\s*|[.!?]\s*|\s*,?\s*(?:but|and)\s+|\s+)"
    r"(?:(?:it|confirmation|verification)\s+)?"
    r"(?:(?:is|are|remains?)\s+(?:still\s+)?|still\s+)"
    r"(?:pending|needed|required)\b|"
    r"\b(?:pending|awaiting)\s+(?:[a-z][a-z-]*\s+){0,3}"
    r"(?:confirmation|verification)\b|"
    r"\b(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:(?:is|remains|was|were)\s+)?"
    r"(?:still\s+)?pending\b|"
    r"\b(?:no|without)\s+(?:supporting\s+)?(?:evidence|proof|confirmation)\s+"
    r"(?:that|whether|of|for)\b|"
    r"\b(?:cannot|can['’]t|could\s+not|couldn['’]t|unable\s+to)\s+"
    r"(?:confirm|verify|be\s+(?:confirmed|verified))\b|"
    r"\b(?:(?:has|have|had)\s+not|(?:hasn|haven|hadn)['’]t)\s+been\s+"
    r"(?:confirmed|verified)\b|"
    r"\b(?:(?:is|are|was|were)\s+not|(?:isn|aren|wasn|weren)['’]t)\s+"
    r"(?:confirmed|verified)\b|"
    r"\b(?:unconfirmed|unverified)\b|"
    r"\b(?:it\s+is\s+)?(?:unclear|unknown)\s+(?:whether|if|that)\b|"
    r"\bnot\s+(?:yet\s+)?(?:confirmed|verified|reported)(?:\s+as)?\b",
    re.I,
)
_NEEDS_CONFIRMATION_RE = re.compile(
    r"(?:仍|还)?需(?!求)(?:要)?[^，。；;！？!?\n]{0,8}?(?:确认|核实)|"
    r"\b(?:still\s+)?(?:needs?|requires?)\s+(?:[a-z][a-z-]*\s+){0,3}"
    r"(?:confirmation|verification)\b|"
    r"\b(?:is\s+)?waiting\s+for\s+(?:[a-z][a-z-]*\s+){0,3}"
    r"(?:confirmation|verification)\b|"
    r"\b(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:(?:is|remains|was|were)\s+)?"
    r"(?:still\s+)?(?:needed|required)\b",
    re.I,
)
_NEGATED_UNCONFIRMED_RE = re.compile(
    r"\b(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:was|were)\s+(?:still\s+)?"
    r"(?:pending|needed|required)(?:\s+(?:yesterday|previously|earlier|before\s+today))?"
    r"(?:[,;:\n]\s*|[.!?]\s*|\s*,?\s*(?:but|and)\s+|\s+)"
    r"(?:(?:it|confirmation|verification)\s+)?"
    r"(?:(?:is|are|remains?)\s+)?"
    r"(?:not|no\s+longer)\s+(?:pending|needed|required)\b|"
    r"(?:已\s*)?(?:无需|无须|不需(?:要)?|不用|不必)\s*(?:再)?\s*"
    r"(?:待|等待)?[^，。；;！？!?\n]{0,8}?(?:确认|核实)|"
    r"不再\s*(?:需要|等待|待)?[^，。；;！？!?\n]{0,8}?(?:确认|核实)|"
    r"\b(?:not|no\s+longer)\s+(?:pending|awaiting)\s+"
    r"(?:[a-z][a-z-]*\s+){0,3}(?:confirmation|verification)\b|"
    r"\b(?:not|no\s+longer)\s+(?:unconfirmed|unverified)\b|"
    r"\bno\s+(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:(?:is|remains|was|were)\s+)?"
    r"(?:still\s+)?(?:pending|needed|required)\b|"
    r"\b(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
    r"(?:confirmation|verification)\s+(?:(?:is|remains|was|were)\s+)?"
    r"(?:not|no\s+longer)\s+(?:pending|needed|required)\b|"
    r"(?:\band\s+)?\b(?:(?:do|does|did)\s+not|(?:don|doesn|didn)['’]t)\s+(?:need|require)\s+"
    r"(?:[a-z][a-z-]*\s+){0,3}(?:confirmation|verification)\b|"
    r"(?:\band\s+)?\b(?:needs?|requires?)\s+no\s+(?:further\s+)?(?:[a-z][a-z-]*\s+){0,3}"
    r"(?:confirmation|verification)\b|"
    r"(?:\band\s+)?\bno\s+longer\s+(?:needs?|requires?)\s+"
    r"(?:[a-z][a-z-]*\s+){0,3}(?:confirmation|verification)\b|"
    r"(?:\band\s+)?\bno\s+(?:further\s+)?(?:[a-z][a-z-]*\s+){0,3}"
    r"(?:confirmation|verification)\s+"
    r"(?:(?:is|remains|was|were)\s+)?(?:needed|required)\b",
    re.I,
)
_QUESTIONED_COMPLETION_RE = re.compile(
    r"(?:请确认[^，。；;！？!?\n]{0,40})?是否(?:已经|已)?(?:全部|完全|部分)?"
    r"(?:到账|付款|支付|完成)|"
    r"(?:请确认)?[^，。；;！？!?\n]{0,60}(?:已经|已)?(?:全部|完全|部分)?"
    r"(?:到账|付款|支付|完成)(?:了)?吗|"
    r"(?:请确认|请核实|请检查)[^，。；;！？!?\n]{0,60}"
    r"(?:已经|已)?(?:全部|完全|部分)?(?:到账|付款|支付|完成)|"
    r"[^，。；;！？!?\n]{0,80}(?:已经|已)?(?:全部|完全|部分)?"
    r"(?:到账|付款|支付|完成)[^，。；;！？!?\n]{0,20}[？?]|"
    r"(?:^|(?<=[,.;!?，。；！？\n]))\s*(?:"
    r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:confirm|check|verify)"
    r"(?:\s*[,，:：;；\-–—]\s*|\s+)"
    r"(?:(?:whether|if)\s+)?|(?:whether|if)\s+)"
    r"[^,.;!?，。；！？\n]{0,80}"
    r"\b(?:unpaid|unreceived|completed?|complete|done|paid|received)\b"
    r"[^,.;!?，。；！？\n]{0,40}(?:[?.!]|$)|"
    r"(?:^|(?<=[,.;!?，。；！？\n]))\s*(?:has|have|had|is|are|was|were|did|does|do|"
    r"hasn['’]?t|haven['’]?t|hadn['’]?t|isn['’]?t|aren['’]?t|wasn['’]?t|"
    r"weren['’]?t|didn['’]?t|doesn['’]?t|don['’]?t)\s+"
    r"[^,.;!?，。；！？\n]{0,80}\b(?:unpaid|unreceived|completed?|complete|done|paid|received)\b"
    r"[^,.;!?，。；！？\n]{0,40}(?:\?|$)|"
    r"(?:^|(?<=[,.;!?，。；！？\n]))\s*[^,.;!?，。；！？\n]{0,100}"
    r"\b(?:unpaid|unreceived|completed?|complete|done|paid|received)\b"
    r"[^,.;!?，。；！？\n]{0,40}\?",
    re.I,
)
_QUESTION_REQUEST_PREFIX_RE = re.compile(
    r"(?:^|(?<=[,.;!?，。；！？\n]))\s*"
    r"(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?(?:confirm|check|verify)"
    r"(?:\s*[,，:：;；\-–—]\s*|\s+)",
    re.I,
)
_DIRECT_AFFIRMATIVE_ANSWER_RE = re.compile(
    r"^\s*[?？]?\s*(?:(?:yes|yeah|yep|confirmed)\b|(?:是的?|对的?))"
    r"\s*(?:[,，:：.!。！]\s*)?"
    r"(?:(?:thanks|thank\s+you|thx)\b|谢谢(?:你)?|感谢)?\s*[.!。！]?\s*$",
    re.I,
)
_DIRECT_NEGATIVE_ANSWER_RE = re.compile(
    r"^\s*[?？]?\s*(?:(?:no|nope|not\s+yet)\b|(?:否|不是|没有|还没有))"
    r"\s*(?:[,，:：.!。！]\s*)?"
    r"(?:(?:thanks|thank\s+you|thx)\b|谢谢(?:你)?|感谢)?\s*[.!。！]?\s*$",
    re.I,
)
_DIRECT_COMPLETION_ANSWER_RE = re.compile(
    r"^\s*(?:complete(?:d)?|done|paid(?:\s+in\s+full)?|fully\s+paid|received)"
    r"\s*[.!。！]?\s*$",
    re.I,
)
_POLITE_TAIL_RE = re.compile(
    r"\s*(?:[,，;；\-–—]\s*)?(?:(?:thanks|thank\s+you|thx)\b|"
    r"谢谢(?:你)?|感谢)\s*[.!。！]?\s*$",
    re.I,
)
_DIRECT_ANSWER_PREFIX_RE = re.compile(
    r"(?<=[?？])\s*(?:(?:yes|yeah|yep|confirmed|no|nope|not\s+yet)\b|"
    r"(?:是的?|对的?|否|不是|没有|还没有)(?=$|[\s,，.。!！]))"
    r"\s*(?:[,，:：.!。！]\s*)?",
    re.I,
)
_TRAILING_META_QUESTION_RE = re.compile(
    r"\s*[,.:;!?，。：；！？]\s*(?:(?:is\s+there\s+)?anything\s+else|what\s+else|"
    r"any(?:thing)?\s+more)\s*[?？]?\s*$",
    re.I,
)
_EMPHATIC_POSITIVE_RE = re.compile(
    r"\b(?:not\s+(?:only|just|merely)|but\s+also)\b",
    re.I,
)
_CONTRAST_RE = re.compile(r"\b(?:but|however)\b|但|不过|然而", re.I)
_PENDING_MARKER_RE = re.compile(
    r"\b(?:will|shall|should|must|may|might|can|could|would|expected|supposed|"
    r"planned|scheduled|due)\b|计划|预计|预期|安排|准备|将",
    re.I,
)
_FUTURE_SUFFIX_RE = re.compile(
    r"^\s*(?:tomorrow|tonight|later|next\b|this\s+(?:week|month)\b|"
    r"(?:next|this)\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|"
    r"(?:by|on)\s+(?:tomorrow|tonight|next\s+(?:week|month)|"
    r"(?:next|this)\s+(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"(?:mon|tues|wednes|thurs|fri|satur|sun)day|"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"(?:,?\s+\d{4})?|(?:the\s+)?end\s+of\s+(?:day|week|month)|eod)\b|"
    r"at\s+(?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:am|pm))?\b|"
    r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|in\s+\d+\s+(?:days?|weeks?)\b|"
    r"明天|稍后|下周|本周|届时)",
    re.I,
)
_STATUS_PRONOUN_RE = re.compile(
    r"\bit\s+(?=(?:is|are|was|were|has|have|had)\b)",
    re.I,
)
_BUSINESS_REQUIREMENT_LINK_RE = re.compile(
    r"\bit\s+(?:(?:is|was)\s+(?:still\s+)?|remains?\s+)"
    r"(?:required|needed)\s+for\b",
    re.I,
)
_DEADLINE_HINTS = ("今天", "周四", "周五", "周六", "本周", "下周")
_DONE_HINTS = ("已到账", "已付款", "已支付", "已完成", "水单已回传", "已回传")
_STALL_HINTS = (
    "未回复", "约不上", "无法登陆", "卡住", "未解决",
    "尚未付款", "尚未支付", "尚未完成", "尚未到账",
    "未付款", "未支付", "未完成", "未到账",
)
_PROGRESS_HINTS = ("今天可付款", "本周付款", "催收", "推进")
_DONE_HINTS_EN = ("completed", "complete", "done", "paid")
_STALL_HINTS_EN = ("no reply", "stalled", "blocked", "unresolved", "unpaid")
_PROGRESS_HINTS_EN = ("in progress", "progressed", "progress", "follow up", "followup")
_NEGATED_DONE_RE = re.compile(
    r"\b(?:no\s+(?:payments?|funds?|money)\s+"
    r"(?:(?:has|have|had)\s+been\s+|(?:is|are|was|were)\s+)?(?:received|made)|"
    r"(?:(?:it\s+)?(?:is|are|was|were|remains?)\s+)?(?:unpaid|unreceived)|"
    r"(?:(?:(?:will|shall|should|must|may|might|can|could|would|did|does|do)\s+"
    r"(?:not|never)|cannot|can['’]t|couldn['’]t|won['’]t|shouldn['’]t|"
    r"wouldn['’]t|mustn['’]t|not(?:\s+yet)?|never|no\s+longer|"
    r"(?:has|have|had|is|are|was|were)n['’]?t(?:\s+yet)?)"
    r"(?:\s+(?:yet|ever|once|previously|possibly|probably|actually|confirmed|verified|"
    r"reported|reportedly|apparently|as|be|been|being|have|has|had|already|currently|"
    r"fully|completely))*\s+"
    r"(?:(?:partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s*)?"
    r"(?:completed?|done|paid|received?))|"
    r"(?:(?:failed|fails|failing)\s+to|unable\s+to)\s+"
    r"(?:be\s+)?(?:completed?|done|paid|received?)|"
    r"(?:(?:is|are|was|were|remains?)\s+)?yet\s+to\s+be\s+"
    r"(?:completed?|done|paid|received?))\b"
)
_NEGATED_DONE_ZH_RE = re.compile(
    r"(?:(?:不再|尚未|还未|没有|没能|不能|无法|未|不)"
    r"(?:全部|完全|部分)?(?:到账|付款|支付|完成)(?:了)?|"
    r"(?:拒绝|停止|暂停)(?:继续)?(?:到账|付款|支付|完成)(?:了)?)"
)
_NEGATED_COMPLETION_BROAD_RE = re.compile(
    r"\b(?:not|never|no\s+(?:supporting\s+)?(?:evidence|proof|confirmation)|"
    r"without\s+(?:supporting\s+)?(?:evidence|proof|confirmation)|"
    r"unclear|unknown|unconfirmed)\b"
    r"[^,.;!?，。；！？\n]{0,80}?"
    r"\b(?:completed?|complete|done|paid|received)\b",
    re.I,
)
_NEGATED_PROGRESS_RE = re.compile(
    r"\b(?:(?:(?:has|have|had)\s+)?made\s+no(?:\s+further)?\s+progress|"
    r"no(?:\s+further)?\s+progress|not\s+in\s+progress|"
    r"not\s+progress(?:ed|ing)?|without\s+progress|"
    r"(?:has|have|had)n['’]?t\s+progressed)\b"
)
_PENDING_DONE_RE = re.compile(
    r"^\s*complete\b|"
    r"\b(?:will|shall|should|must|may|might|can|could|would)\s+"
    r"(?:(?!(?:not|never)\b)[a-z]+\s+){0,3}"
    r"(?:(?:have|has|had)\s+(?:(?!(?:not|never)\b)[a-z]+\s+){0,3}been\s+|"
    r"be\s+)?"
    r"(?:(?:already|fully|completely|partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s*)?(?:completed?|done|paid|received?)\b|"
    r"\b(?:needs?|plans?|planned|scheduled|expected|supposed|due|aims?|aimed|remains?)"
    r"\s+to\s+(?:(?:have|has|had)\s+(?:(?!(?:not|never)\b)[a-z]+\s+){0,3}been\s+|"
    r"be\s+)?(?:(?:already|fully|completely|partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s*)?(?:completed?|done|paid|received?)\b|"
    r"\bto\s+be\s+(?:(?:already|fully|completely|partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s*)?(?:completed?|done|paid|received?)\b"
)
_PENDING_COMPLETION_BROAD_RE = re.compile(
    r"\b(?:will|shall|should|must|may|might|can|could|would|expected|supposed|"
    r"planned|scheduled|due|aimed?)\b"
    r"(?![^,.;!?，。；！？\n]{0,80}\b(?:now|currently|today)\b)"
    r"[^,.;!?，。；！？\n]{0,80}?"
    r"\b(?:completed?|complete|done|paid|received)\b",
    re.I,
)
_PENDING_DONE_ZH_RE = re.compile(
    r"(?:计划(?:于)?|预计|预期|安排(?:在)?|准备|将在|将于|明天)"
    r"[^，。；;！？!?\n]{0,40}?"
    r"(?:部分(?:完成|付款|支付|到账)|"
    r"(?:完成|付款|支付|到账)(?:\s*(?:\d{1,3}(?:\.\d+)?\s*%|一半|部分))?)|"
    r"(?:今日|今天)\s*(?!已经|现已|已)(?:完成|付款|支付|到账)"
    r"(?!\s*(?:\d{1,3}(?:\.\d+)?\s*%|一半|部分))"
)
_CURRENT_DONE_EN_RE = re.compile(
    r"\b(?:(?:has|have|is|are|was|were)\s+)?(?:now|already|currently|today)\s+"
    r"(?:(?:has|have|is|are)\s+)?(?:been\s+)?(?:fully\s+|completely\s+)?"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b"
    r"(?!\s*\d{1,3}(?:\.\d+)?\s*(?:%|percent\b))"
)
_CURRENT_DONE_SUFFIX_EN_RE = re.compile(
    r"\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\s+"
    r"(?:today|now|already)\b"
)
_PRESENT_FULL_DONE_EN_RE = re.compile(
    r"\b(?:is|are|has|have)\s+(?:(?:now|already|currently)\s+)?(?:been\s+)?"
    r"(?:(?:fully|completely)\s+|100(?:\.0+)?\s*(?:%|percent)\s+)"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b",
    re.I,
)
_CURRENT_PARTIAL_EN_RE = re.compile(
    r"\b(?:(?:(?:has|have|is|are|was|were)\s+)?(?:now|already|currently|today)\s+"
    r"(?:(?:has|have|is|are)\s+)?(?:been\s+)?"
    r"(?:(?:(?:partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s*)"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b|"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b"
    r"\s*\d{1,3}(?:\.\d+)?\s*(?:%|percent\b))|"
    r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)\s+"
    r"(?:(?:has|have|is|are)\s+)?(?:now|already|currently|today)\s+"
    r"(?:been\s+)?(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b)"
)
_CURRENT_DONE_ZH_RE = re.compile(
    r"(?:(?:(?:今日|今天)\s*(?:已经|现已|已)|"
    r"(?:现在已经|目前已经|当前已经|现已|现在已|目前已|当前已|已经)|"
    r"(?:刚刚|刚)\s*(?:已经|已)?|已)\s*"
    r"(?:全部|完全)?(?:到账|付款|支付|完成)|"
    r"(?:全部|完全)?(?:到账|付款|支付|完成)了(?=$|[\s，。；;！？!?\n]))"
)
_ZH_STATE_TRANSITION_RE = re.compile(
    r"((?:部分)?(?:付款|支付|到账|完成))后"
    r"(?=(?:已经|现已|已|现在|目前|当前|今日|今天|刚))"
)
_ZH_UNCONFIRMED_TRANSITION_RE = re.compile(
    r"待[^，。；;！？!?\n]{0,8}(?:确认|核实)\s*后"
    r"(?=(?:已经|现已|已|现在|目前|当前|今日|今天|刚)\s*"
    r"(?:全部|完全)?(?:到账|付款|支付|完成))"
)
_ZH_COMPLETION_PREFIX_RE = re.compile(
    r"已(?=(?:全部|完全|部分)?(?:到账|付款|支付|完成))"
)
_CURRENT_PARTIAL_ZH_RE = re.compile(
    r"(?:(?:今日|今天)\s*(?:已经|现已|已)?|"
    r"(?:现在已经|目前已经|当前已经|现已|现在已|目前已|当前已|已经)|"
    r"(?:刚刚|刚)\s*(?:已经|已)?)\s*"
    r"(?:部分(?:完成|付款|支付|到账)|"
    r"(?:完成|付款|支付|到账)\s*(?:\d{1,3}(?:\.\d+)?\s*%|一半|部分))"
)
_EXPLICIT_DONE_RE = re.compile(
    r"^\s*done\s*[:：-]\s*|"
    r"^\s*done\s+(?:customer|client|invoice|order|balance|deposit|payment|"
    r"account|task|contract)\b|"
    r"^\s*paid\s*(?:[:：]\s*|[-–—]\s+)|"
    r"^\s*paid\s+(?:customer|client|invoice|order|balance|deposit|payment|"
    r"account)\b|"
    r"\b(?:customer|client)\s+(?!(?:will|shall|should|must|may|might|can|could|"
    r"would)\b)(?:[a-z][a-z'’-]*\s+){0,4}paid(?![-\s]+media\b)\s+"
    r"(?:the\s+)?(?:invoice|order|balance|deposit|payment|account|contract)\b|"
    r"\b(?:invoice|order|balance|deposit|payment|account|contract)\s+"
    r"paid(?![-\s]+media\b)\s+by\s+(?:customer|client)\b|"
    r"\b(?:completed?|complete|done|paid|received)\s+on\s+time\b|"
    r"\bcompleted\b|"
    r"\b(?:is|are|was|were|marked|now)\s+(?:complete|done)\b|"
    r"\b(?:has|have|had)\s+(?:already\s+)?(?:been\s+)?"
    r"paid(?![-\s]+media\b)\b|"
    r"\b(?:is|are|was|were|now|already|fully)\s+"
    r"paid(?![-\s]+media\b)\b|"
    r"\b(?:has|have|had)\s+(?:already\s+)?been\s+received\b|"
    r"\b(?:is|are|was|were|now|already|fully)\s+received\b|"
    r"\b(?:paid|received)\s+(?:today|yesterday|tonight|now|already|"
    r"(?:usd|rmb|cny|gbp|eur)\s*[\d,]+(?:\.\d+)?|"
    r"[$¥￥€£]\s*[\d,]+(?:\.\d+)?|"
    r"[\d,]+(?:\.\d+)?\s*(?:usd|rmb|cny|gbp|eur|元|万))\b|"
    r"\b(?:complete|done|paid|received)\s*(?:[.!?;；]|$)"
)
_PERCENT_VALUE_RE = re.compile(r"\d{1,3}(?:\.\d+)?\s*(?:%|percent\b)", re.I)
_PERCENT_QUALIFIER_RE = re.compile(
    r"\b(?:only|about|approximately|roughly)\b(?=\s*\d{1,3}(?:\.\d+)?\s*(?:%|percent\b))|"
    r"约(?=\s*\d{1,3}(?:\.\d+)?\s*%)",
    re.I,
)
_COMPLETION_PERCENT_RE = re.compile(
    r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)"
    r"[^,.;!?，。；！？\n]{0,40}?"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received|"
    r"已完成|完成|已付款|付款|已支付|支付|已到账|到账)|"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received|"
    r"已完成|完成|已付款|付款|已支付|支付|已到账|到账)"
    r"[^,.;!?，。；！？\n]{0,24}?"
    r"(\d{1,3}(?:\.\d+)?)\s*(?:%|percent\b)",
    re.I,
)
_FULL_COMPLETION_PERCENT_RE = re.compile(
    r"100(?:\.0+)?\s*(?:%|percent\b)\s*"
    r"(?:\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b|"
    r"已完成|完成|已付款|付款|已支付|支付|已到账|到账)|"
    r"(?:\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b|"
    r"已完成|完成|已付款|付款|已支付|支付|已到账|到账)"
    r"\s*100(?:\.0+)?\s*(?:%|percent\b)",
    re.I,
)
_FULL_COMPLETION_WORDING_RE = re.compile(
    r"\b(?:(?:all|fully|completely|entirely)\s+"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)|"
    r"(?:completed?|done|paid(?![-\s]+media\b)|received)\s+in\s+full)\b",
    re.I,
)
_INCOMPLETE_FULL_PERCENT_RE = re.compile(
    r"\b(?:almost|nearly|less\s+than|under|below|up\s+to|about|"
    r"approximately|roughly|only)\s+100(?:\.0+)?\s*(?:%|percent\b)\s*"
    r"(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\b|"
    r"\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\s+"
    r"(?:almost|nearly|less\s+than|under|below|up\s+to|about|"
    r"approximately|roughly|only)\s+100(?:\.0+)?\s*(?:%|percent\b)|"
    r"(?:接近|不到|不足|少于|低于|约|大约)\s*100(?:\.0+)?\s*%\s*"
    r"(?:已完成|完成|已付款|付款|已支付|支付|已到账|到账)|"
    r"(?:已完成|完成|已付款|付款|已支付|支付|已到账|到账)\s*"
    r"(?:接近|不到|不足|少于|低于|约|大约)\s*100(?:\.0+)?\s*%",
    re.I,
)
_COMPLETION_SCOPE_RE = re.compile(
    r"\b(?:all|entirely)\s+(?=(?:completed?|complete|done|"
    r"paid(?![-\s]+media\b)|received)\b)|"
    r"\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\s+"
    r"in\s+full\b|"
    r"全部(?=(?:已经|已)?(?:到账|付款|支付|完成))|"
    r"(?<![\u4e00-\u9fff])都(?=(?:已经|已)?(?:到账|付款|支付|完成))",
    re.I,
)
_ZH_COMPLETION_SCOPE_RE = re.compile(
    r"都(?=(?:已经|已)(?:到账|付款|支付|完成))"
)
_ZH_PERSON_NAME_RE = re.compile(
    r"(?:(?:欧阳|司马|上官|诸葛|东方|独孤|南宫|夏侯|皇甫|尉迟|公孙|"
    r"慕容|宇文|长孙|令狐|钟离|司徒|司空)[\u4e00-\u9fff]{1,2}|"
    r"[赵钱孙李周吴郑王冯陈蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    r"谢邹苏潘范彭鲁韦马苗方俞任袁柳史唐薛雷贺倪汤罗毕郝安常于傅齐"
    r"康伍余顾孟黄萧尹姚邵汪毛米戴宋熊纪舒屈项董梁杜阮蓝季贾江郭林"
    r"钟徐邱高夏蔡田樊胡霍万卢莫房解丁邓洪石崔龚程邢陆翁叶白廖曾]"
    r"[\u4e00-\u9fff]{1,2})"
)
_ZH_PLURAL_SCOPE_RE = re.compile(
    r"(?:订单|事项|任务|客户|款项|尾款|项目|问题|工单|合同|记录|货款|回款|"
    r"经销商|代理商|分销商|供应商|门店|店铺|渠道|人员|成员|团队|"
    r"所有人|双方|大家|全员|各方|负责人|同事|员工|销售|伙伴|参会人|相关人)$"
)
_PARTIAL_DONE_RE = re.compile(
    r"\b(?:partially|partly|half(?:way)?|mostly|almost|nearly|largely)\s+"
    r"(?:[a-z]+\s+){0,3}(?:completed?|complete|done|"
    r"paid(?![-\s]+media\b)|received)\b|"
    r"\b(?:completed?|complete|done|paid(?![-\s]+media\b)|received)\s+"
    r"(?:(?:only|about|approximately|roughly)\s+)?(?:half|partially|partly|in\s+part)\b|"
    r"(?:部分(?:已)?(?:完成|付款|支付|到账)|(?:已)?(?:完成|付款|支付|到账)(?:一半|部分)|"
    r"基本完成|大部分完成|接近完成)",
    re.I,
)
_STATUS_SET = frozenset({"done", "stalled", "progress", "planned"})
_TASK_STATUS_TOKENS = tuple(sorted(set(
    _DONE_HINTS
    + _STALL_HINTS
    + _PROGRESS_HINTS
    + _DONE_HINTS_EN
    + _STALL_HINTS_EN
    + _PROGRESS_HINTS_EN
    + _DEADLINE_HINTS
    + (
        "待跟进", "待推进", "需跟进", "继续跟进", "需要确认", "待确认",
        "已处理", "待处理",
        "完成", "预计", "预期", "计划于", "计划", "安排", "准备",
        "将在", "将于", "明天", "截止",
        "completed", "complete", "done", "pending", "follow up", "followup",
        "not yet", "has not", "is not", "was not", "no longer", "not", "never",
        "hasn't", "haven't", "hadn't", "isn't", "aren't", "wasn't", "weren't",
        "cannot", "can't", "couldn't", "won't", "shouldn't", "wouldn't", "mustn't",
        "failed to", "fails to", "unable to",
        "received", "receive", "unreceived",
        "yet to be", "been", "being", "fully", "completely",
        "remained", "remains", "remain", "still",
        "has made no progress", "have made no progress", "had made no progress",
        "made no progress", "not in progress", "without progress",
        "no further progress", "no progress",
        "will be", "shall be", "should be", "must be", "may be", "might be",
        "can be", "could be", "to be",
        "need to", "needs to", "plan to", "plans to", "planned to",
        "scheduled to", "expected to", "supposed to", "due to", "aim to", "aims to", "aimed to",
        "remain to", "remains to", "scheduled", "expected", "needs", "need",
        "plan", "plans", "planned", "supposed", "due", "aim", "aims", "aimed",
        "partially", "partly", "halfway", "half", "mostly", "almost", "nearly",
        "largely", "部分", "一半", "基本", "大部分", "接近",
        "水单", "付款凭证", "支付凭证", "receipt", "evidence",
        "will", "shall", "should", "must", "may", "might", "can", "could", "would", "be",
        "has", "have", "had", "is", "are", "was", "were",
        "today", "tomorrow", "yesterday", "tonight", "this week", "next week", "on time",
        "now", "already", "currently",
        "but", "however", "although", "though", "while", "despite", "then", "that", "whether", "if", "of",
        "昨日", "昨天", "此前", "先前", "今日", "随后", "后来", "之后", "以后", "但", "虽然", "尽管", "仍", "尚",
        "请确认", "请核实", "请检查", "是否", "了吗", "吗",
        "please confirm", "please check", "please verify",
        "thank you", "thanks", "thx", "谢谢", "感谢",
        "刚刚", "刚",
    )
), key=len, reverse=True))


def _msg_body(msg: dict) -> str:
    body = msg.get("body") or msg.get("content") or ""
    if isinstance(body, dict):
        return str(body.get("text") or "")
    return str(body or "")


def _amount_text(title: str) -> str:
    match = _AMOUNT_RE.search(title)
    if not match:
        return ""
    if match.group(1):
        return f"${match.group(1).replace(',', '')}"
    if match.group(2):
        return f"${match.group(2).replace(',', '')}"
    if match.group(3) and match.group(4):
        return f"{match.group(3).replace(',', '')}万"
    return ""


def _deadline_text(title: str) -> str:
    """从标题抠截止提示，没有就空。"""
    for token in _DEADLINE_HINTS:
        if token in title:
            return token
    return ""


def _english_hint_present(text: str, hints: tuple[str, ...]) -> bool:
    return any(
        re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", text)
        for token in hints
    )


def _mask_english_entity_names(text: str) -> str:
    """保留字符位置，同时避免把 Will/May/Paid 等姓名当作状态词。"""
    return _ENGLISH_ENTITY_NAME_RE.sub(
        lambda match: f"{match.group(1)} {'x' * len(match.group(2))}",
        text,
    )


def _mask_emphatic_positive(text: str) -> str:
    """去掉 not only/just/merely 结构中的强调词，并保持字符位置。"""
    return _EMPHATIC_POSITIVE_RE.sub(
        lambda match: " " * len(match.group(0)),
        text,
    )


def _pending_completion_present(text: str) -> bool:
    return bool(_pending_completion_mentions(text))


def _completion_kind(text: str) -> str:
    lowered = text.lower()
    if "到账" in text or "received" in lowered:
        return "received"
    if any(token in text for token in ("付款", "支付")) or "paid" in lowered or "unpaid" in lowered:
        return "paid"
    return "completed"


def _historical_state_mention(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 48):start].lower()
    after = text[end:min(len(text), end + 24)].lower()
    return bool(
        re.search(
            r"\b(?:yesterday|previously|earlier)(?:\s+[a-z]+){0,4}\s*$",
            before,
        )
        or re.match(
            r"^\s*(?:(?:(?:as\s+of|through|until|up\s+to)\s+)?yesterday|"
            r"before\s+today|previously|earlier)\b",
            after,
        )
        or re.search(r"(?:昨日|昨天|此前|先前)[^，。；;！？!?\n]{0,8}$", before)
        or re.match(r"^\s*(?:昨日|昨天|此前|先前)", after)
    )


def _pending_completion_mentions(text: str) -> list[tuple[int, int, str, bool]]:
    lowered = text.lower()
    matches = list(_PENDING_DONE_RE.finditer(lowered))
    matches.extend(
        match
        for match in _PENDING_COMPLETION_BROAD_RE.finditer(text)
        if not _contrast_overrides_pending_completion(text, match)
    )
    matches.extend(_PENDING_DONE_ZH_RE.finditer(text))
    mentions = [
        (
            *match.span(),
            _completion_kind(match.group(0)),
            _historical_state_mention(text, *match.span()),
        )
        for match in matches
    ]
    for pattern in (_FULL_COMPLETION_PERCENT_RE, _FULL_COMPLETION_WORDING_RE):
        for match in pattern.finditer(text):
            future = _FUTURE_SUFFIX_RE.match(text[match.end():])
            if future is None:
                continue
            end = match.end() + future.end()
            mentions.append(
                (
                    match.start(),
                    end,
                    _completion_kind(match.group(0)),
                    _historical_state_mention(text, match.start(), end),
                )
            )
    return mentions


def _contrast_overrides_pending_completion(text: str, match: re.Match) -> bool:
    contrasts = list(_CONTRAST_RE.finditer(match.group(0)))
    if not contrasts:
        return False
    before_contrast = match.group(0)[:contrasts[-1].start()]
    after_contrast = match.group(0)[contrasts[-1].end():]
    if _PENDING_MARKER_RE.search(after_contrast):
        return False
    past_context = text[max(0, match.start() - 32):match.start()] + before_contrast
    if re.search(
        r"\b(?:was|were|had\s+been)\s+(?:planned|scheduled|expected|supposed|due)\b",
        past_context,
        re.I,
    ) and re.match(
        r"\s*(?:has\s+|have\s+|had\s+)?(?:been\s+)?"
        r"(?:completed?|complete|done|paid|received)\b",
        after_contrast,
        re.I,
    ):
        return True
    suffix = text[match.end():]
    suffix = re.split(r"[,.;!?，。；！？\n]", suffix, maxsplit=1)[0]
    return not _FUTURE_SUFFIX_RE.search(suffix)


def _pending_completion_blocks_current(
    text: str,
    current_start: int,
    current_end: int,
    status: str,
    current_kind: str,
) -> bool:
    for start, end, pending_kind, historical in _pending_completion_mentions(text):
        overlaps = start < current_end and current_start < end
        if overlaps or not _current_state_resolves(status, current_kind, pending_kind):
            return True
        if end > current_start and not historical:
            return True
    return False


def _negative_state_mentions(text: str) -> list[tuple[int, int, str, bool]]:
    lowered = text.lower()
    mentions = [
        (
            *match.span(),
            _completion_kind(match.group(0)),
            _historical_state_mention(text, *match.span()),
        )
        for match in _NEGATED_DONE_RE.finditer(lowered)
    ]
    mentions.extend(
        (
            *match.span(),
            _completion_kind(match.group(0)),
            _historical_state_mention(text, *match.span()),
        )
        for match in _NEGATED_COMPLETION_BROAD_RE.finditer(lowered)
    )
    mentions.extend(
        (
            *match.span(),
            _completion_kind(match.group(0)),
            _historical_state_mention(text, *match.span()),
        )
        for match in _NEGATED_DONE_ZH_RE.finditer(text)
    )
    mentions.extend(
        (*match.span(), "progress", _historical_state_mention(text, *match.span()))
        for match in _NEGATED_PROGRESS_RE.finditer(lowered)
    )
    for token in _STALL_HINTS:
        kind = _completion_kind(token) if token.startswith(("未", "尚未")) else "generic"
        mentions.extend(
            (*match.span(), kind, _historical_state_mention(text, *match.span()))
            for match in re.finditer(re.escape(token), text)
        )
    for token in _STALL_HINTS_EN:
        kind = "paid" if token == "unpaid" else "generic"
        mentions.extend(
            (*match.span(), kind, _historical_state_mention(text, *match.span()))
            for match in re.finditer(
                rf"(?<![a-z]){re.escape(token)}(?![a-z])",
                lowered,
            )
        )
    return mentions


def _current_state_resolves(
    status: str,
    current_kind: str,
    negative_kind: str,
) -> bool:
    if current_kind == negative_kind:
        return True
    if current_kind == "received":
        return negative_kind in {"received", "paid", "progress"}
    if status == "progress":
        return negative_kind == "progress"
    if current_kind == "completed":
        return negative_kind in {"completed", "progress", "generic"}
    if current_kind == "paid":
        return negative_kind in {"paid", "progress"}
    return False


def _current_completion_state(text: str) -> tuple[str, str, int, int] | None:
    """返回明确当前状态；不同业务阶段的未完成项不会互相覆盖。"""
    lowered = text.lower()
    candidates: list[tuple[int, int, str, str]] = []
    for pattern, source, status in (
        (_CURRENT_DONE_EN_RE, lowered, "done"),
        (_CURRENT_DONE_SUFFIX_EN_RE, lowered, "done"),
        (_PRESENT_FULL_DONE_EN_RE, lowered, "done"),
        (_FULL_COMPLETION_WORDING_RE, lowered, "done"),
        (_FULL_COMPLETION_PERCENT_RE, lowered, "done"),
        (_CURRENT_PARTIAL_EN_RE, lowered, "progress"),
        (_CURRENT_DONE_ZH_RE, text, "done"),
        (_CURRENT_PARTIAL_ZH_RE, text, "progress"),
    ):
        for match in pattern.finditer(source):
            resolved_status = status
            percent = re.search(r"\d{1,3}(?:\.\d+)?\s*(?:%|percent)", match.group(0))
            if status == "progress" and percent:
                value = re.search(r"\d{1,3}(?:\.\d+)?", percent.group(0))
                if value and float(value.group(0)) >= 100:
                    resolved_status = "done"
            candidates.append(
                (*match.span(), resolved_status, _completion_kind(match.group(0)))
            )
    negatives = _negative_state_mentions(text)
    ordered = sorted(
        candidates,
        key=lambda candidate: (candidate[1], -candidate[0]),
        reverse=True,
    )
    for start, current_end, status, kind in ordered:
        if all(
            not (negative_start < current_end and start < end)
            and (end <= start or historical)
            and _current_state_resolves(status, kind, negative_kind)
            for negative_start, end, negative_kind, historical in negatives
        ):
            return status, kind, start, current_end
    return None


def _partial_completion_mentions(text: str) -> list[tuple[int, int, bool]]:
    mentions = []
    for pattern in (_PARTIAL_DONE_RE, _INCOMPLETE_FULL_PERCENT_RE):
        mentions.extend(
            (*match.span(), _historical_state_mention(text, *match.span()))
            for match in pattern.finditer(text)
        )
    for match in _COMPLETION_PERCENT_RE.finditer(text):
        value = next((part for part in match.groups() if part is not None), None)
        if value is not None and float(value) < 100:
            mentions.append(
                (*match.span(), _historical_state_mention(text, *match.span()))
            )
    return mentions


def _partial_completion_present(text: str) -> bool:
    return bool(_partial_completion_mentions(text))


def _partial_completion_affects_current(
    text: str,
    current_start: int,
    current_end: int,
) -> bool:
    for start, end, historical in _partial_completion_mentions(text):
        if start < current_end and current_start < end:
            return True
        if start >= current_start and not historical:
            return True
    return False


def _active_unconfirmed_matches(text: str) -> list[re.Match]:
    negated = [match.span() for match in _NEGATED_UNCONFIRMED_RE.finditer(text)]
    matches = list(_UNCONFIRMED_STATE_RE.finditer(text))
    matches.extend(_NEEDS_CONFIRMATION_RE.finditer(text))
    return sorted([
        match
        for match in matches
        if not any(start <= match.start() and match.end() <= end for start, end in negated)
    ], key=lambda match: (match.start(), match.end()))


def _continues_current_unconfirmed_state(state: str) -> bool:
    return bool(re.search(
        r"(?:\b(?:but|and)\b\s+|[,;:\n]\s*|[.!?]\s*|\s+)"
        r"(?:(?:it|confirmation|verification)\s+)?"
        r"(?:(?:is|are|remains?)\s+(?:still\s+)?|still\s+)"
        r"(?:pending|needed|required)\b",
        state,
        re.I,
    ))


def _past_unconfirmed_state_mention(text: str, match: re.Match) -> bool:
    state = match.group(0).lower()
    if _continues_current_unconfirmed_state(state):
        return False
    if re.match(
        r"^(?:(?:(?:bank|finance|financial|manual|manager|management|further)\s+)?"
        r"(?:confirmation|verification)\s+(?:was|were)\s+(?:still\s+)?"
        r"(?:pending|needed|required)\b|"
        r"(?:(?:was|were)\s+not|(?:wasn|weren)['’]t)\s+"
        r"(?:confirmed|verified)\b|"
        r"(?:(?:had\s+not|hadn['’]t)\s+been\s+(?:confirmed|verified)\b))",
        state,
    ):
        return True
    if not re.match(
        r"^(?:(?:pending|awaiting|unconfirmed|unverified)\b|"
        r"not\s+(?:yet\s+)?(?:confirmed|verified)\b)",
        state,
    ):
        return False
    before = text[max(0, match.start() - 48):match.start()].lower()
    return bool(
        re.search(
            r"\b(?:(?:was|were)\s+(?:(?:still|already|previously|earlier|once)\s+)?|"
            r"had\s+(?:been|remained)\s+"
            r"(?:(?:still|already|previously|earlier)\s+)?)$",
            before,
        )
    )


def _unconfirmed_state_blocks_current(
    text: str,
    current_start: int,
) -> bool:
    separators = ",.;!?，。；！？\n"
    for match in _active_unconfirmed_matches(text):
        if _historical_state_mention(text, match.start(), match.end()):
            continue
        if match.end() <= current_start:
            if _past_unconfirmed_state_mention(text, match):
                continue
            between = text[match.end():current_start]
            if re.fullmatch(r"\s*后[\s,，;；:：\-–—]*", between):
                continue
            state = match.group(0)
            transition_state = bool(
                re.fullmatch(r"(?:待|等待|有待)[^，。；;！？!?\n]{0,8}(?:确认|核实)", state)
                or re.fullmatch(
                    r"(?:pending|awaiting)\s+(?:[a-z][a-z-]*\s+){0,3}"
                    r"(?:confirmation|verification)",
                    state,
                    re.I,
                )
                or re.fullmatch(
                    r"(?:confirmation|verification)\s+(?:is\s+)?pending",
                    state,
                    re.I,
                )
            )
            if (
                transition_state
                and any(separator in between for separator in ",.;，。；")
                and not re.search(
                    r"\b(?:but|however|although|though|while|despite)\b|"
                    r"但|但是|不过|然而|虽然|尽管",
                    between,
                    re.I,
                )
                and not re.search(
                    r"(?:\bstill|\bremains?|仍|尚)\s*$",
                    text[max(0, match.start() - 16):match.start()],
                    re.I,
                )
            ):
                continue
        suffix = text[match.end():]
        if any(
            token in suffix
            for token in ("水单已回传", "付款凭证已回传", "支付凭证已回传")
        ):
            continue
        clause_start = max(
            (text.rfind(char, 0, match.start()) for char in separators),
            default=-1,
        ) + 1
        ends = [text.find(char, match.end()) for char in separators]
        clause_end = min((end for end in ends if end >= 0), default=len(text))
        clause = text[clause_start:clause_end]
        if _continues_current_unconfirmed_state(match.group(0)):
            return True
        historical_ends = [
            clause_start + historical.end()
            for historical in _HISTORICAL_TIME_RE.finditer(clause)
        ]
        historical_ends.extend(
            clause_start + historical.end()
            for historical in re.finditer(r"昨日|昨天|此前|先前", clause)
        )
        if not (
            match.start() < current_start
            and any(end <= current_start for end in historical_ends)
        ):
            return True
    return False


def _normalized_task_key(item: dict, *, strip_evidence: bool) -> str:
    title = _POLITE_TAIL_RE.sub("", str(item.get("title") or ""))
    preserved_orders = ""
    if strip_evidence:
        title = _URL_RE.sub("", title)
        title = _ORDER_RE.sub("", title)
        title = _TASK_EVIDENCE_AMOUNT_RE.sub("", title)
    else:
        preserved_orders = "".join(
            re.sub(r"[^0-9a-z]+", "", order.lower())
            for order in sorted(set(_ORDER_RE.findall(title)), key=str.lower)
        )
        title = _ORDER_RE.sub("", title)
    question_at = max(title.rfind("?"), title.rfind("？"))
    if question_at >= 0:
        answer = title[question_at + 1:]
        if (
            _DIRECT_AFFIRMATIVE_ANSWER_RE.search(answer)
            or _DIRECT_NEGATIVE_ANSWER_RE.search(answer)
        ):
            title = title[:question_at + 1]
        else:
            answer = re.sub(r"\b(?:funds?|money)\b", "payment", answer, flags=re.I)
            title = title[:question_at + 1] + answer
    title = _RELATIVE_DEADLINE_RE.sub("", title)
    title = _ABSOLUTE_DEADLINE_RE.sub("", title)
    title = _HISTORICAL_TIME_RE.sub("", title)
    title = _ZH_UNCONFIRMED_TRANSITION_RE.sub("", title)
    title = _NEGATED_UNCONFIRMED_RE.sub("", title)
    title = _UNCONFIRMED_STATE_RE.sub("", title)
    title = _NEEDS_CONFIRMATION_RE.sub("", title)
    title = _QUESTION_REQUEST_PREFIX_RE.sub("", title)
    title = _DIRECT_ANSWER_PREFIX_RE.sub("", title)
    title = _TRAILING_META_QUESTION_RE.sub("", title)
    title = _ZH_STATE_TRANSITION_RE.sub(r"\1", title)
    title = _mask_emphatic_positive(title)
    title = _BUSINESS_REQUIREMENT_LINK_RE.sub(" for ", title)
    title = _STATUS_PRONOUN_RE.sub("", title)
    protected_names: list[tuple[str, str]] = []

    def protect_name(match: re.Match) -> str:
        placeholder = f"zzperson{len(protected_names)}zz"
        protected_names.append((placeholder, match.group(2).lower()))
        return f"{match.group(1)} {placeholder}"

    title = _ENGLISH_ENTITY_NAME_RE.sub(protect_name, title)
    title = title.lower()
    title = _COMPLETION_SCOPE_RE.sub("", title)
    for pattern in (
        _NEGATED_DONE_ZH_RE,
        _CURRENT_PARTIAL_EN_RE,
        _CURRENT_PARTIAL_ZH_RE,
        _CURRENT_DONE_EN_RE,
        _CURRENT_DONE_SUFFIX_EN_RE,
        _PRESENT_FULL_DONE_EN_RE,
        _FULL_COMPLETION_WORDING_RE,
        _INCOMPLETE_FULL_PERCENT_RE,
        _FULL_COMPLETION_PERCENT_RE,
        _CURRENT_DONE_ZH_RE,
        _NEGATED_DONE_RE,
        _NEGATED_PROGRESS_RE,
        _PENDING_DONE_RE,
        _PENDING_DONE_ZH_RE,
        _ZH_COMPLETION_PREFIX_RE,
        _PARTIAL_DONE_RE,
    ):
        title = pattern.sub("", title)
    title = _PERCENT_QUALIFIER_RE.sub("", title)
    title = _PERCENT_VALUE_RE.sub("", title)
    for token in _TASK_STATUS_TOKENS:
        lowered = token.lower()
        if lowered.isascii() and any(char.isalpha() for char in lowered):
            title = re.sub(rf"(?<![a-z]){re.escape(lowered)}(?![a-z])", "", title)
        else:
            title = title.replace(lowered, "")
    for placeholder, name in protected_names:
        title = title.replace(placeholder, re.sub(r"[^0-9a-z]+", "", name))
    tokens = re.findall(r"[0-9a-z]+|[\u4e00-\u9fff]+", title)
    index = 0
    normalized_tokens: list[str] = []
    while index < len(tokens):
        repeated = False
        for width in range((len(tokens) - index) // 2, 0, -1):
            if tokens[index:index + width] == tokens[index + width:index + 2 * width]:
                normalized_tokens.extend(tokens[index:index + width])
                index += 2 * width
                repeated = True
                break
        if not repeated:
            normalized_tokens.append(tokens[index])
            index += 1
    normalized = "".join(normalized_tokens)
    return normalized + preserved_orders


def task_key(item: dict) -> str:
    """状态词归一后的精确事项键；保留用于区分订单的单号和金额。"""
    return _normalized_task_key(item, strip_evidence=False)


def _task_base_key(item: dict) -> str:
    """仅用于唯一候选回退匹配；剥离后续可能新增的证据。"""
    return _normalized_task_key(item, strip_evidence=True)


def _is_chinese_people_sequence(value: str) -> bool:
    parts = [part for part in re.split(r"[、和与及]", value) if part]
    if len(parts) > 1:
        return all(_ZH_PERSON_NAME_RE.fullmatch(part) for part in parts)
    counts = {0: 0}
    for start in range(len(value)):
        if start not in counts:
            continue
        for end in range(start + 2, min(len(value), start + 4) + 1):
            if _ZH_PERSON_NAME_RE.fullmatch(value[start:end]):
                counts[end] = max(counts.get(end, 0), counts[start] + 1)
    return counts.get(len(value), 0) > 1


def _task_scope_base_key(item: dict) -> str:
    """仅在唯一候选匹配时，把中文完成句末的“都”视为范围词。"""
    base = _task_base_key(item)
    title = str(item.get("title") or "")
    subject = base[:-1]
    if (
        base.endswith("都")
        and (
            _ZH_PERSON_NAME_RE.fullmatch(subject)
            or _is_chinese_people_sequence(subject)
            or _ZH_PLURAL_SCOPE_RE.search(subject)
            or bool(re.search(r"[a-z0-9]", subject))
        )
        and _ZH_COMPLETION_SCOPE_RE.search(title)
    ):
        return base[:-1]
    return base


def _canonical_amount_evidence(text: str) -> str:
    lowered = text.lower()
    if re.search(r"usd|us\$|\$|美金|美元", lowered):
        currency = "usd"
    elif re.search(r"rmb|cny|[¥￥]|人民币|元", lowered):
        currency = "cny"
    elif re.search(r"gbp|£", lowered):
        currency = "gbp"
    elif re.search(r"eur|€", lowered):
        currency = "eur"
    else:
        currency = "unspecified"
    number = re.search(r"[\d,]+(?:\.\d+)?", text)
    if number is None:
        return re.sub(r"[\s,]+", "", lowered)
    value = Decimal(number.group(0).replace(",", ""))
    if re.search(r"[Ww万]", text):
        value *= 10_000
    normalized = format(value.normalize(), "f")
    return f"{currency}:{normalized}"


def _task_identity_evidence(item: dict) -> tuple[frozenset[str], frozenset[str]]:
    title = str(item.get("title") or "")
    orders = frozenset(match.group(0).upper() for match in _ORDER_RE.finditer(title))
    amounts = frozenset(
        _canonical_amount_evidence(match.group(0))
        for match in _TASK_EVIDENCE_AMOUNT_RE.finditer(title)
    )
    return orders, amounts


def _compatible_task_evidence(left: dict, right: dict) -> bool:
    left_orders, left_amounts = _task_identity_evidence(left)
    right_orders, right_amounts = _task_identity_evidence(right)
    if not (left_orders or left_amounts) or not (right_orders or right_amounts):
        return True
    if left_orders and right_orders:
        return bool(left_orders & right_orders)
    return bool(left_amounts & right_amounts)


def _explicit_status_answer_present(
    text: str,
    current_state: tuple[str, str, int, int] | None,
) -> bool:
    """问句后的片段必须含明确状态，不能把空泛回复当成闭环。"""
    lowered = text.lower()
    return bool(
        current_state is not None
        or _DIRECT_AFFIRMATIVE_ANSWER_RE.search(text)
        or _DIRECT_NEGATIVE_ANSWER_RE.search(text)
        or _DIRECT_COMPLETION_ANSWER_RE.search(text)
        or _EXPLICIT_DONE_RE.search(lowered)
        or _NEGATED_DONE_RE.search(lowered)
        or _NEGATED_COMPLETION_BROAD_RE.search(lowered)
        or _NEGATED_PROGRESS_RE.search(lowered)
        or _partial_completion_present(lowered)
        or _pending_completion_present(lowered)
        or _active_unconfirmed_matches(text)
        or any(token in text for token in _DONE_HINTS + _STALL_HINTS + _PROGRESS_HINTS)
        or _english_hint_present(lowered, _STALL_HINTS_EN + _PROGRESS_HINTS_EN)
    )


def _direct_answer_status(question: str, answer: str) -> str:
    """按问句谓词解释简短的“是/否”，避免把部分完成提前闭环。"""
    affirmative = bool(_DIRECT_AFFIRMATIVE_ANSWER_RE.search(answer))
    negative = bool(_DIRECT_NEGATIVE_ANSWER_RE.search(answer))
    if not affirmative and not negative:
        return ""
    lowered = question.lower()
    asks_partial = _partial_completion_present(lowered)
    asks_negative = bool(
        _NEGATED_DONE_RE.search(lowered)
        or _NEGATED_COMPLETION_BROAD_RE.search(lowered)
        or any(token in question for token in _STALL_HINTS)
        or _english_hint_present(lowered, _STALL_HINTS_EN)
    )
    if affirmative:
        if asks_negative:
            return "stalled"
        if asks_partial:
            return "progress"
        return "done"
    if asks_negative:
        return "progress" if asks_partial else "done"
    return "stalled"


def infer_status(item: dict) -> str:
    """done/stalled/progress/planned。已有合法 status 直接用。"""
    current = str(item.get("status") or "")
    if current in _STATUS_SET:
        return current
    title_text = _TRAILING_META_QUESTION_RE.sub(
        "", _POLITE_TAIL_RE.sub("", str(item.get("title") or ""))
    )
    progress_text = _TRAILING_META_QUESTION_RE.sub(
        "", _POLITE_TAIL_RE.sub("", str(item.get("progress") or ""))
    )
    blob = f"{title_text} {progress_text}"
    status_blob = _mask_emphatic_positive(_mask_english_entity_names(blob))
    lowered = status_blob.lower()
    english_parts = (
        _mask_emphatic_positive(
            _mask_english_entity_names(title_text)
        ).lower(),
        _mask_emphatic_positive(
            _mask_english_entity_names(progress_text)
        ).lower(),
    )
    current_state = _current_completion_state(status_blob)
    questions = list(_QUESTIONED_COMPLETION_RE.finditer(status_blob))
    direct_answer_status = ""
    if questions:
        latest_question = max(questions, key=lambda question: question.end())
        answer_blob = status_blob[latest_question.end():]
        answer_current_state = _current_completion_state(answer_blob)
        if not _explicit_status_answer_present(answer_blob, answer_current_state):
            return "planned"
        direct_answer_status = _direct_answer_status(
            latest_question.group(0), answer_blob
        )
        if not direct_answer_status and _DIRECT_COMPLETION_ANSWER_RE.search(answer_blob):
            direct_answer_status = "done"
        status_blob = answer_blob
        lowered = status_blob.lower()
        english_parts = (lowered,)
        current_state = answer_current_state
    pending = any(_pending_completion_present(text) for text in english_parts)
    partial = _partial_completion_present(lowered)
    if _active_unconfirmed_matches(status_blob) and (
        current_state is None
        or _unconfirmed_state_blocks_current(status_blob, current_state[2])
    ):
        return "stalled"
    if direct_answer_status:
        return direct_answer_status
    if current_state is not None and not _pending_completion_blocks_current(
        status_blob,
        current_state[2],
        current_state[3],
        current_state[0],
        current_state[1],
    ):
        if current_state[0] == "progress" or _partial_completion_affects_current(
            status_blob,
            current_state[2],
            current_state[3],
        ):
            return "progress"
        return current_state[0]
    if any(
        _NEGATED_DONE_RE.search(text) or _NEGATED_COMPLETION_BROAD_RE.search(text)
        for text in english_parts
    ):
        return "stalled"
    if pending:
        return "planned"
    if _NEGATED_DONE_ZH_RE.search(status_blob):
        return "stalled"
    if any(token in blob for token in _STALL_HINTS):
        return "stalled"
    if any(_NEGATED_PROGRESS_RE.search(text) for text in english_parts):
        return "stalled"
    if partial:
        return "progress"
    if any(token in blob for token in _DONE_HINTS) or any(
        _EXPLICIT_DONE_RE.search(text) for text in english_parts
    ):
        return "done"
    if _english_hint_present(lowered, _STALL_HINTS_EN):
        return "stalled"
    if any(token in blob for token in _PROGRESS_HINTS) or _english_hint_present(
        lowered, _PROGRESS_HINTS_EN
    ):
        return "progress"
    return "planned"


def diff_tasks(curr: list, prev: list) -> dict[str, list[dict]]:
    """相对上一档：完成 / 推进 / 停滞 / 新增 / 未回复。"""
    prev_map = {task_key(item): item for item in prev if task_key(item)}
    curr_map = {task_key(item): item for item in curr if task_key(item)}
    matches = {key: key for key in curr_map.keys() & prev_map.keys()}
    unmatched_curr = [key for key in curr_map if key not in matches]
    unmatched_prev = [key for key in prev_map if key not in matches.values()]
    curr_by_base: dict[str, list[str]] = {}
    prev_by_base: dict[str, list[str]] = {}
    for key in unmatched_curr:
        curr_by_base.setdefault(_task_base_key(curr_map[key]), []).append(key)
    for key in unmatched_prev:
        prev_by_base.setdefault(_task_base_key(prev_map[key]), []).append(key)
    for base, curr_keys in curr_by_base.items():
        prev_keys = prev_by_base.get(base, [])
        if len(curr_keys) != 1 or len(prev_keys) != 1:
            continue
        curr_key, prev_key = curr_keys[0], prev_keys[0]
        if _compatible_task_evidence(curr_map[curr_key], prev_map[prev_key]):
            matches[curr_key] = prev_key
    scope_curr_by_base: dict[str, list[str]] = {}
    scope_prev_by_base: dict[str, list[str]] = {}
    for key in curr_map:
        if key not in matches:
            scope_curr_by_base.setdefault(_task_scope_base_key(curr_map[key]), []).append(key)
    for key in prev_map:
        if key not in matches.values():
            scope_prev_by_base.setdefault(_task_scope_base_key(prev_map[key]), []).append(key)
    for base, curr_keys in scope_curr_by_base.items():
        prev_keys = scope_prev_by_base.get(base, [])
        if len(curr_keys) != 1 or len(prev_keys) != 1:
            continue
        curr_key, prev_key = curr_keys[0], prev_keys[0]
        if _compatible_task_evidence(curr_map[curr_key], prev_map[prev_key]):
            matches[curr_key] = prev_key
    out: dict[str, list[dict]] = {
        "completed": [],
        "progressed": [],
        "stalled": [],
        "new": [],
        "unanswered": [],
    }
    for key, item in curr_map.items():
        old = prev_map.get(matches.get(key, ""))
        status = infer_status(item)
        if old is None:
            out["new"].append(item)
            continue
        old_status = infer_status(old)
        if status == "done" and old_status == "done":
            continue
        if status == "done":
            out["completed"].append(item)
        elif status != old_status or (item.get("progress") or "") != (old.get("progress") or ""):
            out["progressed"].append(item)
        else:
            out["stalled"].append(item)
    matched_prev = set(matches.values())
    for key, item in prev_map.items():
        if key not in matched_prev:
            out["unanswered"].append(item)
    return out


def _make_task_item(title: str, created: str) -> dict:
    """标题抽金额/截止/状态。"""
    progress = "待确认"
    status = infer_status({"title": title})
    status_text = _mask_emphatic_positive(_mask_english_entity_names(title))
    current_state = _current_completion_state(status_text)
    if status == "done":
        kind = current_state[1] if current_state is not None else _completion_kind(status_text)
        if kind == "received":
            progress = "已到账"
        elif kind == "paid":
            progress = "已付款"
        else:
            progress = "已完成"
    elif status == "progress" and _partial_completion_present(status_text.lower()):
        progress = "部分完成"
    elif status == "stalled":
        progress = "未确认" if _active_unconfirmed_matches(status_text) else "未完成"
    elif "今天可付款" in title:
        progress = "今天可付款"
    elif "本周付款" in title:
        progress = "本周付款"
    elif "周四付款" in title or "周四或周六" in title:
        progress = "本周内付款"
    item = {
        "title": title,
        "amount": _amount_text(title),
        "progress": progress,
        "deadline": _deadline_text(title),
        "source": created,
        "status": status,
    }
    orders = _ORDER_RE.findall(title)
    if orders:
        item["evidence"] = orders
    return item


def _loose_work_titles(body: str) -> list[str]:
    """无编号的「明日/今日工作安排」按行拆。"""
    if not any(token in body for token in ("明日工作", "今日工作", "工作安排")):
        return []
    chunk = body
    for sep in ("工作安排", "工作内容和进展"):
        if sep in chunk:
            chunk = chunk.split(sep, 1)[-1]
            break
    titles: list[str] = []
    for part in re.split(r"[\n；;]+", chunk):
        title = re.sub(r"\s+", " ", part).strip(" ：:·-")
        if 6 < len(title) < 180:
            titles.append(title[:180])
    return titles


def _named_order_titles(body: str) -> list[str]:
    """「索契：水单已回传」这类冒号行。"""
    titles: list[str] = []
    for raw in body.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if _ITEM_RE.match(line):
            continue
        if "：" not in line and ":" not in line:
            continue
        if any(token in line for token in ("水单", "付款", "订单", "USD", "$", "待付", "万RMB")):
            titles.append(line[:180])
    return titles


def _outreach_titles(body: str) -> list[str]:
    """个人跟进群的触达反馈，不当催款单，但要进今日事项。"""
    blob = re.sub(r"\s+", " ", body).strip()
    lowered = blob.lower()
    if any(token in blob for token in ("今日触达", "有效触达", "邮箱触达")):
        return [blob[:180]]
    if "contacted " in lowered:
        return [blob[:180]]
    return []


def _plain_status_update_title(body: str) -> str:
    """普通群回复只更新已有事项，不单独把闲聊建成任务。"""
    title = re.sub(r"\s+", " ", body).strip()
    if not 3 <= len(title) <= 180 or _ITEM_RE.search(body):
        return ""
    masked = _mask_emphatic_positive(_mask_english_entity_names(title))
    if (
        _current_completion_state(masked) is not None
        or infer_status({"title": title}) == "done"
        or _negative_state_mentions(masked)
        or _partial_completion_present(masked)
        or _pending_completion_present(masked)
        or _active_unconfirmed_matches(masked)
        or _QUESTIONED_COMPLETION_RE.search(masked)
    ):
        return title
    return ""


def _push_evidence(evidence: list[str], text: str) -> None:
    blob = re.sub(r"\s+", " ", text).strip()[:160]
    if blob and blob not in evidence:
        evidence.append(blob)


def parse_owner_reports(
    messages: list | None, sender_id: int | None
) -> tuple[list[dict], list[str], list[str]]:
    """从本人群消息抠催款条目/卡点/单号。无百分比就不编。"""
    if not sender_id:
        return [], [], []
    collections_by_key: dict[str, dict] = {}
    blockers: list[str] = []
    evidence: list[str] = []
    ordered = sorted(
        enumerate(messages or []),
        key=lambda row: (
            str(row[1].get("created_at") or "") if isinstance(row[1], dict) else "",
            row[0],
        ),
    )

    def upsert(title: str, created: str, *, existing_only: bool = False) -> bool:
        item = _make_task_item(title, created)
        key = task_key(item)
        if not key:
            return False
        existing_key = key if key in collections_by_key else None
        if existing_key is None:
            base = _task_base_key(item)
            candidates = [
                old_key
                for old_key, old_item in collections_by_key.items()
                if _task_base_key(old_item) == base
                and _compatible_task_evidence(item, old_item)
            ]
            if len(candidates) == 1:
                existing_key = candidates[0]
        if existing_key is None:
            scope_base = _task_scope_base_key(item)
            candidates = [
                old_key
                for old_key, old_item in collections_by_key.items()
                if _task_scope_base_key(old_item) == scope_base
                and _compatible_task_evidence(item, old_item)
            ]
            if len(candidates) == 1:
                existing_key = candidates[0]
        if existing_key is None and existing_only:
            return False
        existing = collections_by_key.pop(existing_key, None) if existing_key else None
        if existing is not None:
            for field in ("amount", "deadline", "evidence"):
                if not item.get(field) and existing.get(field):
                    item[field] = existing[field]
        collections_by_key[key] = item
        return True

    for _index, msg in ordered:
        if not isinstance(msg, dict) or msg.get("revoked_at"):
            continue
        if msg.get("sender_user_id") != sender_id:
            continue
        msg_type = str(msg.get("message_type") or "")
        if msg_type not in {"text", "", "link"}:
            continue
        body = _msg_body(msg).strip()
        if len(body) < 3:
            continue
        has_url = bool(_URL_RE.search(body))
        plain_update = _plain_status_update_title(body)
        if (
            len(body) < 12
            and "已填写" not in body
            and not has_url
            and not _ITEM_RE.search(body)
            and not plain_update
        ):
            continue
        body = re.sub(
            r"(?<=\S)\s+(?:订单\s*)?(\d{1,2})\s*[\.．、:：]\s+",
            r"\n\1. ",
            body,
        )
        created = str(msg.get("created_at") or "")[:10]
        for hit in _ITEM_RE.finditer(body):
            title = re.sub(r"\s+", " ", hit.group(2)).strip()[:180]
            if title:
                upsert(title, created)
        extra_titles = _loose_work_titles(body) + _named_order_titles(body)
        outreach = _outreach_titles(body)
        extra_titles += outreach
        for title in extra_titles:
            upsert(title, created)
        if plain_update:
            upsert(plain_update, created, existing_only=True)
        for title in outreach:
            _push_evidence(evidence, title)
        for hint in _BLOCK_HINTS:
            if hint.lower() in body.lower():
                snippet = re.sub(r"\s+", " ", body)[:120]
                if snippet not in blockers:
                    blockers.append(snippet)
                break
        for order in _ORDER_RE.findall(body):
            _push_evidence(evidence, order)
        if "水单" in body:
            _push_evidence(evidence, "群内提及水单")
        if "已填写" in body:
            _push_evidence(evidence, "跟进表已填写")
        if "金山文档" in body or "kdocs.cn" in body.lower():
            _push_evidence(evidence, "客户跟进台账")
        for url in _URL_RE.findall(body):
            _push_evidence(evidence, url)
    return list(collections_by_key.values())[-12:], blockers[:5], evidence[:8]


def fetch_channel_history(channel_id: str, day: str, limit: str = "120") -> list[dict] | None:
    """拉昨日中午到现在的完整群消息；任一分页失败则按来源不可用处理。"""
    from datetime import date, timedelta

    from app.vertu.client import run_vertu_sync_json

    if not channel_id:
        return None
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    try:
        page_size = min(max(int(limit), 1), 200)
    except (TypeError, ValueError):
        page_size = 120
    messages: list[dict] = []
    seen_pages: set[tuple] = set()
    offset = 0
    for _page in range(100):
        payload = run_vertu_sync_json(
            [
                "im",
                "+history",
                "--channel-id",
                channel_id,
                "--date-from",
                f"{prev}T12:00:00+08:00",
                "--limit",
                str(page_size),
                "--offset",
                str(offset),
            ],
            timeout=40.0,
        )
        if (
            not isinstance(payload, dict)
            or payload.get("ok") is False
            or not isinstance(payload.get("messages"), list)
        ):
            logger.warning("督战官群历史分页失败 channel={} offset={}", channel_id, offset)
            return None
        raw_page = payload["messages"]
        page = [item for item in raw_page if isinstance(item, dict)]
        signature = tuple(str(item.get("id") or "") for item in page)
        if raw_page and signature in seen_pages:
            logger.warning("督战官群历史分页未推进 channel={} offset={}", channel_id, offset)
            return None
        seen_pages.add(signature)
        messages.extend(page)
        if len(raw_page) < page_size:
            return messages
        offset += len(raw_page)
    logger.warning("督战官群历史超过分页上限 channel={}", channel_id)
    return None


def messages_on_day(messages: list[dict], day: str, tz_name: str) -> list[dict]:
    """只保留指定时区的当日消息。"""
    wanted = datetime.strptime(day, "%Y-%m-%d").date()
    out: list[dict] = []
    for msg in messages:
        raw = str(msg.get("created_at") or "")
        if not raw:
            continue
        try:
            created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.astimezone(ZoneInfo(tz_name)).date() == wanted:
            out.append(msg)
    return out


def parse_daily_reports(messages: list[dict], day: str) -> dict[str, dict]:
    """解析海外日报群正式日报卡片。"""
    reports: dict[str, dict] = {}
    for msg in messages:
        meta = msg.get("metadata") or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("kind") != "daily_report_submission":
            continue
        if str(meta.get("work_date") or "") != day:
            continue
        name = str(meta.get("submitter_name") or "").strip()
        if not name:
            continue
        items = [item for item in (meta.get("today") or []) if isinstance(item, dict)]
        spent = sum(as_float(item.get("spent_hours")) for item in items)
        done = sum(1 for item in items if as_int(item.get("progress")) >= 100)
        reports[name] = {
            "submitted": True,
            "submitted_at": str(msg.get("created_at") or ""),
            "items": items,
            "item_count": len(items),
            "done_count": done,
            "spent_hours": round(spent, 2),
        }
    return reports


def daily_report_texts(messages: list[dict], day: str) -> dict[str, str]:
    """按提交人归集当日日报正文：卡片字段 + 本人发的纯文本（含模板正文）。

    老板 2026-09-30 定版模板后，团队会在日报群里直接贴模板正文，
    所以「有没有正经日报」不能只看卡片：这里把两者都收进来，
    同一个人当天多条按时间顺序拼接（15:00 快报 + 20:00 汇总 = 一份完整文本）。
    """
    buckets: dict[str, list[str]] = {}
    for msg in messages or []:
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        parts: list[str] = []
        if meta.get("kind") == "daily_report_submission":
            if str(meta.get("work_date") or "") != day:
                continue
            uid = str(meta.get("submitter_user_id") or msg.get("sender_user_id") or "")
            parts.extend(
                f"{item.get('label')}：{item.get('value')}"
                for item in (meta.get("fields") or [])
                if isinstance(item, dict)
            )
            parts.extend(str(item) for item in (meta.get("items") or []))
            parts.extend(f"明日重点：{item}" for item in (meta.get("tomorrow") or []))
        else:
            uid = str(msg.get("sender_user_id") or "")
            parts.append(str(msg.get("body") or ""))
        if not uid or not any(part.strip() for part in parts):
            continue
        buckets.setdefault(uid, []).append("\n".join(parts))
    return {uid: "\n".join(chunks) for uid, chunks in buckets.items()}


def fetch_mto(channel_id: str, day: str) -> tuple[int | None, list[str]]:
    """vertu-cli im +history 拉当日群图。"""
    from app.vertu.client import run_vertu_sync_json

    if not channel_id:
        return None, []
    payload = run_vertu_sync_json(
        [
            "im",
            "+history",
            "--channel-id",
            channel_id,
            "--date-from",
            f"{day}T00:00:00+08:00",
            "--limit",
            "80",
        ],
        timeout=40.0,
    )
    if not isinstance(payload, dict):
        return None, []
    return parse_mto_images(payload.get("messages") or [])


def _agent_im_path() -> Path | None:
    settings = get_settings()
    raw = settings.duzhan_agent_im_html
    path = Path(raw) if raw else settings.data_dir / "runtime" / "agent_im_report.html"
    return path if path.is_file() else None


def _activity_from_member(row: dict, *, daily: bool) -> dict:
    """统一周报 memberRows 与日报 members 字段。轮数=Standard提问+OpenCode+Harness。"""
    standard = int(row.get("standardTurns") or 0)
    open_code = int(row.get("openCodeCalls") or row.get("openCode") or 0)
    harness = int(row.get("harnessCalls") or row.get("harness") or 0)
    turns = standard + open_code + harness
    return {
        "im_sent": int(row.get("directSent") or 0) + int(row.get("groupSent") or 0),
        "agent_calls": turns,
        "department": str(row.get("department") or ""),
        "first_at": str(row.get("firstAt") or ""),
        "last_at": str(row.get("lastAt") or ""),
        "turns": turns,
        "daily": daily,
    }


def parse_agent_im_activity(html: str, period: str = "current_week") -> dict[str, dict]:
    """HTML payload → {姓名: 使用记录}。有 members 当日口径；否则 memberRows 按 period。"""
    match = _PAYLOAD_RE.search(html or "")
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    out: dict[str, dict] = {}
    members = payload.get("members")
    if isinstance(members, list) and members:
        for row in members:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if name:
                out[name] = _activity_from_member(row, daily=True)
        return out
    for row in payload.get("memberRows") or []:
        if not isinstance(row, dict) or row.get("period") != period:
            continue
        name = str(row.get("name") or "")
        if name:
            out[name] = _activity_from_member(row, daily=False)
    return out


def load_vps_activity() -> dict[str, dict]:
    """读 Agent/IM 分析 HTML。缺文件返回空。"""
    path = _agent_im_path()
    if path is None:
        return {}
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("督战官读 Agent/IM 报告失败: {}", exc)
        return {}
    rows = parse_agent_im_activity(html, "current_week")
    if not rows:
        rows = parse_agent_im_activity(html, "complete_week")
    return rows


def _vps_for_owner(
    owner: Owner, activity: dict[str, dict]
) -> tuple[int | None, int | None, str, str, int | None, bool]:
    names = [owner.cli_name, owner.target_name, owner.display, *owner.vps_names]
    for key in names:
        if key and key in activity:
            item = activity[key]
            turns = item.get("turns")
            return (
                int(item.get("im_sent") or 0),
                int(item.get("agent_calls") or 0),
                str(item.get("first_at") or ""),
                str(item.get("last_at") or ""),
                int(turns) if turns is not None else 0,
                bool(item.get("daily")),
            )
    return None, None, "", "", None, False


def _channel_id(owner: Owner) -> str:
    from app.duzhan import GROUPS

    for group in GROUPS:
        if group.name == owner.group:
            return group.channel_id
    return ""


def _group_timezone(owner: Owner) -> str:
    """负责人所在督战群时区。"""
    from app.duzhan import GROUPS

    group = next((item for item in GROUPS if item.name == owner.group), None)
    return group.tz if group else "Asia/Shanghai"


def _history_ids(owner: Owner) -> list[str]:
    """达标群 + 个人客户跟进群。"""
    ids: list[str] = []
    main = _channel_id(owner)
    if main:
        ids.append(main)
    if owner.follow_channel_id and owner.follow_channel_id not in ids:
        ids.append(owner.follow_channel_id)
    return ids


def vemory_aliases(owner: Owner) -> set[str]:
    """会议 owner_name 与达标群主的对应名。"""
    names = {owner.display, owner.cli_name, owner.target_name, *owner.vps_names}
    if owner.display == "Viki":
        names.add("尤文静")
    if owner.display == "Lina":
        # 老板 2026-09-18 确认：丽娜就是 Lina（早会里写“冯磊 & 丽娜”）
        names.update({"DEHDAHOUMAIMA", "Lina", "丽娜"})
    return {item for item in names if item}


def match_daily_report(owner: Owner, reports: dict[str, dict]) -> dict:
    """按负责人别名匹配日报。"""
    for alias in vemory_aliases(owner):
        if alias in reports:
            return reports[alias]
    return {}


def match_vemory(owner: Owner, meetings: list[dict] | None) -> tuple[list[dict], bool]:
    """按负责人切当日会议。None = 拉取失败。"""
    if meetings is None:
        return [], False
    aliases = vemory_aliases(owner)
    hits = []
    for item in meetings:
        owner_name = str(item.get("owner") or item.get("owner_name") or "")
        if owner_name not in aliases:
            continue
        hits.append(
            {
                "name": item.get("name") or "",
                "link": item.get("link") or "",
                "meeting_id": item.get("id") or item.get("meeting_id") or "",
                "start_time": item.get("start_time") or item.get("start_record_time") or "",
                "end_time": item.get("end_time") or item.get("end_record_time") or "",
                "duration_minutes": meeting_minutes(item),
            }
        )
    return hits, True


def fetch_vemory_openapi(day: str) -> list[dict] | None:
    """Vemory OpenAPI：按人拉当日会议名。接口不回 audio_url。"""
    api_key = os.environ.get("VEMORY_OPENAPI_KEY", "").strip()
    if not api_key:
        return None
    settings = get_settings()
    url = (settings.vemory_openapi_url or "https://vemory-meet.vemory.io").rstrip("/")
    start, end = f"{day} 00:00:00", f"{day} 23:59:59"
    out: list[dict] = []
    any_ok = False
    for owner in OWNERS:
        if not owner.vemory_user_id:
            continue
        try:
            response = httpx.post(
                f"{url}/openapi/getUserMeetingTodos",
                json={
                    "user_id": int(owner.vemory_user_id),
                    "start_time": start,
                    "end_time": end,
                    "timezone": "Asia/Shanghai",
                },
                headers={"X-API-Key": api_key, "Content-Type": "application/json"},
                timeout=30.0,
            )
            body = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("督战官 Vemory OpenAPI 失败 {}: {}", owner.display, exc)
            continue
        if response.status_code != 200 or body.get("status") != 0:
            logger.warning("督战官 Vemory OpenAPI 非0 {}: {}", owner.display, body.get("err_code"))
            continue
        any_ok = True
        for meeting in ((body.get("data") or {}).get("meetings")) or []:
            if not isinstance(meeting, dict):
                continue
            mid = str(meeting.get("meeting_id") or "")
            out.append(
                {
                    "id": mid,
                    "name": meeting.get("meeting_name") or "",
                    "owner": owner.display,
                    "start_time": meeting.get("start_record_time") or meeting.get("start_time") or "",
                    "end_time": meeting.get("end_record_time") or meeting.get("end_time") or "",
                    "duration_minutes": meeting_minutes(meeting),
                    "duration_seconds": meeting.get("duration_seconds") or 0,
                    "link": "",
                }
            )
    return out if any_ok else None


async def _vemory_day_async(day: str) -> list[dict] | None:
    from app.meeting.vemory import list_dealer_meetings, meeting_detail

    rows, error = await list_dealer_meetings(day, day)
    if error and not rows:
        return None
    aliases: set[str] = set()
    for owner in OWNERS:
        aliases |= vemory_aliases(owner)
    wanted = [row for row in rows if str(row.get("owner_name") or "") in aliases]
    out: list[dict] = []
    for row in wanted:
        mid = str(row.get("id") or "")
        detail: dict = {}
        link = ""
        if mid:
            loaded, _ = await meeting_detail(mid)
            detail = loaded or {}
            link = str(detail.get("audio_url") or "")
        minutes = meeting_minutes({**row, **detail})
        if not is_timed_vemory(mid, str(row.get("name") or ""), minutes):
            continue
        out.append(
            {
                "id": mid,
                "name": row.get("name") or "",
                "owner": row.get("owner_name") or "",
                "start_time": detail.get("start_time") or row.get("start_time") or "",
                "end_time": detail.get("end_time") or row.get("end_time") or "",
                "duration_minutes": minutes,
                "link": link,
            }
        )
    return out


def is_timed_vemory(ext_id: str, title: str, minutes: float) -> bool:
    """工时只收有时长的 Vemory 录音。VPS 即时场、快速会议不要。"""
    if minutes <= 0:
        return False
    if str(ext_id).startswith("vps:"):
        return False
    if "快速会议" in (title or ""):
        return False
    return True


def records_to_vemory_rows(records: list) -> list[dict]:
    """meeting_records 行 → 督战官 Vemory 列表。owner 取参与人第一名。"""
    out: list[dict] = []
    for row in records:
        if hasattr(row, "title"):
            title = str(row.title or "")
            ext_id = str(row.external_id or "")
            duration = getattr(row, "duration_minutes", 0) or 0
            raw_people = getattr(row, "participants_json", "") or "[]"
        else:
            title = str(row.get("title") or row.get("name") or "")
            ext_id = str(row.get("external_id") or row.get("id") or "")
            duration = row.get("duration_minutes") or 0
            raw_people = row.get("participants_json") or row.get("participants") or []
        if isinstance(raw_people, str):
            try:
                people = json.loads(raw_people)
            except json.JSONDecodeError:
                people = []
        else:
            people = raw_people or []
        owner = ""
        for person in people:
            if isinstance(person, dict) and person.get("name"):
                owner = str(person.get("name") or "")
                break
            if isinstance(person, str) and person.strip():
                owner = person.strip()
                break
        minutes = meeting_minutes({"duration_minutes": duration})
        if not is_timed_vemory(ext_id, title, minutes):
            continue
        out.append(
            {
                "id": ext_id,
                "name": title,
                "owner": owner,
                "start_time": "",
                "end_time": "",
                "duration_minutes": minutes,
                "link": "",
            }
        )
    return out


def fetch_vemory_from_db(day: str) -> list[dict] | None:
    """工作台 meeting_records，与 /api/meeting-center 同源。"""
    try:
        from sqlmodel import Session, select

        from app.database import get_engine
        from app.models.meeting import MeetingRecord

        with Session(get_engine()) as session:
            rows = list(
                session.exec(select(MeetingRecord).where(MeetingRecord.meeting_date == day)).all()
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官读 meeting_records 失败: {}", exc)
        return None
    if not rows:
        return None
    return records_to_vemory_rows(rows)


def fetch_vemory_day(day: str) -> list[dict] | None:
    """当日会议只收有时长的场次。优先工作台库；OpenAPI 无时长不用。"""
    db_rows = fetch_vemory_from_db(day)
    if db_rows:
        return db_rows
    try:
        rows = asyncio.run(_vemory_day_async(day))
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官拉 Vemory CLI 失败: {}", exc)
    return None


def score_row(row: PersonRow) -> PersonRow:
    """按今日任务完成率打分。回款只记缺口，不进主分。"""
    gaps: list[str] = []
    tasks = list(row.collections or [])
    report_items = list((row.daily_report or {}).get("items") or [])
    if report_items:
        total = len(report_items)
        done = sum(1 for item in report_items if as_int(item.get("progress")) >= 100)
        rate = sum(
            min(max(as_int(item.get("progress")), 0), 100)
            for item in report_items
        ) / (total * 100)
    else:
        total = len(tasks)
        done = sum(1 for item in tasks if infer_status(item) == "done")
        rate = done / total if total else 0.0
    evidenced = min(len(row.evidence or []), 4)
    for item in tasks:
        if item.get("amount") or item.get("evidence"):
            evidenced += 1
    overdue = 0
    for item in tasks:
        blob = f"{item.get('title') or ''} {item.get('progress') or ''} {item.get('deadline') or ''}"
        if infer_status(item) != "done" and ("今天可付款" in blob or item.get("deadline") == "今天"):
            overdue += 1
    if total == 0:
        # 日报群取数失败时不能算「未报」：那是把「读不到」当成「没交」（2026-09-20 审查）。
        # 交了模板日报（含只在群里贴正文的）也不算未报，缺什么由模板缺项来说话。
        if not row.daily_report and getattr(row, "daily_report_ok", True):
            gaps.append("未报今日任务")
    elif done < total:
        prefix = "日报完成" if report_items else "任务完成"
        gaps.append(f"{prefix}{done}/{total}")
    # 模板合规：缺项进缺口，红黑榜理由直接可读（老板 2026-09-30：按模板检查）
    missing = list(((row.daily_report or {}).get("template") or {}).get("missing") or [])
    if row.daily_report and missing:
        gaps.append(f"日报缺{len(missing)}项")
    if evidenced == 0:
        gaps.append("证据不足")
    if overdue:
        gaps.append(f"逾期{overdue}项")
    if row.mtd_wan is None:
        gaps.append("累计已录单未出")
    elif row.mtd_wan <= 0:
        gaps.append("本月已录单0")
    row.score = round(rate * 100 + evidenced * 5 - overdue * 10, 2)
    row.gaps = gaps
    return row


def perf_score(row: PersonRow) -> float | None:
    """业绩达成分（0–120）：累计已录单 ÷ 累计应达 ×100；缺口径返回 None。

    老板 2026-09-18 拍板：红榜要过程完成度和业绩综合，两个都得有，
    所以业绩分只作为红榜的一半权重，不覆盖过程分。
    """
    if row.perf_arrived_wan is None or not row.rolling_target_wan:
        return None
    return round(min(float(row.perf_arrived_wan) / float(row.rolling_target_wan) * 100, 120.0), 1)


def combined_score(row: PersonRow) -> float:
    """红榜综合分：过程分与业绩分各半；业绩无口径时只按过程分（并标注待确认）。"""
    perf = perf_score(row)
    if perf is None:
        return round(float(row.score), 2)
    return round(float(row.score) * 0.5 + perf * 0.5, 2)


def rank_red_black(people: list[PersonRow]) -> tuple[list[dict], list[dict]]:
    """红榜 = 过程 + 业绩综合 TOP3；其余里待改进 2 个进黑榜。"""
    ranked = sorted(
        people,
        key=lambda item: (-combined_score(item), -item.score, item.display),
    )
    red = [_board_item(item) for item in ranked[:3]]
    rest = ranked[3:]
    rest.sort(key=lambda item: (combined_score(item), -len(item.gaps), item.display))
    black = [_board_item(item) for item in rest[:2]]
    return red, black


def _board_item(row: PersonRow) -> dict:
    return {
        "display": row.display,
        "group": row.group,
        "score": row.score,
        "mtd_wan": row.mtd_wan,
        "wa_reached": row.wa_reached,
        "intent_count": row.intent_count,
        "mto_count": row.mto_count,
        "reason": "；".join(row.gaps[:2]) if row.gaps else "过程与回款均有数",
        # 红榜双口径：过程完成度 + 业绩达成（老板 2026-09-18 要求两个都得有）
        "perf_score": perf_score(row),
        "combined_score": combined_score(row),
        "rolling_target_wan": row.rolling_target_wan,
        "group_scope": bool(row.group_target_wan),
    }


def _mcp_unwrap(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return None
    if result.get("error"):
        logger.warning("AINativeSales 错误: {}", result.get("error"))
        return None
    content = ((result.get("result") or {}).get("content") or [{}])[0]
    text = content.get("text") if isinstance(content, dict) else None
    if not text:
        return result if "rows" in result else None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def mcp_call(name: str, arguments: dict) -> dict | None:
    """调 AINativeSales MCP tools/call。个人令牌禁止传 vps_user_id。"""
    settings = get_settings()
    token = settings.aisales_mcp_token
    url = settings.aisales_mcp_url
    if not token or not url:
        logger.warning("AINativeSales MCP 未配置 token/url，本次取数按待确认处理: {}", name)
        return None
    try:
        resp = httpx.post(
            url,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-03-26",
            },
            timeout=20.0,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("AINativeSales 请求失败 {}: {}", name, exc)
        return None
    if resp.status_code != 200:
        # 非 200 以前是静默 None → 十个人的 WhatsApp/意向/工时全变「待确认」且无告警
        logger.error(
            "AINativeSales 非 200（{} {}）: {}", resp.status_code, name, (resp.text or "")[:200]
        )
        return None
    raw = resp.text
    payload = None
    for line in raw.splitlines():
        if line.startswith("data: "):
            try:
                payload = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            break
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            break
    return _mcp_unwrap(payload)


def fetch_personal_okr() -> list[dict]:
    """vertu-cli sales +personal-okr 海外渠道本月。"""
    from app.vertu.client import run_vertu_sync_json

    payload = run_vertu_sync_json(
        [
            "sales",
            "+personal-okr",
            "--period",
            "this_month",
            "--dept-l1",
            "海外渠道",
            "--limit",
            "50",
        ],
        timeout=45.0,
    )
    if not isinstance(payload, dict):
        return []
    return [row for row in (payload.get("rows") or []) if isinstance(row, dict)]


def _mtd_wan(owner: Owner, rows: list[dict]) -> float | None:
    matched: list[dict] = []
    aliases = vemory_aliases(owner)
    for row in rows:
        name = str(row.get("salesperson") or "")
        dept = str(row.get("dept_l2") or "")
        if name and name in aliases:
            matched.append(row)
        elif owner.display == "Safae" and "safae" in name.lower():
            matched.append(row)
        elif owner.dept_l2 and dept == owner.dept_l2:
            matched.append(row)
    if not matched:
        return None
    try:
        if any(item.get("sales_amount") in (None, "") or isinstance(item.get("sales_amount"), bool)
               for item in matched):
            return None
        amounts = [float(item["sales_amount"]) for item in matched]
        total = sum(amounts)
        return round(total / 10000, 2) if all(math.isfinite(value) for value in amounts) and math.isfinite(total) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _parallel_map(func, items: list, workers: int, label: str) -> list:
    """并发映射，保持输入顺序；单项异常只记日志并留 None。

    采集全是 I/O（IM 拉群、MCP、Qwen OCR），串行时一轮要跑几分钟；并发度按上游
    承受力给上限（IM/MCP 6~8，单机推理的 Qwen 只给 2），一个源慢或挂不影响其它源。
    """
    items = list(items)
    if not items:
        return []
    workers = max(1, min(int(workers or 1), len(items)))
    if workers == 1:
        results = []
        for item in items:
            try:
                results.append(func(item))
            except Exception as exc:  # noqa: BLE001
                logger.warning("{} 失败: {}", label, exc)
                results.append(None)
        return results
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdca") as pool:
        futures = [pool.submit(func, item) for item in items]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("{} 失败: {}", label, exc)
                results.append(None)
        return results


def _parallel_map_deadline(func, items: list, workers: int, label: str, budget_seconds: int) -> list:
    """带总预算的并发映射：超时没跑完的项按 None 返回（宁可写「待确认」，不拖过整点）。

    背景：MTO 图片 OCR 是整轮采集的瓶颈（2026-09-18 实测 44 张图、并发 2 ≈ 9 分钟）。
    采集是整点前 15 分钟起跑，一旦超时就会让 15:00 的推送拿到半张表，所以给 OCR 单独
    设时间预算，到点没读完的直接记「待确认」。未完成的线程不再等（shutdown 不阻塞）。
    """
    items = list(items)
    if not items:
        return []
    workers = max(1, min(int(workers or 1), len(items)))
    timeout = None
    try:
        timeout = int(budget_seconds)
    except (TypeError, ValueError):
        timeout = None
    if timeout is not None and timeout <= 0:
        timeout = None
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pdca")
    try:
        futures = [pool.submit(func, item) for item in items]
        _, pending = wait(futures, timeout=timeout)
        if pending:
            logger.warning(
                "{} 超出 {}s 预算，{} 项未完成按待确认处理", label, timeout, len(pending)
            )
        results = []
        for future in futures:
            if future in pending:
                results.append(None)
                continue
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                logger.warning("{} 失败: {}", label, exc)
                results.append(None)
        return results
    finally:
        # 不等未完成的线程：它们最多再占用一会儿 Qwen，本轮采集不再被拖住。
        pool.shutdown(wait=False, cancel_futures=True)


def _safe_fetch(name: str, fn):
    """单数据源兜底：失败只记日志返回 None，绝不让一个源拖垮整轮采集。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官 {} 失败: {}", name, exc)
        return None


def _subject(owner: Owner) -> dict | None:
    if owner.employee_id:
        return {"employee_id": owner.employee_id}
    if owner.department_id:
        return {"department_id": owner.department_id}
    return None


def _mcp_bundle(subject: dict, period: dict) -> tuple:
    """一人的三项 MCP 查询（触达/经营/客户明细）并发预取用。

    mcp_call 自身失败只返回 None，三项互不影响，与串行版本语义一致。
    """
    reach = mcp_call(
        "business.query",
        {
            "domain": "conversations",
            "query_mode": "reach_summary",
            "subject": subject,
            "period": period,
            "platform": "WhatsApp",
        },
    )
    ops = mcp_call("sales.operation_summary", {"subject": subject, "period": period})
    customers = mcp_call(
        "business.query",
        {
            "domain": "conversations",
            "query_mode": "customers",
            "subject": subject,
            "period": period,
            "filters": {"platform": "WhatsApp", "page_size": 50},
        },
    )
    return reach, ops, customers


def _review_mto_inputs(
    inputs: list[tuple],
    *,
    quota_by_owner: dict[str, int],
    max_images: int,
    workers: int,
    budget: int,
    qwen_enabled: bool,
) -> dict[str, tuple[int | None, list[str], list[dict]]]:
    """按人轮转单图任务，共享全局并发与预算，避免大批图片独占工作线程。"""
    from app.mto_ocr import (
        finalize_mto_review,
        review_mto_attachment,
        select_mto_attachments,
    )

    selected: dict[str, tuple[list[dict], bool]] = {}
    for display, messages, sender_id in inputs:
        limit = max(int(max_images or 8), int(quota_by_owner.get(display) or 0), 1)
        selected[display] = select_mto_attachments(messages, sender_id, limit)

    if not qwen_enabled:
        return {
            display: finalize_mto_review(attachments, [], truncated, qwen_enabled=False)
            for display, (attachments, truncated) in selected.items()
        }

    queue: list[tuple[str, int, dict]] = []
    largest = max((len(attachments) for attachments, _truncated in selected.values()), default=0)
    for index in range(largest):
        for display, (attachments, _truncated) in selected.items():
            if index < len(attachments):
                queue.append((display, index, attachments[index]))
    reviewed = _parallel_map_deadline(
        lambda item: review_mto_attachment(item[2]),
        queue,
        workers,
        "督战官 MTO OCR",
        budget,
    )
    grouped: dict[str, list[dict | None]] = {
        display: [None] * len(attachments)
        for display, (attachments, _truncated) in selected.items()
    }
    for item, result in zip(queue, reviewed):
        grouped[item[0]][item[1]] = result
    return {
        display: finalize_mto_review(
            attachments,
            grouped[display],
            truncated,
            qwen_enabled=True,
        )
        for display, (attachments, truncated) in selected.items()
    }


def collect_ledger(day: str) -> dict:
    """踩点采集：达标群+跟进群+日报群、WhatsApp MCP、Vemory、VPS、回款。失败字段留空。"""
    ledger = empty_ledger(day)
    # 长假期间照常推送，但一律不处罚（不列黑榜、不记扣罚）——渲染侧读这个标记。
    from app.workday_calendar import penalty_exempt

    ledger["_penalty_exempt"] = penalty_exempt(day)
    monthly_targets = load_month_targets(day)
    # 月度目标单一来源：文件缺当月条目时告警（每月一次），仅兜底不静默。
    warn_target_fallback(day, monthly_targets)
    period = {"start_date": day, "end_date": day}
    # 早会待办：按天+群渲染一次，逐人带进台账（数据源 app/meeting_todos.json）
    from app.meeting_todos import block_for_group as _todos_for_group
    _todo_cache: dict[str, str] = {}

    settings = get_settings()
    report_channel = settings.todo_group_channel_id
    # 四个互不依赖的源并发抓（原来串行，一轮白等几十秒）；失败各自兜底。
    sources = {
        "personal-okr": lambda: fetch_personal_okr(),
        "Agent/IM 报告": lambda: load_vps_activity(),
        "Vemory": lambda: fetch_vemory_day(day),
        "日报群拉取": lambda: fetch_channel_history(report_channel, day, "300"),
    }
    names = list(sources)
    # 按名字取值而不是下标：将来调整源顺序也不会把 A 的数据接到 B 的字段上。
    fetched = dict(
        zip(
            names,
            _parallel_map(
                lambda name: _safe_fetch(name, sources[name]), names, len(names), "督战官采集"
            ),
        )
    )
    okr_rows = fetched["personal-okr"] or []
    vps_activity = fetched["Agent/IM 报告"] or {}
    vemory_rows = fetched["Vemory"]
    report_messages = fetched["日报群拉取"]
    # report_messages 为 None = 日报群取数失败（_safe_fetch 吞异常），
    # 与「今天没人交日报」必须区分开：前者写「待确认」，后者才是「未见日报」。
    daily_reports_ok = report_messages is not None
    if not daily_reports_ok:
        logger.warning("日报群取数失败，日报字段一律写「待确认」，不参与扣分")
    daily_reports = parse_daily_reports(report_messages, day) if report_messages else {}
    # 模板正文按提交人归集（卡片字段 + 群里贴的模板文本），逐人做合规核对
    report_texts = daily_report_texts(report_messages, day) if report_messages else {}
    channel_ids = sorted({cid for item in OWNERS for cid in _history_ids(item) if cid})
    history_list = _parallel_map(
        lambda cid: fetch_channel_history(cid, day, "200"),
        channel_ids,
        8,
        "督战官拉群历史",
    )
    histories = dict(zip(channel_ids, history_list))
    # 每人三项 MCP 查询并发预取（串行时这是除 OCR 外的第二个大头）。
    from app.duzhan_departments import is_task_only

    subjects = {item.display: _subject(item) for item in OWNERS
                if not is_task_only(item.group, item.display)}
    queried = [item for item in OWNERS if subjects.get(item.display)]
    bundles = _parallel_map(
        lambda item: _mcp_bundle(subjects[item.display], period),
        queried,
        6,
        "督战官 MCP",
    )
    mcp_cache: dict[str, tuple] = {
        item.display: (bundle or (None, None, None))
        for item, bundle in zip(queried, bundles)
    }
    # 当日消息过滤 + 图片 OCR：Qwen 是单机推理，按人并发预取（默认 3，避免打爆网关）。
    owner_msgs: dict[str, list[dict]] = {}
    owner_history_ok: dict[str, bool] = {}
    ocr_inputs: list[tuple] = []
    for owner in OWNERS:
        if not owner.im_user_id:
            continue
        raw_msgs: list[dict] = []
        ids = _history_ids(owner)
        owner_history_ok[owner.display] = bool(ids) and all(isinstance(histories.get(cid), list) for cid in ids)
        for cid in ids:
            raw_msgs.extend(histories.get(cid) or [])
        try:
            day_msgs = messages_on_day(raw_msgs, day, _group_timezone(owner))
        except Exception as exc:  # noqa: BLE001
            logger.warning("督战官当日消息过滤失败 {}: {}", owner.display, exc)
            day_msgs = []
            owner_history_ok[owner.display] = False
        owner_msgs[owner.display] = day_msgs
        if owner_history_ok[owner.display] and not is_task_only(owner.group, owner.display):
            ocr_inputs.append((owner.display, day_msgs, owner.im_user_id))

    # 三个 OCR 开关都用 getattr 兜底：采集是关键路径，Settings 少一个字段也不能整轮失败。
    ocr_workers = getattr(settings, "mto_ocr_workers", 3)
    ocr_budget = getattr(settings, "mto_ocr_budget_seconds", 420)
    ocr_max_images = getattr(settings, "mto_ocr_max_images", 8)
    from app.duzhan_monthly_metrics import metrics_for_owner

    monthly_by_group = {group: metrics_for_owner(group, day) for group in {owner.group for owner in OWNERS}}
    quota_by_owner = {owner.display: monthly_by_group[owner.group]["mto_daily_count"] for owner in OWNERS}

    # OCR 单独给时间预算：图片按负责人轮转进入同一队列；超时的人保留已核明细，
    # 总数仍写「待确认」，绝不把部分结果当完整结果。
    ocr_cache = _review_mto_inputs(
        ocr_inputs,
        quota_by_owner=quota_by_owner,
        max_images=ocr_max_images,
        workers=ocr_workers,
        budget=ocr_budget,
        qwen_enabled=bool(getattr(settings, "qwen_api_key", "")),
    )
    people: list[PersonRow] = []
    for owner in OWNERS:
        row = PersonRow(
            group=owner.group,
            display=owner.display,
            target_wan=owner.target_wan,
            mtd_wan=_mtd_wan(owner, okr_rows),
        )
        (
            row.vps_im_sent,
            row.vps_agent_calls,
            row.vps_first,
            row.vps_last,
            row.vps_turns,
            row.vps_daily,
        ) = _vps_for_owner(owner, vps_activity)
        row.vemory, row.vemory_ok = match_vemory(owner, vemory_rows)
        row.daily_report = match_daily_report(owner, daily_reports)
        row.daily_report_ok = daily_reports_ok
        row.history_ok = owner_history_ok.get(owner.display, False)
        # 模板合规核对：卡片交了但正文没按模板 → 记缺项；只有群里正文、没有卡片 → 也算已交
        _report_text = report_texts.get(str(owner.im_user_id or ""), "")
        if row.daily_report:
            row.daily_report["template"] = check_template(_report_text, submitter=owner.display)
        elif _report_text and looks_like_report(_report_text):
            row.daily_report = {
                "submitted": True,
                "submitted_at": "",
                "items": [],
                "item_count": 0,
                "done_count": 0,
                "spent_hours": 0.0,
                "from": "text",
                "template": check_template(_report_text, submitter=owner.display),
            }
        if owner.group not in _todo_cache:
            _todo_cache[owner.group] = _todos_for_group(day, owner.group)
        row.meeting_todos = _todo_cache[owner.group]
        msgs: list[dict] = owner_msgs.get(owner.display, [])
        try:
            if owner.im_user_id:
                row.mto_count, row.mto_names, row.mto_quotes = ocr_cache.get(
                    owner.display
                ) or (None, [], [])
                row.collections, row.blockers, row.evidence = parse_owner_reports(
                    msgs, owner.im_user_id
                )
                # 业绩三关键词：到账（系统已录单）/ 水单（已付款未到账）/ 意向
                row.perf_arrived_wan = row.mtd_wan
                task_only = is_task_only(owner.group, owner.display)
                buckets = parse_performance_buckets(
                    msgs, owner.im_user_id, arrived_wan=row.mtd_wan
                )
                if not task_only:
                    image_slips, image_intents, image_pending = image_performance_facts(row.mto_quotes, day)
                    row.perf_slip = list(buckets.get("slip") or []) + image_slips
                    row.perf_intent = list(buckets.get("intent") or []) + image_intents
                    for evidence_text in image_pending:
                        _push_evidence(row.evidence, evidence_text)
                    pending_images = pending_group_image_count(msgs, owner.im_user_id, row.mto_quotes)
                    if pending_images:
                        _push_evidence(
                            row.evidence,
                            f"群图片{pending_images}张待核（未计入系统已录单业绩）",
                        )
                    for item in (row.perf_slip + row.perf_intent)[:4]:
                        if item.get("amount_text"):
                            _push_evidence(row.evidence, item["amount_text"])
                    for name in row.mto_names[:4]:
                        _push_evidence(row.evidence, f"MTO图 {name}")
                    if row.daily_report:
                        _push_evidence(
                            row.evidence,
                            "海外日报已交"
                            f"{row.daily_report.get('item_count', 0)}项/"
                            f"{row.daily_report.get('spent_hours', 0)}h",
                        )
                else:
                    # 三位仅追待办成员仍计正式 OKR 业绩；群内水单/意向只留待核证据，
                    # 不进入 MTO/日报/WhatsApp 专项催办。
                    for key, label in (("slip", "水单"), ("intent", "意向")):
                        for item in list(buckets.get(key) or [])[:4]:
                            amount_text = str(item.get("amount_text") or "金额待核")
                            _push_evidence(
                                row.evidence,
                                f"群内{label}证据待核（未计入系统已录单业绩）：{amount_text}",
                            )
                    pending_images = pending_group_image_count(msgs, owner.im_user_id, [])
                    if pending_images:
                        _push_evidence(
                            row.evidence,
                            f"群图片{pending_images}张待核（未计入系统已录单业绩）",
                        )
            else:
                row.mto_count, row.mto_names, row.mto_quotes = None, [], []
        except Exception as exc:  # noqa: BLE001
            logger.warning("督战官拉群消息失败 {}: {}", owner.display, exc)
            row.mto_count, row.mto_names, row.mto_quotes = None, [], []
            row.history_ok = False
        subject = subjects.get(owner.display)
        if subject:
            reach, ops, customers = mcp_cache.get(owner.display, (None, None, None))
            row.wa_reached, row.wa_lower_bound = parse_wa_reached(reach)
            row.intent_count = parse_intent_count(ops)
            if customers is None:
                row.hours_minutes = None
                row.hours_band = ""
                row.hours_window = ""
                row.hours_parts = {}
            else:
                payload = asdict(row)
                payload["vps_weekdays"] = 1 if row.vps_daily else workdays_this_week(day)
                est = estimate_hours(parse_wa_hour_chats(customers), payload)
                row.hours_minutes = est["minutes"]
                row.hours_band = est["band"]
                row.hours_window = est["window"]
                row.hours_parts = est["parts"]
        # 滚动日目标：月目标 ÷ 当月天数 × 已过天数（缺月目标写待确认）
        # 月目标单一来源＝目标文件（用户每月更新）；文件缺条目才兜底并告警。
        month_target, row.target_source = resolve_month_target(owner, day, monthly_targets)
        if row.target_source == "group":
            # 新人小组：老板 2026-09-18 拍板 100 万按人头平均分；
            # 同时保留组口径字段，渲染侧能标出“这是小组目标摊下来的”。
            split = split_group_target_of(owner.display, day)
            if split:
                row.group_target_wan = split[0] * split[2]
                row.group_target_name = split[1]
        progress = daily_target_progress(month_target, row.mtd_wan, day)
        row.target_wan = month_target
        row.daily_target_wan = progress["daily_target"]
        row.rolling_target_wan = progress["rolling_target"]
        row.days_elapsed = progress["days_elapsed"]
        row.days_in_month = progress["days_in_month"]
        row.target_gap_wan = progress["gap"]
        row.target_ahead = progress["ahead"]
        policy = monthly_by_group[owner.group]
        row.mto_daily_goal, row.mto_min_wan = policy["mto_daily_count"], policy["mto_min_wan"]
        if policy["source"] == "saved" and not is_task_only(owner.group, owner.display):
            from app.duzhan_monthly_metrics import recheck_row

            checked = recheck_row(asdict(row), {"mto_daily_count": row.mto_daily_goal, "mto_min_wan": row.mto_min_wan})
            row.mto_count, row.mto_quotes = checked["mto_count"], checked["mto_quotes"]
            row.mto_names = checked.get("mto_names", [])
        people.append(score_row(row))
    from app.duzhan_departments import task_scope_row

    ledger["people"] = [task_scope_row(asdict(item)) for item in people]
    red, black = rank_red_black([row for row in people if not is_task_only(row.group, row.display)])
    ledger["red"] = red
    ledger["black"] = black
    return ledger


def person_for(group_name: str, ledger: dict | None) -> dict | None:
    """按群名取台账第一行（兼容旧调用）。"""
    rows = people_for(group_name, ledger)
    return rows[0] if rows else None


def people_for(group_name: str, ledger: dict | None) -> list[dict]:
    """按群名取全部按人台账行。"""
    if not ledger:
        return []
    return [item for item in (ledger.get("people") or []) if item.get("group") == group_name]
