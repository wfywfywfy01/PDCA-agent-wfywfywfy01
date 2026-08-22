# -*- coding: utf-8 -*-
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "outputs" / "2026-W29_raw_lines.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
ov = json.loads((ROOT / "outputs" / "2026-W29_overview.json").read_text(encoding="utf-8"))
non = set(cfg["attribution"]["non_team_salespeople"])
meta = {d["name"]: d for d in cfg["dealers"]}
sm = cfg["salespeople"]


def wan(x: float) -> float:
    return round(x / 10000, 2)


bd = defaultdict(float)
for r in raw["week"]:
    if (r.get("salesperson") or "").strip() in non:
        continue
    bd[r["dealer"]] += r["amount"]
print("WEEK_DEALERS")
for n, a in sorted(bd.items(), key=lambda x: -x[1]):
    if abs(a) < 1:
        continue
    m = meta.get(n, {})
    g = sm.get(m.get("sales", ""), {}).get("report_group", "?")
    print(f"{wan(a)}\t{n}\t{m.get('country','')}\t{g}")

print("TOP_MTD")
for d in ov["top_dealers_mtd"][:12]:
    print(f"{wan(d['amount'])}\t{d['name']}\t{d['group']}\t{d['region']}")

print("GROUP_PRODUCTS")
for p in ov["products"]["by_group_mtd"][:12]:
    print(f"{p['group']}\t{p['series']}\t{p['major']}\t{wan(p['amount'])}")

print("HIGH")
for h in ov["products"].get("high_ticket_mtd", [])[:8]:
    print(f"{h['series']}\t{h['major']}\t{wan(h['amount'])}\t{wan(h['avg_per_order'])}")
