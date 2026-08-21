# -*- coding: utf-8 -*-
"""
从 Vemory 周数据 JSON 生成按周汇总 HTML 报告。

用法:
  python build_vemory_weekly_html.py
  python build_vemory_weekly_html.py --input ../../data_raw/liu_vemory_week_2026-06-08.json
  python build_vemory_weekly_html.py --pull   # 先拉取本周再生成
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date, timedelta
from html import escape
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MVP_ROOT = SCRIPT_DIR.parent
REPO_ROOT = MVP_ROOT.parent.parent
DATA_RAW = REPO_ROOT / "data_raw"
OUT_DIR = MVP_ROOT / "outputs" / "vemory_weekly"
PULL_SCRIPT = DATA_RAW / "pull_liu_vemory_week.py"
VERTU = Path.home() / "AppData/Roaming/npm/vertu.cmd"

WEEKDAY_ZH = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
CATEGORY_LABEL = {
    "dealer_customer": "经销商/客户",
    "interview": "招聘面试",
    "internal_report": "内部汇报",
    "other": "其他",
}
CATEGORY_COLOR = {
    "dealer_customer": "#047857",
    "interview": "#7c3aed",
    "internal_report": "#2563eb",
    "other": "#6b7280",
}
OUTLIER_MINUTES = 120
STOP_WORDS = {
    "会议", "讨论", "沟通", "确认", "方案", "进行", "关于", "简短", "内部", "重点", "主要",
    "围绕", "展开", "整体", "最终", "形成", "明确", "表示", "提到", "认为", "需要", "继续",
    "以及", "通过", "如果", "可以", "已经", "目前", "相关", "一个", "我们", "他们", "这个",
    "that", "this", "with", "from", "were", "was", "are", "for", "and", "the", "brief",
    "internal", "meeting", "discussion", "update", "review", "held", "focus", "focused",
    "speaker", "content", "transcript", "exchange", "unclear", "identity", "language", "test",
    "audio", "setup", "issue", "shopping", "beverage", "container", "selection", "check",
    "introductory", "substantive", "no", "yes",
}
DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}\s*")
EN_WORD = re.compile(r"[A-Za-z]{3,}")
ZH_SEG = re.compile(r"[\u4e00-\u9fff]+")


def week_bounds(day: date | None = None) -> tuple[date, date]:
    """返回本周一至今天。"""
    today = day or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, today


def week_key(monday: date) -> str:
    iso = monday.isocalendar()
    return f"{monday.year}-W{iso.week:02d}"


def default_input_path(monday: date) -> Path:
    return DATA_RAW / f"liu_vemory_week_{monday.isoformat()}.json"


def classify_meeting(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("面试", "interview", "招聘", "hr ", "candidate")):
        return "interview"
    if any(k in text for k in ("经销商", "dealer", "代理", "客户", "customer", "拜访", "store", "boutique")):
        return "dealer_customer"
    if any(k in text for k in ("周会", "月会", "汇报", "复盘", "对齐", "review", "报表", "周报")):
        return "internal_report"
    return "other"


def load_payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_meetings(payload: dict) -> list[dict]:
    """从 summary.all_meetings 或 raw 构建统一会议列表。"""
    summary = payload.get("summary") or {}
    if summary.get("all_meetings"):
        return summary["all_meetings"]

    rows: list[dict] = []
    for person in payload.get("raw") or []:
        name = person.get("name") or ""
        for m in person.get("meetings") or []:
            secs = int(m.get("duration_seconds") or 0)
            rows.append(
                {
                    "person": name,
                    "title": m.get("name") or "",
                    "start_time": m.get("start_time") or "",
                    "duration_minutes": round(secs / 60, 1) if secs else 0,
                    "todo_count": len(m.get("todos") or []),
                    "category": classify_meeting(str(m.get("name") or ""), str(m.get("summary") or "")),
                    "summary": (m.get("summary") or "")[:300],
                    "is_outlier": (secs / 60) > OUTLIER_MINUTES if secs else False,
                }
            )
    rows.sort(key=lambda x: x.get("start_time") or "", reverse=True)
    return rows


def enrich_meetings_from_raw(meetings: list[dict], payload: dict) -> list[dict]:
    """从 raw 补全 summary 等字段。"""
    raw_index: dict[tuple[str, str, str], dict] = {}
    for person in payload.get("raw") or []:
        pname = person.get("name") or ""
        for m in person.get("meetings") or []:
            key = (pname, str(m.get("start_time") or ""), str(m.get("name") or ""))
            raw_index[key] = m

    enriched = []
    for m in meetings:
        row = dict(m)
        key = (str(row.get("person") or ""), str(row.get("start_time") or ""), str(row.get("title") or ""))
        raw = raw_index.get(key)
        if raw:
            row["summary"] = (raw.get("summary") or "")[:500]
        else:
            row.setdefault("summary", "")
        enriched.append(row)
    return enriched


def tokenize_for_cloud(text: str) -> list[str]:
    """从标题/摘要提取词云词条。"""
    text = DATE_PREFIX.sub("", text or "")
    text = re.sub(r"\d{4}-\d{2}-\d{2}", " ", text)
    text = re.sub(r"\d+", " ", text)
    tokens: list[str] = []
    for word in EN_WORD.findall(text):
        tokens.append(word.lower())
    for seg in ZH_SEG.findall(text):
        if len(seg) <= 5:
            tokens.append(seg)
            continue
        for size in (2, 3, 4):
            for i in range(len(seg) - size + 1):
                tokens.append(seg[i : i + size])
    return tokens


def build_word_cloud(meetings: list[dict], limit: int = 90) -> list[list]:
    """
    构建词云数据 [[word, weight], ...]。
    @param meetings 会议列表
    @param limit 最大词条数
    """
    counter: dict[str, float] = defaultdict(float)
    for m in meetings:
        weight = 0.35 if float(m.get("duration_minutes") or 0) > OUTLIER_MINUTES else 1.0
        cat = m.get("category") or "other"
        if cat == "dealer_customer":
            weight *= 1.15
        elif cat == "interview":
            weight *= 1.05
        parts = [str(m.get("title") or "")]
        if m.get("summary"):
            parts.append(str(m["summary"])[:220])
        for text in parts:
            for tok in tokenize_for_cloud(text):
                if tok in STOP_WORDS or len(tok) < 2:
                    continue
                if re.fullmatch(r"[a-z]+", tok) and len(tok) < 4:
                    continue
                counter[tok] += weight

    ranked = sorted(counter.items(), key=lambda x: (-x[1], -len(x[0])))
    deduped: list[list] = []
    seen: set[str] = set()
    for word, weight in ranked:
        if any(word in kept and word != kept for kept in seen):
            continue
        if word in seen:
            continue
        seen.add(word)
        deduped.append([word, round(weight, 1)])
        if len(deduped) >= limit:
            break
    return deduped


def aggregate(payload: dict) -> dict:
    summary = payload.get("summary") or {}
    window = summary.get("window") or {}
    start = window.get("from") or ""
    end = window.get("to") or ""

    meetings = enrich_meetings_from_raw(normalize_meetings(payload), payload)
    by_person: dict[str, dict] = defaultdict(lambda: {"count": 0, "minutes": 0.0, "todos": 0, "outlier_minutes": 0.0})
    by_day: dict[str, dict] = defaultdict(lambda: {"count": 0, "minutes": 0.0})
    by_category: dict[str, int] = defaultdict(int)

    for m in meetings:
        person = m.get("person") or "未知"
        mins = float(m.get("duration_minutes") or 0)
        day = (m.get("start_time") or "")[:10]
        cat = m.get("category") or "other"
        by_person[person]["count"] += 1
        by_person[person]["minutes"] += mins
        by_person[person]["todos"] += int(m.get("todo_count") or 0)
        if m.get("is_outlier") or mins > OUTLIER_MINUTES:
            by_person[person]["outlier_minutes"] += mins
        if day:
            by_day[day]["count"] += 1
            by_day[day]["minutes"] += mins
        by_category[cat] += 1

    people = []
    for name, stats in by_person.items():
        effective = max(0.0, stats["minutes"] - stats["outlier_minutes"])
        people.append(
            {
                "name": name,
                "count": stats["count"],
                "hours": round(stats["minutes"] / 60, 1),
                "effective_hours": round(effective / 60, 1),
                "avg_minutes": round(stats["minutes"] / stats["count"], 1) if stats["count"] else 0,
                "todos": stats["todos"],
                "outlier_hours": round(stats["outlier_minutes"] / 60, 1),
            }
        )
    people.sort(key=lambda x: (-x["count"], -x["hours"]))

    days = []
    if start and end:
        cur = date.fromisoformat(start)
        end_d = date.fromisoformat(end)
        while cur <= end_d:
            key = cur.isoformat()
            d = by_day.get(key, {"count": 0, "minutes": 0.0})
            days.append(
                {
                    "date": key,
                    "weekday": WEEKDAY_ZH[cur.weekday()],
                    "count": d["count"],
                    "hours": round(d["minutes"] / 60, 1),
                }
            )
            cur += timedelta(days=1)

    total_minutes = sum(float(m.get("duration_minutes") or 0) for m in meetings)
    outlier_minutes = sum(
        float(m.get("duration_minutes") or 0)
        for m in meetings
        if float(m.get("duration_minutes") or 0) > OUTLIER_MINUTES
    )
    active_days = sum(1 for d in days if d["count"] > 0)

    return {
        "window": {"from": start, "to": end, "label": f"{start} ~ {end}"},
        "week_key": week_key(date.fromisoformat(start)) if start else "",
        "viewer": summary.get("viewer") or "刘春梅",
        "generated_at": date.today().isoformat(),
        "totals": {
            "meetings": len(meetings),
            "hours": round(total_minutes / 60, 1),
            "effective_hours": round((total_minutes - outlier_minutes) / 60, 1),
            "outlier_hours": round(outlier_minutes / 60, 1),
            "todos": sum(int(m.get("todo_count") or 0) for m in meetings),
            "active_people": sum(1 for p in people if p["count"] > 0),
            "active_days": active_days,
            "avg_per_day": round(len(meetings) / active_days, 1) if active_days else 0,
        },
        "by_person": people,
        "by_day": days,
        "by_category": {CATEGORY_LABEL.get(k, k): v for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "word_cloud": build_word_cloud(meetings),
        "meetings": [
            {
                **m,
                "category_label": CATEGORY_LABEL.get(m.get("category") or "other", "其他"),
            }
            for m in meetings
        ],
    }


def fmt_hours(h: float) -> str:
    if h < 1:
        return f"{round(h * 60)}min"
    return f"{h:.1f}h"


def render_bar(value: float, max_value: float, color: str = "#0891b2") -> str:
    pct = 0 if max_value <= 0 else min(100, round(value / max_value * 100))
    return (
        f'<div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>'
    )


def render_html(data: dict) -> str:
    t = data["totals"]
    max_person_hours = max((p["hours"] for p in data["by_person"]), default=1)
    cat_total = sum(data["by_category"].values()) or 1

    person_rows = []
    for p in data["by_person"]:
        if p["count"] == 0:
            continue
        outlier_note = f'<span class="muted">含异常 {p["outlier_hours"]}h</span>' if p["outlier_hours"] else ""
        person_rows.append(
            f"""<tr>
              <td><strong>{escape(p['name'])}</strong></td>
              <td class="num">{p['count']}</td>
              <td class="num">{p['hours']}</td>
              <td class="num">{p['effective_hours']}</td>
              <td class="num">{p['avg_minutes']}</td>
              <td class="num">{p['todos']}</td>
              <td>{render_bar(p['hours'], max_person_hours)}{outlier_note}</td>
            </tr>"""
        )

    cat_blocks = []
    for label, count in data["by_category"].items():
        pct = round(count / cat_total * 100)
        color = next((CATEGORY_COLOR[k] for k, v in CATEGORY_LABEL.items() if v == label), "#6b7280")
        cat_blocks.append(
            f"""<div class="cat-item">
              <div class="cat-head"><span>{escape(label)}</span><strong>{count} ({pct}%)</strong></div>
              <div class="bar-track"><div class="bar-fill" style="width:{pct}%;background:{color}"></div></div>
            </div>"""
        )

    word_cloud_json = json.dumps(data.get("word_cloud") or [], ensure_ascii=False)
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Vemory 周报 · {escape(data['window']['label'])}</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --card: #ffffff;
      --ink: #0f172a;
      --muted: #64748b;
      --line: #e2e8f0;
      --accent: #0891b2;
      --accent-soft: #ecfeff;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      background: linear-gradient(180deg, #eef6ff 0%, var(--bg) 220px);
      color: var(--ink);
    }}
    .page {{ max-width: 1180px; margin: 0 auto; padding: 28px 20px 56px; }}
    .hero {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 24px 28px;
      box-shadow: 0 10px 30px rgba(15,23,42,.05);
      margin-bottom: 18px;
    }}
    .hero h1 {{ margin: 0 0 6px; font-size: 28px; }}
    .hero p {{ margin: 0; color: var(--muted); font-size: 14px; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
    .pill {{
      background: var(--accent-soft);
      color: #155e75;
      border: 1px solid #a5f3fc;
      border-radius: 999px;
      padding: 6px 12px;
      font-size: 12px;
      font-weight: 600;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
      margin-bottom: 18px;
    }}
    .kpi {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px 20px;
      box-shadow: 0 6px 18px rgba(15,23,42,.04);
    }}
    .kpi .label {{ color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
    .kpi .value {{ font-size: 32px; font-weight: 800; line-height: 1; }}
    .kpi .sub {{ margin-top: 8px; font-size: 12px; color: var(--muted); }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 18px 20px;
      margin-bottom: 18px;
      box-shadow: 0 6px 18px rgba(15,23,42,.04);
    }}
    .panel h2 {{ margin: 0 0 14px; font-size: 18px; }}
    .split {{ display: grid; grid-template-columns: 1.2fr .8fr; gap: 18px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 10px 8px; border-bottom: 1px solid #f1f5f9; text-align: left; vertical-align: middle; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 12px; }}
    tr.muted td {{ color: #94a3b8; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }}
    .bar-track {{ height: 8px; background: #f1f5f9; border-radius: 999px; overflow: hidden; min-width: 80px; }}
    .bar-fill {{ height: 100%; border-radius: 999px; }}
    .cat-item {{ margin-bottom: 12px; }}
    .cat-head {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 6px; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 12px; }}
    .toolbar select, .toolbar input, .toolbar-btn {{
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 8px 12px;
      font-size: 13px;
      background: #fff;
    }}
    .toolbar-btn {{ cursor: pointer; font-weight: 600; color: #334155; }}
    .tag {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 700;
    }}
    .tag.warn {{ background: #fef3c7; color: #b45309; }}
    .note {{
      background: #fffbeb;
      border: 1px solid #fde68a;
      color: #92400e;
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 13px;
      line-height: 1.6;
      margin-bottom: 18px;
    }}
    .muted {{ color: var(--muted); font-size: 12px; }}
    .cloud-wrap {{
      position: relative;
      background: linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
      border: 1px dashed #cbd5e1;
      border-radius: 16px;
      min-height: 520px;
      overflow: hidden;
    }}
    #wordCloudCanvas {{ display: block; width: 100%; height: 520px; }}
    .cloud-legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }}
    .cloud-chip {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 12px;
      color: #475569;
    }}
    @media (max-width: 960px) {{
      .grid {{ grid-template-columns: repeat(2, 1fr); }}
      .split {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <section class="hero">
      <h1>Vemory 会议周报</h1>
      <p>按周汇总会议数量与时长 · 视角：{escape(data['viewer'])} 可访问范围</p>
      <div class="meta">
        <span class="pill">周期 {escape(data['window']['label'])}</span>
        <span class="pill">周次 {escape(data.get('week_key') or '')}</span>
        <span class="pill">生成 {escape(data['generated_at'])}</span>
      </div>
    </section>

    <section class="grid">
      <div class="kpi"><div class="label">会议总数</div><div class="value">{t['meetings']}</div><div class="sub">活跃 {t['active_people']} 人 · 有记录 {t['active_days']} 天</div></div>
      <div class="kpi"><div class="label">录音总时长</div><div class="value">{t['hours']}h</div><div class="sub">有效约 {t['effective_hours']}h（剔除 &gt;2h 异常）</div></div>
      <div class="kpi"><div class="label">日均会议</div><div class="value">{t['avg_per_day']}</div><div class="sub">场/有记录工作日</div></div>
      <div class="kpi"><div class="label">提取待办</div><div class="value">{t['todos']}</div><div class="sub">来自 AI 纪要</div></div>
    </section>

    <div class="note">
      说明：时长 &gt; 2 小时的录音标记为「超长」，可能是设备未关导致的误录；「有效时长」= 总时长 − 超长部分。
      异常时长本周合计约 <strong>{t['outlier_hours']}h</strong>。
    </div>

    <section class="split">
      <div class="panel">
        <h2>按人汇总</h2>
        <table>
          <thead><tr><th>姓名</th><th>会议数</th><th>总时长(h)</th><th>有效(h)</th><th>场均(min)</th><th>待办</th><th>占比</th></tr></thead>
          <tbody>{''.join(person_rows) or '<tr><td colspan="7" class="muted">暂无数据</td></tr>'}</tbody>
        </table>
      </div>
      <div class="panel">
        <h2>会议类型</h2>
        {''.join(cat_blocks) or '<div class="muted">暂无</div>'}
      </div>
    </section>

    <section class="panel panel-cloud">
      <h2>会议主题词云</h2>
      <p class="muted" style="margin:-6px 0 14px">由本周会议标题与 AI 摘要提取关键词，字号越大表示出现越频繁</p>
      <div class="toolbar">
        <select id="filterPerson"><option value="">全部人员</option></select>
        <select id="filterCategory">
          <option value="">全部类型</option>
          <option value="dealer_customer">经销商/客户</option>
          <option value="interview">招聘面试</option>
          <option value="internal_report">内部汇报</option>
          <option value="other">其他</option>
        </select>
        <input id="filterKeyword" type="search" placeholder="过滤关键词…" />
        <button type="button" class="toolbar-btn" id="cloudReset">重置</button>
      </div>
      <div class="cloud-wrap">
        <canvas id="wordCloudCanvas" width="1120" height="520"></canvas>
      </div>
      <div class="cloud-legend" id="cloudTopWords"></div>
    </section>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/wordcloud@1.2.2/src/wordcloud2.min.js"></script>
  <script>
    const REPORT = {data_json};
    const DEFAULT_CLOUD = {word_cloud_json};
    const STOP_WORDS = new Set({json.dumps(list(STOP_WORDS), ensure_ascii=False)});
    const COLORS = ['#0891b2','#6366f1','#047857','#7c3aed','#db2777','#ea580c','#0f766e','#4338ca'];

    function tokenizeForCloud(text) {{
      let t = (text || '').replace(/^\\d{{4}}-\\d{{2}}-\\d{{2}}\\s*/, '').replace(/\\d{{4}}-\\d{{2}}-\\d{{2}}/g, ' ').replace(/\\d+/g, ' ');
      const tokens = [];
      (t.match(/[A-Za-z]{{3,}}/g) || []).forEach(w => tokens.push(w.toLowerCase()));
      (t.match(/[\\u4e00-\\u9fff]+/g) || []).forEach(seg => {{
        if (seg.length <= 5) {{ tokens.push(seg); return; }}
        [2, 3, 4].forEach(size => {{
          for (let i = 0; i <= seg.length - size; i++) tokens.push(seg.slice(i, i + size));
        }});
      }});
      return tokens;
    }}

    function buildCloudData(meetings) {{
      const counter = new Map();
      meetings.forEach(m => {{
        let weight = Number(m.duration_minutes || 0) > {OUTLIER_MINUTES} ? 0.35 : 1;
        if (m.category === 'dealer_customer') weight *= 1.15;
        if (m.category === 'interview') weight *= 1.05;
        [m.title || '', (m.summary || '').slice(0, 220)].forEach(text => {{
          tokenizeForCloud(text).forEach(tok => {{
            if (STOP_WORDS.has(tok) || tok.length < 2) return;
            if (/^[a-z]+$/.test(tok) && tok.length < 4) return;
            counter.set(tok, (counter.get(tok) || 0) + weight);
          }});
        }});
      }});
      const ranked = [...counter.entries()].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length);
      const seen = new Set();
      const out = [];
      for (const [word, w] of ranked) {{
        if ([...seen].some(k => k.includes(word) && k !== word)) continue;
        if (seen.has(word)) continue;
        seen.add(word);
        out.push([word, Math.round(w * 10) / 10]);
        if (out.length >= 90) break;
      }}
      return out;
    }}

    function renderWordCloud(list) {{
      const canvas = document.getElementById('wordCloudCanvas');
      const wrap = canvas.parentElement;
      const width = Math.max(320, wrap.clientWidth - 2);
      canvas.width = width;
      canvas.height = 520;
      const max = list.length ? Math.max(...list.map(i => i[1])) : 1;
      WordCloud(canvas, {{
        list,
        gridSize: Math.round(16 * width / 1024),
        weightFactor: size => Math.pow(size / max, 0.62) * (width / 8),
        fontFamily: '"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif',
        color: () => COLORS[Math.floor(Math.random() * COLORS.length)],
        rotateRatio: 0.08,
        rotationSteps: 2,
        backgroundColor: 'transparent',
        shrinkToFit: true,
        drawOutOfBound: false,
      }});
      const top = document.getElementById('cloudTopWords');
      top.innerHTML = list.slice(0, 12).map(([w, c]) => `<span class="cloud-chip">${{w}} · ${{c}}</span>`).join('');
    }}

    function filteredMeetings() {{
      const p = document.getElementById('filterPerson').value;
      const c = document.getElementById('filterCategory').value;
      const q = document.getElementById('filterKeyword').value.trim().toLowerCase();
      return (REPORT.meetings || []).filter(m => {{
        const okP = !p || m.person === p;
        const okC = !c || m.category === c;
        const text = `${{m.title || ''}} ${{m.summary || ''}}`.toLowerCase();
        const okQ = !q || text.includes(q);
        return okP && okC && okQ;
      }});
    }}

    function applyFilters() {{
      const meetings = filteredMeetings();
      renderWordCloud(buildCloudData(meetings));
    }}

    (function initCloud() {{
      const people = [...new Set((REPORT.meetings || []).map(m => m.person).filter(Boolean))].sort();
      const sel = document.getElementById('filterPerson');
      people.forEach(name => {{
        const opt = document.createElement('option');
        opt.value = name; opt.textContent = name; sel.appendChild(opt);
      }});
      ['filterPerson','filterCategory','filterKeyword'].forEach(id => {{
        document.getElementById(id).addEventListener('input', applyFilters);
        document.getElementById(id).addEventListener('change', applyFilters);
      }});
      document.getElementById('cloudReset').addEventListener('click', () => {{
        document.getElementById('filterPerson').value = '';
        document.getElementById('filterCategory').value = '';
        document.getElementById('filterKeyword').value = '';
        renderWordCloud(DEFAULT_CLOUD);
      }});
      renderWordCloud(DEFAULT_CLOUD);
      window.addEventListener('resize', () => applyFilters());
    }})();
  </script>
</body>
</html>"""


