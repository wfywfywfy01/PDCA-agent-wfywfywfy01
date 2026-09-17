# -*- coding: utf-8 -*-
"""C转B 跟进群：工作日 20:00 晚追一次，读 WhatsApp MCP，不跑经销商三追。"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from loguru import logger

from app.duzhan import is_duzhan_workday
from app.duzhan_ledger import mcp_call
from app.vps_im_push import push_duzhan_message

TZ_SHANGHAI = "Asia/Shanghai"
FOCUS_KINDS = frozenset({"汽车", "转B"})
_CAR_RE = re.compile(
    r"汽车|买车|用车|车主|GTS|BRABUS|预售车|轿车|(?<![a-z])car(?![a-z])|(?<![a-z])auto(?![a-z])",
    re.I,
)
_CTOB_RE = re.compile(
    r"转\s*B|C转B|询盘|弃单|线索|进线|官网|自拓|总代|经销|代理|想做|开店|"
    r"批发|渠道|维修店|也卖|dealer|distributor|wholesale",
    re.I,
)
_CEND_RE = re.compile(r"耳机|手表|皮套|鳄鱼|黑钻表|折叠屏|ivertu|quantum", re.I)


def _blob(*parts: object) -> str:
    return " ".join(str(part or "").replace("\n", " ") for part in parts)


def classify_lead(blob: str) -> str:
    """客户备注/昵称粗分：汽车、转B线索、C端、未标。MCP 无品类字段时用这一层。"""
    text = blob or ""
    if _CAR_RE.search(text):
        return "汽车"
    if _CTOB_RE.search(text):
        return "转B"
    if _CEND_RE.search(text):
        return "C端"
    return "未标"


@dataclass(frozen=True)
class CtobOwner:
    """一个 C转B 跟进群负责人。"""

    display: str
    channel_id: str
    employee_id: int


# 仅督战官 bot 已在群内的 16 个 C转B 跟进群。
OWNERS: tuple[CtobOwner, ...] = (
    CtobOwner("张心言", "776e2a94-884a-45dd-aab5-566e15e6b521", 31),
    CtobOwner("刘佳鑫", "4a816327-286b-47c2-b7be-a9475929a9c7", 34),
    CtobOwner("周佳丽", "9ad46449-4a0b-41d8-89d5-9738bcb4e319", 25),
    CtobOwner("刘彦麟", "fcd074bd-7f3e-4d8c-a9fd-d035aae74267", 29),
    CtobOwner("陈晓霜", "68ceb1cc-f013-4e80-a863-b7e384d1be63", 33),
    CtobOwner("郑丽苹", "7b2c5f76-8345-462f-b48d-ccde4b4cf962", 26),
    CtobOwner("许淋玲", "b4fadadf-3266-457c-a6ab-57b4246e80c9", 28),
    CtobOwner("陈莉", "28b6a7a8-6f9b-4968-aecf-5816caf2ca30", 32),
    CtobOwner("李玉琴", "0ed20261-dbf9-49e9-99cc-1e02af32fedf", 27),
    CtobOwner("贾梦林", "f58bc611-2751-469c-a37d-6066caecdf2d", 9),
    CtobOwner("李晓悦", "d6e8555f-6112-4507-82ee-7f8a329d2ac3", 10),
    CtobOwner("向俞金", "8151eb75-e355-4fc7-bc58-bc61d31419b2", 35),
    CtobOwner("夏欢", "363667ae-1a05-4927-8cc5-883332b23ac6", 24),
    CtobOwner("宋依亭", "21416579-5648-4ec9-a098-a2aed9f684bf", 11),
    CtobOwner("何川", "f1293c01-55b2-4155-b5e7-c13f531f08f4", 23),
    CtobOwner("陈玉霞", "9bce6f79-27bf-4730-bcbc-5ae3bf05948c", 30),
)


def _period(day: str) -> dict:
    return {"start_date": day, "end_date": day}


def _summary_row(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    for row in payload.get("rows") or []:
        if isinstance(row, dict) and row.get("row_type") == "summary":
            return row
    return None


def parse_wa_summary(payload: dict | None) -> dict:
    """conversations.customers 日汇总。未覆盖字段留空。附带汽车/转B/其他拆分。"""
    row = _summary_row(payload)
    base = {
        "reached": row.get("reached_customer_count") if row else None,
        "replied": row.get("replied_customer_count") if row else None,
        "outbound": row.get("outbound_message_count") if row else None,
        "inbound": row.get("inbound_message_count") if row else None,
        "new": row.get("new_customer_count") if row else None,
        "complete": row.get("is_complete") if row else None,
        "car": 0,
        "ctob": 0,
        "other": 0,
    }
    for item in (payload or {}).get("rows") or []:
        if not isinstance(item, dict) or item.get("row_type") != "detail":
            continue
        kind = classify_lead(
            _blob(
                item.get("customer_nickname"),
                item.get("customer_display_name"),
                item.get("customer_remark"),
                item.get("customer_tags"),
            )
        )
        if kind == "汽车":
            base["car"] += 1
        elif kind == "转B":
            base["ctob"] += 1
        else:
            base["other"] += 1
    return base


def parse_wa_chats(payload: dict | None, limit: int = 8) -> list[dict]:
    """今日有消息的汽车/转B客户。轮次按 min(发,收)，只发未收记 0 轮。"""
    chats: list[dict] = []
    for row in (payload or {}).get("rows") or []:
        if not isinstance(row, dict) or row.get("row_type") != "detail":
            continue
        outbound = int(row.get("outbound_message_count") or 0)
        inbound = int(row.get("inbound_message_count") or 0)
        name = (
            str(row.get("customer_nickname") or "").strip()
            or str(row.get("customer_display_name") or "").strip()
            or str(row.get("customer_display") or "").strip()
            or "未命名"
        )
        name = " ".join(name.replace("\n", " ").split())
        kind = classify_lead(
            _blob(
                row.get("customer_nickname"),
                row.get("customer_display_name"),
                row.get("customer_remark"),
                row.get("customer_tags"),
            )
        )
        if kind not in FOCUS_KINDS:
            continue
        chats.append(
            {
                "name": name[:24],
                "kind": kind,
                "country": str(row.get("country") or ""),
                "outbound": outbound,
                "inbound": inbound,
                "rounds": min(outbound, inbound),
                "replied": bool(row.get("replied")),
                "touched": bool(row.get("touched")),
                "last": str(row.get("last_message_time") or "")[11:16],
            }
        )
    chats.sort(key=lambda item: (item["rounds"], item["outbound"] + item["inbound"]), reverse=True)
    return chats[:limit]


def parse_cohort(payload: dict | None) -> dict:
    """sales.customer_cohort：只留汽车/转B 新客。"""
    summary = (payload or {}).get("summary") if isinstance(payload, dict) else None
    if not isinstance(summary, dict):
        summary = {}
    rows: list[dict] = []
    for row in (payload or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = " ".join(str(row.get("customer_display_name") or "未命名").replace("\n", " ").split())
        kind = classify_lead(_blob(name, row.get("latest_progress"), row.get("stage")))
        if kind not in FOCUS_KINDS:
            continue
        rows.append(
            {
                "name": name[:20],
                "kind": kind,
                "has_chat": bool(row.get("has_chat")),
                "has_reply": bool(row.get("has_reply")),
                "outbound": int(row.get("outbound_message_count") or 0),
                "inbound": int(row.get("inbound_message_count") or 0),
                "rounds": min(
                    int(row.get("outbound_message_count") or 0),
                    int(row.get("inbound_message_count") or 0),
                ),
                "stage": str(row.get("stage") or ""),
                "progress": str(row.get("latest_progress") or "").strip(),
            }
        )
    return {
        "new": summary.get("new_customer_count"),
        "chatted": summary.get("has_chat_count"),
        "replied": summary.get("has_reply_count"),
        "intent": summary.get("in_intent_pipeline_count"),
        "focus_new": len(rows),
        "rows": rows,
    }


def infer_blockers(chats: list[dict], cohort: dict) -> list[str]:
    """卡点：客户在等回复优先，再只发未回、未聊、未进意向台账。不编造支持。"""
    lines: list[str] = []

    def _add(line: str) -> None:
        if line not in lines:
            lines.append(line)

    for item in chats:
        if item["inbound"] > item["outbound"]:
            _add(f"{item['name']} 发{item['outbound']}收{item['inbound']} 客户在等回复")
        elif item["outbound"] > 0 and item["inbound"] == 0:
            _add(f"{item['name']} 发{item['outbound']}收0 等客户回")
        if len(lines) >= 6:
            return lines[:6]
    for row in (cohort.get("rows") or [])[:8]:
        if not row.get("has_chat"):
            _add(f"{row['name']} 新客未聊")
        elif not row.get("has_reply"):
            extra = f" {row['progress']}" if row.get("progress") else ""
            _add(f"{row['name']} 发{row['outbound']}收0 等客户回{extra}")
        elif row.get("stage") == "not_in_intent_ledger":
            _add(f"{row['name']} 已回但未进意向台账")
        if len(lines) >= 6:
            break
    return lines[:6]


def infer_support(blockers: list[str], chats: list[dict], other: int = 0) -> str:
    """支持需求：只根据 MCP 信号给可执行下一步，未知标待确认。"""
    if not chats and not blockers:
        if other:
            return f"有 {other} 户 C端/未标在聊，不追。补备注：汽车或转B线索。"
        return "今日未见汽车/转B线索。补：有无名单、账号是否在线。"
    if any("客户在等回复" in item for item in blockers):
        return "汽车/转B 已回未接：先回人，卡政策/车源/代理资质在群里 @中台。"
    if any("等客户回" in item for item in blockers):
        return "汽车/转B 未回：群内写是否要中台补资料/报价；不要干等。"
    if any("意向台账" in item for item in blockers):
        return "已回客户补意向台账，标转B或汽车阶段。"
    return "有聊。群内补：转B/汽车意向是否成单、卡点、要中台什么。待确认。"


def render_brief(
    owner: CtobOwner,
    day: str,
    summary: dict,
    chats: list[dict],
    cohort: dict,
) -> str:
    """一群一条晚追，不含红黑榜。"""
    reached = summary.get("reached")
    replied = summary.get("replied")
    outbound = summary.get("outbound")
    inbound = summary.get("inbound")
    if reached is None and not chats:
        body = "WhatsApp 数据未覆盖，不当 0。"
        return (
            f"【海外渠道督战官｜20:00 C转B晚追｜{day}】\n"
            f"@{owner.display}\n{body}\n"
            "请补：今天汽车/转B线索有没有聊、几轮、卡点、要什么支持。"
        )
    chat_lines = []
    for item in chats[:5]:
        flag = "有回" if item["replied"] else "未回"
        loc = f"{item['country']} " if item["country"] else ""
        kind = item.get("kind") or "转B"
        chat_lines.append(
            f"- [{kind}] {loc}{item['name']} 发{item['outbound']}收{item['inbound']}"
            f"（{item['rounds']}轮）{flag} {item['last']}".rstrip()
        )
    blockers = infer_blockers(chats, cohort)
    other = int(summary.get("other") or 0)
    support = infer_support(blockers, chats, other)
    car_n = summary.get("car")
    ctob_n = summary.get("ctob")
    new_n = cohort.get("new")
    focus_new = cohort.get("focus_new")
    if chat_lines:
        talk_head = "汽车/转B对话"
    elif other:
        talk_head = f"汽车/转B对话：无。C端/未标 {other} 户不展开，待确认有无漏标。"
    else:
        talk_head = "汽车/转B对话：无明细（可能只发未回、未同步或没标备注）"
    lines = [
        f"【海外渠道督战官｜20:00 C转B晚追｜{day}】",
        f"@{owner.display} 重点：汽车 + 转B线索（C端耳机/手表等不追）",
        f"WA总触达 {reached if reached is not None else '待确认'} / "
        f"回复 {replied if replied is not None else '待确认'} / "
        f"发{outbound if outbound is not None else '待确认'}"
        f"收{inbound if inbound is not None else '待确认'}",
        f"其中汽车 {car_n if car_n is not None else '待确认'} / "
        f"转B {ctob_n if ctob_n is not None else '待确认'} / "
        f"其他 {other if other is not None else '待确认'}",
        f"新客全量 {new_n if new_n is not None else '待确认'}，"
        f"其中汽车/转B {focus_new if focus_new is not None else '待确认'}",
        talk_head,
        *chat_lines,
        "卡点：" + ("；".join(blockers) if blockers else "MCP 未见汽车/转B卡点，待群内确认。"),
        f"可能要的支持：{support}",
        "回复格式：客户名 / 汽车或转B / 几轮 / 进度 / 卡点 / 要中台什么。没聊写「无」。",
    ]
    return "\n".join(lines)


def collect_owner(owner: CtobOwner, day: str) -> dict:
    """拉一人当日 WhatsApp 客户列表 + 新客队列。"""
    period = _period(day)
    subject = {"employee_id": owner.employee_id}
    customers = mcp_call(
        "business.query",
        {
            "domain": "conversations",
            "query_mode": "customers",
            "subject": subject,
            "period": period,
            "filters": {"platform": "WhatsApp", "page_size": 30},
        },
    )
    cohort = mcp_call(
        "sales.customer_cohort",
        {
            "subject": subject,
            "period": period,
            "platform": "WhatsApp",
            "page_size": 20,
        },
    )
    return {
        "summary": parse_wa_summary(customers),
        "chats": parse_wa_chats(customers),
        "cohort": parse_cohort(cohort),
    }


def run_ctob(day: str | None = None, now: datetime | None = None) -> dict:
    """工作日 20:00 向 16 个 C转B 群各推一条。"""
    clock = now or datetime.now(ZoneInfo(TZ_SHANGHAI))
    if not is_duzhan_workday(TZ_SHANGHAI, clock):
        logger.info("周末不推 C转B 晚追")
        return {"sent": [], "failed": [], "skipped": "weekend"}
    day = day or clock.strftime("%Y-%m-%d")
    collected: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect_owner, owner, day): owner for owner in OWNERS}
        for fut in as_completed(futures):
            owner = futures[fut]
            try:
                collected[owner.channel_id] = fut.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("C转B 采集失败 {}: {}", owner.display, exc)
                collected[owner.channel_id] = {"summary": {}, "chats": [], "cohort": {}}
    sent: list[str] = []
    failed: list[str] = []
    for owner in OWNERS:
        data = collected.get(owner.channel_id) or {"summary": {}, "chats": [], "cohort": {}}
        body = render_brief(owner, day, data["summary"], data["chats"], data["cohort"])
        ok = push_duzhan_message(
            body,
            owner.channel_id,
            idempotency_key=f"ctob-{day.replace('-', '')}-2000-{owner.channel_id[:8]}",
        )
        if ok:
            sent.append(owner.display)
        else:
            failed.append(owner.display)
            logger.warning("C转B 晚追推送失败 {}", owner.display)
    return {"day": day, "sent": sent, "failed": failed}
