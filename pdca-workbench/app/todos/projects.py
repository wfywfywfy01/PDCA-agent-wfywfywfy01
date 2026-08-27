# -*- coding: utf-8 -*-
"""待办项目（事项）收敛：标题 → 项目。

规则经业务确认（2026-08-27）：
- 物流备货/证书/港澳退换货 → 鲜娜、张琪、张懿（三人分工相同，共同执行）
- 印度总代/独代 → 何海文 + 杨晶晶（杨晶晶是何海文上级且同做印度市场，双人承接）
- 「证书」区分：出货证书（UN38.3/MSDS/原产地证/CO/FE/鉴定报告/提单）→ 物流；
  「认证」（如 BIS 认证）不算物流，归对应市场项目。
纯逻辑模块，不依赖应用层。
"""
from __future__ import annotations

import re
from typing import Optional

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9+.-]+")

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


import json as _json
from sqlmodel import Session as _Session, select as _select

from app.models.todo_project import TodoProject as _TodoProject


def ensure_projects(session) -> tuple[dict, dict]:
    """按 PROJECT_RULES 种子化 todo_projects；返回 (key→项目, id→项目)。"""
    existing = list(session.exec(_select(_TodoProject)).all())
    by_key = {row.key: row for row in existing}
    for rule in PROJECT_RULES:
        row = by_key.get(rule["key"])
        if row is None:
            row = _TodoProject(
                key=rule["key"],
                name=rule["name"],
                executors=_json.dumps(rule["executors"], ensure_ascii=False),
                coordinator=rule.get("coordinator", ""),
            )
            session.add(row)
            by_key[rule["key"]] = row
        else:
            row.name = rule["name"]
            row.executors = _json.dumps(rule["executors"], ensure_ascii=False)
            row.coordinator = rule.get("coordinator", "")
            session.add(row)
    session.commit()
    refreshed = list(session.exec(_select(_TodoProject)).all())
    return (
        {row.key: row for row in refreshed},
        {row.id: row for row in refreshed},
    )
