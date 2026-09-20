# -*- coding: utf-8 -*-
"""三策略 WhatsApp 前 24 小时 HTML：每天 08:00 私聊徐华俊。

查于冰 / 杨晶晶 / Lina / 何海文 / Viki：
  ① 30 万加提腕表资格
  ② 清库存 30% 现金拿货
  ③ 圣诞 / 黑五 / 购物节
不带 MCP keyword（于冰教训：词面对不上只回 summary）。本地 regex 打分。
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

from app.config import get_settings
from app.duzhan_ledger import OWNERS, mcp_call

TZ = ZoneInfo("Asia/Shanghai")
TARGETS = ("于冰", "杨晶晶", "Lina", "何海文", "Viki")
MAX_PAGES = 8
PAGE_SIZE = 50

TOPIC_WATCH = "watch"
TOPIC_CLEAR = "clearance"
TOPIC_HOLIDAY = "holiday"
TOPIC_LABELS = {
    TOPIC_WATCH: "① 30万加提腕表资格策略",
    TOPIC_CLEAR: "② 清库存30%现金拿货策略",
    TOPIC_HOLIDAY: "③ 圣诞节黑五购物节",
}

_WATCH_STRONG = [
    re.compile(r"加提.{0,16}(腕表|手表)", re.I),
    re.compile(r"(腕表|手表).{0,16}加提", re.I),
    re.compile(r"腕表资格|加提资格", re.I),
    re.compile(r"30\s*万.{0,24}(腕表|手表)", re.I),
    re.compile(r"(腕表|手表).{0,24}30\s*万", re.I),
]
_WATCH_WEAK = [
    re.compile(r"加提"),
    re.compile(r"(?<![Aa]pple\s)(?<!苹果)腕表"),
    re.compile(r"(?<![Aa]pple\s)luxury\s+watch", re.I),
]
_CLEAR_STRONG = [
    re.compile(
        r"(清库|clearance|clearence|liquidation).{0,40}(30\s*%|三成|upfront|down\s*payment|现金拿货)",
        re.I,
    ),
    re.compile(
        r"(30\s*%|三成|upfront).{0,40}(清库|clearance|clearence|liquidation|goods|拿货)",
        re.I,
    ),
    re.compile(r"pay\s*30%\s*.{0,40}(goods|three months|full[- ]price)", re.I),
    re.compile(r"30%\s*upfront.{0,40}(70%|Q4|settled)", re.I),
]
_CLEAR_WEAK = [
    re.compile(r"清库|clearance|clearence|liquidation", re.I),
    re.compile(r"30\s*%\s*(down|upfront|定金|首付|现金)", re.I),
    re.compile(r"现金拿货|100\s*%\s*(goods|inventory|拿货)", re.I),
]
_HOLIDAY = [
    re.compile(r"圣诞|christmas|\bxmas\b", re.I),
    re.compile(r"黑五|black\s*friday", re.I),
    re.compile(r"购物节|holiday\s*(cash|season|sale)", re.I),
    re.compile(r"boxing\s*day|网络星期一|cyber\s*monday", re.I),
]
_WATCH_NOISE = re.compile(r"apple\s*watch|苹果表|维修|repair", re.I)


@dataclass
class Hit:
    """一条命中的 WhatsApp 消息。"""

    owner: str
    topic: str
    strength: str
    time: str
    customer: str
    direction: str
    kind: str
    text: str
    complete: bool = True


@dataclass
class OwnerScan:
    """一人窗口内的扫描结果。"""

    display: str
    employee_id: int | None
    message_count: int = 0
    complete: bool = True
    wa_configured: bool = True
    hits: list[Hit] = field(default_factory=list)
    note: str = ""


def window_for(push_day: str) -> tuple[datetime, datetime]:
    """推送日 08:00 往前 24 小时。"""
    end = datetime.strptime(push_day, "%Y-%m-%d").replace(
        hour=8, minute=0, second=0, tzinfo=TZ
    )
    return end - timedelta(hours=24), end


def window_text(start: datetime, end: datetime) -> str:
    """窗口文案。"""
    return f"{start.strftime('%m-%d %H:%M')} → {end.strftime('%m-%d %H:%M')}"


def _msg_text(row: dict) -> str:
    for key in ("content", "message_body", "body", "text", "message_text", "preview"):
        val = row.get(key)
        if isinstance(val, str) and val.strip():
            return val
    mm = row.get("multimodal")
    if isinstance(mm, dict) and mm:
        return json.dumps(mm, ensure_ascii=False)
    return ""


def _msg_time(row: dict) -> datetime | None:
    raw = str(row.get("time") or row.get("message_time") or row.get("created_at") or "")
    if not raw:
        return None
    raw = raw.replace("T", " ").replace("Z", "")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw[:19], fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def classify(text: str) -> list[tuple[str, str]]:
    """返回 [(topic, strong|weak), ...]。维修店 Apple Watch 不进腕表策略。"""
    blob = text or ""
    out: list[tuple[str, str]] = []
    if not _WATCH_NOISE.search(blob):
        if any(p.search(blob) for p in _WATCH_STRONG):
            out.append((TOPIC_WATCH, "strong"))
        elif any(p.search(blob) for p in _WATCH_WEAK):
            out.append((TOPIC_WATCH, "weak"))
    if any(p.search(blob) for p in _CLEAR_STRONG):
        out.append((TOPIC_CLEAR, "strong"))
    elif any(p.search(blob) for p in _CLEAR_WEAK):
        out.append((TOPIC_CLEAR, "weak"))
    if any(p.search(blob) for p in _HOLIDAY):
        out.append((TOPIC_HOLIDAY, "strong"))
    return out


def _in_window(row: dict, start: datetime, end: datetime) -> bool:
    when = _msg_time(row)
    if when is None:
        return True
    return start <= when < end


def fetch_owner_messages(
    employee_id: int, start: datetime, end: datetime
) -> tuple[list[dict], bool, str]:
    """无 keyword 分页拉 WhatsApp；本地再按 24h 过滤。"""
    details: list[dict] = []
    complete = True
    note = ""
    period = {
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
    }
    for page in range(1, MAX_PAGES + 1):
        payload = mcp_call(
            "business.query",
            {
                "domain": "conversations",
                "query_mode": "messages",
                "subject": {"employee_id": employee_id},
                "period": period,
                "filters": {
                    "platform": "WhatsApp",
                    "page": page,
                    "page_size": PAGE_SIZE,
                },
            },
        ) or {}
        if payload.get("is_complete") is False:
            complete = False
        rows = [r for r in (payload.get("rows") or []) if r.get("row_type") == "detail"]
        summary = next(
            (r for r in (payload.get("rows") or []) if r.get("row_type") == "summary"),
            None,
        )
        if summary:
            wa = ((summary.get("data_freshness") or {}).get("platforms") or {}).get(
                "whatsapp"
            ) or {}
            if wa.get("status") == "not_configured":
                return [], True, "未配置 WhatsApp"
            note = str(wa.get("note") or note)
            if wa.get("is_complete") is False:
                complete = False
        if not rows:
            break
        details.extend(rows)
        paging = payload.get("pagination") or {}
        if not paging.get("has_more"):
            break
    kept = [r for r in details if _in_window(r, start, end)]
    return kept, complete, note


def scan_owners(start: datetime, end: datetime) -> list[OwnerScan]:
    """扫五人。"""
    wanted = [o for o in OWNERS if o.display in TARGETS]
    out: list[OwnerScan] = []
    for owner in wanted:
        scan = OwnerScan(display=owner.display, employee_id=owner.employee_id)
        if not owner.employee_id:
            scan.wa_configured = False
            scan.note = "无 employee_id"
            out.append(scan)
            continue
        rows, complete, note = fetch_owner_messages(owner.employee_id, start, end)
        scan.message_count = len(rows)
        scan.complete = complete
        scan.note = note
        if note == "未配置 WhatsApp" or (complete and len(rows) == 0 and not note):
            cust = mcp_call(
                "business.query",
                {
                    "domain": "conversations",
                    "query_mode": "customers",
                    "subject": {"employee_id": owner.employee_id},
                    "period": {
                        "start_date": start.date().isoformat(),
                        "end_date": end.date().isoformat(),
                    },
                    "filters": {"platform": "WhatsApp", "page_size": 1},
                },
            ) or {}
            summary_text = str(cust.get("summary") or "")
            if "客户 0" in summary_text or "触达 0" in summary_text:
                scan.wa_configured = False
                scan.note = summary_text[:180] or "区间 WhatsApp 触达 0"
        seen: set[str] = set()
        for row in rows:
            text = _msg_text(row)
            labels = classify(text)
            if not labels:
                continue
            mid = str(row.get("id") or text[:80])
            for topic, strength in labels:
                key = f"{mid}|{topic}"
                if key in seen:
                    continue
                seen.add(key)
                scan.hits.append(
                    Hit(
                        owner=owner.display,
                        topic=topic,
                        strength=strength,
                        time=str(row.get("time") or ""),
                        customer=str(
                            row.get("customer_display")
                            or row.get("customer_id")
                            or ""
                        ),
                        direction=str(row.get("direction") or ""),
                        kind=str(row.get("message_kind") or row.get("message_type") or ""),
                        text=text[:800],
                        complete=complete,
                    )
                )
        out.append(scan)
    return out


def topic_verdict(scan: OwnerScan, topic: str) -> str:
    """有 / 部分 / 无 / 无WA / 待确认。

    已扫到正文但没命中 → 无（同步未完写在 HTML 副标题，不把「无」改成待确认）。
    0 条且同步未完 → 待确认。
    """
    if not scan.wa_configured:
        return "无WA"
    hits = [h for h in scan.hits if h.topic == topic]
    if any(h.strength == "strong" for h in hits):
        return "有"
    if hits:
        return "部分"
    if scan.message_count == 0 and not scan.complete:
        return "待确认"
    return "无"


def build_im_body(push_day: str, start: datetime, end: datetime, scans: list[OwnerScan]) -> str:
    """私聊短正文；明细在 HTML 附件。"""
    lines = [
        f"【三策略 WhatsApp｜{push_day} 08:00】",
        f"窗口 {window_text(start, end)}｜对象 {' / '.join(TARGETS)}",
        "",
    ]
    for topic, label in TOPIC_LABELS.items():
        bits = [f"{s.display}{topic_verdict(s, topic)}" for s in scans]
        lines.append(f"{label}：{' · '.join(bits)}")
    lines.append("")
    lines.append("明细见 HTML 附件。未检出 ≠ 没发过图（file/image 无 OCR）。")
    return "\n".join(lines)


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _verdict_class(verdict: str) -> str:
    return {
        "有": "v-strong",
        "部分": "v-mid",
        "待确认": "v-weak",
        "无": "v-none",
        "无WA": "v-none",
    }.get(verdict, "v-weak")


def build_html(
    push_day: str, start: datetime, end: datetime, scans: list[OwnerScan]
) -> str:
    """与 Q4 Liquidation 检索页同一套金黑单文件 HTML。"""
    kpis = []
    for scan in scans:
        cells = " / ".join(
            f"{TOPIC_LABELS[t][0]}{topic_verdict(scan, t)}"
            for t in (TOPIC_WATCH, TOPIC_CLEAR, TOPIC_HOLIDAY)
        )
        kpis.append(
            f'<div class="kpi"><div class="who">{_esc(scan.display)}</div>'
            f'<div class="verdict">{_esc(cells)}</div>'
            f'<div class="sub">窗口内 {scan.message_count} 条'
            f'{" · 同步未完" if not scan.complete else ""}'
            f'{" · " + _esc(scan.note[:80]) if scan.note else ""}</div></div>'
        )
    tables = []
    for topic, label in TOPIC_LABELS.items():
        rows = []
        for scan in scans:
            verdict = topic_verdict(scan, topic)
            hits = [h for h in scan.hits if h.topic == topic]
            if not hits:
                rows.append(
                    "<tr>"
                    f"<td>{_esc(scan.display)}</td><td>—</td><td>—</td>"
                    f'<td class="{_verdict_class(verdict)}">{_esc(verdict)}</td>'
                    f"<td>{_esc(scan.note[:120] if verdict in ('无WA', '待确认') else '未检出正文')}</td>"
                    "</tr>"
                )
                continue
            for hit in hits:
                rows.append(
                    "<tr>"
                    f"<td>{_esc(scan.display)}</td>"
                    f"<td>{_esc(hit.time)}</td>"
                    f"<td>{_esc(hit.customer)} / { _esc(hit.direction)}</td>"
                    f'<td class="{_verdict_class(verdict)}">{_esc(verdict)}（{ _esc(hit.strength)}）</td>'
                    f"<td>{_esc(hit.text)}</td>"
                    "</tr>"
                )
        tables.append(
            f'<section id="{topic}"><h2>{_esc(label)}</h2>'
            "<table><thead><tr>"
            "<th>销售</th><th>时间</th><th>客户 / 方向</th><th>结论</th><th>原文</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table></section>"
        )
    people = []
    for scan in scans:
        blocks = []
        for topic in (TOPIC_WATCH, TOPIC_CLEAR, TOPIC_HOLIDAY):
            hits = [h for h in scan.hits if h.topic == topic]
            verdict = topic_verdict(scan, topic)
            if hits:
                quotes = "".join(
                    f"<blockquote>{_esc(h.text)}</blockquote>"
                    f'<p class="note">{_esc(h.time)} · {_esc(h.customer)} · {_esc(h.direction)}</p>'
                    for h in hits[:6]
                )
            else:
                quotes = f'<p class="note">{_esc(verdict)}：窗口内无匹配正文。</p>'
            blocks.append(
                f"<h3>{_esc(TOPIC_LABELS[topic])} "
                f'<span class="tag { _verdict_class(verdict)}">{_esc(verdict)}</span></h3>'
                + quotes
            )
        people.append(
            f'<section class="person" id="p-{_esc(scan.display)}">'
            f"<h3>{_esc(scan.display)} <span class=\"tag\">employee_id {scan.employee_id}</span>"
            f'<span class="tag">{scan.message_count} 条</span></h3>'
            + "".join(blocks)
            + "</section>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>三策略 WhatsApp · { _esc(push_day) } 08:00</title>
<style>
:root {{
  --bg:#10141c; --panel:#171d28; --line:#2a3344; --gold:#d4b56a;
  --text:#e8edf5; --muted:#8b95a7; --strong:#3d9a6a; --mid:#c9a227; --none:#c45c5c;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
header.top {{ padding:28px 32px 18px; border-bottom:1px solid var(--line); }}
header.top h1 {{ margin:0; font-size:22px; color:var(--gold); font-weight:650; }}
header.top p {{ margin:8px 0 0; color:var(--muted); font-size:13px; }}
nav {{ display:flex; gap:8px; flex-wrap:wrap; padding:12px 32px; border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); }}
nav a {{ color:var(--text); text-decoration:none; border:1px solid var(--line); padding:6px 10px; font-size:13px; }}
main {{ padding:8px 32px 56px; max-width:1080px; }}
h2 {{ font-size:16px; color:var(--gold); border-bottom:1px solid var(--line); padding-bottom:8px; margin:28px 0 14px; }}
h3 {{ font-size:15px; margin:16px 0 8px; }}
.note {{ color:var(--muted); font-size:12px; margin:8px 0 12px; }}
.grid5 {{ display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin:16px 0; }}
.kpi {{ background:var(--panel); border:1px solid var(--line); padding:14px 12px; }}
.kpi .who {{ font-size:13px; color:var(--muted); }}
.kpi .verdict {{ font-size:15px; font-weight:650; margin-top:6px; }}
.kpi .sub {{ font-size:12px; color:var(--muted); margin-top:6px; }}
.v-strong {{ color:var(--strong); }}
.v-mid {{ color:var(--mid); }}
.v-weak {{ color:var(--muted); }}
.v-none {{ color:var(--none); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ border:1px solid var(--line); padding:8px 10px; vertical-align:top; text-align:left; }}
th {{ background:#1c2432; color:var(--gold); }}
.person {{ background:var(--panel); border:1px solid var(--line); margin:0 0 14px; padding:16px 18px; }}
blockquote {{ margin:0; padding:10px 12px; background:#121821; border:1px solid var(--line); font-size:13px; white-space:pre-wrap; }}
.tag {{ display:inline-block; font-size:11px; padding:2px 7px; border:1px solid var(--line); color:var(--muted); margin-right:6px; }}
.caveat {{ border:1px solid #5a4630; background:#1a1712; padding:12px 14px; font-size:13px; color:#e2d3b3; }}
@media (max-width:900px) {{ .grid5 {{ grid-template-columns:1fr 1fr; }} }}
</style>
</head>
<body>
<header class="top">
  <h1>三策略 WhatsApp 语义检索</h1>
  <p>对象：{' / '.join(TARGETS)} · 窗口 { _esc(window_text(start, end)) } · 推送日 { _esc(push_day) } 08:00 北京 · 来源 AINativeSales MCP messages（无 keyword，本地 regex）</p>
</header>
<nav>
  <a href="#summary">总览</a>
  <a href="#watch">①腕表</a>
  <a href="#clearance">②清库30%</a>
  <a href="#holiday">③圣诞黑五</a>
</nav>
<main>
<section id="summary">
  <h2>总览</h2>
  <p class="note">对照话术：30 万加提腕表资格 / 清库存 30% 现金拿货 / 圣诞·黑五·购物节。结论按已同步聊天正文。</p>
  <div class="grid5">{''.join(kpis)}</div>
</section>
{''.join(tables)}
{''.join(people)}
<section>
  <h2>口径</h2>
  <div class="caveat">MCP 无 keyword 分页 + 本地过滤。keyword 会漏「30% upfront」这类词面。file/image 无 OCR，海报图可能漏。is_complete=false 时「无」只能写成待确认。Apple Watch / 维修店不计入腕表加提。</div>
</section>
</main>
</body>
</html>
"""


