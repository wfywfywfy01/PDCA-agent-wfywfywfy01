# -*- coding: utf-8 -*-
"""增长飞轮：基于素材 + 热点生成 SEO/GEO/开发信/投流内容，推 VPS 审核群。"""
from __future__ import annotations

import json
import os

from sqlmodel import Session, func, select

from app.growth.models import GrowthAsset, GrowthContent
from app.vps_im_push import _push

ASSET_BUDGET = 16000  # 素材总字符上限，防止 prompt 超长

_ARTICLE = (
    "People-first article for our Shopify blog (one page serves both Google and AI answer "
    "engines; never write thin AI-only copy). Body in Markdown: line 1 'Meta: <=155 chars', "
    "line 2 'Slug: url-slug', then a 2-3 sentence direct answer, H2/H3 headings phrased like "
    "real queries, self-contained answer blocks, a comparison table where relevant, figures and "
    "quotes ONLY from the materials with their source named, a FAQ, one CTA, and finally a "
    "```json JSON-LD block (Article + FAQPage). No keyword stuffing."
)

KIND_SPECS = {
    "seo": _ARTICLE + " Target the topic as a search keyword; title <=60 chars; 1200-1800 words.",
    "geo": _ARTICLE + (
        " Title is the exact question a buyer asks ChatGPT/Perplexity; name entities explicitly "
        "(brand, model, material, country); 800-1200 words; FAQ with 5-8 concise Q&A."
    ),
    "email": (
        "First-touch cold email to the dealer. title = subject: 2-4 words, lowercase, looks "
        "internal, no pitch/urgency/emoji/name. body = plain text under 80 words, peer tone, "
        "opens with an observation from the dossier that leads into their problem, one proof "
        "point, one interest-based question as CTA (not a meeting request), NO links, sign-off "
        "{{sender_name}}. Banned: 'I hope this finds you well', 'I came across', leverage, "
        "synergy, best-in-class, unlock, 'it's not X, it's Y', self-answered questions, em dashes."
    ),
    "ad": (
        "Paid ads copy. title = campaign angle name; body in Markdown: '## Google RSA' = 15 "
        "headlines (each <=30 chars) and 4 descriptions (each <=90 chars); '## Meta' = 3 primary "
        "texts (<=125 chars), 3 headlines (<=40 chars), suggested audience and CTA button."
    ),
}

SYSTEM = (
    "You are a senior B2B growth marketer for VERTU luxury phones. Use ONLY facts in the provided "
    "materials (they are the approved claims); never invent prices, specs, certifications, stats "
    "or customer names. If a needed fact is missing write [待确认]. Variants must differ in ONE "
    "variable only (the angle, e.g. craftsmanship, privacy, dealer margin, after-sales) so the "
    "A/B result is attributable. 'angle' is a hypothesis: 'Because <observation>, we believe "
    "<angle> will raise <metric> for <audience>.' "
    'Reply with JSON only: {"variants":[{"angle":"...","title":"...","body":"..."}]}'
)


SEO_SYS = (
    "You are a senior SEO editor for VERTU's Shopify blog. Use ONLY facts from the provided "
    "article text and traffic table; never invent metrics, rankings or demand. If a needed fact "
    "is missing write [待确认]. 'angle' is the core opportunity hypothesis: 'Because <signal from "
    "the table>, <change> should raise <metric>.' "
    'Reply with JSON only: {"variants":[{"angle":"...","title":"...","body":"..."}]}'
)

SEO_FIX = (
    "Audit ONE live article against its traffic. body in Markdown: 1) what underperforms, citing "
    "the table numbers; 2) suggested new page title + meta description; 3) heading/content gaps to "
    "add; 4) target keywords, FAQ/JSON-LD and internal-link fixes. Give an actionable brief the "
    "human editor applies on Shopify; do NOT rewrite the whole article. title = suggested new page "
    "title."
)

SEO_IDEA = (
    "Propose {n} NEW blog topics driven by demand in the table and gaps versus the existing slugs "
    "listed. Each variant = one topic: title = the target search query; body in Markdown = search "
    "intent, a 4-6 item H2 outline, entities to name, primary keyword, suggested internal links. "
    "No overlap with existing slugs."
)


