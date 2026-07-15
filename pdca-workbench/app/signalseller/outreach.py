# -*- coding: utf-8 -*-
"""OutreachCrafter · FABE / SPIN / 触达模板生成。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.config import get_settings
from app.legacy import bridge

PRODUCT_DEFAULT = "VERTU 高端智能终端与 IoT 解决方案"


def _methodology() -> dict:
    path = get_settings().config_dir / "signalseller_methodology.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _contact_label(customer: dict) -> str:
    return (
        customer.get("contact_name")
        or customer.get("contactName")
        or customer.get("dealer_nickname")
        or customer.get("nickname")
        or "您好"
    )


def _company_label(customer: dict) -> str:
    return customer.get("dealer_name") or customer.get("name") or customer.get("customer") or "贵司"


def generate_fabe(customer: dict, product: str = PRODUCT_DEFAULT) -> dict:
    """
    基于 FABE 法则生成触达文案（模板引擎，零压力结尾）。

    @param customer 客户字段 dict
    @param product 产品描述
    """
    contact = _contact_label(customer)
    company = _company_label(customer)
    country = customer.get("country") or customer.get("region") or "海外"
    pain = customer.get("pain_points") or customer.get("note") or "客户跟进与成交转化"

    feature = f"{product} 提供门店数字化与客户全周期管理"
    advantage = "相比传统 Excel 台账，可实时看漏斗、跟进提醒与团队过程指标"
    benefit = f"当 {company} 拓展 {country} 市场时，你不需要反复手工汇总日报，系统自动 Check 超期客户"
    evidence = str(customer.get("evidence") or customer.get("verified_evidence") or "").strip()

    body = (
        f"{contact}，关注到 {company} 在 {pain} 上的投入。\n\n"
        f"【功能】{feature}。\n"
        f"【优势】{advantage}。\n"
        f"【利益】{benefit}。\n"
        + (f"【已核验证据】{evidence}。\n" if evidence else "")
        + "\n"
        f"若方便，我可以发一份 1 页案例摘要供参考，无需回复也没关系。"
    )

    return {
        "template_type": "fabe_email",
        "contact": contact,
        "company": company,
        "fabe": {"F": feature, "A": advantage, "B": benefit, "E": evidence or None},
        "content": body,
        "constraints": _methodology().get("hard_constraints", []),
    }


def generate_private_message(customer: dict) -> dict:
    """一对一私信模板。"""
    contact = _contact_label(customer)
    company = _company_label(customer)
    last = customer.get("next_action") or customer.get("last_topic") or "上次沟通的方向"
    content = (
        f"{contact}，关于 {company} {last}，我整理了一份简短行业参考，"
        f"看看是否对你们当前选品有帮助。不需要回复，仅供查阅。"
    )
    return {"template_type": "private_message", "content": content}


def generate_social_post() -> dict:
    """朋友圈/社群模板。"""
    content = (
        "做海外经销最怕客户说「我再想想」——"
        "往往不是没需求，而是跟进节奏断了。\n"
        "我们现在用 ABCD 分级 + 24h 触达规则，"
        "A 类客户 weekly 2-3 次，沉默 7 天自动提醒。\n"
        "想了解具体怎么落地的，可以私信「分级」。"
    )
    return {"template_type": "social_post", "content": content}


def generate_spin(customer: dict) -> dict:
    """SPIN 问题库。"""
    industry = customer.get("industry") or "经销"
    company = _company_label(customer)
    questions = {
        "S": [
            f"目前 {company} 用什么方式管理 {industry} 客户跟进？",
            "团队日报和过程指标现在怎么汇总？",
            "重点客户名单主要在谁手里维护？",
        ],
        "P": [
            "有没有出现过 A 类客户超过一周没人跟的情况？",
            "新线索录入后，是否有时来不及 24h 内触达？",
            "不同销售之间的客户资料是否经常不一致？",
        ],
        "I": [
            "如果重点客户长期沉默，对本月回款目标影响大吗？",
            "跟进不及时时，团队长一般怎么发现和介入？",
        ],
        "N": [
            "如果能自动提醒超期客户并给出下一步话术，对你们有帮助吗？",
            "若有一套 ABCD 分级看板，你会更愿意用吗？",
        ],
    }
    return {"company": company, "spin": questions}


def generate_outreach(
    customer: dict,
    template_type: str = "fabe_email",
    product: str = PRODUCT_DEFAULT,
    use_hermes: bool = False,
) -> dict:
    """
    统一触达生成入口。

    @param template_type fabe_email | private_message | social_post | spin
    @param use_hermes 是否尝试 Hermes 润色（失败则回退模板）
    """
    template_type = (template_type or "fabe_email").strip().lower()
    if template_type == "spin":
        return {"ok": True, **generate_spin(customer)}
    if template_type == "private_message":
        base = generate_private_message(customer)
    elif template_type == "social_post":
        base = generate_social_post()
    else:
        base = generate_fabe(customer, product)

    if use_hermes and template_type != "spin":
        prompt = (
            "你是 B2B 销售文案专家。根据以下草稿，用 FABE 法则润色为≤150字中文触达邮件。"
            "规则：先听后说、价值前置、零压力结尾、不贬竞品、不空承诺。\n\n"
            f"草稿：\n{base.get('content', '')}"
        )
        try:
            result = bridge.run_hermes_chat(prompt)
            text = result.get("answer") or result.get("content") or result.get("message")
            if text and isinstance(text, str) and len(text.strip()) > 20:
                base["content"] = text.strip()
                base["source"] = "hermes"
                return {"ok": True, **base}
        except Exception:
            pass

    base["source"] = "template"
    return {"ok": True, **base}
