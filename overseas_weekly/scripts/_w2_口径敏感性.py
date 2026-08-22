# -*- coding: utf-8 -*-
"""W2: see if excluding 权益服务/预售虚拟类 explains PPT gaps."""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
sandbox = ROOT / "scripts" / "_sandbox_overview.py"
npm = Path.home() / "AppData" / "Roaming" / "npm"
cjs = npm / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
cmd = ["node", str(cjs), "odoo", "data", "sandbox", "--code", f"@{sandbox}"]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
raw = json.loads(proc.stdout.strip())["result"]["execution"]["result"]

dealer_meta = {d["name"]: d for d in cfg["dealers"]}
sales_map = cfg["salespeople"]
EXCLUDE = {"权益服务", "预售虚拟类"}


def wan(x: float) -> float:
    return round(x / 10000, 2)


def agg(period: str, exclude: bool):
    """Aggregate dealer amounts; optionally subtract excluded series via products_dealer_*."""
    by_group = defaultdict(float)
    by_dealer = {}
    for r in raw[period]:
        m = dealer_meta.get(r["dealer"])
        if not m:
            continue
        g = sales_map[m["sales"]]["report_group"]
        by_group[g] += r["amount"]
        by_dealer[r["dealer"]] = r["amount"]

    if exclude:
        key = f"products_dealer_{period}"
        for r in raw.get(key, []):
            if r.get("series") not in EXCLUDE and "权益" not in (r.get("series") or "") and "预售" not in (
                r.get("series") or ""
            ):
                continue
            # only subtract excluded
            series = r.get("series") or ""
            if series not in EXCLUDE and "权益服务" not in series and "预售虚拟" not in series:
                continue
            m = dealer_meta.get(r["dealer"])
            if not m:
                continue
            g = sales_map[m["sales"]]["report_group"]
            by_group[g] -= r["amount"]
            by_dealer[r["dealer"]] = by_dealer.get(r["dealer"], 0) - r["amount"]

    return by_group, by_dealer


lines = ["# W2 口径敏感性：全量 vs 剔除权益服务/预售虚拟类", ""]
for label, excl in [("全量(当前系统)", False), ("剔除权益服务+预售虚拟类", True)]:
    g_mtd, _ = agg("mtd", excl)
    g_week, d_week = agg("week", excl)
    total_mtd = sum(g_mtd.values())
    total_week = sum(g_week.values())
    lines.append(f"## {label}")
    lines.append(f"- MTD合计: {wan(total_mtd)}万 | 本周合计: {wan(total_week)}万")
    for g in ["Lina组", "于冰组", "杨晶晶组"]:
        lines.append(f"- {g}: MTD {wan(g_mtd.get(g,0))}万 / 周 {wan(g_week.get(g,0))}万")
    lines.append("")
    if excl:
        lines.append("本周代理商(剔除后):")
        for name, amt in sorted(d_week.items(), key=lambda x: -x[1]):
            if abs(amt) < 1:
                continue
            lines.append(f"- {wan(amt)}万 | {name}")
        lines.append("")

# series contribution mtd/week
lines.append("## 权益服务 / 预售虚拟类 贡献拆解")
for period in ["mtd", "week"]:
    lines.append(f"### {period}")
    for r in raw[f"products_{period}"]:
        s = r.get("series") or ""
        if "权益" in s or "预售" in s:
            lines.append(f"- {s}: {wan(r['amount'])}万 | lines={r['lines']}")

