# -*- coding: utf-8 -*-
"""三政策 WhatsApp 7 日核查：经销商一部/二部/三部全员。

① BESPOKE MTO +5% rebate（$42k / 30 万，9/20–22 72h）
② 机械腕表配给（满 $42k 赠表，TODAY ONLY）
③ Q4 Liquidation 30% down / 100% 拿货 / 3 个月免息
"""
from __future__ import annotations

import html
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from dotenv import load_dotenv

load_dotenv(APP_ROOT / ".env")

from app.duzhan_ledger import mcp_call  # noqa: E402
from app.im_files import send_files  # noqa: E402

TZ = ZoneInfo("Asia/Shanghai")
DEPTS = ((2231, "经销商一部"), (2227, "经销商二部"), (2223, "经销商三部"))
ALIAS = {
    "DEHDAHOUMAIMA": "Lina",
    "尤文静": "Viki",
    "Safae Ben M'hamed": "Safae",
}
POLICIES = (
    ("mto", "① BESPOKE MTO +5% 返点"),
    ("watch", "② 机械腕表配给（满 30 万赠表）"),
    ("clear", "③ Q4 清库 30% 现金拿货"),
)
KEYWORDS: tuple[tuple[str, str], ...] = (
    ("5% rebate", "mto"),
    ("+5%", "mto"),
    ("BESPOKE MTO", "mto"),
    ("bespoke", "mto"),
    ("Agent Q", "mto"),
    ("Himalaya", "mto"),
    ("Full-Diamond", "mto"),
    ("72 hours", "mto"),
    ("profit rebate", "mto"),
    ("MECHANICAL WATCH", "watch"),
    ("WATCH ALLOCATION", "watch"),
    ("complimentary", "watch"),
    ("TODAY ONLY", "watch"),
    ("加提", "watch"),
    ("机械腕表", "watch"),
    ("赠表", "watch"),
    ("LIQUIDATION", "clear"),
    ("liquidation", "clear"),
    ("30% DOWN", "clear"),
    ("30% down", "clear"),
    ("30% upfront", "clear"),
    ("interest-free", "clear"),
    ("GOODS IN HAND", "clear"),
    ("清库", "clear"),
    ("Q4 LIQUIDATION", "clear"),
    ("100% INVENTORY", "clear"),
    ("clearence", "clear"),
    ("clearance", "clear"),
)

_MTO_STRONG = [
    re.compile(r"5\s*%\s*rebate|\+5\s*%|profit rebate", re.I),
    re.compile(r"bespoke\s*mto", re.I),
    re.compile(r"agent\s*q|himalaya|full[- ]?diamond|72\s*hours", re.I),
]
_WATCH_STRONG = [
    re.compile(r"mechanical\s+watch\s+allocation|watch\s+allocation", re.I),
    re.compile(r"complimentary.{0,40}watch|赠.{0,8}(腕表|机械表)", re.I),
    re.compile(r"加提.{0,12}(腕表|手表)|机械腕表", re.I),
    re.compile(r"today\s+only.{0,40}(42,?000|watch)|42,?000.{0,40}watch", re.I),
]
_CLEAR_STRONG = [
    re.compile(r"q4\s*liquidation|liquidation\s*facility", re.I),
    re.compile(r"30\s*%\s*(down|upfront|定金|首付).{0,40}(goods|inventory|拿货|70%|Q4|three months)", re.I),
    re.compile(r"pay\s*30%.{0,40}(goods|three months|full[- ]price)", re.I),
    re.compile(r"interest[- ]free|100\s*%\s*(goods|inventory)", re.I),
    re.compile(r"(清库|clearance|clearence).{0,40}(30\s*%|meta\s*1|watch)", re.I),
]
_MTO_WEAK = [re.compile(r"bespoke|\+5\s*%|rebate|agent\s*q|himalaya", re.I)]
_WATCH_WEAK = [re.compile(r"加提|complimentary|today\s+only|机械", re.I)]
_CLEAR_WEAK = [re.compile(r"清库|liquidation|clearance|clearence|30\s*%\s*(down|upfront)", re.I)]
_NOISE = re.compile(r"apple\s*watch|苹果表|维修|repair", re.I)


