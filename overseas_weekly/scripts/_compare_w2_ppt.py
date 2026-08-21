# -*- coding: utf-8 -*-
"""Compare W2 system numbers vs PPT reported figures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
overview = json.loads((ROOT / "outputs" / "2026-W28_overview.json").read_text(encoding="utf-8"))
sandbox = ROOT / "scripts" / "_sandbox_overview.py"

npm = Path.home() / "AppData" / "Roaming" / "npm"
cjs = npm / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
cmd = ["node", str(cjs), "odoo", "data", "sandbox", "--code", f"@{sandbox}"]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
raw = json.loads(proc.stdout.strip())["result"]["execution"]["result"]

dealer_meta = {d["name"]: d for d in cfg["dealers"]}
sales_map = cfg["salespeople"]


def wan(x: float) -> float:
    return round(x / 10000, 2)


def pct_diff(sys_v: float, ppt_v: float) -> str:
    if ppt_v == 0:
        return "N/A"
    d = (sys_v - ppt_v) / abs(ppt_v) * 100
    return f"{d:+.1f}%"


lines: list[str] = []
lines.append("# 第二周 PPT vs 系统核对")
lines.append("")
lines.append(f"- 系统窗口: {overview['meta']['week_start']} ~ {overview['meta']['week_end']} (as_of {overview['meta']['as_of']})")
lines.append(f"- MTD: {overview['meta']['mtd_start']} ~ {overview['meta']['mtd_end']}")
lines.append(f"- 环比对照: {overview['meta']['prev_month_start']} ~ {overview['meta']['prev_month_end']}")
lines.append(f"- 同比对照: {overview['meta']['yoy_start']} ~ {overview['meta']['yoy_end']}")
lines.append("")

# PPT targets from extract
ppt = {
    "headline": {
        "mtd": 335.4,
        "week": 211.0,
        "okr": 695.0,
        "okr_rate": 48.3,
        "mom": -3.0,
        "yoy": 224.0,
        "week_target": 157.0,
        "week_rate": 134.0,
    },
    "groups": {
        "Lina组": {"mtd": 163.8, "week": 69.1, "okr": 290.0, "okr_rate": 44.2, "mom": -15.0, "yoy": 732.0},
        "于冰组": {"mtd": 64.0, "week": 47.58, "okr": 110.0, "okr_rate": 58.2, "mom": 96.0, "yoy": -10.0},
        "杨晶晶组": {"mtd": 107.2, "week": None, "okr": 235.0, "okr_rate": 46.0, "mom": -12.0, "yoy": 764.0},
    },
    "lina_week_dealers": {
        "Veysel Sevis Ltd": 9.1196,
        "TİVALİ Commercial Broker LLC": 29.4079,
        "Safiranhamrah": 30.5587,
    },
    "lina_week_total": 69.0862,
    "yjj_personal": {
        # PPT table: 杨晶晶 80.5 / 海文 47 / 总计 127.5 — 与总览 107~108 不一致，单独核对
        "杨晶晶_mtd": 80.5,
        "海文_mtd": 47.0,
        "组合计_表内": 127.5,
    },
}

h = overview["headline"]
sys_h = {
    "mtd": wan(h["mtd_amount"]),
    "week": wan(h["week_amount"]),
    "okr": wan(h["okr_target"]),
    "okr_rate": h["okr_rate"],
    "mom": h["mom_pct"],
    "yoy": h["yoy_pct"],
}

lines.append("## 1. 全盘 KPI")
lines.append("")
lines.append("| 指标 | PPT | 系统 | 差额(万/pp) | 相对偏差 | 判定 |")
lines.append("|------|-----|------|-------------|----------|------|")


def row(name, ppt_v, sys_v, unit="万", tol_wan=3.0, tol_pp=3.0):
    if ppt_v is None or sys_v is None:
        lines.append(f"| {name} | {ppt_v} | {sys_v} | — | — | 缺一侧 |")
        return
    if unit == "%":
        diff = round(sys_v - ppt_v, 1)
        ok = abs(diff) <= tol_pp
        flag = "✅ 接近" if ok else "⚠ 偏差"
        lines.append(f"| {name} | {ppt_v}{unit} | {sys_v}{unit} | {diff:+}pp | — | {flag} |")
    else:
        diff = round(sys_v - ppt_v, 2)
        rel = pct_diff(sys_v, ppt_v)
        ok = abs(diff) <= tol_wan
        flag = "✅ 接近" if ok else "⚠ 偏差"
        lines.append(f"| {name} | {ppt_v} | {sys_v} | {diff:+} | {rel} | {flag} |")


row("MTD SI", ppt["headline"]["mtd"], sys_h["mtd"])
row("本周 SI", ppt["headline"]["week"], sys_h["week"])
row("OKR 目标", ppt["headline"]["okr"], sys_h["okr"], tol_wan=0.1)
row("达成率", ppt["headline"]["okr_rate"], sys_h["okr_rate"], unit="%")
row("环比", ppt["headline"]["mom"], sys_h["mom"], unit="%")
row("同比", ppt["headline"]["yoy"], sys_h["yoy"], unit="%", tol_pp=30)

lines.append("")
lines.append("## 2. 三组")
lines.append("")
lines.append("| 组 | 指标 | PPT | 系统 | 差额 | 判定 |")
lines.append("|----|------|-----|------|------|------|")

gmap = {g["name"]: g for g in overview["groups"]}
for gname, p in ppt["groups"].items():
    g = gmap[gname]
    pairs = [
        ("MTD", p["mtd"], wan(g["mtd_amount"])),
        ("本周", p["week"], wan(g["week_amount"]) if p["week"] is not None else None),
        ("达成率%", p["okr_rate"], g["okr_rate"]),
        ("环比%", p["mom"], g["mom_pct"]),
        ("同比%", p["yoy"], g["yoy_pct"]),
    ]
    for label, pv, sv in pairs:
        if pv is None or sv is None:
            lines.append(f"| {gname} | {label} | {pv} | {sv} | — | 缺 |")
            continue
        if label.endswith("%"):
            diff = round(sv - pv, 1)
            ok = abs(diff) <= (30 if "同比" in label else 5)
            flag = "✅" if ok else "⚠"
            lines.append(f"| {gname} | {label} | {pv} | {sv} | {diff:+}pp | {flag} |")
        else:
            diff = round(sv - pv, 2)
            ok = abs(diff) <= 3
            flag = "✅" if ok else "⚠"
            lines.append(f"| {gname} | {label} | {pv} | {sv} | {diff:+} | {flag} |")

# Week dealers
lines.append("")
lines.append("## 3. Lina 组本周代理商（PPT 表）")
lines.append("")
lines.append("| 经销商 | PPT(万) | 系统(万) | 差额 | 判定 |")
lines.append("|--------|---------|----------|------|------|")

week_by = {r["dealer"]: r["amount"] for r in raw["week"]}
# alias map for Tivali encoding
aliases = {
    "TİVALİ Commercial Broker LLC": ["TİVALİ Commercial Broker LLC", "Tivali commercial broker LLC"],
}

ppt_sum = 0.0
sys_sum = 0.0
for name, ppt_wan in ppt["lina_week_dealers"].items():
    # find in week
    amt = week_by.get(name)
    if amt is None:
        for k, v in week_by.items():
            if name.split()[0].upper() in k.upper() or (name[:6] in k):
                amt = v
                name_sys = k
                break
        else:
            name_sys = name
            amt = 0
    else:
        name_sys = name
    sv = wan(float(amt or 0))
    ppt_sum += ppt_wan
    sys_sum += sv
    diff = round(sv - ppt_wan, 2)
    flag = "✅" if abs(diff) <= 1 else "⚠"
    lines.append(f"| {name_sys} | {ppt_wan} | {sv} | {diff:+} | {flag} |")

lines.append(f"| **合计(三家)** | {round(ppt_sum,2)} | {round(sys_sum,2)} | {round(sys_sum-ppt_sum,2):+} | — |")
lines.append(f"| PPT 表总计 | {ppt['lina_week_total']} | 系统 Lina 周 | {wan(gmap['Lina组']['week_amount'])} | — | — |")

# All week dealers
lines.append("")
lines.append("## 4. 系统本周全部匹配代理商")
lines.append("")
total_w = 0.0
for r in sorted(raw["week"], key=lambda x: -x["amount"]):
    m = dealer_meta.get(r["dealer"], {})
    sales = m.get("sales", "?")
    group = sales_map.get(sales, {}).get("report_group", "?")
    w = wan(r["amount"])
    total_w += r["amount"]
    lines.append(f"- {w}万 | {r['dealer']} | {m.get('country','')} | {sales} | {group}")
lines.append(f"- **合计** {wan(total_w)}万")

# MTD dealers
lines.append("")
lines.append("## 5. 系统 MTD 代理商")
lines.append("")
for r in sorted(raw["mtd"], key=lambda x: -x["amount"])[:20]:
    m = dealer_meta.get(r["dealer"], {})
    sales = m.get("sales", "?")
    group = sales_map.get(sales, {}).get("report_group", "?")
    lines.append(f"- {wan(r['amount'])}万 | {r['dealer']} | {sales} | {group}")

# Yangjingjing personal from sales mapping
lines.append("")
lines.append("## 6. 杨晶晶组个人拆分（对照 PPT 80.5/47/127.5）")
lines.append("")
by_sales_mtd = {}
for r in raw["mtd"]:
    m = dealer_meta.get(r["dealer"])
    if not m:
        continue
    if sales_map[m["sales"]]["report_group"] != "杨晶晶组":
        continue
    by_sales_mtd[m["sales"]] = by_sales_mtd.get(m["sales"], 0) + r["amount"]
for s, a in sorted(by_sales_mtd.items(), key=lambda x: -x[1]):
    lines.append(f"- {s}: {wan(a)}万")
lines.append(f"- 组合计: {wan(sum(by_sales_mtd.values()))}万")
lines.append(f"- PPT 表: 杨晶晶 80.5 / 海文 47 / 总计 127.5（与总览页 107~108 本身不一致）")

# Products week for Lina focus
lines.append("")
lines.append("## 7. 口径备注")
lines.append("")
lines.append("- PPT 于冰页写「6月目标¥110万」应为笔误，系统按 7 月 110 万。")
lines.append("- PPT 杨晶晶总览约 107~108 万，组内表写 127.5 万：疑似含家具/未入 SI 口径。")
lines.append("- 判定阈值：金额 ±3 万视为接近；达成率/环比 ±5pp；同比 ±30pp（基期小易放大）。")

out = ROOT / "outputs" / "2026-W28_ppt_vs_system.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
print("\n".join(lines))
