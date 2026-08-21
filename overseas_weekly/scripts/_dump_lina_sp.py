# -*- coding: utf-8 -*-
"""Inspect salesperson fields on Lina-group dealers for W28."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "outputs" / "2026-W28_raw_lines.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
dealer_meta = {d["name"]: d for d in cfg["dealers"]}
sales_map = cfg["salespeople"]

lina_dealers = {d["name"] for d in cfg["dealers"] if sales_map[d["sales"]]["report_group"] == "Lina组"}

print("=== Lina dealers week by salesperson ===")
bucket = defaultdict(float)
for r in raw["week"]:
    if r["dealer"] not in lina_dealers:
        continue
    key = f"{r['dealer']} | sp='{r['salesperson']}'"
    bucket[key] += r["amount"]
for k, v in sorted(bucket.items(), key=lambda x: -x[1]):
    print(f"{v/10000:.2f}万\t{k}")

print("\n=== unknown / non-mapped week (all) ===")
name_index = {}
for key, meta in sales_map.items():
    name_index[key.casefold()] = key
    for n in meta.get("system_names", []):
        name_index[str(n).casefold()] = key
non_team = set(cfg["attribution"]["non_team_salespeople"])

for r in raw["week"]:
    if r["dealer"] not in lina_dealers:
        continue
    sp = (r.get("salesperson") or "").strip()
    if not sp:
        tag = "EMPTY"
    elif sp in non_team:
        tag = "NON_TEAM"
    elif sp.casefold() in name_index:
        tag = f"TEAM:{name_index[sp.casefold()]}"
    else:
        tag = "UNKNOWN"
    if tag.startswith("TEAM"):
        continue
    print(f"{r['amount']/10000:.2f}万\t{tag}\tsp='{sp}'\t{r['dealer']}\t{r['series'][:30]}")
