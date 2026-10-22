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
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from loguru import logger
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, func, select

from app.config import get_settings
from app.growth.models import GrowthContent, GrowthDelivery, GrowthSend, GrowthUnsub
from app.models.writes import _lock_business_key

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


def _legacy_utc(value: datetime) -> datetime:
    """Legacy TIMESTAMP columns store UTC wall clock, independent of DB timezone."""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc)
    return value.replace(tzinfo=None)


def sent_today(session: Session) -> int:
    start = _legacy_utc(datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
    return session.exec(select(func.count()).select_from(GrowthSend)
                        .where(GrowthSend.sent_at >= start)).one()


def quota_used_today(session: Session, now: datetime | None = None) -> int:
    """Count successful sends plus all other reserved attempts, by UTC claim day."""
    start = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    sent = select(func.count()).select_from(GrowthSend).where(
        GrowthSend.sent_at >= _legacy_utc(start)).scalar_subquery()
    reserved = select(func.count()).select_from(GrowthDelivery).where(
        GrowthDelivery.claimed_at >= start, GrowthDelivery.status != "sent").scalar_subquery()
    # One statement snapshot: pending -> sent may commit in another worker.
    # Separate READ COMMITTED counts could miss the row on both sides.
    return session.exec(select(sent + reserved)).one()


def check_stop_loss(session: Session, content: GrowthContent) -> None:
    """近 7 天退信率 >2%（≥20 封）全局停；单版本 ≥300 封且回复率 <1% 停该版本。"""
    week = session.exec(select(GrowthSend).where(
        GrowthSend.sent_at >= _legacy_utc(datetime.now(timezone.utc) - timedelta(days=7)))).all()
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


def _reserve_deliveries(session: Session, content: GrowthContent, recipients: list[str],
                        track: bool, domain: str) -> tuple[list[GrowthDelivery], dict]:
    """Commit claims before SMTP. The DB lock serializes quota across workers."""
    content_id = content.id
    session.commit()  # End any caller read transaction before SQLite BEGIN IMMEDIATE.
    if session.get_bind().dialect.name == "sqlite":
        session.execute(sql_text("BEGIN IMMEDIATE"))
    elif session.get_bind().dialect.name == "postgresql":
        _lock_business_key(session, "growth-delivery-quota")
    else:
        raise RuntimeError("开发信发送仅支持 PostgreSQL/SQLite 原子占额")
    try:
        check_stop_loss(session, content)
        now = datetime.now(timezone.utc)
        cap = max(int(_env("PDCA_GROWTH_DAILY_CAP", "25") or 25), 0)
        remaining = max(cap - quota_used_today(session, now), 0)
        unsubs = set(session.exec(select(GrowthUnsub.email)).all())
        done = set(session.exec(select(GrowthSend.to_addr).where(
            GrowthSend.content_id == content_id)).all())
        claims = {c.to_addr: c for c in session.exec(select(GrowthDelivery).where(
            GrowthDelivery.content_id == content_id))}
        result = {"sent": [], "skipped": [], "failed": [], "pending": [],
                  "uncertain": [], "error_details": {}, "cap_left": remaining}
        todo = []
        for addr in dict.fromkeys(r.strip().lower() for r in recipients if r.strip()):
            if not EMAIL_RE.match(addr) or addr in unsubs or addr in done:
                result["skipped"].append(addr)
            elif addr in claims:
                claim = claims[addr]
                bucket = claim.status if claim.status in ("pending", "uncertain", "failed") else "skipped"
                result[bucket].append(addr)
                if bucket != "skipped":
                    result["error_details"][addr] = claim.detail or "已有发送凭证；请人工核对邮箱，系统不会自动重发"
            elif remaining <= 0:
                result["skipped"].append(addr)
            else:
                claim = GrowthDelivery(content_id=content_id, to_addr=addr,
                                       token=secrets.token_urlsafe(18), message_id=make_msgid(domain=domain),
                                       tracked=track, claimed_at=now)
                session.add(claim)
                todo.append(claim)
                remaining -= 1
        session.commit()
        result["cap_left"] = remaining
        return todo, result
    except Exception:
        session.rollback()
        raise


def _finish_delivery(session: Session, claim: GrowthDelivery, status: str, detail: str = "") -> None:
    claim.status, claim.detail = status, detail[:500]
    claim.finished_at = datetime.now(timezone.utc)
    session.add(claim)
    session.commit()


def send(session: Session, content: GrowthContent, recipients: list[str], *,
         track: bool = False) -> dict:
    """At-most-once attempts: reserve durably; never retry an uncertain/pending send."""
    sender = _env("PDCA_GROWTH_FROM") or _env("PDCA_GROWTH_SMTP_USER")
    todo, result = _reserve_deliveries(session, content, recipients, track, sender.rsplit("@", 1)[-1])
    if not todo:
        return result
    # Freeze addresses before later commits expire ORM objects.
    addresses = [claim.to_addr for claim in todo]
    reported = set()
    port = int(_env("PDCA_GROWTH_SMTP_PORT", "465") or 465)
    smtp_cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    try:
        with smtp_cls(_env("PDCA_GROWTH_SMTP_HOST"), port, timeout=30) as smtp:
            if port != 465:
                smtp.starttls()
            smtp.login(_env("PDCA_GROWTH_SMTP_USER"), _env("PDCA_GROWTH_SMTP_PASSWORD"))
            for claim, addr in zip(todo, addresses):
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = content.title, sender, addr
                msg["Message-ID"] = claim.message_id
                msg["List-Unsubscribe"] = f"<{public_base()}/api/growth/t/u/{claim.token}>"
                msg.set_content(plain_body(content))
                if track:
                    msg.add_alternative(render_html(content, claim.token), subtype="html")
                status, detail = "sent", ""
                try:
                    refused = smtp.send_message(msg)
                    if isinstance(refused, dict) and refused:
                        raise smtplib.SMTPRecipientsRefused(refused)
                except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as exc:
                    status, detail = "failed", f"SMTP 明确拒绝：{type(exc).__name__}；未自动重发"
                except Exception as exc:
                    status, detail = "uncertain", f"SMTP 结果未确认：{type(exc).__name__}；请核对邮箱，禁止直接重发"
                if status == "sent":
                    session.add(GrowthSend(content_id=claim.content_id, to_addr=addr, token=claim.token,
                                           message_id=claim.message_id, tracked=track,
                                           sent_at=_legacy_utc(claim.claimed_at)))
                    content.status = "sent"
                    session.add(content)
                try:
                    _finish_delivery(session, claim, status, detail)
                except SQLAlchemyError:
                    session.rollback()
                    # The pre-SMTP pending claim survives a failed outcome commit.
                    status, detail = "uncertain", "SMTP 已尝试但结果保存失败；请人工核对，系统不会自动重发"
                    result[status].append(addr)
                    result["error_details"][addr] = detail
                    reported.add(addr)
                    break
                result[status].append(addr)
                reported.add(addr)
                if detail:
                    result["error_details"][addr] = detail
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning("growth SMTP 会话中断：{}", type(exc).__name__)
    # Includes connection/setup failure and unattempted rows after a DB failure.
    # Claims stay pending: no inference that the remote server did or did not send.
    for addr in addresses:
        if addr not in reported:
            result["pending"].append(addr)
            result["error_details"][addr] = "发送流程未确认完成；请人工核对邮箱，系统不会自动重发"
    return result


class _ReplyHTML(HTMLParser):
    """Extract visible reply text, excluding common client quote containers."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.stopped = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        marker = (attrs.get("class", "") + " " + attrs.get("id", "")).lower()
        quoted = tag in ("blockquote", "script", "style") or any(
            name in marker for name in ("gmail_quote", "yahoo_quoted", "moz-cite-prefix"))
        if "divrplyfwdmsg" in marker or tag == "hr":
            self.stopped = True
        hidden = self.stopped or quoted or bool(self.stack and self.stack[-1][1])
        if tag not in ("br", "hr", "img", "meta", "link", "input", "wbr"):
            self.stack.append((tag, hidden))
        if not hidden and tag in ("br", "p", "div", "li"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break
        if tag in ("p", "div", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.stopped and not (self.stack and self.stack[-1][1]):
            self.parts.append(data)


def _message_text(message: EmailMessage, *, reply: bool) -> str:
    """Decode transfer encoding/charset before classifying, not raw MIME bytes."""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        value = part.get_content()
    except (LookupError, UnicodeError):
        value = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if not isinstance(value, str):
        return ""
    if reply and part.get_content_type() == "text/html":
        parser = _ReplyHTML()
        parser.feed(value)
        value = "".join(parser.parts)
    if not reply:
        return value
    lines = []
    for line in value.splitlines():
        if re.match(r"^\s*(On .+wrote:|[-_]{2,}\s*(Original Message|原始邮件)|From:|发件人[:：])", line, re.I):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines).strip()


def poll_replies(session: Session, days: int = 14) -> int:
    """IMAP 只读扫描：退信按正文中的 Message-ID 记 bounced；回复按 In-Reply-To/References
    匹配，自动回复不计，退订类回复记 unsub 并加入退订名单。返回新处理条数。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    # A new reply can reference an old, already-replied campaign. Only incoming
    # mail is windowed; unsubscribe always wins over earlier/later positive replies.
    pending = {row.message_id: row for row in session.exec(select(GrowthSend).where(
        GrowthSend.message_id != ""))}
    unconfirmed = {row.message_id: row for row in session.exec(select(GrowthDelivery).where(
        GrowthDelivery.status.in_(("pending", "uncertain"))))}
    if not pending and not unconfirmed:
        return 0
    port = int(_env("PDCA_GROWTH_IMAP_PORT", "993") or 993)
    handled = 0
    now = _legacy_utc(datetime.now(timezone.utc))
    with imaplib.IMAP4_SSL(_env("PDCA_GROWTH_IMAP_HOST"), port) as imap:
        imap.login(_env("PDCA_GROWTH_SMTP_USER"), _env("PDCA_GROWTH_SMTP_PASSWORD"))
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, "SINCE", since)
        for num in (data[0] or b"").split():
            _, parts = imap.fetch(num, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT]<0.20000>)")
            chunks = [p[1] for p in parts if isinstance(p, tuple)]
            raw_headers = chunks[0] if chunks else b""
            raw_body = chunks[1] if len(chunks) > 1 else b""
            headers = email.message_from_bytes(raw_headers.rstrip(b"\r\n") + b"\r\n\r\n" + raw_body,
                                               policy=email.policy.default)
            if BOUNCE_FROM_RE.search(headers.get("From", "")):
                text = _message_text(headers, reply=False) + "\n" + raw_body.decode("utf-8", "replace")
                for mid in set(re.findall(r"<[^<>\s]+@[^<>\s]+>", text)):
                    row = pending.get(mid)
                    if row and row.bounced_at is None:
                        row.bounced_at = now
                        session.add(row)
                        handled += 1
                continue
            if (headers.get("Auto-Submitted", "no").lower() != "no"
                    or OOO_RE.search(headers.get("Subject", ""))):
                continue
            refs = f"{headers.get('In-Reply-To', '')} {headers.get('References', '')}"
            text = _message_text(headers, reply=True)
            if not text:
                continue
            for mid in set(re.findall(r"<[^>]+>", refs)):
                row = pending.get(mid)
                kind = "unsub" if UNSUB_RE.search(text[:2000]) else "reply"
                if not row:
                    claim = unconfirmed.get(mid)
                    # SMTP outcome remains unresolved. Honor recipient intent
                    # without turning an incoming message into a sent receipt.
                    if claim and kind == "unsub" and not session.get(GrowthUnsub, claim.to_addr):
                        session.add(GrowthUnsub(email=claim.to_addr, at=now))
                        handled += 1
                    continue
                if row.reply_kind == "unsub" or (row.replied_at is not None and kind != "unsub"):
                    continue
                row.replied_at = row.replied_at or now
                row.reply_kind = kind
                if kind == "unsub" and not session.get(GrowthUnsub, row.to_addr):
                    session.add(GrowthUnsub(email=row.to_addr, at=now))
                session.add(row)
                handled += 1
    session.commit()
    return handled
