# -*- coding: utf-8 -*-
"""增长飞轮 API；/api/growth/t/* 为邮件追踪公开端点（无登录）。"""
from __future__ import annotations

import asyncio
import base64
import hmac
import os
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.auth.deps import require_role
from app.auth.models import User
from app.database import get_session
from app.growth import mailer, service
from app.growth.models import GrowthAsset, GrowthContent, GrowthSend, GrowthUnsub

router = APIRouter(prefix="/api/growth", tags=["growth"])
Manager = Annotated[User, Depends(require_role("manager"))]
DB = Annotated[Session, Depends(get_session)]

PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


class AssetBody(BaseModel):
    kind: Literal["product", "service", "dealer", "dossier"]
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=200_000)


class GenerateBody(BaseModel):
    kind: Literal["seo", "geo", "email", "ad"]
    topic: str = Field(min_length=1, max_length=300)
    hotspots: str = Field(default="", max_length=8000)
    dealer_asset_id: int | None = None
    variants: int = Field(default=2, ge=1, le=3)
    language: str = Field(default="English", max_length=40)


class SeoReviewBody(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=20)
    table: str = Field(default="", max_length=60000)
    ideas: int = Field(default=5, ge=1, le=10)


class ContentPatch(BaseModel):
    title: str = Field(max_length=500)
    body: str = Field(min_length=1)


class SendBody(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=500)
    track: bool = False


def _content(session: Session, content_id: int) -> GrowthContent:
    row = session.get(GrowthContent, content_id)
    if not row:
        raise HTTPException(404, "内容不存在")
    return row


@router.post("/assets")
async def create_asset(body: AssetBody, _: Manager, session: DB):
    row = GrowthAsset(**body.model_dump())
    session.add(row)
    session.commit()
    return {"id": row.id}


@router.get("/assets")
async def list_assets(_: Manager, session: DB):
    rows = session.exec(select(GrowthAsset).order_by(GrowthAsset.id.desc())).all()
    return [{"id": r.id, "kind": r.kind, "title": r.title, "chars": len(r.body),
             "created_at": r.created_at} for r in rows]


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: int, _: Manager, session: DB):
    row = session.get(GrowthAsset, asset_id)
    if row:
        session.delete(row)
        session.commit()
    return {"ok": True}


@router.post("/generate")
async def generate(body: GenerateBody, _: Manager, session: DB):
    try:
        rows = await asyncio.to_thread(service.generate, session, **body.model_dump())
    except Exception as exc:  # 模型未配置/超时/截断/JSON 错误统一回 502，不落空数据
        raise HTTPException(502, f"生成失败：{exc}") from exc
    if not rows:
        raise HTTPException(502, "模型没有返回可用版本")
    return [r.model_dump() for r in rows]


@router.get("/seo/ga4")
async def seo_ga4(_: Manager, days: int = 28, refresh: bool = False):
    """近 N 天内容页流量，并与选题表 TSV 对齐。默认读快照。"""
    from app.growth import ga4

    if not ga4.configured() and not os.environ.get("PDCA_GROWTH_GA4_SNAPSHOT"):
        raise HTTPException(503, "GA4 未配置（PDCA_GROWTH_GA4_PROPERTY_ID 与服务账号）")
    try:
        return await asyncio.to_thread(lambda: ga4.briefing(days, force=refresh))
    except Exception as exc:
        raise HTTPException(502, f"GA4 拉取失败：{exc}") from exc


@router.get("/seo/posts")
async def seo_posts(_: Manager, limit: int = 200):
    """vertu.com 海外站文章清单（钉 CDN IP 直连，只读）。"""
    from app.growth import fetcher
    return await asyncio.to_thread(fetcher.list_posts, min(max(limit, 1), 500))


@router.post("/seo/review")
async def seo_review(body: SeoReviewBody, _: Manager, session: DB):
    """给定文章 URL 出修改建议；URL 为空则基于流量表出新选题。"""
    try:
        rows = await asyncio.to_thread(
            service.seo_review, session, urls=body.urls or None, table=body.table, ideas=body.ideas)
    except Exception as exc:  # 抓取/模型失败统一回 502
        raise HTTPException(502, f"分析失败：{exc}") from exc
    if not rows:
        raise HTTPException(502, "模型没有返回可用建议")
    return [r.model_dump() for r in rows]


@router.get("/contents")
async def list_contents(_: Manager, session: DB, kind: str = ""):
    query = select(GrowthContent).order_by(GrowthContent.id.desc()).limit(200)
    if kind:
        query = query.where(GrowthContent.kind == kind)
    return [r.model_dump() for r in session.exec(query).all()]


