# -*- coding: utf-8 -*-
"""开发信：SMTP 纯文本发送（可选打开/点击追踪）+ IMAP 回复/退信采集 + 止损。

默认不追踪：像素是垃圾信号，Apple MPP 让打开率失真；以回复率为主指标。
环境变量（.env，不入库）：
  PDCA_GROWTH_SMTP_HOST / PDCA_GROWTH_SMTP_PORT(465) / PDCA_GROWTH_SMTP_USER /
  PDCA_GROWTH_SMTP_PASSWORD / PDCA_GROWTH_FROM（默认同 USER，建议用副域名邮箱）
  PDCA_GROWTH_IMAP_HOST / PDCA_GROWTH_IMAP_PORT(993)
  PDCA_GROWTH_DAILY_CAP（默认 25，单邮箱日上限）
  PDCA_GROWTH_POSTAL_ADDRESS（CAN-SPAM 要求的公司地址，附在签名）
  PDCA_GROWTH_SENDER_NAME（替换正文 {{sender_name}}，多行用 \\n 分隔）
  PDCA_GROWTH_PUBLIC_BASE（默认 https://pdca-workbench-teams.vertu.cn）
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import hmac
import html
import imaplib
import os
import re
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import make_msgid
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from loguru import logger
from sqlmodel import Session, func, select

from app.config import get_settings
from app.growth.models import GrowthContent, GrowthSend, GrowthUnsub

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BOUNCE_FROM_RE = re.compile(r"mailer-daemon|postmaster", re.I)
OOO_RE = re.compile(r"out of (the )?office|automatic reply|auto[- ]?reply|自动回复", re.I)
UNSUB_RE = re.compile(r"unsubscribe|remove me|stop emailing|do not contact|退订|^\s*no[.!]?\s*$",
                      re.I | re.M)

BOUNCE_STOP = 0.02  # 近 7 天退信率上限
REPLY_FLOOR = 0.01  # 单版本 300 封后回复率下限
OPT_OUT = "If this isn't relevant, just reply \"no\" and I won't follow up."


class StopLoss(RuntimeError):
    """触发止损，拒绝继续发送。"""


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def smtp_configured() -> bool:
    return bool(_env("PDCA_GROWTH_SMTP_HOST") and _env("PDCA_GROWTH_SMTP_USER")
                and _env("PDCA_GROWTH_SMTP_PASSWORD"))


def imap_configured() -> bool:
    return bool(_env("PDCA_GROWTH_IMAP_HOST") and _env("PDCA_GROWTH_SMTP_USER")
                and _env("PDCA_GROWTH_SMTP_PASSWORD"))


def public_base() -> str:
    return _env("PDCA_GROWTH_PUBLIC_BASE", "https://pdca-workbench-teams.vertu.cn").rstrip("/")


def sign(token: str, url: str) -> str:
    """点击跳转签名，防止被当作开放重定向。"""
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{token}|{url}".encode(), hashlib.sha256).hexdigest()[:20]


def with_utm(url: str, content: GrowthContent) -> str:
    """补 UTM，GA4 才能按轮次/版本归因；已有 utm_* 不覆盖。"""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("utm_source", "email")
    query.setdefault("utm_medium", "outreach")
    query.setdefault("utm_campaign", f"growth-r{content.round_no}")
    query.setdefault("utm_content", f"c{content.id}{content.variant}")
    return urlunsplit(parts._replace(query=urlencode(query)))


def plain_body(content: GrowthContent) -> str:
    """正文（填署名）+ 退订句 + 公司地址（CAN-SPAM）。"""
    body = re.sub(r"(?<!\n)[ \t]*\{\{sender_name\}\}", "\n\n{{sender_name}}", content.body.rstrip())
    body = body.replace(
        "{{sender_name}}", _env("PDCA_GROWTH_SENDER_NAME", "VERTU Global Team").replace("\\n", "\n"))
    footer = "\n".join(filter(None, [OPT_OUT, _env("PDCA_GROWTH_POSTAL_ADDRESS")]))
    return f"{body}\n\n{footer}\n"


def render_html(content: GrowthContent, token: str) -> str:
    """仅追踪模式：链接改写为跟踪跳转，末尾加像素与退订链接。"""
    base = public_base()
    text = plain_body(content)

    def _link(match: re.Match) -> str:
        target = with_utm(match.group(0), content)
        href = f"{base}/api/growth/t/c/{token}?u={quote(target, safe='')}&s={sign(token, target)}"
        return f'<a href="{html.escape(href)}">{html.escape(match.group(0))}</a>'

    parts, last = [], 0
    for match in URL_RE.finditer(text):
        parts += [html.escape(text[last:match.start()]), _link(match)]
        last = match.end()
    parts.append(html.escape(text[last:]))
    return (
        f"<div>{''.join(parts).replace(chr(10), '<br>')}</div>"
        f'<p style="font-size:11px;color:#999"><a href="{base}/api/growth/t/u/{token}">unsubscribe</a></p>'
        f'<img src="{base}/api/growth/t/o/{token}.gif" width="1" height="1" alt="">'
    )


def sent_today(session: Session) -> int:
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.exec(select(func.count()).select_from(GrowthSend)
                        .where(GrowthSend.sent_at >= start)).one()


def check_stop_loss(session: Session, content: GrowthContent) -> None:
    """近 7 天退信率 >2%（≥20 封）全局停；单版本 ≥300 封且回复率 <1% 停该版本。"""
    week = session.exec(select(GrowthSend).where(
        GrowthSend.sent_at >= datetime.utcnow() - timedelta(days=7))).all()
    bounced = sum(s.bounced_at is not None for s in week)
    if len(week) >= 20 and bounced / len(week) > BOUNCE_STOP:
        raise StopLoss(f"止损：近 7 天退信率 {bounced / len(week):.1%} > 2%，先清洗名单再发")
    mine = [s for s in session.exec(select(GrowthSend).where(GrowthSend.content_id == content.id))]
    replied = sum(s.reply_kind == "reply" for s in mine)
    if len(mine) >= 300 and replied / len(mine) < REPLY_FLOOR:
        content.status = "paused"
        session.add(content)
        session.commit()
        raise StopLoss(f"止损：该版本已发 {len(mine)} 封，回复率 {replied / len(mine):.1%} < 1%，换定位或卖点")


def send(session: Session, content: GrowthContent, recipients: list[str], *,
         track: bool = False) -> dict:
    """逐封发送；跳过退订/重复/非法地址，触达日上限即停。"""
    check_stop_loss(session, content)
    sender = _env("PDCA_GROWTH_FROM") or _env("PDCA_GROWTH_SMTP_USER")
    domain = sender.rsplit("@", 1)[-1]
    remaining = int(_env("PDCA_GROWTH_DAILY_CAP", "25") or 25) - sent_today(session)
    unsubs = set(session.exec(select(GrowthUnsub.email)).all())
    done = set(session.exec(select(GrowthSend.to_addr)
                            .where(GrowthSend.content_id == content.id)).all())
    result = {"sent": [], "skipped": [], "failed": [], "cap_left": max(remaining, 0)}
    todo = []
    for raw in dict.fromkeys(r.strip().lower() for r in recipients if r.strip()):
        if not EMAIL_RE.match(raw) or raw in unsubs or raw in done:
            result["skipped"].append(raw)
        else:
            todo.append(raw)
    if not todo or remaining <= 0:
        result["skipped"] += todo
        return result

    port = int(_env("PDCA_GROWTH_SMTP_PORT", "465") or 465)
    smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with smtp_cls(_env("PDCA_GROWTH_SMTP_HOST"), port, timeout=30) as smtp:
        if port != 465:
            smtp.starttls()
        smtp.login(_env("PDCA_GROWTH_SMTP_USER"), _env("PDCA_GROWTH_SMTP_PASSWORD"))
        for addr in todo:
            if remaining <= 0:
                result["skipped"].append(addr)
                continue
            token = secrets.token_urlsafe(18)
            msg = EmailMessage()
            msg["Subject"], msg["From"], msg["To"] = content.title, sender, addr
            msg["Message-ID"] = make_msgid(domain=domain)
            msg["List-Unsubscribe"] = f"<{public_base()}/api/growth/t/u/{token}>"
            msg.set_content(plain_body(content))
            if track:
                msg.add_alternative(render_html(content, token), subtype="html")
            try:
                smtp.send_message(msg)
            except smtplib.SMTPException as exc:
                logger.warning("growth 发信失败 {}: {}", addr, exc)
                result["failed"].append(addr)
                continue
            session.add(GrowthSend(content_id=content.id, to_addr=addr, token=token,
                                   message_id=msg["Message-ID"], tracked=track))
            session.commit()
            result["sent"].append(addr)
            remaining -= 1
    if result["sent"]:
        content.status = "sent"
        session.add(content)
        session.commit()
    result["cap_left"] = max(remaining, 0)
    return result


def poll_replies(session: Session, days: int = 14) -> int:
    """IMAP 只读扫描：退信按正文中的 Message-ID 记 bounced；回复按 In-Reply-To/References
    匹配，自动回复不计，退订类回复记 unsub 并加入退订名单。返回新处理条数。"""
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%d-%b-%Y")
    pending = {
        row.message_id: row for row in session.exec(select(GrowthSend).where(
            GrowthSend.replied_at.is_(None), GrowthSend.bounced_at.is_(None),
            GrowthSend.sent_at >= datetime.utcnow() - timedelta(days=days)))
    }
    if not pending:
        return 0
    port = int(_env("PDCA_GROWTH_IMAP_PORT", "993") or 993)
    handled = 0
    now = datetime.utcnow()
    with imaplib.IMAP4_SSL(_env("PDCA_GROWTH_IMAP_HOST"), port) as imap:
        imap.login(_env("PDCA_GROWTH_SMTP_USER"), _env("PDCA_GROWTH_SMTP_PASSWORD"))
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, "SINCE", since)
        for num in (data[0] or b"").split():
            _, parts = imap.fetch(num, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.20000>)")
            chunks = [p[1] for p in parts if isinstance(p, tuple)]
            headers = email.message_from_bytes(chunks[0] if chunks else b"", policy=email.policy.default)
            text = (chunks[1] if len(chunks) > 1 else b"").decode("utf-8", "ignore")
            if BOUNCE_FROM_RE.search(headers.get("From", "")):
                for mid in set(re.findall(r"<[^<>\s]+@[^<>\s]+>", text)):
                    row = pending.pop(mid, None)
                    if row:
                        row.bounced_at = now
                        session.add(row)
                        handled += 1
                continue
            if (headers.get("Auto-Submitted", "no").lower() != "no"
                    or OOO_RE.search(headers.get("Subject", ""))):
                continue
            refs = f"{headers.get('In-Reply-To', '')} {headers.get('References', '')}"
            for mid in re.findall(r"<[^>]+>", refs):
                row = pending.pop(mid, None)
                if not row:
                    continue
                row.replied_at = now
                row.reply_kind = "unsub" if UNSUB_RE.search(text[:2000]) else "reply"
                if row.reply_kind == "unsub" and not session.get(GrowthUnsub, row.to_addr):
                    session.add(GrowthUnsub(email=row.to_addr))
                session.add(row)
                handled += 1
    session.commit()
    return handled