def seo_review(
    session: Session,
    *,
    urls: list[str] | None = None,
    table: str = "",
    ideas: int = 5,
    language: str = "中文",
) -> list[GrowthContent]:
    """P3 只读 SEO 顾问：给已有文章出修改建议（urls 非空），或基于流量表出新选题。

    不改线上文章，只产出建议供人工在 Shopify 执行。table 为空且 GA4 已配置时自动拉流量。
    """
    from app.growth import fetcher, ga4

    if not table.strip() and ga4.configured():
        try:
            table = ga4.briefing()["table"]
        except Exception as exc:
            table = f"(GA4 拉取失败：{exc})"
    round_no = (session.exec(select(func.max(GrowthContent.round_no))).one() or 0) + 1
    rows: list[GrowthContent] = []
    if urls:
        for url in urls:
            art = fetcher.fetch_post(url)
            user = (
                f"Task: {SEO_FIX}\nLanguage: {language}\nArticle URL: {url}\n"
                f"Current title: {art['title']}\nCurrent meta: {art['meta']}\n"
                f"Word count: {art['words']}\nTraffic table:\n{table or '(none)'}\n\n"
                f"Article text:\n{art['text'] or '(fetch failed)'}"
            )
            raw = _llm([{"role": "system", "content": SEO_SYS},
                        {"role": "user", "content": user}], 4000)
            for v in parse_variants(raw)[:1]:
                rows.append(GrowthContent(
                    round_no=round_no, kind="seo_fix", topic=url[:300], variant="A",
                    angle=str(v.get("angle") or "")[:500],
                    title=str(v.get("title") or "")[:500], body=str(v["body"])))
    else:
        n = max(1, min(ideas or 5, 10))
        existing = " | ".join(p["slug"] for p in fetcher.list_posts(300))
        user = (
            f"Task: {SEO_IDEA.format(n=n)}\nLanguage: {language}\n"
            f"Traffic table:\n{table or '(none)'}\n\nExisting slugs:\n{existing[:6000]}"
        )
        raw = _llm([{"role": "system", "content": SEO_SYS},
                    {"role": "user", "content": user}], 4000)
        for i, v in enumerate(parse_variants(raw)[:n]):
            rows.append(GrowthContent(
                round_no=round_no, kind="seo_idea", topic="新选题", variant=chr(65 + i),
                angle=str(v.get("angle") or "")[:500],
                title=str(v.get("title") or "")[:500], body=str(v["body"])))
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def _materials(session: Session, dealer_asset_id: int | None) -> str:
    """拼接 catalog 素材（背调只取指定那份），按预算截断。"""
    rows = session.exec(
        select(GrowthAsset).where(GrowthAsset.kind != "dossier").order_by(GrowthAsset.id)
    ).all()
    if dealer_asset_id:
        dossier = session.get(GrowthAsset, dealer_asset_id)
        if dossier:
            rows = [dossier, *rows]
    parts, used = [], 0
    for row in rows:
        chunk = f"### [{row.kind}] {row.title}\n{row.body.strip()}\n"
        if used + len(chunk) > ASSET_BUDGET:
            chunk = chunk[: max(0, ASSET_BUDGET - used)]
        parts.append(chunk)
        used += len(chunk)
        if used >= ASSET_BUDGET:
            break
    return "\n".join(parts)


def _llm(messages: list[dict], max_tokens: int) -> str:
    """DeepSeek（PDCA_SUPERVISOR_*）JSON 模式调用；复用 Omega 的供应商路由。"""
    from app.omega.jobs import _default_generate

    return _default_generate("report", messages, max_tokens)


def parse_variants(content: str) -> list[dict]:
    """解析模型 JSON；兼容 ```json 包裹。"""
    content = content.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1].rsplit("```", 1)[0]
    variants = json.loads(content).get("variants") or []
    return [v for v in variants if isinstance(v, dict) and str(v.get("body") or "").strip()]


def generate(
    session: Session,
    *,
    kind: str,
    topic: str,
    hotspots: str = "",
    dealer_asset_id: int | None = None,
    variants: int = 2,
    language: str = "English",
) -> list[GrowthContent]:
    """生成一轮 N 个版本并落库为 draft。"""
    materials = _materials(session, dealer_asset_id)
    user = (
        f"Task: {KIND_SPECS[kind]}\nVariants: {variants}\nLanguage: {language}\n"
        f"Topic: {topic}\nRecent leads / hot topics:\n{hotspots or '(none)'}\n\n"
        f"Materials:\n{materials or '(none)'}"
    )
    raw = _llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
               8000)
    round_no = (session.exec(select(func.max(GrowthContent.round_no))).one() or 0) + 1
    rows = [
        GrowthContent(
            round_no=round_no, kind=kind, topic=topic[:300], variant=chr(65 + i),
            angle=str(v.get("angle") or "")[:500], title=str(v.get("title") or "")[:500],
            body=str(v["body"]),
        )
        for i, v in enumerate(parse_variants(raw)[:variants])
    ]
    session.add_all(rows)
    session.commit()
    for row in rows:
        session.refresh(row)
    return rows


def push_for_review(content: GrowthContent, page_url: str) -> bool:
    """推送到「海外官网&海外中台沟通」群（PDCA_GROWTH_REVIEW_CHANNEL_ID）审核。"""
    channel = os.environ.get("PDCA_GROWTH_REVIEW_CHANNEL_ID", "").strip()
    labels = {"seo": "SEO 文章", "geo": "GEO 文章", "email": "开发信", "ad": "投流文案",
              "seo_fix": "SEO 修改建议", "seo_idea": "SEO 新选题"}
    advice = content.kind in ("seo_fix", "seo_idea")
    body = content.body if len(content.body) <= 3500 else content.body[:3500] + "\n…（全文见工作台）"
    tail = ("由人工在 Shopify 执行，仅建议不自动改稿" if advice
            else "审核通过后发布到 Shopify 独立站")
    message = (
        f"【待审核·{labels.get(content.kind, content.kind)}】第{content.round_no}轮 "
        f"版本{content.variant}｜{content.title}\n角度：{content.angle}\n\n{body}\n\n"
        f"{tail}；全文/编辑：{page_url}"
    )
    return _push(message, channel, idempotency_key=f"growth-review-{content.id}")
