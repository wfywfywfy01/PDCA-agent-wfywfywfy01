# -*- coding: utf-8 -*-
"""导出最新一周（W30 · as_of 当日）海外经销商周报 HTML · Neo-Swiss 风格。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OV = ROOT / "outputs" / "2026-W30_overview.json"
OUT = ROOT / "html-design-w29" / "海外经销商_2026-W30_周报.html"
DESKTOP = Path.home() / "Desktop" / "海外经销商_2026-W30_周报.html"


def wan(x: float | int | None) -> float:
    return round(float(x or 0) / 10000, 2)


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def main() -> None:
    d = json.loads(OV.read_text(encoding="utf-8"))
    h = d["headline_ppt"]
    groups = d.get("groups_ppt") or d["groups"]
    regions = d["regions_mtd"]
    dealers = d["top_dealers_mtd"][:10]
    people = [p for p in d["people"] if p["week_amount"] or p["mtd_amount"]]
    majors = [m for m in d["products"]["mtd_majors"] if m["amount"] > 0][:8]
    series_mtd = d["products"]["mtd_series"][:10]
    series_week = [s for s in d["products"]["week_series"] if s["amount"] > 0][:8]
    meta = d["meta"]
    day = int(meta["as_of"].split("-")[2])
    time_pct = day / 31 * 100
    rate = float(h["okr_rate"])
    mtd_w = wan(h["mtd_amount"])
    week_w = wan(h["week_amount"])
    target_w = wan(h["okr_target"])

    group_cards = "".join(
        f"""
        <div class="dept{' hot' if g['okr_rate'] >= 100 else ''}">
          <div class="dept-name">{g['name']}</div>
          <div class="dept-rate">{g['okr_rate']}%</div>
          <div class="dept-meta">本周 {wan(g['week_amount'])} 万 · MTD {wan(g['mtd_amount'])} 万<br/>
          环比 {pct(g.get('mom_pct'))} · 同比 {pct(g.get('yoy_pct'))}<br/>
          目标 {wan(g['okr_target'])} 万</div>
        </div>"""
        for g in groups
    )

    group_rows = "".join(
        f"<tr><td>{g['name']}</td><td class='n'>{wan(g['week_amount'])}</td>"
        f"<td class='n'>{wan(g['mtd_amount'])}</td><td class='n'>{g['okr_rate']}%</td>"
        f"<td class='n'>{pct(g.get('mom_pct'))}</td><td class='n'>{pct(g.get('yoy_pct'))}</td>"
        f"<td class='n'>{wan(g['okr_target'])}</td></tr>"
        for g in groups
    )
    region_rows = "".join(
        f"<tr><td>{r['region']}</td><td class='n'>{wan(r['amount'])}</td></tr>" for r in regions
    )
    dealer_rows = "".join(
        f"<tr><td>{x['name'][:40]}</td><td>{x.get('group') or '—'}</td>"
        f"<td>{x.get('region') or '—'}</td><td class='n'>{wan(x['amount'])}</td></tr>"
        for x in dealers
    )
    people_rows = "".join(
        f"<tr><td>{p['name']}</td><td>{p['group']}</td>"
        f"<td class='n'>{wan(p['week_amount'])}</td>"
        f"<td class='n'>{wan(p['mtd_amount'])}</td></tr>"
        for p in people
    )
    major_rows = "".join(
        f"<tr><td>{m['major']}</td><td class='n'>{wan(m['amount'])}</td></tr>" for m in majors
    )
    series_mtd_rows = "".join(
        f"<tr><td>{s['series']}</td><td>{s['major']}</td>"
        f"<td class='n'>{wan(s['amount'])}</td><td class='n'>{s.get('orders') or '—'}</td></tr>"
        for s in series_mtd
    )
    series_week_rows = "".join(
        f"<tr><td>{s['series']}</td><td>{s['major']}</td>"
        f"<td class='n'>{wan(s['amount'])}</td></tr>"
        for s in series_week
    )

    bar_w = min(rate, 100)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>海外经销商 2026-W30 周报</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500&family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet"/>
<style>
  :root {{
    --ink: #0a0a0a;
    --muted: #6b6b6b;
    --line: #e5e5e5;
    --accent: #2d5bff;
    --paper: #ffffff;
    --bg: #f4f4f5;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.5;
  }}
  .hero {{
    background: var(--paper);
    border-bottom: 1px solid var(--line);
    position: relative;
    overflow: hidden;
  }}
  .hero .grid-bg {{
    position: absolute; inset: 0;
    background-image:
      linear-gradient(var(--line) 1px, transparent 1px),
      linear-gradient(90deg, var(--line) 1px, transparent 1px);
    background-size: 80px 80px; opacity: .5; pointer-events: none;
  }}
  .hero-inner {{
    position: relative; z-index: 1;
    max-width: 1080px; margin: 0 auto;
    padding: 56px 28px 48px;
    display: grid; grid-template-columns: 1.2fr .8fr; gap: 32px; align-items: end;
  }}
  .brand {{
    font-weight: 800; font-size: 13px; letter-spacing: .28em;
  }}
  .eyebrow {{
    font-family: "IBM Plex Mono", monospace;
    font-size: 12px; letter-spacing: .12em; color: var(--muted);
    text-transform: uppercase; margin-top: 8px;
  }}
  h1 {{
    font-size: clamp(36px, 5vw, 56px); font-weight: 800;
    letter-spacing: -.04em; line-height: 1.08; margin-top: 20px;
  }}
  .bar-accent {{ width: 56px; height: 8px; background: var(--accent); margin: 22px 0 16px; }}
  .lede {{ font-size: 16px; color: var(--muted); max-width: 36ch; }}
  .hero-num {{ text-align: right; }}
  .hero-num .n {{
    font-size: clamp(72px, 12vw, 120px); font-weight: 800;
    letter-spacing: -.06em; line-height: .9;
    font-variant-numeric: tabular-nums;
  }}
  .hero-num .u {{
    margin-top: 10px; font-family: "IBM Plex Mono", monospace;
    font-size: 13px; color: var(--accent);
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 28px 28px 72px; }}
  h2 {{
    font-size: 22px; font-weight: 800; letter-spacing: -.02em;
    margin: 36px 0 14px; padding-top: 8px;
    border-top: 1px solid var(--line);
  }}
  h2 .tag {{
    font-family: "IBM Plex Mono", monospace; font-size: 12px;
    color: var(--muted); font-weight: 500; margin-right: 10px;
  }}
  .kpis {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    border: 1px solid var(--line); background: var(--paper); margin-top: 8px;
  }}
  .kpi {{ padding: 20px 18px; border-right: 1px solid var(--line); }}
  .kpi:last-child {{ border-right: 0; }}
  .kpi .l {{
    font-family: "IBM Plex Mono", monospace; font-size: 11px;
    letter-spacing: .08em; text-transform: uppercase; color: var(--muted);
  }}
  .kpi .v {{
    font-size: 32px; font-weight: 800; letter-spacing: -.03em;
    margin-top: 8px; font-variant-numeric: tabular-nums;
  }}
  .kpi .v.accent {{ color: var(--accent); }}
  .progress {{
    background: var(--paper); border: 1px solid var(--line);
    padding: 18px 20px; margin-top: 16px;
  }}
  .progress .top {{ display: flex; justify-content: space-between; font-size: 14px; }}
  .track {{ height: 10px; background: #ececec; margin-top: 12px; }}
  .track > i {{ display: block; height: 100%; width: {bar_w}%; background: var(--accent); }}
  .depts {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 14px;
  }}
  .dept {{
    background: var(--paper); border: 1px solid var(--line); padding: 20px 18px; min-height: 180px;
  }}
  .dept.hot {{ border: 2px solid var(--accent); }}
  .dept-name {{ font-size: 15px; font-weight: 700; }}
  .dept-rate {{
    font-size: 44px; font-weight: 800; letter-spacing: -.04em;
    margin-top: 8px; font-variant-numeric: tabular-nums;
  }}
  .dept.hot .dept-rate {{ color: var(--accent); }}
  .dept-meta {{ margin-top: 12px; font-size: 13px; color: var(--muted); line-height: 1.55; }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--paper);
    border: 1px solid var(--line); font-size: 13px; margin-top: 8px;
  }}
  th, td {{ padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; }}
  th {{
    font-family: "IBM Plex Mono", monospace; font-size: 11px;
    letter-spacing: .06em; text-transform: uppercase; color: var(--muted); font-weight: 500;
    background: #fafafa;
  }}
  tr:last-child td {{ border-bottom: 0; }}
  td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .note {{
    margin-top: 14px; padding: 12px 14px; border-left: 3px solid var(--accent);
    background: var(--paper); font-size: 13px; color: var(--muted);
  }}
  footer {{
    margin-top: 40px; padding-top: 16px; border-top: 1px solid var(--line);
    font-size: 12px; color: var(--muted);
    font-family: "IBM Plex Mono", monospace;
  }}
  @media (max-width: 860px) {{
    .hero-inner, .kpis, .depts {{ grid-template-columns: 1fr 1fr; }}
    .hero-num {{ text-align: left; }}
  }}
  @media (max-width: 560px) {{
    .kpis, .depts {{ grid-template-columns: 1fr; }}
  }}
  @media print {{
    body {{ background: #fff; }}
    .dept, table, .progress, .kpis {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
  <header class="hero">
    <div class="grid-bg"></div>
    <div class="hero-inner">
      <div>
        <div class="brand">VERTU · OVERSEAS</div>
        <div class="eyebrow">{meta['week_label']} · as of {meta['as_of']}</div>
        <h1>海外经销商<br/>七月第四周周报</h1>
        <div class="bar-accent"></div>
        <p class="lede">本周 {meta['week_start']} ~ {meta['week_end']}（取数至 {meta['as_of']}）· MTD {meta['mtd_start']} ~ {meta['mtd_end']}</p>
      </div>
      <div class="hero-num">
        <div class="n">{rate}<span style="font-size:.42em">%</span></div>
        <div class="u">MTD 达成 · {mtd_w} / {target_w} 万</div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <div class="kpis">
      <div class="kpi"><div class="l">月目标</div><div class="v">{target_w}</div></div>
      <div class="kpi"><div class="l">MTD SI</div><div class="v">{mtd_w}</div></div>
      <div class="kpi"><div class="l">达成率</div><div class="v accent">{rate}%</div></div>
      <div class="kpi"><div class="l">本周 SI</div><div class="v">{week_w}</div></div>
    </div>

    <div class="progress">
      <div class="top">
        <strong>全盘 OKR</strong>
        <span>时间进度约 {time_pct:.0f}% · 环比 {pct(h.get('mom_pct'))} · 同比 {pct(h.get('yoy_pct'))}</span>
      </div>
      <div class="track"><i></i></div>
    </div>

    <div class="note">
      口径：ppt（经销商归组 − 非团队记名）。MTD 已剔跨人记名约 {wan(h.get('cross_person_mtd') or 0)} 万。
      金额单位：万元。Source: odoo_sale。
    </div>

    <h2><span class="tag">01</span>三组业绩</h2>
    <div class="depts">{group_cards}</div>
    <table>
      <thead><tr>
        <th>组别</th><th class="n">本周</th><th class="n">月累计</th><th class="n">达成率</th>
        <th class="n">环比</th><th class="n">同比</th><th class="n">月目标</th>
      </tr></thead>
      <tbody>{group_rows}</tbody>
    </table>

    <h2><span class="tag">02</span>区域贡献（月累计）</h2>
    <table>
      <thead><tr><th>区域</th><th class="n">销售额（万）</th></tr></thead>
      <tbody>{region_rows}</tbody>
    </table>

    <h2><span class="tag">03</span>核心代理商 Top 10（月累计）</h2>
    <table>
      <thead><tr><th>代理商</th><th>组别</th><th>区域</th><th class="n">销售额（万）</th></tr></thead>
      <tbody>{dealer_rows}</tbody>
    </table>

    <h2><span class="tag">04</span>个人贡献</h2>
    <table>
      <thead><tr><th>销售</th><th>组别</th><th class="n">本周</th><th class="n">月累计</th></tr></thead>
      <tbody>{people_rows}</tbody>
    </table>

    <h2><span class="tag">05</span>商品大类（月累计）</h2>
    <table>
      <thead><tr><th>大类</th><th class="n">销售额（万）</th></tr></thead>
      <tbody>{major_rows}</tbody>
    </table>

    <h2><span class="tag">06</span>商品细类 Top（月累计）</h2>
    <table>
      <thead><tr><th>细类</th><th>大类</th><th class="n">销售额（万）</th><th class="n">订单数</th></tr></thead>
      <tbody>{series_mtd_rows}</tbody>
    </table>

    <h2><span class="tag">07</span>商品细类 Top（本周）</h2>
    <table>
      <thead><tr><th>细类</th><th>大类</th><th class="n">销售额（万）</th></tr></thead>
      <tbody>{series_week_rows}</tbody>
    </table>

    <footer>
      VERTU OVERSEAS · {meta['week_label']} · generated 2026-07-22 · Neo-Swiss<br/>
      打印：浏览器 Ctrl+P → 另存为 PDF
    </footer>
  </main>
</body>
</html>
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    DESKTOP.write_text(html, encoding="utf-8")
    print(OUT)
    print(DESKTOP)
    print(f"MTD {mtd_w} / {target_w} = {rate}% · week {week_w}")


if __name__ == "__main__":
    main()
