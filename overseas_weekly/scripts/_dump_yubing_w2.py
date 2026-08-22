# -*- coding: utf-8 -*-
import json
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sandbox = ROOT / "scripts" / "_sandbox_yubing_w2.py"
cjs = Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
cmd = ["node", str(cjs), "odoo", "data", "sandbox", "--code", f"@{sandbox}"]
proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
(ROOT / "outputs" / "_yubing_w2_raw.json").write_text(proc.stdout, encoding="utf-8")
if proc.returncode != 0:
    raise SystemExit(proc.stderr or proc.stdout)
data = json.loads(proc.stdout.strip())
if data["result"]["execution"].get("error"):
    raise SystemExit(json.dumps(data["result"]["execution"]["error"], ensure_ascii=False, indent=2))
r = data["result"]["execution"]["result"]
lines = [
    f"week_sum={r['week_sum']/10000:.2f}万 mtd_sum={r['mtd_sum']/10000:.2f}万",
    "--- week lines ---",
]
for x in r["week"]:
    lines.append(
        f"{x['amount']/10000:.2f}万\t{x['d']}\t{x['dealer']}\t{x['major']}/{x['series']}\t"
        f"{x['order_no']}\t{x['salesperson']}\t{x['sku'][:40]}"
    )
out = ROOT / "outputs" / "_yubing_w2.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(out)
print("\n".join(lines))
