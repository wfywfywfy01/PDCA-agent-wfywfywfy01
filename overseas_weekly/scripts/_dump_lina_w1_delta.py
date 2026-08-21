# -*- coding: utf-8 -*-
"""Explain ~1014 CNY gap between PPT Lina table and system."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "outputs" / "2026-W27_raw_lines.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
sales_map = cfg["salespeople"]
lina = {
    d["name"]
    for d in cfg["dealers"]
    if sales_map[d["sales"]]["report_group"] == "Lina组"
}
ppt = {
    "Veysel Sevis Ltd": 65562,
    "VERTU LONDON LTD": 397981,
    "Luxem Store": 226840,  # PPT says Luxem
    "HASSIB ABDALLAH AMIR ALLAH": 255462,
}
# aggregate system by dealer
from collections import defaultdict

sys_d = defaultdict(float)
for r in raw["week"]:
    if r["dealer"] in lina:
        sys_d[r["dealer"]] += r["amount"]
        print(
            f"{r['amount']:.2f}\t{r['dealer']}\tsp={r['salesperson']}\t"
            f"{r['major']}/{r['series'][:24]}"
        )

print("\n=== dealer totals ===")
for k, v in sorted(sys_d.items(), key=lambda x: -x[1]):
    # match ppt
    ppt_v = None
    for pk, pv in ppt.items():
        if pk[:6].lower() in k.lower() or "LUXEM" in k.upper() and "LUXEM" in pk.upper():
            ppt_v = pv
            break
    print(f"{v:.2f} sys | ppt={ppt_v} | diff={v-(ppt_v or 0):+.2f} | {k}")
print(f"sys sum={sum(sys_d.values()):.2f} ppt sum={sum(ppt.values()):.2f}")
