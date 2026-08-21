# -*- coding: utf-8 -*-
"""Extract dealer/people bits for W27 report drafting."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "outputs" / "2026-W27_raw_lines.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
ov = json.loads((ROOT / "outputs" / "2026-W27_overview.json").read_text(encoding="utf-8"))
dealer_meta = {d["name"]: d for d in cfg["dealers"]}
sales_map = cfg["salespeople"]
non_team = set(cfg.get("attribution", {}).get("non_team_salespeople", {}))


def wan(x: float) -> float:
    return round(x / 10000, 2)


# dealer week totals (ppt = exclude non_team)
by_dealer = defaultdict(lambda: {"amount": 0.0, "lines": 0})
for r in raw["week"]:
    sp = (r.get("salesperson") or "").strip()
    if sp in non_team:
        continue
    by_dealer[r["dealer"]]["amount"] += r["amount"]
    by_dealer[r["dealer"]]["lines"] += r["lines"]

print("=== DEALERS week/mtd (ppt) ===")
for name, v in sorted(by_dealer.items(), key=lambda x: -x[1]["amount"]):
    m = dealer_meta.get(name, {})
    sales = m.get("sales", "?")
    group = sales_map.get(sales, {}).get("report_group", "?")
    print(f"{wan(v['amount'])}\t{name}\t{m.get('country','')}\t{sales}\t{group}")

print("\n=== PEOPLE ===")
for p in ov.get("people", []):
    if p["week_amount"] or p["mtd_amount"]:
        print(f"{p['name']}\tweek={wan(p['week_amount'])}\tmtd={wan(p['mtd_amount'])}\t{p['group']}")

print("\n=== GROUPS PPT ===")
for g in ov["groups_ppt"]:
    print(
        f"{g['name']}\tweek={wan(g['week_amount'])}\tmtd={wan(g['mtd_amount'])}\t"
        f"okr={g['okr_rate']}%\tmom={g['mom_pct']}\tyoy={g['yoy_pct']}\t"
        f"yoy_base={wan(g['yoy_base_amount'])}"
    )