def roster(start: str, end: str) -> list[dict]:
    """MCP 部门拆分：一二三部可见员工。"""
    people: dict[int, dict] = {}
    period = {"start_date": start, "end_date": end}
    for did, dept in DEPTS:
        payload = mcp_call(
            "business.query",
            {
                "domain": "conversations",
                "query_mode": "reach_summary",
                "subject": {"department_id": did},
                "period": period,
                "filters": {"platform": "WhatsApp", "page_size": 100},
            },
        ) or {}
        for row in payload.get("rows") or []:
            if row.get("row_type") != "detail" or not row.get("employee_id"):
                continue
            eid = int(row["employee_id"])
            name = str(row.get("employee_name") or eid)
            people[eid] = {
                "employee_id": eid,
                "name": ALIAS.get(name, name),
                "hr_name": name,
                "dept": dept,
                "outbound": row.get("outbound_message_count"),
                "inbound": row.get("inbound_message_count"),
                "customers": row.get("customer_count"),
            }
    return sorted(people.values(), key=lambda p: (p["dept"], p["name"]))


def classify(text: str) -> list[tuple[str, str]]:
    """返回 [(policy, strong|weak)]。"""
    blob = text or ""
    if _NOISE.search(blob):
        blob_watch_ok = False
    else:
        blob_watch_ok = True
    out: list[tuple[str, str]] = []
    if any(p.search(blob) for p in _MTO_STRONG):
        out.append(("mto", "strong"))
    elif any(p.search(blob) for p in _MTO_WEAK):
        out.append(("mto", "weak"))
    if blob_watch_ok:
        if any(p.search(blob) for p in _WATCH_STRONG):
            out.append(("watch", "strong"))
        elif any(p.search(blob) for p in _WATCH_WEAK):
            out.append(("watch", "weak"))
    if any(p.search(blob) for p in _CLEAR_STRONG):
        out.append(("clear", "strong"))
    elif any(p.search(blob) for p in _CLEAR_WEAK):
        out.append(("clear", "weak"))
    return out


def fetch_kw(employee_id: int, keyword: str, start: str, end: str) -> list[dict]:
    payload = mcp_call(
        "business.query",
        {
            "domain": "conversations",
            "query_mode": "messages",
            "subject": {"employee_id": employee_id},
            "period": {"start_date": start, "end_date": end},
            "filters": {
                "platform": "WhatsApp",
                "keyword": keyword,
                "text_only": True,
                "page_size": 50,
            },
        },
    ) or {}
    return [r for r in (payload.get("rows") or []) if r.get("row_type") == "detail"]


def scan_person(person: dict, start: str, end: str) -> dict:
    """一人全部关键词，按 message id 去重后本地分政策。"""
    hits: dict[str, dict] = {}

    def one(item: tuple[str, str]) -> tuple[str, str, list[dict]]:
        keyword, hint = item
        try:
            return keyword, hint, fetch_kw(person["employee_id"], keyword, start, end)
        except Exception as exc:  # noqa: BLE001
            return keyword, hint, []

    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(one, KEYWORDS))
    for keyword, hint, rows in batches:
        for row in rows:
            mid = str(row.get("id") or "")
            if not mid:
                continue
            text = str(row.get("content") or "")
            rec = hits.setdefault(
                mid,
                {
                    "id": mid,
                    "time": str(row.get("time") or ""),
                    "customer": str(row.get("customer_display") or row.get("customer_id") or ""),
                    "direction": str(row.get("direction") or ""),
                    "text": text,
                    "keywords": [],
                    "policies": [],
                },
            )
            rec["keywords"].append(keyword)
            labels = classify(text) or ([(hint, "weak")] if text.strip() else [])
            for policy, strength in labels:
                if policy not in rec["policies"]:
                    rec["policies"].append(policy)
                rec.setdefault("strength", {})
                prev = rec["strength"].get(policy)
                if prev != "strong":
                    rec["strength"][policy] = strength
    ordered = sorted(hits.values(), key=lambda x: x.get("time") or "", reverse=True)
    verdicts = {}
    outbound = person.get("outbound") or 0
    for key, _label in POLICIES:
        matched = [h for h in ordered if key in h.get("policies", [])]
        strong = any((h.get("strength") or {}).get(key) == "strong" for h in matched)
        if outbound == 0 and person.get("customers") in (0, None) and not matched:
            verdicts[key] = "无WA"
        elif strong:
            verdicts[key] = "有"
        elif matched:
            verdicts[key] = "部分"
        else:
            verdicts[key] = "无"
    person = dict(person)
    person["hits"] = ordered
    person["verdicts"] = verdicts
    return person


