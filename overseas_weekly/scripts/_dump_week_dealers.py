# -*- coding: utf-8 -*-
"""Dump week dealer SI for W29 report drafting."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
cfg = json.loads((ROOT / "config" / "dealers.json").read_text(encoding="utf-8"))
sandbox = ROOT / "scripts" / "_sandbox_overview.py"
npm = Path.home() / "AppData" / "Roaming" / "npm"
cjs = npm / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
cmd = ["node", str(cjs), "odoo", "data", "sandbox", "--code", f"@{sandbox}"]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
if proc.returncode != 0:
    raise SystemExit(proc.stderr or proc.stdout)
data = json.loads(proc.stdout.strip())
raw = data["result"]["execution"]["result"]
dealer_meta = {d["name"]: d for d in cfg["dealers"]}
sales_map = cfg["salespeople"]

out_lines = ["=== WEEK dealers (7/13-7/16 window end) ==="]
for r in raw["week"]:
    m = dealer_meta.get(r["dealer"], {})
    sales = m.get("sales", "?")
    group = sales_map.get(sales, {}).get("report_group", "?")
    wan = r["amount"] / 10000
    out_lines.append(
        f"{wan:.2f}万\t{r['dealer']}\t{m.get('country','')}\t{sales}\t{group}"
    )

out_lines.append("\n=== MTD dealers ===")
for r in raw["mtd"]:
    m = dealer_meta.get(r["dealer"], {})
    sales = m.get("sales", "?")
    group = sales_map.get(sales, {}).get("report_group", "?")
    wan = r["amount"] / 10000
    out_lines.append(
        f"{wan:.2f}万\t{r['dealer']}\t{m.get('country','')}\t{sales}\t{group}"
    )

out = ROOT / "outputs" / "_w29_week_dealers.txt"
out.write_text("\n".join(out_lines), encoding="utf-8")
print(out)
print("\n".join(out_lines[:40]))
