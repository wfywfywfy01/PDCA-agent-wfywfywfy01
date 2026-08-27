# -*- coding: utf-8 -*-
"""岗位 SOP 收敛：Vemory 待办 → 岗位 → 执行人。

规则来源：海外事业部-岗位SOP-按人整理.md。
纯逻辑模块，不依赖应用层，便于本地/容器内 dry-run 与单测。

判定链（由强到弱）：
  1. 人名提及（"让海文写邮件"）= 明确指派 → 该人（覆盖岗位默认人）
  2. 岗位关键词 → 岗位（主管 / 商务 / 物流 / 数据 / 销售）
  3. 区域 / 代理锚点 → 销售执行人（代理名优先于区域；伊拉克/印度区域歧义只走代理名）
  4. speaker 是团队成员 → speaker 本人
  5. 岗位为单人 → 岗位默认人
  6. 全部落空 → unclassified（执行人回退会议参与人，由上层策略决定）
"""
from __future__ import annotations

import re
from typing import Optional

# ── 人员与别名（别名按长度降序匹配，避免短别名误吞）─────────────────────────
PEOPLE: dict[str, dict] = {
    "Lina": {
        "aliases": ["Lina", "lina", "丽娜", "DEHDAHOUMAIMA"],
        "position": "海外经销商销售",
        # IM 组织里海外 Lina 的实名（login 13263459330，经销商三部）；
        # "Lina" 搜到的是国内苏州门店同事，必须用此规范名落 owner。
        "im_name": "DEHDAHOUMAIMA",
    },
    "尤文静": {"aliases": ["尤文静", "文静"], "position": "海外经销商销售"},
    "于冰": {"aliases": ["于冰"], "position": "海外经销商销售"},
    "何海文": {"aliases": ["何海文", "海文"], "position": "海外经销商销售"},
    "杨晶晶": {"aliases": ["杨晶晶", "晶晶"], "position": "海外经销商销售"},
    # 转写同音字补别名：会议纪要常把「宇彤」写成「雨桐/雨彤」
    "王宇彤": {"aliases": ["王宇彤", "宇彤", "雨桐", "雨彤"], "position": "海外经销商销售"},
    "Safae": {"aliases": ["Safae", "safae"], "position": "海外经销商销售"},
    "刘春梅": {"aliases": ["刘春梅", "春梅"], "position": "海外经销商主管"},
    "冯磊": {"aliases": ["冯磊", "冯雷"], "position": "海外商务"},
    "鲜娜": {"aliases": ["鲜娜", "仙娜"], "position": "海外物流"},
    "张琪": {"aliases": ["张琪"], "position": "海外物流"},
    "张懿": {"aliases": ["张懿"], "position": "海外物流"},
    "付汪阳": {"aliases": ["付汪阳", "汪洋", "frank", "Frank"], "position": "海外数据"},
    # 注意：SOP 中「雪梅」为中台支持，users.json 中为「刘雪梅」，暂按同一人处理，需业务确认。
    "刘雪梅": {"aliases": ["刘雪梅", "雪梅"], "position": "中台支持"},
    "邢哲夫": {"aliases": ["邢哲夫", "哲夫"], "position": "海外经销商销售"},
    "李浩然-1": {"aliases": ["李浩然", "浩然"], "position": "海外经销商销售"},
}

