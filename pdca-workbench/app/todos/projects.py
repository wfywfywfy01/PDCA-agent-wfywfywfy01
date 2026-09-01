# -*- coding: utf-8 -*-
"""待办项目（事项）收敛：标题 → 关键词项目；会议主题 → 会议项目。

规则经业务确认（2026-08-27）：
- 物流备货/证书/港澳退换货 → 鲜娜、张琪、张懿（三人分工相同，共同执行）
- 印度总代/独代 → 何海文 + 杨晶晶（杨晶晶是何海文上级且同做印度市场，双人承接）
- 「证书」区分：出货证书（UN38.3/MSDS/原产地证/CO/FE/鉴定报告/提单）→ 物流；
  「认证」（如 BIS 认证）不算物流，归对应市场项目。

项目收敛优先级（2026-08-28 起）：
1. 关键词项目（PROJECT_RULES 命中）——业务主题项目，人工维护；
2. 会议主题项目——Vemory 待办按归一化会议主题自动收敛（kind="meeting"），
   同一主题多次开会合并为同一个长期项目，executors 随项目内待办负责人自动刷新；
3. 都挂不上 → 散单，走个人消息兜底。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.statuses import is_done as _is_done

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9+.-]+")
_DATE_PREFIX_RE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s+")
_ORDINAL_RE = re.compile(r"第[一二三四五六七八九十百\d]+次")
_PAREN_SUFFIX_RE = re.compile(r"\s*[（(][^（）()]{0,24}[)）]\s*$")

# key 唯一；executors 可多人（各自收到同一条项目催办）
PROJECT_RULES: list[dict] = [
    {
        "key": "india-distro",
        "name": "印度总代/独代谈判",
        "executors": ["何海文", "杨晶晶"],
        "coordinator": "刘春梅",
        "keywords_cn": [
            "印度", "总代", "独代", "孟买", "新德里", "保证金", "代理指标",
        ],
        "keywords_en": [
            "india", "secro", "bharat", "skytech", "jio", "dlf", "mumbai",
            "delhi", "bis",
        ],
    },
    {
        "key": "logistics-fulfillment",
        "name": "物流备货与出货证书",
        "executors": ["鲜娜", "张琪", "张懿"],
        "coordinator": "刘春梅",
        "keywords_cn": [
            "备货", "发货", "出运", "出货证书", "原产地证", "鉴定报告",
            "提单", "运费", "货代", "标签", "包装", "退件", "取件",
            "双清", "空运", "快递",
        ],
        "keywords_en": ["un38.3", "msds", "co", "fe", "shipping", "shipment", "freight"],
    },
    {
        "key": "hk-mo-returns",
        "name": "港澳退换货与调货",
        "executors": ["鲜娜", "张琪", "张懿"],
        "coordinator": "刘春梅",
        "keywords_cn": ["港澳", "退换货", "调货", "入库"],
        "keywords_en": [],
    },
    {
        "key": "russia-restor",
        "name": "俄罗斯提货与RESTOR开店",
        "executors": ["杨晶晶"],
        "coordinator": "刘春梅",
        "keywords_cn": ["俄罗斯", "提货"],
        "keywords_en": ["russia", "restor"],
    },
    {
        "key": "dubai-90day",
        "name": "迪拜线上方案(90天)",
        "executors": ["DEHDAHOUMAIMA"],
        "coordinator": "刘春梅",
        "keywords_cn": ["迪拜", "九十天", "90天", "线上方案"],
        "keywords_en": ["dubai"],
    },
    {
        "key": "malaysia",
        "name": "马来西亚市场拆解",
        "executors": ["于冰"],
        "coordinator": "刘春梅",
        "keywords_cn": ["马来西亚", "马来"],
        "keywords_en": ["malaysia"],
    },
    {
        "key": "vietnam",
        "name": "越南市场",
        "executors": ["于冰"],
        "coordinator": "刘春梅",
        "keywords_cn": ["越南"],
        "keywords_en": ["vietnam", "vmg"],
    },
    {
        "key": "thailand",
        "name": "泰国市场与定制项目",
        "executors": ["于冰"],
        "coordinator": "刘春梅",
        "keywords_cn": ["泰国", "定制"],
        "keywords_en": ["thailand"],
    },
    {
        "key": "kuwait-iraq",
        "name": "科威特/伊拉克市场",
        "executors": ["尤文静"],
        "coordinator": "DEHDAHOUMAIMA",
        "keywords_cn": ["科威特", "伊拉克"],
        "keywords_en": ["kuwait", "iraq"],
    },
    {
        "key": "saudi-jeddah",
        "name": "沙特吉达首单",
        "executors": ["DEHDAHOUMAIMA"],
        "coordinator": "刘春梅",
        "keywords_cn": ["沙特", "吉达"],
        "keywords_en": ["saudi", "jeddah"],
    },
    {
        "key": "armenia",
        "name": "亚美尼亚客户方案",
        "executors": ["DEHDAHOUMAIMA"],
        "coordinator": "刘春梅",
        "keywords_cn": ["亚美尼亚"],
        "keywords_en": ["armenia"],
    },
    {
        "key": "lina-regions",
        "name": "Lina区域经销网络",
        "executors": ["DEHDAHOUMAIMA"],
        "coordinator": "刘春梅",
        "keywords_cn": [
            "伊朗", "乌克兰", "英国", "阿塞拜疆", "土耳其", "卡塔尔",
            "斯洛文尼亚", "保加利亚", "德国", "波兰", "加纳", "伦敦",
        ],
        "keywords_en": [
            "iran", "ukraine", "uk", "london", "azerbaijan", "turkey",
            "qatar", "slovenia", "bulgaria", "germany", "poland", "ghana",
        ],
    },
    {
        "key": "landmark",
        "name": "Landmark 合作",
        "executors": ["杨晶晶"],
        "coordinator": "刘春梅",
        "keywords_cn": ["保密协议", "定价", "商业条件"],
        "keywords_en": ["landmark", "nda"],
    },
    {
        "key": "private-domain-reorg",
        "name": "私域团队重组",
        "executors": ["刘春梅"],
        "coordinator": "刘春梅",
        "keywords_cn": ["私域", "团队重组", "人力方案"],
        "keywords_en": [],
    },
    {
        "key": "oman",
        "name": "阿曼市场",
        "executors": ["于冰"],
        "coordinator": "刘春梅",
        "keywords_cn": ["阿曼"],
        "keywords_en": ["oman"],
    },
    {
        "key": "mclaren",
        "name": "迈凯伦/McLaren",
        "executors": ["于冰"],
        "coordinator": "刘春梅",
        "keywords_cn": ["迈凯伦", "麦凯伦"],
        "keywords_en": ["mclaren"],
    },
    {
        "key": "vps-ai-tools",
        "name": "VPS/AI工具推广",
        "executors": ["付汪阳"],
        "coordinator": "刘春梅",
        "keywords_cn": ["技能", "智能", "机器人", "背调专家", "工具使用", "录音功能"],
        "keywords_en": ["vps", "ai"],
    },
    {
        "key": "data-dashboard",
        "name": "数据看板与报表",
        "executors": ["付汪阳"],
        "coordinator": "刘春梅",
        "keywords_cn": ["看板", "报表", "周报", "月报", "提成", "业绩", "数据", "货代账单"],
        "keywords_en": ["dashboard", "report", "commission"],
    },
    {
        "key": "biz-order-payment",
        "name": "商务订单与收款",
        "executors": ["冯磊"],
        "coordinator": "刘春梅",
        "keywords_cn": ["报价", "询单", "查款", "水单", "付款", "结汇", "录单", "录入"],
        "keywords_en": ["pi", "swift", "invoice", "payment"],
    },
]

# 会议主题归一：按长度倒序匹配，避免「同步会」被「会」先剥掉一层
_MEETING_SUFFIXES = [
    "推进会", "讨论会", "沟通会", "同步会", "研讨会", "洽谈会",
    "会议", "讨论", "沟通", "跟进", "纪要", "同步", "研讨", "会",
    "meeting", "discussion", "discussions", "update", "updates",
    "review", "coordination", "follow-up", "follow up",
]


def normalize_meeting_topic(meeting_name: str) -> str:
    """会议名 → 长期主题：去日期前缀、第N次、括号备注与会议类后缀。

    例：「2026-08-17 越南门店与代理策略同步会」→「越南门店与代理策略」；
        「Virtue and Landmark 第一次会议(杨晶晶&何海文)」→「Virtue and Landmark」。
    归一化后为空（如「周会」被剥干净）则回退为去日期后的原文。
    """
    topic = (meeting_name or "").strip()
    if not topic:
        return ""
    topic = _DATE_PREFIX_RE.sub("", topic).strip()
    topic = _ORDINAL_RE.sub("", topic).strip()
    topic = _PAREN_SUFFIX_RE.sub("", topic).strip()
    original = topic
    lower = topic.lower()
    changed = True
    while changed and len(topic) > 2:
        changed = False
        for suffix in _MEETING_SUFFIXES:
            if lower.endswith(suffix) and len(topic) - len(suffix) >= 2:
                topic = topic[: len(topic) - len(suffix)].strip(" -—、,，")
                lower = topic.lower()
                changed = True
                break
    return topic or original


def meeting_project_key(topic: str) -> str:
    """会议主题 → 稳定项目 key（mtg: + 12 位哈希）。"""
    return "mtg:" + hashlib.sha1(topic.casefold().strip().encode("utf-8")).hexdigest()[:12]


def match_project(title: str) -> Optional[dict]:
    """标题 → 项目规则；按规则顺序取第一个命中（印度优先于其他区域）。"""
    cn = title
    en = title.lower()
    tokens = set(_LATIN_TOKEN_RE.findall(en))
    for rule in PROJECT_RULES:
        if any(kw in cn for kw in rule["keywords_cn"]):
            return rule
        if any(kw in tokens for kw in rule["keywords_en"]):
            return rule
    return None


def ensure_projects(session) -> tuple[dict, dict]:
    """按 PROJECT_RULES 种子化 todo_projects；返回 (key→项目, id→项目)。"""
    existing = list(session.exec(select(TodoProject)).all())
    by_key = {row.key: row for row in existing}
    for rule in PROJECT_RULES:
        row = by_key.get(rule["key"])
        if row is None:
            row = TodoProject(
                key=rule["key"],
                name=rule["name"],
                kind="keyword",
                executors=json.dumps(rule["executors"], ensure_ascii=False),
                coordinator=rule.get("coordinator", ""),
            )
            session.add(row)
            by_key[rule["key"]] = row
        else:
            row.name = rule["name"]
            row.kind = row.kind or "keyword"
            row.executors = json.dumps(rule["executors"], ensure_ascii=False)
            row.coordinator = rule.get("coordinator", "")
            session.add(row)
    session.commit()
    refreshed = list(session.exec(select(TodoProject)).all())
    return (
        {row.key: row for row in refreshed},
        {row.id: row for row in refreshed},
    )


def load_all_projects(session) -> dict[int, TodoProject]:
    """全部项目（关键词 + 会议 + 手动）按 id 索引。"""
    return {row.id: row for row in session.exec(select(TodoProject)).all()}


def ensure_meeting_project(session, meeting_name: str) -> Optional[TodoProject]:
    """会议名 → 会议主题项目（kind="meeting"）；主题为空返回 None。"""
    topic = normalize_meeting_topic(meeting_name)
    if not topic:
        return None
    key = meeting_project_key(topic)
    row = session.exec(select(TodoProject).where(TodoProject.key == key)).first()
    if row is None:
        row = TodoProject(
            key=key,
            name=topic[:256],
            kind="meeting",
            status="新建",
            executors="[]",
            coordinator="",
        )
        session.add(row)
        # 立即分配主键：调用方（vemory 同步/回填）需要 row.id 挂到待办上
        session.flush()
    return row


def refresh_meeting_project_members(session) -> int:
    """会议项目 executors = 项目内全部待办负责人去重集合；返回更新数。"""
    members: dict[int, set] = defaultdict(set)
    for task in session.exec(
        select(PdcaTask).where(PdcaTask.project_id.is_not(None))
    ).all():
        if task.owner:
            members[task.project_id].add(task.owner.strip())
    rows = list(
        session.exec(select(TodoProject).where(TodoProject.kind == "meeting")).all()
    )
    updated = 0
    for row in rows:
        executors = json.dumps(sorted(members.get(row.id, set())), ensure_ascii=False)
        if row.executors != executors:
            row.executors = executors
            session.add(row)
            updated += 1
    return updated


def meeting_project_stats(session) -> tuple[dict[int, int], dict[int, int]]:
    """各项目 (总数, 未完成数)，仅统计已挂项目的待办。"""
    total: dict[int, int] = defaultdict(int)
    open_count: dict[int, int] = defaultdict(int)
    for task in session.exec(
        select(PdcaTask).where(PdcaTask.project_id.is_not(None))
    ).all():
        total[task.project_id] += 1
        if not _is_done(task.status):
            open_count[task.project_id] += 1
    return total, open_count


def auto_close_meeting_projects(session) -> int:
    """会议项目全部待办已完成 → 自动「已闭环」（新待办挂入时由调用方重开）。"""
    total, open_count = meeting_project_stats(session)
    closed = 0
    for row in session.exec(
        select(TodoProject).where(TodoProject.kind == "meeting")
    ).all():
        if (
            total.get(row.id, 0) > 0
            and open_count.get(row.id, 0) == 0
            and row.status != "已闭环"
        ):
            row.status = "已闭环"
            row.updated_at = datetime.utcnow()
            session.add(row)
            closed += 1
    return closed