def pull_week_data() -> Path:
    if not PULL_SCRIPT.is_file():
        raise FileNotFoundError(f"缺少拉取脚本: {PULL_SCRIPT}")
    subprocess.run([sys.executable, str(PULL_SCRIPT)], check=True)
    monday, _ = week_bounds()
    return default_input_path(monday)


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Vemory 按周汇总 HTML")
    parser.add_argument("--input", type=str, default="", help="周数据 JSON 路径")
    parser.add_argument("--pull", action="store_true", help="生成前先拉取本周 Vemory")
    parser.add_argument("--output", type=str, default="", help="输出 HTML 路径")
    args = parser.parse_args()

    if args.pull:
        input_path = pull_week_data()
    else:
        monday, _ = week_bounds()
        input_path = Path(args.input) if args.input else default_input_path(monday)

    if not input_path.is_file():
        print(f"数据文件不存在: {input_path}", file=sys.stderr)
        print("请先运行: python data_raw/pull_liu_vemory_week.py", file=sys.stderr)
        return 1

    payload = load_payload(input_path)
    data = aggregate(payload)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if args.output:
        out_path = Path(args.output)
    else:
        start = data["window"]["from"] or date.today().isoformat()
        out_path = OUT_DIR / f"vemory_weekly_{start}.html"

    out_path.write_text(render_html(data), encoding="utf-8")
    print(f"已生成: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