# ── 岗位关键词（中文子串匹配；拉丁词按词边界匹配，避免 ai⊂email 之类误命中）───
POSITIONS: dict[str, dict] = {
    "海外经销商主管": {
        "people": ["刘春梅"],
        "keywords_cn": [
            "面试", "简历", "组员", "团队", "统筹", "战略", "高层",
            "工作安排", "资源协调", "跨组", "多组", "招聘销售", "人员招聘",
        ],
        "keywords_en": [],
        # 招聘单独出现归主管（招聘店员/门店语境由销售岗的「招聘店员」吃掉）；
        # 协调单独出现仅作弱信号，避免把普通待办都挂给主管。
        "weak_cn": ["协调", "招聘"],
    },
    "海外商务": {
        "people": ["冯磊"],
        "keywords_cn": [
            "询单", "报价", "交期", "查款", "水单", "到账", "结汇",
            "录单", "订单录入", "录入", "付款", "邀请函", "商务接待", "出口资料", "报关",
            "清关", "贸易条款", "代理协议", "收款", "生产进度", "备货申请",
        ],
        "keywords_en": [
            "pi", "sku", "swift", "usdt", "worldfirst", "cif", "cip", "exw",
            "quote", "quotation", "pricing", "price", "payment", "invoice",
            "customs", "export", "bank", "order",
        ],
    },
    "海外物流": {
        "people": ["鲜娜", "张琪", "张懿"],
        "keywords_cn": [
            "备货", "发货", "包装", "出运", "空运", "快递", "双清",
            "货代", "运费", "对账", "退件", "取件", "盘点", "库存",
            "证书", "鉴定报告", "原产地证", "提单", "贸促会", "报检",
            "资产申请", "社媒拍摄", "不良品", "港澳门店", "补货",
        ],
        "keywords_en": [
            "un38.3", "msds", "shipping", "shipment", "delivery", "warehouse",
            "freight", "certificate", "packing",
        ],
    },
    "海外数据": {
        "people": ["付汪阳"],
        "keywords_cn": [
            "提成", "激励", "核算", "看板", "推送", "报表", "周报",
            "月报", "业绩", "达成率", "同比", "环比", "数据", "货代账单",
            "自动化", "获客", "机器人",
        ],
        "keywords_en": [
            "livechat", "ai", "report", "dashboard", "commission", "data",
            "automation", "robot", "automated",
        ],
        "weak_cn": ["技能", "智能"],
    },
    "海外经销商销售": {
        "people": ["Lina", "尤文静", "于冰", "何海文", "杨晶晶", "王宇彤", "Safae"],
        "keywords_cn": [
            "领英", "建联", "触达", "开发客户", "背调", "签约", "代理合同",
            "落位", "装修", "开业", "门店", "店员", "招聘店员", "培训",
            "社媒", "营销", "巡视", "售后", "复盘", "展会", "市场分析",
            "客户", "经销商", "代理", "五件套",
        ],
        "keywords_en": [
            "linkedin", "kol", "brand deck", "branddeck", "deck",
            "client", "customer", "retail", "store", "dealer", "distributor",
            "dealership", "negotiation", "negotiate", "partnership", "partner",
            "nda", "boutique", "shop", "opening", "storefront", "bis",
        ],
    },
}

# ── 销售锚点：代理名（精确子串，大小写不敏感）───────────────────────────────
AGENT_ANCHORS: dict[str, str] = {
    "billionaire": "Lina", "luxem": "Lina", "veehoo": "Lina",
    "vertu london": "Lina", "mygroup": "Lina", "veysel": "Lina",
    "hassib": "Lina", "click tech": "Lina", "optimizers": "Lina",
    "robo trading": "Lina", "vipconnect": "Lina", "iq-quest": "Lina",
    "tivali": "Lina", "westone": "Lina",
    "safiranhamrah": "尤文静", "dar al sabaek": "尤文静",
    "vmg": "于冰", "vst ecs": "于冰", "yuemmai": "于冰", "bin bin": "于冰",
    "parth": "何海文", "sidd senthil": "何海文", "ankit jain": "何海文",
    "tc azimut": "杨晶晶", "azimut": "杨晶晶", "continental plus": "杨晶晶",
    "altyn zaman": "杨晶晶", "bizcon": "杨晶晶", "sun international": "杨晶晶",
    "guru electronics": "杨晶晶", "lzb india": "杨晶晶", "lyzhina": "杨晶晶",
}

