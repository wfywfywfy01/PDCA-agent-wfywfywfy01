# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
raw = json.loads((ROOT / "outputs" / "2026-W28_raw_lines.json").read_text(encoding="utf-8"))
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
sales_map = cfg["salespeople"]
dealer_meta = {d["name"]: d for d in cfg["dealers"]}
yjj = {d["name"] for d in cfg["dealers"] if sales_map[d["sales"]]["report_group"] == "杨晶晶组"}
name_index = {}
for key, meta in sales_map.items():
    name_index[key.casefold()] = key
    for n in meta.get("system_names", []):
        name_index[str(n).casefold()] = key

print("=== 杨晶晶组 dealers MTD by salesperson ===")
bucket = defaultdict(float)
for r in raw["mtd"]:
    if r["dealer"] not in yjj:
        continue
    sp = (r.get("salesperson") or "").strip() or "(empty)"
    mapped = name_index.get(sp.casefold(), "UNMAPPED")
    bucket[f"{r['dealer']} | {sp} → {mapped}"] += r["amount"]
for k, v in sorted(bucket.items(), key=lambda x: -x[1]):
    print(f"{v/10000:.2f}万\t{k}")

print("\n=== rows where salesperson NOT in 杨晶晶组成员 ===")
yjj_people = {k for k, m in sales_map.items() if m["report_group"] == "杨晶晶组"}
for r in raw["mtd"]:
    if r["dealer"] not in yjj:
        continue
    sp = (r.get("salesperson") or "").strip()
    key = name_index.get(sp.casefold()) if sp else None
    if key in yjj_people or (not sp):  # empty falls to owner which is yjj
        if not sp or key in yjj_people:
            if key in yjj_people or not sp:
                # empty → owner in yjj group, counts in ppt
                # only print if mapped outside yjj
                pass
    if key and sales_map[key]["report_group"] != "杨晶晶组":
        print(f"{r['amount']/10000:.2f}万\tsp={sp}→{key}\t{r['dealer']}\t{r['series'][:24]}")
    elif sp and not key:
        print(f"{r['amount']/10000:.2f}万\tsp={sp}→UNMAPPED\t{r['dealer']}\t{r['series'][:24]}")
