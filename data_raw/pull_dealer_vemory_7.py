# -*- coding: utf-8 -*-
"""拉取经销商团队 7 人本周 Vemory 会议数据。"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
WORKSPACE = Path(__file__).resolve().parents[1]
SLEEP_SEC = 6

today = date.today()
week_start = today - timedelta(days=today.weekday())
START = week_start.isoformat()
END = today.isoformat()
OUT_JSON = Path(__file__).resolve().parent / f"dealer_vemory_7_{week_start.isoformat()}.json"

TARGETS = [
    (12564, "刘春梅"),
    (13063, "于冰"),
    (13551, "尤文静"),
    (14113, "何海文"),
    (14344, "王宇彤"),
    (13122, "杨晶晶"),
    (13365, "付汪阳"),
]


def run_vertu(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    proc = subprocess.run(
        [VERTU, *args],
        cwd=str(WORKSPACE),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def extract_json(text: str):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            return payload
        except json.JSONDecodeError:
            continue
    return None


def classify_meeting(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("面试", "interview", "招聘", "hr ", "candidate")):
        return "interview"
    if any(k in text for k in ("经销商", "dealer", "代理", "客户", "customer", "拜访", "store", "boutique", "india", "russia", "luxem")):
        return "dealer_customer"
    if any(k in text for k in ("周会", "月会", "汇报", "复盘", "对齐", "review", "报表", "周报")):
        return "internal_report"
    return "other"


def pull_one(user_id: int, name: str) -> dict:
    code, out, err = run_vertu(
        [
            "odoo", "vemory", "meetings",
            "--user-id", str(user_id),
            "--start-date", START,
            "--end-date", END,
            "--max-meetings", "100",
        ]
    )
    merged = (out or "") + (err or "")
    if code != 0:
        status = "denied" if "没有权限" in merged else "rate_limited" if "RATE_LIMITED" in merged or "配额" in merged else "error"
        return {"ok": False, "status": status, "user_id": user_id, "name": name, "error": merged.strip()[:250]}
    payload = extract_json(out)
    if not payload:
        return {"ok": False, "status": "error", "user_id": user_id, "name": name, "error": "非 JSON"}
    meetings = payload.get("meetings") or []
    return {
        "ok": True,
        "status": "ok",
        "user_id": user_id,
        "name": payload.get("user_name") or name,
        "total_meetings": payload.get("total_meetings", len(meetings)),
        "meetings": meetings,
    }


def main() -> int:
    if not Path(VERTU).exists():
        print("vertu.cmd 未找到", file=sys.stderr)
        return 1

    results = []
    for idx, (uid, name) in enumerate(TARGETS):
        if idx:
            time.sleep(SLEEP_SEC)
        print(f"[{idx + 1}/{len(TARGETS)}] {name}", flush=True)
        row = pull_one(uid, name)
        results.append(row)
        n = len(row.get("meetings") or []) if row.get("ok") else 0
        print(f"  -> {row.get('status')} {n} meetings", flush=True)

    allowed = [r for r in results if r.get("ok")]
    denied = [r for r in results if not r.get("ok")]

    by_person = []
    by_category = defaultdict(int)
    flat = []
    total_secs = 0
    total_todos = 0

    for row in allowed:
        meetings = row.get("meetings") or []
        secs = sum(int(m.get("duration_seconds") or 0) for m in meetings)
        todos = sum(len(m.get("todos") or []) for m in meetings)
        cats = defaultdict(int)
        for m in meetings:
            cat = classify_meeting(str(m.get("name") or ""), str(m.get("summary") or ""))
            cats[cat] += 1
            by_category[cat] += 1
            flat.append({
                "person": row["name"],
                "title": m.get("name"),
                "start_time": m.get("start_time"),
                "duration_minutes": round((m.get("duration_seconds") or 0) / 60, 1),
                "todo_count": len(m.get("todos") or []),
                "category": cat,
            })
        total_secs += secs
        total_todos += todos
        by_person.append({
            "name": row["name"],
            "user_id": row["user_id"],
            "meetings": len(meetings),
            "duration_hours": round(secs / 3600, 1),
            "todos": todos,
            "categories": dict(cats),
        })

    flat.sort(key=lambda x: x.get("start_time") or "", reverse=True)
    summary = {
        "window": {"from": START, "to": END, "label": f"{START} ~ {END}"},
        "viewer": "刘春梅",
        "people_ok": len(allowed),
        "people_failed": len(denied),
        "total_meetings": sum(p["meetings"] for p in by_person),
        "total_duration_hours": round(total_secs / 3600, 1),
        "total_todos": total_todos,
        "by_category": dict(by_category),
        "by_person": sorted(by_person, key=lambda x: -x["meetings"]),
        "failed": [{"name": d["name"], "status": d.get("status")} for d in denied],
        "all_meetings": flat,
    }

    OUT_JSON.write_text(json.dumps({"summary": summary, "raw": allowed}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