# 区域 → 销售。伊拉克区域有歧义（Lina/尤文静）不放，只靠代理名/人名解；
# 印度默认何海文（SOP 明示其为印度执行人），代理名仍可覆盖到杨晶晶。
REGION_ANCHORS: dict[str, str] = {
    "迪拜": "Lina", "dubai": "Lina",
    "伊朗": "Lina", "iran": "Lina",
    "乌克兰": "Lina", "ukraine": "Lina",
    "英国": "Lina", "uk": "Lina", "london": "Lina",
    "阿塞拜疆": "Lina", "azerbaijan": "Lina",
    "土耳其": "Lina", "turkey": "Lina",
    "卡塔尔": "Lina", "qatar": "Lina",
    "斯洛文尼亚": "Lina", "slovenia": "Lina",
    "保加利亚": "Lina", "bulgaria": "Lina",
    "德国": "Lina", "germany": "Lina",
    "波兰": "Lina", "poland": "Lina",
    "加纳": "Lina", "ghana": "Lina",
    "沙特": "Lina", "吉达": "Lina", "saudi": "Lina", "jeddah": "Lina",
    "科威特": "尤文静", "kuwait": "尤文静",
    "越南": "于冰", "vietnam": "于冰",
    "泰国": "于冰", "thailand": "于冰",
    "柬埔寨": "于冰", "cambodia": "于冰",
    "俄罗斯": "杨晶晶", "russia": "杨晶晶",
    "土库曼": "杨晶晶", "turkmenistan": "杨晶晶",
    "乌兹别克": "杨晶晶", "uzbekistan": "杨晶晶",
    "哈萨克": "杨晶晶", "kazakhstan": "杨晶晶",
    "印度": "何海文", "india": "何海文",
    "孟买": "何海文", "新德里": "何海文", "mumbai": "何海文", "delhi": "何海文",
}

SALES_PEOPLE = set(POSITIONS["海外经销商销售"]["people"])

_LATIN_TOKEN_RE = re.compile(r"[a-z0-9+.-]+")


def _hit_count_cn(text: str, keywords: list[str]) -> int:
    return sum(1 for kw in keywords if kw in text)


def _hit_count_en(text: str, keywords: list[str]) -> int:
    tokens = set(_LATIN_TOKEN_RE.findall(text))
    return sum(1 for kw in keywords if kw in tokens)


def score_positions(text: str) -> dict[str, float]:
    """按岗位关键词计分（主管弱词 0.5/个）。"""
    text_cn = text
    text_en = text.lower()
    scores: dict[str, float] = {}
    for position, spec in POSITIONS.items():
        score = float(_hit_count_cn(text_cn, spec["keywords_cn"]))
        score += float(_hit_count_en(text_en, spec["keywords_en"]))
        score += 0.5 * _hit_count_cn(text_cn, spec.get("weak_cn", []))
        if score:
            scores[position] = score
    return scores


def find_mentions(text: str) -> list[str]:
    """按出现位置升序返回被提及的团队成员（别名最长优先）。"""
    lowered = text.lower()
    found: list[tuple[int, str]] = []
    for name, spec in PEOPLE.items():
        for alias in sorted(spec["aliases"], key=len, reverse=True):
            idx = lowered.find(alias.lower())
            if idx >= 0:
                found.append((idx, name))
                break
    found.sort(key=lambda item: (item[0], item[1]))
    return [name for _, name in found]


def find_agent_person(text: str) -> Optional[str]:
    lowered = text.lower()
    hits = [(name, lowered.find(anchor)) for anchor, name in AGENT_ANCHORS.items()
            if anchor in lowered]
    if not hits:
        return None
    hits.sort(key=lambda item: item[1])
    persons = {name for name, _ in hits}
    if len(persons) == 1:
        return hits[0][0]
    return None  # 多个不同销售 → 交给其他信号


def find_region_person(text: str) -> Optional[str]:
    lowered = text.lower()
    persons = {
        person for region, person in REGION_ANCHORS.items()
        if region in lowered or region in text
    }
    if len(persons) == 1:
        return persons.pop()
    return None