def save_html(push_day: str, html_text: str) -> Path:
    """落到 data/exports/strategy_wa/。"""
    out_dir = get_settings().data_dir / "exports" / "strategy_wa"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"三策略_WA_{push_day}.html"
    path.write_text(html_text, encoding="utf-8")
    files = sorted(out_dir.glob("三策略_WA_*.html"), key=lambda p: p.stat().st_mtime)
    for stale in files[: max(len(files) - 45, 0)]:
        stale.unlink(missing_ok=True)
    return path


def run_brief(push_day: str, *, dry_run: bool = False) -> dict:
    """采集 → HTML → 私聊徐华俊。"""
    start, end = window_for(push_day)
    scans = scan_owners(start, end)
    html_text = build_html(push_day, start, end, scans)
    path = save_html(push_day, html_text)
    body = build_im_body(push_day, start, end, scans)
    result = {
        "day": push_day,
        "html": str(path),
        "body": body,
        "scans": [
            {
                "display": s.display,
                "messages": s.message_count,
                "complete": s.complete,
                "watch": topic_verdict(s, TOPIC_WATCH),
                "clearance": topic_verdict(s, TOPIC_CLEAR),
                "holiday": topic_verdict(s, TOPIC_HOLIDAY),
            }
            for s in scans
        ],
        "sent": False,
        "reason": "",
    }
    if dry_run:
        result["reason"] = "dry_run"
        return result
    settings = get_settings()
    user_id = int(getattr(settings, "strategy_wa_brief_user_id", 13102) or 13102)
    from app.todos.service import send_direct_message

    ok, err, _mid = send_direct_message(
        user_id,
        body,
        f"strategy-wa-{push_day}",
        attach=str(path),
    )
    result["sent"] = ok
    result["reason"] = err
    if not ok:
        logger.warning("三策略 WhatsApp HTML 私聊失败 {}: {}", push_day, err)
    return result


def main() -> None:
    """CLI：python -m app.strategy_wa_brief [--day YYYY-MM-DD] [--dry-run]。"""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--day", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    day = args.day or datetime.now(TZ).strftime("%Y-%m-%d")
    result = run_brief(day, dry_run=args.dry_run)
    print(json.dumps({k: result[k] for k in result if k != "body"}, ensure_ascii=False, indent=2))
    print(result["body"])


if __name__ == "__main__":
    main()