@router.put("/contents/{content_id}")
async def update_content(content_id: int, body: ContentPatch, _: Manager, session: DB):
    row = _content(session, content_id)
    row.title, row.body = body.title, body.body
    session.add(row)
    session.commit()
    return row.model_dump()


@router.post("/contents/{content_id}/push")
async def push_content(content_id: int, _: Manager, session: DB):
    row = _content(session, content_id)
    page = mailer.public_base() + "/growth"
    if not await asyncio.to_thread(service.push_for_review, row, page):
        raise HTTPException(502, "推送失败：检查 PDCA_GROWTH_REVIEW_CHANNEL_ID 与机器人是否在群内")
    row.status = "pushed"
    session.add(row)
    session.commit()
    return {"ok": True}


@router.post("/contents/{content_id}/send")
async def send_content(content_id: int, body: SendBody, _: Manager, session: DB):
    row = _content(session, content_id)
    if row.kind != "email":
        raise HTTPException(422, "只有开发信可以发送")
    if not mailer.smtp_configured():
        raise HTTPException(503, "邮箱未配置（PDCA_GROWTH_SMTP_*）")
    try:
        return await asyncio.to_thread(mailer.send, session, row, body.recipients,
                                       track=body.track)
    except mailer.StopLoss as exc:
        raise HTTPException(409, str(exc)) from exc


MIN_SAMPLE = 100  # 每版本送达不足 100 不判胜负


@router.get("/stats")
async def stats(_: Manager, session: DB):
    """按内容版本汇总；比率以送达（发送-退信）为分母，打开/点击只算开启追踪的邮件。"""
    contents = {c.id: c for c in session.exec(
        select(GrowthContent).where(GrowthContent.kind == "email"))}
    agg: dict[int, dict] = {}
    for s in session.exec(select(GrowthSend)):
        a = agg.setdefault(s.content_id, {"sent": 0, "bounced": 0, "tracked": 0, "opened": 0,
                                          "clicked": 0, "replied": 0, "unsub": 0})
        a["sent"] += 1
        a["bounced"] += s.bounced_at is not None
        a["tracked"] += s.tracked
        a["opened"] += s.tracked and s.opened_at is not None
        a["clicked"] += s.tracked and s.clicked_at is not None
        a["replied"] += s.reply_kind == "reply"
        a["unsub"] += s.reply_kind == "unsub"
    rows = []
    for cid, a in agg.items():
        c = contents.get(cid)
        if not c:
            continue
        delivered = a["sent"] - a["bounced"]
        rows.append({"content_id": cid, "round_no": c.round_no, "variant": c.variant,
                     "title": c.title, "angle": c.angle, "status": c.status, **a,
                     "delivered": delivered, "enough_sample": delivered >= MIN_SAMPLE,
                     "bounce_rate": a["bounced"] / (a["sent"] or 1),
                     "reply_rate": a["replied"] / (delivered or 1),
                     "open_rate": a["opened"] / (a["tracked"] or 1) if a["tracked"] else None,
                     "click_rate": a["clicked"] / (a["tracked"] or 1) if a["tracked"] else None})
    rows.sort(key=lambda r: (-r["round_no"], r["variant"]))
    return {"rows": rows, "sent_today": mailer.sent_today(session),
            "smtp": mailer.smtp_configured(), "imap": mailer.imap_configured()}


def _send_by_token(session: Session, token: str) -> GrowthSend | None:
    return session.exec(select(GrowthSend).where(GrowthSend.token == token)).first()


@router.get("/t/o/{token}.gif", include_in_schema=False)
async def track_open(token: str, session: DB):
    row = _send_by_token(session, token)
    if row:
        row.open_count += 1
        row.opened_at = row.opened_at or datetime.utcnow()
        session.add(row)
        session.commit()
    return Response(PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@router.get("/t/c/{token}", include_in_schema=False)
async def track_click(token: str, u: str, s: str, session: DB):
    if not (u.startswith(("https://", "http://"))
            and hmac.compare_digest(s, mailer.sign(token, u))):
        raise HTTPException(400, "invalid link")
    row = _send_by_token(session, token)
    if row:
        row.click_count += 1
        row.clicked_at = row.clicked_at or datetime.utcnow()
        session.add(row)
        session.commit()
    return RedirectResponse(u, status_code=302)


@router.get("/t/u/{token}", include_in_schema=False)
async def track_unsub(token: str, session: DB):
    row = _send_by_token(session, token)
    if row and not session.get(GrowthUnsub, row.to_addr):
        session.add(GrowthUnsub(email=row.to_addr))
        session.commit()
    return HTMLResponse("<p>You have been unsubscribed. 已退订。</p>")