def classify_todo(
    title: str,
    meeting_name: str = "",
    speaker: str = "",
    participant: str = "",
) -> dict:
    """收敛一条待办。返回 {position, executor, signals, mentions}。

    匹配只基于待办标题：会议名（如「俄罗斯售后问题跟进」「多区域业务进展」）
    含大量跨区域/泛化词，纳入会污染区域锚点与关键词判定。
    """
    text = title
    lowered = text.lower()
    signals: list[str] = []
    mentions = find_mentions(text)

    # 1. 人名提及 = 明确指派（最长别名匹配；多个提及按出现顺序取第一个）
    if mentions:
        key = mentions[0]
        if key == participant and len(mentions) > 1:
            # 参与者自己说话不算指派；取下一个被点名人
            key = mentions[1]
        position = PEOPLE[key]["position"]
        # 执行人统一输出 IM 规范名（如 Lina → DEHDAHOUMAIMA）
        executor = PEOPLE[key].get("im_name") or key
        signals.append(f"person:{key}")
        scores = score_positions(text)
        # 若内容命中更强力的单人岗位关键词（主管/商务/数据），岗位标注该域，
        # 但执行人仍以点名人为准（delegation over role）。
        for domain in ("海外经销商主管", "海外商务", "海外数据"):
            if domain in scores and len(POSITIONS[domain]["people"]) == 1:
                position = domain
                signals.append(f"domain:{domain}")
                break
        return {
            "position": position,
            "executor": executor,
            "signals": signals,
            "mentions": mentions,
        }

    # 2. 岗位关键词计分
    scores = score_positions(text)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        # 无关键词命中但命中代理/区域锚点 → 按销售岗收敛到该人
        person = find_agent_person(lowered) or find_region_person(text)
        if person and person in SALES_PEOPLE:
            return _result(
                "海外经销商销售",
                person,
                [f"anchor:{person}"],
                mentions,
            )
    if ranked:
        position, _score = ranked[0]
        people = POSITIONS[position]["people"]
        signals.append(f"keywords:{position}")

        # 2a. 销售岗：代理/区域锚点细分到人
        if position == "海外经销商销售":
            person = find_agent_person(lowered) or find_region_person(text)
            if person and person in SALES_PEOPLE:
                return _result(position, person, signals + [f"anchor:{person}"], mentions)
            # 无锚点：speaker/参与者是销售 → 本人
            for candidate in (speaker, participant):
                if candidate in SALES_PEOPLE:
                    return _result(position, candidate, signals + [f"participant:{candidate}"], mentions)
            return _result(position, "", signals + ["anchor:unresolved"], mentions)

        # 2b. 单人岗位 → 岗位默认人
        if len(people) == 1:
            return _result(position, people[0], signals, mentions)

        # 2c. 物流三人：speaker/参与者命中其中一人 → 本人；否则未定人
        for candidate in (speaker, participant):
            if candidate in people:
                return _result(position, candidate, signals + [f"participant:{candidate}"], mentions)
        return _result(position, "", signals + ["person:unresolved"], mentions)

    # 3. speaker 是团队成员 → speaker 本人
    if speaker in PEOPLE:
        return _result(
            "unclassified", speaker, [f"speaker:{speaker}"], mentions
        )

    # 4. 兜底：未识别
    return _result("unclassified", "", ["unmatched"], mentions)


def _result(position: str, executor: str, signals: list[str], mentions: list[str]) -> dict:
    # 执行人统一输出 IM 规范名（如 Lina → DEHDAHOUMAIMA），保证催办引擎可解析
    if executor and executor in PEOPLE and PEOPLE[executor].get("im_name"):
        executor = PEOPLE[executor]["im_name"]
    return {
        "position": position,
        "executor": executor,
        "signals": signals,
        "mentions": mentions,
    }
