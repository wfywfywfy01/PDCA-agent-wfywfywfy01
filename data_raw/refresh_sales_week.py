# -*- coding: utf-8 -*-
"""强制刷新尤文静（及于冰）本周 Vemory 并写回 JSON。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
JSON_PATH = Path(__file__).resolve().parent / "liu_vemory_week_2026-06-08.json"
WEEK_START, WEEK_END = "2026-06-08", "2026-06-14"

REFRESH = [
    (13063, "于冰"),
    (13551, "尤文静"),
]


def extract_json(text: str):
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            return decoder.raw_decode(text[i:])[0]
        except json.JSONDecodeError:
            continue
    return None


def classify(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ("面试", "interview", "招聘")):
        return "interview"
    if any(k in t for k in ("经销商", "dealer", "代理", "客户", "customer")):
        return "dealer_customer"
    if any(k in t for k in ("周会", "汇报", "复盘", "review", "报表")):
        return "internal_report"
    return "other"


def pull(uid: int) -> dict | None:
    proc = subprocess.run(
        [VERTU, "odoo", "vemory", "meetings", "--user-id", str(uid),
         "--start-date", WEEK_START, "--end-date", WEEK_END, "--max-meetings", "100"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout)[:250], file=sys.stderr)
        return None
    return extract_json(proc.stdout)


def main() -> int:
    subprocess.run([VERTU, "reauth"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    summary = payload["summary"]
    raw = payload.get("raw") or []
    refresh_names = {n for _, n in REFRESH}
    refresh_uids = {u for u, _ in REFRESH}

    raw = [r for r in raw if r.get("user_id") not in refresh_uids]
    summary["all_meetings"] = [m for m in summary.get("all_meetings") or [] if m.get("person") not in refresh_names]

    for idx, (uid, name) in enumerate(REFRESH):
        if idx:
            time.sleep(10)
        print(f"拉取 {name}...", flush=True)
        data = pull(uid)
        if not data:
            return 1
        meetings = data.get("meetings") or []
        person = data.get("user_name") or name
        raw.append({"ok": True, "user_id": uid, "name": person,
                    "total_meetings": data.get("total_meetings", len(meetings)), "meetings": meetings})
        for m in meetings:
            secs = int(m.get("duration_seconds") or 0)
            title = m.get("name") or ""
            summary["all_meetings"].append({
                "person": person, "title": title, "start_time": m.get("start_time") or "",
                "duration_minutes": round(secs / 60, 1), "todo_count": len(m.get("todos") or []),
                "category": classify(title),
            })
        print(f"  {person}: {len(meetings)} 场", flush=True)

    all_m = summary["all_meetings"]
    summary["total_meetings"] = len(all_m)
    summary["total_duration_hours"] = round(sum(float(m.get("duration_minutes") or 0) for m in all_m) / 60, 1)
    summary["total_todos"] = sum(int(m.get("todo_count") or 0) for m in all_m)

    by_person, by_cat = {}, {}
    uid_map = {r["name"]: r.get("user_id") for r in raw}
    for m in all_m:
        p = m["person"]
        by_person.setdefault(p, {"name": p, "user_id": uid_map.get(p, 0), "meetings": 0,
                                  "duration_hours": 0.0, "todos": 0, "categories": {}})
        by_person[p]["meetings"] += 1
        by_person[p]["duration_hours"] = round(by_person[p]["duration_hours"] + float(m.get("duration_minutes") or 0) / 60, 1)
        by_person[p]["todos"] += int(m.get("todo_count") or 0)
        c = m.get("category") or "other"
        by_person[p]["categories"][c] = by_person[p]["categories"].get(c, 0) + 1
        by_cat[c] = by_cat.get(c, 0) + 1

    labels = {"dealer_customer": "经销商/客户", "interview": "招聘面试", "internal_report": "内部汇报", "other": "其他"}
    summary["by_person"] = sorted(by_person.values(), key=lambda x: -x["meetings"])
    summary["by_category"] = {labels.get(k, k): v for k, v in sorted(by_cat.items(), key=lambda x: -x[1])}
    t = summary.setdefault("totals", {})
    t.update({"meetings": summary["total_meetings"], "hours": summary["total_duration_hours"],
              "todos": summary["total_todos"], "active_people": len(by_person)})

    payload["raw"] = raw
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：共 {summary['total_meetings']} 场 / {summary['total_duration_hours']}h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
