# -*- coding: utf-8 -*-
"""补拉经销商三部 Vemory。"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path

VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
CLI = str(Path.home() / "AppData/Roaming/npm/vertu-cli.cmd")
OUT = Path(__file__).resolve().parents[1] / "outputs" / "2026-07_三部_vemory.json"


def classify(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("面试", "interview", "候选人", "招聘")):
        return "面试"
    if any(
        k in text
        for k in (
            "经销商",
            "代理",
            "客户",
            "门店",
            "商场",
            "合作",
            "dealer",
            "customer",
            "拜访",
            "london",
            "billionaire",
        )
    ):
        return "外部会议"
    return "内部会议"


def main() -> None:
    r = subprocess.run(
        [CLI, "hr", "+job-details", "--department", "经销商三部", "--limit", "50"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    d = json.loads(r.stdout[r.stdout.find("{") :])
    targets = []
    for row in d["rows"]:
        if "离职" in (row.get("在职状态") or ""):
            continue
        targets.append((int(row["user_id"]), row["name"]))
    print("targets", targets, flush=True)

    results = []
    for i, (uid, name) in enumerate(targets):
        if i:
            time.sleep(5)
        print("pull", name, uid, flush=True)
        p = subprocess.run(
            [
                VERTU,
                "odoo",
                "vemory",
                "meetings",
                "--user-id",
                str(uid),
                "--start-date",
                "2026-07-01",
                "--end-date",
                "2026-07-19",
                "--max-meetings",
                "100",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        text = (p.stdout or "") + (p.stderr or "")
        if "没有权限" in text:
            results.append({"name": name, "uid": uid, "status": "denied"})
            print(" denied", flush=True)
            continue
        j = text.find("{")
        if j < 0:
            results.append({"name": name, "uid": uid, "status": "error", "err": text[:120]})
            continue
        payload = json.loads(text[j:])
        ms = payload.get("meetings") or []
        cats: Counter = Counter()
        items = []
        for m in ms:
            cat = classify(m.get("name") or "", m.get("summary") or "")
            cats[cat] += 1
            items.append(
                {
                    "day": (m.get("start_time") or "")[:10],
                    "cat": cat,
                    "title": m.get("name"),
                    "dur": int(m.get("duration_seconds") or 0) // 60,
                }
            )
        results.append(
            {
                "name": name,
                "uid": uid,
                "status": "ok",
                "total": payload.get("total_meetings", len(ms)),
                "cats": dict(cats),
                "items": items,
            }
        )
        print(" ok", len(ms), dict(cats), flush=True)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
