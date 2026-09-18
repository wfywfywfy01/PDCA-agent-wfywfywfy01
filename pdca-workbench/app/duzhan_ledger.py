# -*- coding: utf-8 -*-
"""督战官台账：vertu-cli 回款 + AINativeSales WhatsApp/意向 + 红黑榜。

对标催收机器人：台账是唯一数据源，模板只读台账。Vemory 等接口到再填。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from loguru import logger

from app.config import get_settings

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


# 新人小组：邓琳莹/Safae/王宇彤/张月馨。张倩、李浩然、邢哲夫、陈鹏飞不在此名单。
OWNERS: tuple[Owner, ...] = (
    Owner(
        "新人小组业绩达标群",
        "邓琳莹",
        cli_name="邓琳莹",
        employee_id=36,
        im_user_id=14247,
        follow_channel_id="8bb5ae97-3ffb-42e7-869d-c5cef358510a",
    ),
    Owner(
        "新人小组业绩达标群",
        "Safae",
        cli_name="Safae Ben M'hamed",
        employee_id=305,
        im_user_id=14460,
        vps_names=("Safae Ben M'hamed", "Safae"),
        follow_channel_id="8cf4b40b-0e60-4819-9120-a22f3c808a00",
    ),
    Owner(
        "新人小组业绩达标群",
        "王宇彤",
        cli_name="王宇彤",
        employee_id=278,
        im_user_id=14344,
        vemory_user_id=121,
        follow_channel_id="792c8c09-4c4f-4162-b0cb-45f6d009b504",
    ),
    Owner(
        "新人小组业绩达标群",
        "张月馨",
        cli_name="张月馨",
        employee_id=559,
        # ponytail: 月馨群仅 14660 回飞书表；组织搜索无名。错了再改。
        im_user_id=14660,
        follow_channel_id="743227fa-07cc-4bfd-be74-9242aaa56e71",
    ),
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
        "Lina业绩达标群",
        "Lina",
        cli_name="DEHDAHOUMAIMA",
        target_name="Lina",
        employee_id=171,
        im_user_id=13050,
        vps_names=("DEHDAHOUMAIMA",),
        target_wan=400,
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
    collections: list[dict] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    # 滚动日目标（月目标 ÷ 当月天数 × 已过天数）；Nove 为 None 时渲染“待确认”。
    daily_target_wan: float | None = None
    rolling_target_wan: float | None = None
    days_elapsed: int | None = None
    days_in_month: int | None = None
    target_gap_wan: float | None = None
    target_ahead: bool | None = None
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
    minutes = min(covered, STANDARD_DAY_MIN)
    gap = max(STANDARD_DAY_MIN - covered, 0.0)
    hours = round(minutes / 60.0, 2)
    std = round(STANDARD_DAY_MIN / 60.0, 1)
    ratio = covered / STANDARD_DAY_MIN if STANDARD_DAY_MIN else 0
    if (
        chats == []
        and row.get("mto_count") is None
        and not collect_n
        and meeting_n == 0
        and row.get("vps_turns") is None
    ):
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
        "minutes": round(minutes, 1),
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
    if lang == "en":
        text = (
            f"{progress['daily_target']} wan/day (day {progress['days_elapsed']}/"
            f"{progress['days_in_month']}, cumulative due {progress['rolling_target']} wan)"
        )
        if progress.get("gap") is not None:
            lead = "ahead" if progress["ahead"] else "behind"
            text += f" | {lead} {abs(progress['gap'])} wan"
        return text
    text = (
        f"{progress['daily_target']} 万/天（第 {progress['days_elapsed']}/"
        f"{progress['days_in_month']} 天，累计应达 {progress['rolling_target']} 万）"
    )
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
_PERF_AMOUNT_RE = re.compile(
    r"(?:USD|usd|\$|美金|美元)\s*([\d,]+(?:\.\d+)?)|"
    r"([\d,]+(?:\.\d+)?)\s*(?:USD|usd|\$|美金|美元)|"
    r"([\d]+(?:\.\d+)?)\s*([Ww万])|"
    r"([\d]+(?:\.\d+)?)\s*(?:万?RMB|人民币|元)"
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
        if not isinstance(msg, dict) or msg.get("revoked_at"):
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
        return {"text": "$" + format(usd, "g"), "wan": round(usd * RATE_CNY / 10000, 1), "usd": usd}
    if match.group(3):
        try:
            wan = float(match.group(3).replace(",", ""))
        except ValueError:
            return {"text": "", "wan": None, "usd": None}
        return {"text": format(wan, "g") + "万", "wan": wan, "usd": None}
    if match.group(5):
        try:
            yuan = float(match.group(5).replace(",", ""))
        except ValueError:
            return {"text": "", "wan": None, "usd": None}
        return {"text": format(yuan, "g") + "元", "wan": round(yuan / 10000, 2), "usd": None}
    return {"text": "", "wan": None, "usd": None}


def load_month_targets(day: str) -> dict[str, float]:
    """本地月度目标（万）。CLI target_amount 当前全 0，先用这张表。"""
    month = day[:7]
    try:
        payload = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    entries = (payload.get(month) or {}).get("entries") or []
    out: dict[str, float] = {}
    for item in entries:
        name = str(item.get("name") or "")
        if name:
            out[name] = float(item.get("target_wan") or 0)
    return out


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


def parse_mto_images(messages: list | None, sender_id: int | None = None) -> tuple[int, list[str]]:
    """群历史里非机器人、未撤回的图片。给了 sender_id 则只计本人。"""
    names: list[str] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("revoked_at"):
            continue
        if str(msg.get("sender_bot_id") or "") == DUZHAN_BOT_ID:
            continue
        if str(msg.get("message_type") or "") != "image":
            continue
        if sender_id is not None and msg.get("sender_user_id") != sender_id:
            continue
        for att in msg.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            if str(att.get("attachment_type") or "") != "image":
                continue
            names.append(str(att.get("name") or "image"))
    return len(names), names


_ITEM_RE = re.compile(
    r"(?m)^\s*(?:订单\s*)?(\d+)\s*[\.．、:：]\s*(.+?)(?=^\s*(?:订单\s*)?\d+\s*[\.．、:：]|\Z)",
    re.S,
)
_AMOUNT_RE = re.compile(
    r"(?:USD|usd|\$|美金|美元)\s*([\d,]+(?:\.\d+)?)|"
    r"([\d,]+(?:\.\d+)?)\s*(?:USD|usd|\$|美金|美元)|"
    r"(\d+(?:\.\d+)?)\s*([Ww万])"
)
_ORDER_RE = re.compile(r"XSD-[A-Z0-9-]+")
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
_DEADLINE_HINTS = ("今天", "周四", "周五", "周六", "本周", "下周")
_DONE_HINTS = ("已到账", "已付款", "已支付", "已完成", "水单已回传", "已回传")
_STALL_HINTS = ("未回复", "约不上", "无法登陆", "卡住", "未解决")
_PROGRESS_HINTS = ("今天可付款", "本周付款", "催收", "推进")
_STATUS_SET = frozenset({"done", "stalled", "progress", "planned"})


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
        return f"{match.group(3)}万"
    return ""


def _deadline_text(title: str) -> str:
    """从标题抠截止提示，没有就空。"""
    for token in _DEADLINE_HINTS:
        if token in title:
            return token
    return ""


def task_key(item: dict) -> str:
    """同一事项的短键，用来做档间 diff。"""
    return re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:24]


def infer_status(item: dict) -> str:
    """done/stalled/progress/planned。已有合法 status 直接用。"""
    current = str(item.get("status") or "")
    if current in _STATUS_SET:
        return current
    blob = f"{item.get('title') or ''} {item.get('progress') or ''}"
    if any(token in blob for token in _DONE_HINTS):
        return "done"
    if any(token in blob for token in _STALL_HINTS):
        return "stalled"
    if any(token in blob for token in _PROGRESS_HINTS):
        return "progress"
    return "planned"


def diff_tasks(curr: list, prev: list) -> dict[str, list[dict]]:
    """相对上一档：完成 / 推进 / 停滞 / 新增 / 未回复。"""
    prev_map = {task_key(item): item for item in prev if task_key(item)}
    curr_map = {task_key(item): item for item in curr if task_key(item)}
    out: dict[str, list[dict]] = {
        "completed": [],
        "progressed": [],
        "stalled": [],
        "new": [],
        "unanswered": [],
    }
    for key, item in curr_map.items():
        old = prev_map.get(key)
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
    for key, item in prev_map.items():
        if key not in curr_map:
            out["unanswered"].append(item)
    return out


def _make_task_item(title: str, created: str) -> dict:
    """标题抽金额/截止/状态。"""
    progress = "待确认"
    if any(token in title for token in _DONE_HINTS):
        progress = "已到账"
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
    }
    item["status"] = infer_status(item)
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
    collections: list[dict] = []
    blockers: list[str] = []
    evidence: list[str] = []
    seen: set[str] = set()
    for msg in messages or []:
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
        if len(body) < 12 and "已填写" not in body and not has_url:
            continue
        body = re.sub(
            r"(?<=\S)\s+(?:订单\s*)?(\d{1,2})\s*[\.．、:：]\s+",
            r"\n\1. ",
            body,
        )
        created = str(msg.get("created_at") or "")[:10]
        for hit in _ITEM_RE.finditer(body):
            title = re.sub(r"\s+", " ", hit.group(2)).strip()[:180]
            key = title[:24]
            if not title or key in seen:
                continue
            seen.add(key)
            collections.append(_make_task_item(title, created))
        extra_titles = _loose_work_titles(body) + _named_order_titles(body)
        outreach = _outreach_titles(body)
        extra_titles += outreach
        for title in extra_titles:
            key = title[:24]
            if key in seen:
                continue
            seen.add(key)
            collections.append(_make_task_item(title, created))
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
    return collections[:12], blockers[:5], evidence[:8]


def fetch_channel_history(channel_id: str, day: str, limit: str = "120") -> list[dict]:
    """拉昨日中午到现在的群消息，避免漏掉晚间更新。"""
    from datetime import date, timedelta

    from app.vertu.client import run_vertu_sync_json

    if not channel_id:
        return []
    prev = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
    payload = run_vertu_sync_json(
        [
            "im",
            "+history",
            "--channel-id",
            channel_id,
            "--date-from",
            f"{prev}T12:00:00+08:00",
            "--limit",
            limit,
        ],
        timeout=40.0,
    )
    if not isinstance(payload, dict):
        return []
    return [item for item in (payload.get("messages") or []) if isinstance(item, dict)]


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
        spent = sum(float(item.get("spent_hours") or 0) for item in items)
        done = sum(1 for item in items if int(item.get("progress") or 0) >= 100)
        reports[name] = {
            "submitted": True,
            "submitted_at": str(msg.get("created_at") or ""),
            "items": items,
            "item_count": len(items),
            "done_count": done,
            "spent_hours": round(spent, 2),
        }
    return reports


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
        names.update({"DEHDAHOUMAIMA", "Lina"})
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
        done = sum(1 for item in report_items if int(item.get("progress") or 0) >= 100)
        rate = sum(
            min(max(int(item.get("progress") or 0), 0), 100)
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
        gaps.append("未报今日任务")
    elif done < total:
        prefix = "日报完成" if report_items else "任务完成"
        gaps.append(f"{prefix}{done}/{total}")
    if evidenced == 0:
        gaps.append("证据不足")
    if overdue:
        gaps.append(f"逾期{overdue}项")
    if row.mtd_wan is None:
        gaps.append("累计回款未出")
    elif row.mtd_wan <= 0:
        gaps.append("本月回款0")
    row.score = round(rate * 100 + evidenced * 5 - overdue * 10, 2)
    row.gaps = gaps
    return row


def rank_red_black(people: list[PersonRow]) -> tuple[list[dict], list[dict]]:
    """红榜 TOP3，其余里待改进 2 个进黑榜。"""
    ranked = sorted(people, key=lambda item: (-item.score, item.display))
    red = [_board_item(item) for item in ranked[:3]]
    rest = ranked[3:]
    rest.sort(key=lambda item: (item.score, -len(item.gaps), item.display))
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
        logger.warning("AINativeSales 请求失败: {}", exc)
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
    for row in rows:
        name = str(row.get("salesperson") or "")
        dept = str(row.get("dept_l2") or "")
        if owner.cli_name and name == owner.cli_name:
            matched.append(row)
        elif owner.display == "Safae" and "safae" in name.lower():
            matched.append(row)
        elif owner.dept_l2 and dept == owner.dept_l2:
            matched.append(row)
    if not matched:
        return None
    total = sum(float(item.get("sales_amount") or 0) for item in matched)
    return round(total / 10000, 2)


def _subject(owner: Owner) -> dict | None:
    if owner.employee_id:
        return {"employee_id": owner.employee_id}
    if owner.department_id:
        return {"department_id": owner.department_id}
    return None


def collect_ledger(day: str) -> dict:
    """踩点采集：达标群+跟进群+日报群、WhatsApp MCP、Vemory、VPS、回款。失败字段留空。"""
    ledger = empty_ledger(day)
    monthly_targets = load_month_targets(day)
    period = {"start_date": day, "end_date": day}
    try:
        okr_rows = fetch_personal_okr()
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官 personal-okr 失败: {}", exc)
        okr_rows = []
    try:
        vps_activity = load_vps_activity()
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官 Agent/IM 报告失败: {}", exc)
        vps_activity = {}
    try:
        vemory_rows = fetch_vemory_day(day)
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官 Vemory 失败: {}", exc)
        vemory_rows = None
    report_channel = get_settings().todo_group_channel_id
    try:
        report_messages = fetch_channel_history(report_channel, day, "300")
        daily_reports = parse_daily_reports(report_messages, day)
    except Exception as exc:  # noqa: BLE001
        logger.warning("督战官日报群拉取失败: {}", exc)
        daily_reports = {}
    histories: dict[str, list[dict]] = {}
    channel_ids = {cid for item in OWNERS for cid in _history_ids(item) if cid}
    for channel_id in channel_ids:
        try:
            histories[channel_id] = fetch_channel_history(channel_id, day, "200")
        except Exception as exc:  # noqa: BLE001
            logger.warning("督战官拉群历史失败 {}: {}", channel_id, exc)
            histories[channel_id] = []
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
        try:
            msgs: list[dict] = []
            for cid in _history_ids(owner):
                msgs.extend(histories.get(cid) or [])
            msgs = messages_on_day(msgs, day, _group_timezone(owner))
            if owner.im_user_id:
                from app.mto_ocr import review_mto_images

                row.mto_count, row.mto_names, row.mto_quotes = review_mto_images(
                    msgs, owner.im_user_id
                )
                row.collections, row.blockers, row.evidence = parse_owner_reports(
                    msgs, owner.im_user_id
                )
                # 业绩三关键词：到账（系统已录单）/ 水单（已付款未到账）/ 意向
                row.perf_arrived_wan = row.mtd_wan
                buckets = parse_performance_buckets(
                    msgs, owner.im_user_id, arrived_wan=row.mtd_wan
                )
                row.perf_slip = buckets.get("slip") or []
                row.perf_intent = buckets.get("intent") or []
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
                row.mto_count, row.mto_names, row.mto_quotes = 0, [], []
        except Exception as exc:  # noqa: BLE001
            logger.warning("督战官拉群消息失败 {}: {}", owner.display, exc)
            row.mto_count, row.mto_names, row.mto_quotes = None, [], []
        subject = _subject(owner)
        if subject:
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
            row.wa_reached, row.wa_lower_bound = parse_wa_reached(reach)
            ops = mcp_call(
                "sales.operation_summary",
                {"subject": subject, "period": period},
            )
            row.intent_count = parse_intent_count(ops)
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
        month_target = row.target_wan
        if month_target is None:
            month_target = monthly_targets.get(owner.display)
        progress = daily_target_progress(month_target, row.mtd_wan, day)
        row.target_wan = month_target
        row.daily_target_wan = progress["daily_target"]
        row.rolling_target_wan = progress["rolling_target"]
        row.days_elapsed = progress["days_elapsed"]
        row.days_in_month = progress["days_in_month"]
        row.target_gap_wan = progress["gap"]
        row.target_ahead = progress["ahead"]
        people.append(score_row(row))
    ledger["people"] = [asdict(item) for item in people]
    red, black = rank_red_black(people)
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
