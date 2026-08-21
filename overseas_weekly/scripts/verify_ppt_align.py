# -*- coding: utf-8 -*-
"""
用 ppt 口径（dealer_owner − 非团队记名）核对第二周 PPT 关键数字。

默认读 outputs/2026-W28_overview.json（需先 fetch --as-of 2026-07-12）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
OVERVIEW = ROOT / "outputs" / "2026-W28_overview.json"

# PPT 手填关键数（万元）；Lina 达成率按 163.8/290 校正为 56.5
PPT = {
    "mtd": 335.4,
    "week": 211.0,
    "okr_rate": 48.3,
    "mom": -3.0,
    "groups": {
        "Lina组": {"mtd": 163.8, "week": 69.1, "okr_rate": 56.5},
        "于冰组": {"mtd": 64.0, "week": 47.58, "okr_rate": 58.2},
        "杨晶晶组": {"mtd": 107.2, "okr_rate": 46.0},
    },
}


def wan(x: float) -> float:
    return round(float(x) / 10000, 2)


def check(name: str, got: float, expect: float, tol: float = 0.5) -> tuple[bool, str]:
    ok = abs(got - expect) <= tol
    flag = "PASS" if ok else "FAIL"
    return ok, f"[{flag}] {name}: got={got} expect={expect} diff={got - expect:+.2f}"


def main() -> int:
    if not OVERVIEW.exists():
        print(f"missing {OVERVIEW}; run: py fetch_overview.py --as-of 2026-07-12")
        return 1
    data = json.loads(OVERVIEW.read_text(encoding="utf-8"))
    lines = ["# W28 PPT 对齐核对（headline_ppt / groups_ppt）", ""]
    ok_all = True

    h = data["headline_ppt"]
    checks = [
        ("全盘 MTD(ppt)", wan(h["mtd_amount"]), PPT["mtd"], 1.5),
        ("全盘 本周(ppt)", wan(h["week_amount"]), PPT["week"], 1.5),
        ("全盘 达成率(ppt)", h["okr_rate"], PPT["okr_rate"], 1.5),
        ("全盘 环比(owner)", data["headline"]["mom_pct"], PPT["mom"], 1.0),
    ]
    gmap = {g["name"]: g for g in data["groups_ppt"]}
    for gname, p in PPT["groups"].items():
        g = gmap[gname]
        checks.append((f"{gname} MTD(ppt)", wan(g["mtd_amount"]), p["mtd"], 1.0))
        if "week" in p:
            checks.append((f"{gname} 本周(ppt)", wan(g["week_amount"]), p["week"], 0.5))
        checks.append((f"{gname} 达成率(ppt)", g["okr_rate"], p["okr_rate"], 1.0))

    lines.append("| 项 | 结果 |")
    lines.append("|----|------|")
    for name, got, expect, tol in checks:
        ok, msg = check(name, got, expect, tol)
        ok_all = ok_all and ok
        lines.append(f"| {msg} | {'✅' if ok else '⚠'} |")

    lines.append("")
    lines.append("## cross_person（已从 ppt 剔除）")
    for row in data.get("cross_person", {}).get("week", []):
        lines.append(f"- week {row['salesperson']}: {wan(row['amount'])}万")

    lines.append("")
    lines.append("## 三口径对照（万）")
    lines.append("| 组 | owner周 | ppt周 | aligned周 | owner月 | ppt月 | aligned月 |")
    lines.append("|----|----------|-------|-----------|---------|-------|-----------|")
    omap = {g["name"]: g for g in data["groups"]}
    amap = {g["name"]: g for g in data["groups_aligned"]}
    for gname in ["Lina组", "于冰组", "杨晶晶组"]:
        o, p, a = omap[gname], gmap[gname], amap[gname]
        lines.append(
            f"| {gname} | {wan(o['week_amount'])} | {wan(p['week_amount'])} | {wan(a['week_amount'])} | "
            f"{wan(o['mtd_amount'])} | {wan(p['mtd_amount'])} | {wan(a['mtd_amount'])} |"
        )

    lines.append("")
    lines.append("## people (salesperson_aligned 个人贡献)")
    for p in data.get("people", []):
        lines.append(
            f"- {p['name']}({p['group']}): week={wan(p['week_amount'])} mtd={wan(p['mtd_amount'])}"
        )

    lines.append("")
    lines.append(f"**总体: {'对齐通过 ✅' if ok_all else '仍有偏差 ⚠'}**")
    lines.append(
        f"- owner MTD={wan(data['headline']['mtd_amount'])} / "
        f"ppt={wan(h['mtd_amount'])} / cross={wan(h.get('cross_person_mtd') or 0)}"
    )
    lines.append(
        f"- 家具系统大类={wan(data['headline'].get('furniture_amount') or 0)} "
        f"（PPT 另约 19 万家具台账未进 odoo_sale）"
    )

    out = ROOT / "outputs" / "2026-W28_align_verify.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)
    print("\n".join(lines))
    return 0 if ok_all else 2


if __name__ == "__main__":
    raise SystemExit(main())
