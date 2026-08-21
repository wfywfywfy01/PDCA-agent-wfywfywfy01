# -*- coding: utf-8 -*-
"""补拉于冰、尤文静并合并进指定周的 JSON。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
DATA_RAW = Path(__file__).resolve().parent

WEEK_START = "2026-06-08"
WEEK_END = "2026-06-14"
JSON_PATH = DATA_RAW / f"liu_vemory_week_{WEEK_START}.json"

EXTRA = [
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
    if any(k in t for k in ("经销商", "dealer", "代理", "客户", "customer", "store", "boutique")):
        return "dealer_customer"
    if any(k in t for k in ("周会", "汇报", "复盘", "review", "报表")):
        return "internal_report"
    return "other"


def pull(uid: int, name: str) -> dict | None:
    proc = subprocess.run(
        [
            VERTU, "odoo", "vemory", "meetings",
            "--user-id", str(uid),
            "--start-date", WEEK_START,
            "--end-date", WEEK_END,
            "--max-meetings", "100",
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    merged = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        print(f"  失败 {name}: {merged.strip()[:200]}", file=sys.stderr)
        return None
    data = extract_json(proc.stdout)
    if not data:
        print(f"  失败 {name}: 非 JSON 响应", file=sys.stderr)
        return None
    print(f"  成功 {name}: {data.get('total_meetings', 0)} 场", flush=True)
    return data


def recompute_summary(summary: dict, raw: list[dict]) -> None:
    all_m = summary["all_meetings"]
    summary["total_meetings"] = len(all_m)
    summary["total_duration_hours"] = round(
        sum(float(m.get("duration_minutes") or 0) for m in all_m) / 60, 1
    )
    summary["total_todos"] = sum(int(m.get("todo_count") or 0) for m in all_m)
    summary["people_ok"] = len([r for r in raw if r.get("ok")])

    by_person: dict[str, dict] = {}
    by_category: dict[str, int] = {}
    for m in all_m:
        p = m["person"]
        by_person.setdefault(
            p,
            {"name": p, "user_id": 0, "meetings": 0, "duration_hours": 0.0, "todos": 0, "categories": {}},
        )
        by_person[p]["meetings"] += 1
        by_person[p]["duration_hours"] = round(
            by_person[p]["duration_hours"] + float(m.get("duration_minutes") or 0) / 60, 1
        )
        by_person[p]["todos"] += int(m.get("todo_count") or 0)
        cat = m.get("category") or "other"
        by_person[p]["categories"][cat] = by_person[p]["categories"].get(cat, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1

    for row in raw:
        name = row.get("name")
        if name in by_person:
            by_person[name]["user_id"] = row.get("user_id") or 0

    summary["by_person"] = sorted(by_person.values(), key=lambda x: -x["meetings"])
    cat_labels = {
        "dealer_customer": "经销商/客户",
        "interview": "招聘面试",
        "internal_report": "内部汇报",
        "other": "其他",
    }
    summary["by_category"] = {
        cat_labels.get(k, k): v for k, v in sorted(by_category.items(), key=lambda x: -x[1])
    }
    totals = summary.setdefault("totals", {})
    totals["meetings"] = summary["total_meetings"]
    totals["hours"] = summary["total_duration_hours"]
    totals["todos"] = summary["total_todos"]
    totals["active_people"] = len(by_person)


def main() -> int:
    if not JSON_PATH.is_file():
        print(f"缺少周数据: {JSON_PATH}", file=sys.stderr)
        return 1

    subprocess.run([VERTU, "reauth"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)

    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    summary = payload["summary"]
    raw = payload.get("raw") or []
    existing_uids = {r.get("user_id") for r in raw}
    existing_names = {m.get("person") for m in summary.get("all_meetings") or []}

    for idx, (uid, name) in enumerate(EXTRA):
        if uid in existing_uids or name in existing_names:
            print(f"跳过 {name}（已在数据中）", flush=True)
            continue
        if idx:
            time.sleep(10)
        print(f"补拉 {name} uid={uid}...", flush=True)
        data = pull(uid, name)
        if not data:
            continue
        meetings = data.get("meetings") or []
        person_name = data.get("user_name") or name
        raw.append({
            "ok": True,
            "status": "ok",
            "user_id": uid,
            "name": person_name,
            "total_meetings": data.get("total_meetings", len(meetings)),
            "meetings": meetings,
        })
        for m in meetings:
            secs = int(m.get("duration_seconds") or 0)
            title = m.get("name") or ""
            summary["all_meetings"].append({
                "person": person_name,
                "title": title,
                "start_time": m.get("start_time") or "",
                "duration_minutes": round(secs / 60, 1),
                "todo_count": len(m.get("todos") or []),
                "category": classify(title),
            })

    recompute_summary(summary, raw)
    payload["raw"] = raw
    JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已更新 {JSON_PATH}，共 {summary['total_meetings']} 场，{summary['total_duration_hours']}h")
    for p in summary["by_person"]:
        if p["name"] in ("于冰", "尤文静"):
            print(f"  {p['name']}: {p['meetings']}场 / {p['duration_hours']}h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