# Lina focus customers MoM week from PPT
lines.append("")
lines.append("## Lina 重点客户：本周 vs 上月同周（系统）")
focus = [
    "Veysel Sevis Ltd",
    "TİVALİ Commercial Broker LLC",
    "Safiranhamrah",
    "Luxem Store",
    "Billionaire Collections",
    "ECN GmbH",
]
# Need prev month same week window — sandbox has prev_month as MTD same days, not same ISO week.
# Compute from products? We only have dealer totals for prev_month MTD window.
# For week-over-week same calendar: would need another query.
# Approximate: show current week dealers for focus list
week_by = {r["dealer"]: r["amount"] for r in raw["week"]}
mtd_by = {r["dealer"]: r["amount"] for r in raw["mtd"]}
ppt_week = {
    "Veysel Sevis Ltd": 91196,
    "TİVALİ Commercial Broker LLC": 294079,
    "Safiranhamrah": 305587,
    "Luxem Store": 0,
    "Billionaire Collections": 0,
    "ECN GmbH": 0,
}
ppt_prev_week = {
    "Veysel Sevis Ltd": 0,
    "TİVALİ Commercial Broker LLC": 0,
    "Safiranhamrah": 190499,
    "Luxem Store": 170158,
    "Billionaire Collections": 1157714,
    "ECN GmbH": 175758,
}
lines.append("| 客户 | PPT本周 | 系统本周 | PPT上月同周 |")
lines.append("|------|---------|----------|-------------|")
for name in focus:
    # fuzzy match system
    sys_amt = 0
    for k, v in week_by.items():
        if name[:6].lower() in k.lower() or k[:6].lower() in name.lower():
            sys_amt = v
            break
        if "TIVAL" in name.upper().replace("İ", "I") and "TIVAL" in k.upper().replace("İ", "I"):
            sys_amt = v
            break
        if "Billionaire" in name and "Billionaire" in k:
            sys_amt = v
            break
        if "Luxem" in name and "Luxem" in k:
            sys_amt = v
            break
        if "ECN" in name and "ECN" in k:
            sys_amt = v
            break
        if "Safiran" in name and "Safiran" in k:
            sys_amt = v
            break
        if "Veysel" in name and "Veysel" in k:
            sys_amt = v
            break
    lines.append(
        f"| {name} | {wan(ppt_week.get(name,0)*1.0) if ppt_week.get(name,0)>100 else wan(ppt_week.get(name,0))} | {wan(sys_amt)} | {wan(ppt_prev_week.get(name,0))} |"
    )

# fix ppt_week already in yuan for some
# Actually I mixed — ppt_week values are in yuan. wan() ok.
# For zeros wan(0)=0. For Veysel 91196 -> 9.12. Good.
# Wait I wrote a broken ternary. Let me fix output manually in rewrite.

out = ROOT / "outputs" / "2026-W28_口径敏感性.md"
# rewrite Lina table cleanly
lines2 = [x for x in lines if not x.startswith("| 客户") and not x.startswith("|------") and not x.startswith("| Veysel") and not x.startswith("| Tİ") and not x.startswith("| Safiran") and not x.startswith("| Luxem") and not x.startswith("| Billionaire") and not x.startswith("| ECN") and x != "## Lina 重点客户：本周 vs 上月同周（系统）"]
lines2.append("## Lina 重点客户：本周 SI 核对")
lines2.append("")
lines2.append("| 客户 | PPT本周(万) | 系统本周(万) | 差额 | PPT上月同周(万) |")
lines2.append("|------|-------------|--------------|------|-----------------|")
for name, ppt_yuan in ppt_week.items():
    sys_amt = 0.0
    for k, v in week_by.items():
        ku = k.upper().replace("İ", "I")
        nu = name.upper().replace("İ", "I")
        if any(tok in ku and tok in nu for tok in ["VEYSEL", "SAFIRAN", "LUXEM", "BILLIONAIRE", "ECN"]) or (
            "TIVAL" in ku and "TIVAL" in nu
        ):
            sys_amt = float(v)
            break
    pv = wan(ppt_yuan)
    sv = wan(sys_amt)
    lines2.append(f"| {name} | {pv} | {sv} | {sv-pv:+.2f} | {wan(ppt_prev_week[name])} |")

out.write_text("\n".join(lines2), encoding="utf-8")
print(out)
print("\n".join(lines2))
