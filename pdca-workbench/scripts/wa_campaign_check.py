# -*- coding: utf-8 -*-
"""机械腕表闪购活动 · WhatsApp 触达核查（一份 HTML 报告）。

用途：核查经销商有没有把「VERTU 机械腕表配给（TODAY ONLY）」活动讲到 WhatsApp 客户面前。
只读 AINativeSales MCP 的 conversations/evidence，不发任何消息。

    python scripts/wa_campaign_check.py --days 3 --out "C:/Users/frank/Desktop/机械腕表闪购_WhatsApp核查.html"

口径：platform=WhatsApp；evidence_type=messages；keyword 为服务端子串匹配；
命中按 message id 去重，多关键词命中的同一条只算一次。
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

TZ = "Asia/Shanghai"
TARGETS = (
    ("于冰", 45),
    ("杨晶晶", 47),
    ("何海文", 238),
    ("尤文静（Viki）", 216),
    ("Lina", 171),
)
# 关键词 → 主题（命中后归到这个主题下展示）
KEYWORDS: tuple[tuple[str, str], ...] = (
    ("mechanical", "机械腕表"),
    ("机械", "机械腕表"),
    ("watch", "腕表/表"),
    ("腕表", "腕表/表"),
    ("手表", "腕表/表"),
    ("allocation", "配给/配货"),
    ("配给", "配给/配货"),
    ("提货", "配给/配货"),
    ("42,000", "门槛 4.2 万美元"),
    ("84,000", "门槛 8.4 万美元"),
    ("42000", "门槛 4.2 万美元"),
    ("84000", "门槛 8.4 万美元"),
    ("300,000", "门槛 30 万人民币"),
    ("30万", "门槛 30 万人民币"),
    ("600,000", "门槛 60 万人民币"),
    ("60万", "门槛 60 万人民币"),
    ("amber", "琥珀款"),
    ("琥珀", "琥珀款"),
    ("carbon", "碳纤款"),
    ("白碳", "碳纤款"),
    ("deposit", "定金/付款"),
    ("定金", "定金/付款"),
    ("usdt", "定金/付款"),
    ("swift", "定金/付款"),
    ("black friday", "Q4 旺季话术"),
    ("christmas", "Q4 旺季话术"),
    ("holiday", "Q4 旺季话术"),
    ("deadline", "限时截止"),
    ("today only", "限时截止"),
)
REQUIRED_THEMES = ("机械腕表", "配给/配货", "门槛 4.2 万美元", "门槛 8.4 万美元", "限时截止")


def load_env_file() -> None:
    path = APP_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def mcp_call(name: str, arguments: dict, timeout: float = 180.0) -> dict:
    """调用 AINativeSales MCP，返回解析后的业务 JSON。"""
    url = os.environ.get("PDCA_AISALES_MCP_URL", "").strip()
    token = os.environ.get("PDCA_AISALES_MCP_TOKEN", "").strip()
    if not (url and token):
        raise RuntimeError("未配置 PDCA_AISALES_MCP_URL / PDCA_AISALES_MCP_TOKEN")
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    ).encode()
    request = httpx.Request(
        "POST",
        url,
        content=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    raw = httpx.Client(timeout=timeout).send(request).text
    text = raw.split("data: ", 1)[-1] if "data: " in raw else raw
    payload = json.loads(text.strip().splitlines()[-1])
    content = (payload.get("result") or {}).get("content") or []
    if not content:
        return {}
    return json.loads(content[0].get("text") or "{}")
def fetch_hits(display: str, employee_id: int, start: str, end: str) -> dict:
    """一个人的全部关键词命中（按 message id 去重）。"""
    hits: dict[str, dict] = {}
    errors: list[str] = []
    themes: dict[str, list[str]] = {}

    def one(keyword: str, theme: str) -> tuple[str, str, dict]:
        try:
            data = mcp_call(
                "business.get_evidence",
                {
                    "evidence_type": "messages",
                    "subject": {"employee_id": employee_id},
                    "period": {"start_date": start, "end_date": end},
                    "platform": "WhatsApp",
                    "keyword": keyword,
                    "text_only": True,
                    "page": 1,
                    "page_size": 100,
                },
            )
            return keyword, theme, data
        except Exception as exc:  # noqa: BLE001 — 单关键词失败不影响整份报告
            return keyword, theme, {"error": str(exc)[:200]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda item: one(*item), KEYWORDS))
    for keyword, theme, data in results:
        if data.get("error"):
            errors.append(f"{keyword}: {data['error']}")
            continue
        for row in data.get("rows") or []:
            if row.get("row_type") != "detail":
                continue
            mid = str(row.get("id") or "")
            if not mid:
                continue
            item = hits.setdefault(
                mid,
                {
                    "id": mid,
                    "time": str(row.get("time") or ""),
                    "direction": str(row.get("direction") or ""),
                    "customer": str(row.get("customer_display") or row.get("customer_id") or ""),
                    "content": str(row.get("content") or ""),
                    "themes": [],
                    "keywords": [],
                },
            )
            item["keywords"].append(keyword)
            if theme not in item["themes"]:
                item["themes"].append(theme)
            themes.setdefault(theme, []).append(mid)
    ordered = sorted(hits.values(), key=lambda item: item["time"], reverse=True)
    return {"display": display, "employee_id": employee_id, "hits": ordered, "themes": themes, "errors": errors}


def fetch_baseline(employee_id: int, start: str, end: str) -> dict:
    """区间内该人的 WhatsApp 总触达/回复（不带关键词），用来区分“没提”和“没数据”。"""
    try:
        from app.ctob import parse_wa_summary

        data = mcp_call(
            "business.query",
            {
                "domain": "conversations",
                "query_mode": "customers",
                "subject": {"employee_id": employee_id},
                "period": {"start_date": start, "end_date": end},
                "filters": {"platform": "WhatsApp", "page_size": 30},
            },
        )
        summary = parse_wa_summary(data)
        return {
            "reached": summary.get("reached"),
            "replied": summary.get("replied"),
            "outbound": summary.get("outbound"),
            "inbound": summary.get("inbound"),
        }
    except Exception as exc:  # noqa: BLE001 — 基线取不到就写待确认
        return {"error": str(exc)[:160]}


def judge(person: dict) -> tuple[str, str]:
    """判定：明确传达活动 / 只擦边 / 完全没提。"""
    themes = set(person.get("themes") or {})
    hits = person.get("hits") or []
    if not hits:
        return "完全没提", "bad"
    core = {"机械腕表", "配给/配货"}
    money = {"门槛 4.2 万美元", "门槛 8.4 万美元", "门槛 30 万人民币", "门槛 60 万人民币"}
    if themes & core and (themes & money or themes & {"限时截止", "Q4 旺季话术", "定金/付款"}):
        return "明确传达了活动", "good"
    if themes & core:
        return "提到了，但没讲清门槛", "warn"
    return "只提到表/表字，未涉及活动", "warn"


def poster_b64(path: Path, max_width: int = 420) -> str | None:
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.width > max_width:
                ratio = max_width / float(image.width)
                image = image.resize((max_width, int(image.height * ratio)))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=70, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None
CSS = """
body { font-family: "Segoe UI","Microsoft YaHei",sans-serif; margin:0; padding:24px 30px 60px; background:#f6f7f9; color:#1f2328; }
h1 { font-size:22px; margin:0 0 4px; }
h2 { font-size:17px; margin:26px 0 10px; border-bottom:2px solid #d0d7de; padding-bottom:6px; }
h3 { font-size:15px; margin:16px 0 6px; }
.meta { color:#57606a; font-size:13px; line-height:1.7; }
table { border-collapse:collapse; width:100%; font-size:13px; background:#fff; }
th,td { border:1px solid #d0d7de; padding:6px 8px; text-align:left; vertical-align:top; }
th { background:#eef1f4; }
.card { background:#fff; border:1px solid #d0d7de; border-radius:8px; padding:14px 16px; margin:12px 0; }
.good { color:#1a7f37; font-weight:600; }
.bad { color:#b42318; font-weight:600; }
.warn { color:#9a6700; font-weight:600; }
.msg { background:#f6f8fa; border:1px solid #e3e6ea; border-radius:6px; padding:8px 10px; margin:6px 0; font-size:12.5px; }
.tag { display:inline-block; font-size:12px; padding:1px 6px; border-radius:10px; background:#eef1f4; color:#57606a; margin-right:4px; }
.posters { display:flex; gap:12px; flex-wrap:wrap; }
.posters figure { margin:0; }
.posters img { width:330px; border:1px solid #d0d7de; border-radius:6px; }
.posters figcaption { font-size:12px; color:#57606a; }
.note { color:#57606a; font-size:12.5px; }
"""


def render(payload: dict) -> str:
    day = payload["period_end"]
    people = payload["people"]
    lines: list[str] = []
    lines.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    lines.append(f"<title>机械腕表闪购 · WhatsApp 触达核查 {day}</title>")
    lines.append(f"<style>{CSS}</style></head><body>")
    lines.append("<h1>机械腕表闪购活动 · WhatsApp 触达核查</h1>")
    lines.append(
        "<p class='meta'>"
        f"核查区间：{payload['period_start']} ~ {payload['period_end']}（WhatsApp，AINativeSales MCP 消息证据）"
        f"｜生成时间：{payload['generated_at']}（北京时间）<br/>"
        "活动口径（来自官方通知 + 两张海报）：VERTU 官方通知 · 今日限定的奢华机械腕表配给 —— "
        "今日确认订单 <b>≥ $42,000（≈¥300,000）配 1 只</b>、<b>≥ $84,000（≈¥600,000）配 2 只</b>，"
        "定金（SWIFT / USDT）须在 <b>当日 24:00 GMT+8 前</b>到账，先到先得，Q4 全球满额。"
        "</p>"
    )
    posters = payload.get("posters") or []
    if posters:
        lines.append("<div class='posters'>")
        for item in posters:
            if item.get("b64"):
                lines.append(
                    f"<figure><img src='{item['b64']}' alt='海报'/><figcaption>{html.escape(item['label'])}</figcaption></figure>"
                )
        lines.append("</div>")
    lines.append("<h2>一、结论速览</h2>")
    lines.append(
        "<table><tr><th>负责人</th><th>判定</th><th>区间内 WhatsApp 触达/回复</th><th>命中消息</th>"
        "<th>覆盖客户</th><th>涉及主题</th><th>最早</th><th>最晚</th></tr>"
    )
    for person in people:
        verdict, tone = person["verdict"]
        customers = {hit["customer"] for hit in person["hits"]}
        times = sorted(hit["time"] for hit in person["hits"] if hit["time"])
        base = person.get("baseline") or {}
        base_text = (
            f"{base.get('reached') if base.get('reached') is not None else '待确认'} 户"
            f" / 回复 {base.get('replied') if base.get('replied') is not None else '待确认'}"
            if base.get("reached") is not None or base.get("replied") is not None
            else "待确认（拿不到平台统计）"
        )
        lines.append(
            "<tr>"
            f"<td><b>{html.escape(person['display'])}</b></td>"
            f"<td class='{tone}'>{verdict}</td>"
            f"<td>{html.escape(base_text)}</td>"
            f"<td>{len(person['hits'])}</td><td>{len(customers)}</td>"
            f"<td>{html.escape('、'.join(sorted(person['themes'])) or '—')}</td>"
            f"<td>{html.escape(times[0] if times else '—')}</td>"
            f"<td>{html.escape(times[-1] if times else '—')}</td>"
            "</tr>"
        )
    lines.append("</table>")
    lines.append(
        "<p class='note'>判定规则：命中「机械腕表」类 + 「配给/配货」类，且同时命中金额门槛/限时/定金任一 → "
        "<span class='good'>明确传达了活动</span>；只命中机械腕表类 → <span class='warn'>提到但没讲清门槛</span>；"
        "只命中 watch/表 这类泛词 → <span class='warn'>只擦边</span>；零命中 → <span class='bad'>完全没提</span>。"
        "关键词为服务端子串匹配，命中后逐条人工核对原文。</p>"
    )
    lines.append("<h2>二、逐人原文（按时间倒序，最多 25 条/人）</h2>")
    for person in people:
        verdict, tone = person["verdict"]
        lines.append(f"<div class='card'><h3>{html.escape(person['display'])} <span class='{tone}'>{verdict}</span></h3>")
        base = person.get("baseline") or {}
        lines.append(
            "<p class='note'>区间内 WhatsApp：触达 "
            + str(base.get("reached") if base.get("reached") is not None else "待确认")
            + " 户｜回复 " + str(base.get("replied") if base.get("replied") is not None else "待确认")
            + "｜发出 " + str(base.get("outbound") if base.get("outbound") is not None else "待确认")
            + " 条。</p>"
        )
        if not person["hits"]:
            lines.append(
                "<p class='note'>区间内没有命中任何相关关键词——结合上面的触达量判断："
                "有触达但零命中 = 没把活动讲到客户面前；触达也是待确认 = 先确认数据接入。</p>"
            )
        for hit in person["hits"][:25]:
            arrow = "发" if hit["direction"] == "outbound" else "收"
            tags = "".join(f"<span class='tag'>{html.escape(t)}</span>" for t in hit["themes"])
            if hit["themes"] == ["腕表/表"]:
                tags += "<span class='tag'>疑似字符命中（人名/其他产品等），请人工看原文</span>"
            lines.append(
                "<div class='msg'>"
                f"<b>{html.escape(hit['time'])}</b> ｜ {arrow} ｜ 客户 {html.escape(hit['customer'])} ｜ {tags}<br/>"
                f"{html.escape(hit['content'][:400])}"
                "</div>"
            )
        if person["errors"]:
            lines.append("<p class='note'>部分关键词查询失败：" + html.escape("；".join(person["errors"])[:400]) + "</p>")
        lines.append("</div>")
    lines.append("<h2>三、核查口径与复查要点</h2>")
    lines.append(
        "<ol>"
        "<li>数据源：AINativeSales MCP（platform=WhatsApp，evidence_type=messages，text_only），"
        "关键词为服务端子串匹配；同一客户多条消息会分别列出。</li>"
        "<li>命中不等于有效传达：要看是不是把「门槛金额 + 配几只 + 截止时间」讲清楚，原文都在上面。</li>"
        "<li>没命中不等于没做：微信/电话/当面沟通、或用了别的说法（如「买表送表」「满额赠」）可能漏检；"
        "必要时补扫更多关键词。</li>"
        "<li>要追动作：对「完全没提」和「只擦边」的人，明早 10:00 档点名让其回一句已发客户数，20:00 档核交付物。</li>"
        "</ol>"
    )
    lines.append("</body></html>")
    return "".join(lines)


def run(days: int = 2, end: str = "", posters_dir: str = "", out: str = "") -> dict:
    """采集 + 渲染 + 落盘，返回 {"html", "json", "summary"}。定时任务与 CLI 共用。"""
    load_env_file()
    end = end or datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")
    start = (
        datetime.strptime(end, "%Y-%m-%d") - timedelta(days=max(days - 1, 0))
    ).strftime("%Y-%m-%d")
    people = []
    for display, employee_id in TARGETS:
        person = fetch_hits(display, employee_id, start, end)
        person["baseline"] = fetch_baseline(employee_id, start, end)
        person["verdict"] = judge(person)
        people.append(person)
    posters = []
    if posters_dir:
        folder = Path(posters_dir)
        for label in ("琥珀", "白碳"):
            match = list(folder.glob("*" + label + "*.png")) if folder.exists() else []
            if match:
                posters.append({"label": label + "款海报", "b64": poster_b64(match[0])})
    payload = {
        "period_start": start,
        "period_end": end,
        "generated_at": datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M"),
        "people": people,
        "posters": posters,
    }
    summary = {
        "period": [start, end],
        "people": [
            {
                "display": p["display"],
                "verdict": p["verdict"][0],
                "hits": len(p["hits"]),
                "themes": sorted(p["themes"]),
            }
            for p in people
        ],
    }
    out_path = Path(out) if out else Path.home() / "Desktop" / ("机械腕表闪购_WhatsApp核查_" + end + ".html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(payload), encoding="utf-8")
    json_path = out_path.with_suffix(".json")
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "html": str(out_path),
        "json": str(json_path),
        "summary": summary,
        "bytes": out_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="机械腕表闪购 WhatsApp 触达核查（只读，出 HTML）")
    parser.add_argument("--days", type=int, default=3, help="核查区间天数（含今天）")
    parser.add_argument("--end", default="", help="区间结束日 YYYY-MM-DD，默认今天（北京时间）")
    parser.add_argument("--out", default="")
    parser.add_argument("--posters", default="", help="海报图片目录（可选，用于内嵌缩略图）")
    args = parser.parse_args()
    load_env_file()
    end = args.end or datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d")
    start = (
        datetime.strptime(end, "%Y-%m-%d") - timedelta(days=max(args.days - 1, 0))
    ).strftime("%Y-%m-%d")
    people = []
    for display, employee_id in TARGETS:
        person = fetch_hits(display, employee_id, start, end)
        person["baseline"] = fetch_baseline(employee_id, start, end)
        person["verdict"] = judge(person)
        people.append(person)
        print(f"{display}: {person['verdict'][0]}｜命中 {len(person['hits'])} 条")
    posters = []
    if args.posters:
        folder = Path(args.posters)
        for label in ("琥珀", "白碳"):
            match = list(folder.glob(f"*{label}*.png"))
            if match:
                posters.append({"label": label + "款海报", "b64": poster_b64(match[0])})
    payload = {
        "period_start": start,
        "period_end": end,
        "generated_at": datetime.now(ZoneInfo(TZ)).strftime("%Y-%m-%d %H:%M"),
        "people": people,
        "posters": posters,
    }
    out = Path(args.out) if args.out else Path.home() / "Desktop" / f"机械腕表闪购_WhatsApp核查_{end}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(payload), encoding="utf-8")
    (out.with_suffix(".json")).write_text(
        json.dumps(
            {
                "period": [start, end],
                "people": [
                    {"display": p["display"], "verdict": p["verdict"][0], "hits": len(p["hits"]),
                     "themes": sorted(p["themes"])}
                    for p in people
                ],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"HTML: {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())