def _esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def _cls(verdict: str) -> str:
    return {"有": "v-strong", "部分": "v-mid", "无": "v-none", "无WA": "v-none"}.get(verdict, "v-weak")


def build_html(start: str, end: str, people: list[dict]) -> str:
    """金黑单文件 HTML。"""
    gen = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    kpis = []
    for p in people:
        v = p["verdicts"]
        kpis.append(
            f'<div class="kpi"><div class="who">{_esc(p["dept"])} · {_esc(p["name"])}</div>'
            f'<div class="verdict">①<span class="{_cls(v["mto"])}">{_esc(v["mto"])}</span> '
            f'②<span class="{_cls(v["watch"])}">{_esc(v["watch"])}</span> '
            f'③<span class="{_cls(v["clear"])}">{_esc(v["clear"])}</span></div>'
            f'<div class="sub">发 {p.get("outbound") or 0} / 收 {p.get("inbound") or 0} · '
            f'客户池 {p.get("customers") or 0}</div></div>'
        )
    rows = []
    for p in people:
        v = p["verdicts"]
        rows.append(
            "<tr>"
            f"<td>{_esc(p['dept'])}</td><td>{_esc(p['name'])}</td>"
            f'<td class="{_cls(v["mto"])}">{_esc(v["mto"])}</td>'
            f'<td class="{_cls(v["watch"])}">{_esc(v["watch"])}</td>'
            f'<td class="{_cls(v["clear"])}">{_esc(v["clear"])}</td>'
            f"<td>{len(p['hits'])}</td>"
            f"<td>{p.get('outbound') or 0}/{p.get('inbound') or 0}</td>"
            "</tr>"
        )
    sections = []
    for key, label in POLICIES:
        body = []
        for p in people:
            matched = [h for h in p["hits"] if key in h.get("policies", [])]
            if not matched:
                body.append(
                    f"<p class='note'>{_esc(p['dept'])} {_esc(p['name'])}："
                    f"{_esc(p['verdicts'][key])}（无匹配正文）</p>"
                )
                continue
            quotes = []
            for h in matched[:8]:
                quotes.append(
                    f"<blockquote>{_esc(h.get('text') or '')}</blockquote>"
                    f"<p class='note'>{_esc(h.get('time'))} · {_esc(h.get('customer'))} · "
                    f"{_esc(h.get('direction'))} · kw { _esc(', '.join(h.get('keywords') or [])[:80])}</p>"
                )
            body.append(
                f"<h3>{_esc(p['dept'])} {_esc(p['name'])} "
                f'<span class="tag {_cls(p["verdicts"][key])}">{_esc(p["verdicts"][key])}</span></h3>'
                + "".join(quotes)
            )
        sections.append(f'<section id="{key}"><h2>{_esc(label)}</h2>{"".join(body)}</section>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>三政策 WhatsApp 7日核查 { _esc(end) }</title>
<style>
:root {{ --bg:#10141c; --panel:#171d28; --line:#2a3344; --gold:#d4b56a;
  --text:#e8edf5; --muted:#8b95a7; --strong:#3d9a6a; --mid:#c9a227; --none:#c45c5c; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.55 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
header.top {{ padding:28px 32px 18px; border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font-size:22px; color:var(--gold); }}
header.top p {{ margin:8px 0 0; color:var(--muted); font-size:13px; }}
nav {{ display:flex; gap:8px; flex-wrap:wrap; padding:12px 32px; border-bottom:1px solid var(--line); position:sticky; top:0; background:var(--bg); }}
nav a {{ color:var(--text); text-decoration:none; border:1px solid var(--line); padding:6px 10px; font-size:13px; }}
main {{ padding:8px 32px 56px; max-width:1100px; }}
h2 {{ font-size:16px; color:var(--gold); border-bottom:1px solid var(--line); padding-bottom:8px; margin:28px 0 14px; }}
h3 {{ font-size:15px; margin:16px 0 8px; }}
.note {{ color:var(--muted); font-size:12px; margin:8px 0 12px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:10px; margin:16px 0; }}
.kpi {{ background:var(--panel); border:1px solid var(--line); padding:12px; }}
.kpi .who {{ font-size:12px; color:var(--muted); }}
.kpi .verdict {{ font-size:14px; font-weight:650; margin-top:6px; }}
.sub {{ font-size:12px; color:var(--muted); margin-top:6px; }}
.v-strong {{ color:var(--strong); }} .v-mid {{ color:var(--mid); }} .v-none {{ color:var(--none); }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ border:1px solid var(--line); padding:8px 10px; vertical-align:top; text-align:left; }}
th {{ background:#1c2432; color:var(--gold); }}
blockquote {{ margin:0; padding:10px 12px; background:#121821; border:1px solid var(--line); font-size:13px; white-space:pre-wrap; }}
.tag {{ display:inline-block; font-size:11px; padding:2px 7px; border:1px solid var(--line); margin-left:6px; }}
.caveat {{ border:1px solid #5a4630; background:#1a1712; padding:12px 14px; font-size:13px; color:#e2d3b3; }}
</style></head>
<body>
<header class="top">
  <h1>三政策 WhatsApp 核查 · 经销商一二三部</h1>
  <p>区间 { _esc(start) } ~ { _esc(end) }（近 7 天）· 生成 { _esc(gen) } 北京 · AINativeSales MCP WhatsApp · 名单=部门 reach_summary 可见员工</p>
</header>
<nav>
  <a href="#summary">总览</a>
  <a href="#mto">① MTO +5%</a>
  <a href="#watch">② 腕表配给</a>
  <a href="#clear">③ 清库 30%</a>
</nav>
<main>
<section id="summary">
  <h2>总览</h2>
  <p class="note">对照海报：BESPOKE MTO +5% rebate / $42,000 机械腕表配给 TODAY ONLY / Q4 LIQUIDATION 30% DOWN 100% GOODS。结论按已同步聊天正文；只发海报图无 OCR 可能漏。</p>
  <div class="grid">{''.join(kpis)}</div>
  <table>
    <thead><tr><th>部门</th><th>销售</th><th>① MTO+5%</th><th>② 腕表配给</th><th>③ 清库30%</th><th>命中条</th><th>发/收</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</section>
{''.join(sections)}
<section>
  <h2>口径</h2>
  <div class="caveat">人员来自 MCP 经销商一部(2231)/二部(2227)/三部(2223) 近 7 天可见员工，不含新部。keyword 子串 + 本地 regex。无WA=区间发收均为 0。未检出 ≠ 没发过图。</div>
</section>
</main></body></html>
"""


def build_caption(start: str, end: str, people: list[dict]) -> str:
    """私聊短正文。"""
    lines = [
        f"【三政策 WhatsApp｜{start}~{end}｜一二三部】",
        "",
    ]
    for key, label in POLICIES:
        bits = [f"{p['name']}{p['verdicts'][key]}" for p in people]
        lines.append(f"{label}：{' · '.join(bits)}")
    lines.append("")
    lines.append("明细见 HTML 附件。")
    return "\n".join(lines)


def main() -> None:
    """扫 7 天、落盘、私聊付汪阳+徐华俊。"""
    end = datetime.now(TZ).strftime("%Y-%m-%d")
    start = (datetime.now(TZ) - timedelta(days=6)).strftime("%Y-%m-%d")
    people = roster(start, end)
    print("ROSTER", [(p["dept"], p["name"], p["employee_id"]) for p in people])
    scanned = []
    for person in people:
        print("scan", person["name"], person["employee_id"])
        scanned.append(scan_person(person, start, end))
    html_text = build_html(start, end, scanned)
    out_dir = APP_ROOT / "data" / "exports" / "policy3_wa"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"三政策_WA_{start}_{end}.html"
    path.write_text(html_text, encoding="utf-8")
    caption = build_caption(start, end, scanned)
    Path(str(path) + ".json").write_text(
        json.dumps(
            {
                "start": start,
                "end": end,
                "people": [
                    {
                        "name": p["name"],
                        "dept": p["dept"],
                        "employee_id": p["employee_id"],
                        "verdicts": p["verdicts"],
                        "hits": len(p["hits"]),
                        "outbound": p.get("outbound"),
                    }
                    for p in scanned
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(caption)
    print(path)
    delivery = send_files(
        html_path=path,
        user_ids=[13365, 13102],
        caption=caption,
        idempotency_key=f"policy3-wa-{end}",
    )
    print("SEND", json.dumps(delivery, ensure_ascii=False))


if __name__ == "__main__":
    main()
