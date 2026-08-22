# -*- coding: utf-8 -*-
"""将第三周周报导出为独立 HTML（可浏览器打开 / 打印 PDF）。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OV = ROOT / "outputs" / "2026-W29_overview.json"
OUT = ROOT / "outputs" / "2026-W29_第三周周报.html"
DESKTOP = Path.home() / "Desktop" / "海外经销商2026年7月第三周周报.html"


def wan(x: float) -> float:
    return round(float(x) / 10000, 2)


def pct(v: float | None) -> str:
    if v is None:
        return "—"
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}%"


def main() -> None:
    d = json.loads(OV.read_text(encoding="utf-8"))
    h = d["headline_ppt"]
    groups = d["groups_ppt"]
    regions = d["regions_mtd"]
    dealers = d["top_dealers_mtd"][:10]
    people = [p for p in d["people"] if p["week_amount"] or p["mtd_amount"]]
    majors = [m for m in d["products"]["mtd_majors"] if m["amount"] > 0][:8]
    series_mtd = d["products"]["mtd_series"][:10]
    series_week = [s for s in d["products"]["week_series"] if s["amount"] > 0][:8]
    meta = d["meta"]
    day = int(meta["as_of"].split("-")[2])
    time_pct = day / 31 * 100

    group_rows = "".join(
        f"<tr><td>{g['name']}</td><td class='n'>{wan(g['week_amount'])}</td>"
        f"<td class='n'>{wan(g['mtd_amount'])}</td><td class='n'>{g['okr_rate']}%</td>"
        f"<td class='n'>{pct(g['mom_pct'])}</td><td class='n'>{pct(g['yoy_pct'])}</td>"
        f"<td class='n'>{wan(g['okr_target'])}</td></tr>"
        for g in groups
    )
    region_rows = "".join(
        f"<tr><td>{r['region']}</td><td class='n'>{wan(r['amount'])}</td></tr>" for r in regions
    )
    dealer_rows = "".join(
        f"<tr><td>{x['name'][:36]}</td><td>{x['group']}</td><td>{x['region']}</td>"
        f"<td class='n'>{wan(x['amount'])}</td></tr>"
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

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>海外经销商 2026年7月第三周周报</title>
<style>
  :root {{
    --bg: #f7f6f3;
    --card: #fff;
    --ink: #1a1a1a;
    --muted: #5c5c5c;
    --line: #e5e2db;
    --accent: #0f4c5c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px 64px;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--ink); line-height: 1.5;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; }}
  h1 {{ font-size: 28px; margin: 0 0 6px; letter-spacing: -0.02em; }}
  h2 {{ font-size: 18px; margin: 28px 0 12px; color: var(--accent); }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 4px; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border: 1px solid var(--line);
    border-radius: 4px; font-size: 12px; color: var(--muted); margin-right: 6px;
  }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 18px 0; }}
  .stat {{
    background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    padding: 14px 16px;
  }}
  .stat .v {{ font-size: 26px; font-weight: 650; letter-spacing: -0.02em; }}
  .stat .l {{ font-size: 12px; color: var(--muted); margin-top: 4px; }}
  .card {{
    background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    padding: 16px 18px; margin: 14px 0;
  }}
  .bar {{
    height: 10px; background: #eceae4; border-radius: 999px; overflow: hidden; margin-top: 10px;
  }}
  .bar > i {{
    display: block; height: 100%; background: var(--accent); width: {min(h['okr_rate'], 100)}%;
  }}
  table {{
    width: 100%; border-collapse: collapse; background: var(--card);
    border: 1px solid var(--line); font-size: 13px;
  }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; }}
  th {{ background: #f0eee8; font-weight: 600; font-size: 12px; color: var(--muted); }}
  tr:last-child td {{ border-bottom: 0; }}
  td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .note {{
    font-size: 13px; color: var(--muted); border-left: 3px solid var(--accent);
    padding: 8px 12px; margin: 12px 0; background: #fff;
  }}
  .warn {{
    font-size: 13px; border-left: 3px solid #b45309; padding: 8px 12px;
    margin: 12px 0; background: #fff8f0; color: #5c4a2a;
  }}
  footer {{ margin-top: 28px; font-size: 12px; color: var(--muted); }}
  @media print {{
    body {{ background: #fff; padding: 12px; }}
    .stat, .card, table {{ break-inside: avoid; }}
  }}
  @media (max-width: 720px) {{
    .grid {{ grid-template-columns: 1fr 1fr; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <h1>海外经销商 · 第三周周报</h1>
  <div class="sub">
    <span class="badge">2026-W29</span>
    <span class="badge">ppt 口径</span>
    本周 {meta['week_start']} ~ {meta['week_end']}（取数至 {meta['as_of']}）
  </div>
  <div class="sub">月累计 {meta['mtd_start']} ~ {meta['mtd_end']} · Source: odoo_sale / dealers.json</div>

  <div class="note">
    ppt = 经销商归组 − 非团队记名（MTD 已剔 郑丽苹+陈晓霜 共 {wan(h.get('cross_person_mtd') or 0)} 万）。
    环比=上月同期；同比=去年同期。金额单位：万元。
  </div>

  <div class="grid">
    <div class="stat"><div class="v">{wan(h['mtd_amount'])}</div><div class="l">月累计 SI（万）</div></div>
    <div class="stat"><div class="v">{wan(h['week_amount'])}</div><div class="l">本周 SI（万）</div></div>
    <div class="stat"><div class="v">{pct(h['mom_pct'])}</div><div class="l">环比</div></div>
    <div class="stat"><div class="v">{pct(h['yoy_pct'])}</div><div class="l">同比</div></div>
  </div>

  <div class="card">
    <strong>全盘 OKR 达成 {h['okr_rate']}%</strong>
    <div class="sub">已完成 {wan(h['mtd_amount'])} 万 / 目标 {wan(h['okr_target'])} 万 · 时间进度约 {time_pct:.0f}%</div>
    <div class="bar"><i></i></div>
  </div>

  <div class="warn">
    本周结构：Billionaire 约 102.1 万占本周大头；于冰组本周 SI=0；Lina 组月达成约 98%。
    「预售虚拟类 / 权益服务」请确认是否计入 OKR。
  </div>

  <h2>三组业绩（ppt）</h2>
  <table>
    <thead><tr>
      <th>组别</th><th class="n">本周</th><th class="n">月累计</th><th class="n">达成率</th>
      <th class="n">环比</th><th class="n">同比</th><th class="n">月目标</th>
    </tr></thead>
    <tbody>{group_rows}</tbody>
  </table>

  <h2>区域贡献（月累计）</h2>
  <table>
    <thead><tr><th>区域</th><th class="n">销售额（万）</th></tr></thead>
    <tbody>{region_rows}</tbody>
  </table>

  <h2>核心代理商 Top 10（月累计）</h2>
  <table>
    <thead><tr><th>代理商</th><th>组别</th><th>区域</th><th class="n">销售额（万）</th></tr></thead>
    <tbody>{dealer_rows}</tbody>
  </table>

  <h2>个人贡献（salesperson_aligned）</h2>
  <table>
    <thead><tr><th>销售</th><th>组别</th><th class="n">本周</th><th class="n">月累计</th></tr></thead>
    <tbody>{people_rows}</tbody>
  </table>

  <h2>商品大类（月累计）</h2>
  <table>
    <thead><tr><th>大类</th><th class="n">销售额（万）</th></tr></thead>
    <tbody>{major_rows}</tbody>
  </table>

  <h2>商品细类 Top（月累计）</h2>
  <table>
    <thead><tr><th>细类</th><th>大类</th><th class="n">销售额（万）</th><th class="n">订单数</th></tr></thead>
    <tbody>{series_mtd_rows}</tbody>
  </table>

  <h2>商品细类 Top（本周）</h2>
  <table>
    <thead><tr><th>细类</th><th>大类</th><th class="n">销售额（万）</th></tr></thead>
    <tbody>{series_week_rows}</tbody>
  </table>

  <h2>业务组交付（四份 PPT + 于冰 PDF）</h2>

  <div class="card">
    <strong>Lina 组 · 中东与欧北美（业务自报）</strong>
    <div class="sub">本周 172.1 万 · MTD 336.7 万 / 目标 335.7 万 → 116% · W4 待收线索约 143 万</div>
    <div class="sub">中东 81% / 欧洲 19% · AQ*59、QUANTUM*32、AF*17</div>
    <p style="font-size:13px;margin:8px 0 0">
      录单：Billionaire 102.1 · 伦敦 29.1 · Taher Jasem 17.7 · Tivali 8.0 · Safiran 8.0 · Luxem 3.9 · Veysel 3.4。
      环比约 -22%；高定黄金4/喜马拉雅 AF；跟进瑞士尺寸、沙特首单、荷兰 AQ 试单。
    </p>
  </div>

  <div class="card">
    <strong>何海文 · 印度</strong>
    <div class="sub">目标 75W · 第三周收款 27.8W · 累计 75.4W → <b>101%</b></div>
    <p style="font-size:13px;margin:8px 0 0">
      W3：潮汕/喀拉拉名单；商会 10 人；获客 28 条；售后 3；内洛尔接待 PPT。
      Thakral 待反馈；Zimson NDA+9 月访问；PLF/Black Apple 推进。
      W4：名单与系统、内洛尔接待、印度出差专题汇报。
    </p>
  </div>

  <div class="card">
    <strong>刘雪梅 · 商务中台（7.13–7.17 / 计划 7.20–7.24）</strong>
    <p style="font-size:13px;margin:8px 0 0">
      完成：GURU 发货审核；Sidd 尾款发货；越南录单发货；印度清关；越/印售后；VST 合同与印度 NDA 预审。<br/>
      计划：印录单 8 单约 14.1 万美金、发货物流 9 单；Sidd 预付 1 万待清库；越/印免费换新；
      越南预付款 17 日已付；VST/伊拉克协议；广交会与 VPS 异常。
    </p>
  </div>

  <div class="card">
    <strong>Vivi · 商务助理 + 拓客</strong>
    <p style="font-size:13px;margin:8px 0 0">
      P1 拓客（6W）：土库曼来蓉、乌克兰 boutique、metrogroup、圣彼得堡酒店；日均触达 10+。<br/>
      P2 Sell-out 视频/报关；协助春梅带教。P3 Konstantin/restore/Perspectiva 跟单与售后。<br/>
      W4：跟单推单、高管清单、PR 博主、带教；卡点为熟悉期提效与俄语区响应。
    </p>
  </div>

  <div class="card">
    <strong>于冰组 · 东南亚（PDF 7.13–7.17）</strong>
    <div class="sub">目标 110W · 已完成 ¥640,347 → <b>58.2%</b>（与系统一致）· 在途约 ¥489,787 · 本周 SI=0</div>
    <p style="font-size:13px;margin:8px 0 0">
      越南 PO：26 台 / ~$12 万 · AF*20（约 81% 金额）+ AQ*6（3% rebate）；鳄鱼皮撑利润、小牛皮走量。<br/>
      Sell-out 7/1–7/16（越4+泰1）：进店97 / 触摸14 / 成交3 / ~$8,292（几乎全靠 Saigon）；Siam 金额漏报。<br/>
      马来：云顶+Pavilion/KLCC 双店；SWAP/云顶/SWITCH/KLCC 多场会议，主体未定。印尼 TI 下周；澳洲拒免费样机。<br/>
      W4：马来商务定案、印尼框架、越南发货到账、泰国 PO、澳洲意向。
    </p>
  </div>

  <footer>
    系统 SI as_of 2026-07-17（Vertu 会话过期未能刷 07-18）。仍缺杨晶晶本人整页、全盘待收台账。<br/>
    打印 PDF：浏览器打开本页 → Ctrl+P → 另存为 PDF。
  </footer>
</div>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    DESKTOP.write_text(html, encoding="utf-8")
    print(OUT)
    print(DESKTOP)


if __name__ == "__main__":
    main()
