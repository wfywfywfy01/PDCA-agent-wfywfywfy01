# -*- coding: utf-8 -*-
"""用刘春梅账号逐人拉取经销商一部/二部/新部本月 Vemory。"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

VERTU_CLI = str(Path.home() / "AppData/Roaming/npm/vertu-cli.cmd")
VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
OUT_DIR = Path(__file__).resolve().parent
START = "2026-07-01"
END = date.today().isoformat()
SLEEP_SEC = 6
DEPTS = [("经销商一部", "一部"), ("经销商二部", "二部"), ("经销商新部", "新部")]


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def parse_json(text: str):
    for i, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            return json.loads(text[i:])
        except json.JSONDecodeError:
            continue
    return None


def load_roster() -> list[dict]:
    people: list[dict] = []
    for dept, label in DEPTS:
        _, text = run(
            [VERTU_CLI, "hr", "+job-details", "--department", dept, "--limit", "100"]
        )
        data = parse_json(text)
        if not data:
            raise RuntimeError(f"roster fail {dept}: {text[:200]}")
        for row in data.get("rows") or []:
            uid = row.get("user_id")
            name = row.get("name") or row.get("employee_name")
            if uid and name:
                people.append(
                    {
                        "dept": label,
                        "dept_full": dept,
                        "user_id": int(uid),
                        "name": str(name).strip(),
                    }
                )
    return people


def pull_one(user_id: int, name: str) -> dict:
    code, text = run(
        [
            VERTU,
            "odoo",
            "vemory",
            "meetings",
            "--user-id",
            str(user_id),
            "--start-date",
            START,
            "--end-date",
            END,
            "--max-meetings",
            "100",
        ]
    )
    if "没有权限" in text:
        return {
            "ok": False,
            "status": "denied",
            "user_id": user_id,
            "name": name,
            "error": "没有权限",
        }
    if code != 0:
        status = (
            "rate_limited"
            if ("RATE_LIMITED" in text or "配额" in text)
            else "error"
        )
        return {
            "ok": False,
            "status": status,
            "user_id": user_id,
            "name": name,
            "error": text.strip()[:250],
        }
    payload = parse_json(text)
    if not payload:
        return {
            "ok": False,
            "status": "error",
            "user_id": user_id,
            "name": name,
            "error": "非 JSON",
        }
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
    print(f"window {START} ~ {END}", flush=True)
    people = load_roster()
    print(f"roster {len(people)}", flush=True)

    results = []
    for idx, p in enumerate(people):
        if idx:
            time.sleep(SLEEP_SEC)
        print(
            f"[{idx+1}/{len(people)}] {p['dept']} {p['name']} uid={p['user_id']}",
            flush=True,
        )
        row = pull_one(p["user_id"], p["name"])
        row["dept"] = p["dept"]
        row["dept_full"] = p["dept_full"]
        results.append(row)
        if row.get("ok"):
            print(f"  -> {row.get('total_meetings')} meetings", flush=True)
        else:
            print(f"  -> {row.get('status')}: {row.get('error','')[:80]}", flush=True)

    by_dept = defaultdict(list)
    for r in results:
        by_dept[r["dept"]].append(r)

    payload = {
        "as_of": END,
        "window": {"from": START, "to": END},
        "login": "13281878861",
        "user_id": 12564,
        "user_name": "刘春梅",
        "roster_count": len(people),
        "ok_count": sum(1 for r in results if r.get("ok")),
        "denied_count": sum(1 for r in results if r.get("status") == "denied"),
        "results": results,
    }
    out_json = OUT_DIR / f"overseas_123_vemory_liu_{START}.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_json}", flush=True)

    lines = [
        f"# 海外经销商一部/二部/新部 Vemory（刘春梅账号）· {START} ~ {END}",
        "",
        f"> 登录：13281878861 / 刘春梅 · 花名册 {len(people)} 人 · "
        f"成功 {payload['ok_count']} · 无权限 {payload['denied_count']}",
        "",
    ]
    for label in ("一部", "二部", "新部"):
        rows = by_dept.get(label, [])
        ok_rows = [r for r in rows if r.get("ok")]
        denied = [r for r in rows if not r.get("ok")]
        total_m = sum(int(r.get("total_meetings") or 0) for r in ok_rows)
        lines += [
            f"## {label}（人员 {len(rows)} · 有会 {sum(1 for r in ok_rows if (r.get('total_meetings') or 0)>0)} · 会议合计 {total_m}）",
            "",
            "| 人员 | 状态 | 会议数 |",
            "|------|------|--------|",
        ]
        for r in sorted(
            rows,
            key=lambda x: (-(x.get("total_meetings") or 0), x.get("name") or ""),
        ):
            st = "ok" if r.get("ok") else r.get("status")
            n = r.get("total_meetings") if r.get("ok") else "-"
            lines.append(f"| {r.get('name')} | {st} | {n} |")
        if denied:
            lines.append("")
            lines.append(
                "无权限：" + "、".join(r.get("name") or "?" for r in denied)
            )
        lines.append("")
        # top meetings per person with data
        for r in ok_rows:
            ms = r.get("meetings") or []
            if not ms:
                continue
            lines.append(f"### {r.get('name')}（{r.get('total_meetings')}）")
            for m in sorted(ms, key=lambda x: x.get("start_time") or "", reverse=True)[:12]:
                st = (m.get("start_time") or "")[:16].replace("T", " ")
                dur = int(m.get("duration_seconds") or 0) // 60
                summ = (m.get("summary") or "").split("\n")[0][:120]
                lines.append(f"- **{st}** · {dur}min · {m.get('name')}")
                if summ:
                    lines.append(f"  - {summ}")
            if len(ms) > 12:
                lines.append(f"- … 另有 {len(ms)-12} 场，见 JSON")
            lines.append("")

    out_md = OUT_DIR / f"overseas_123_vemory_liu_{START}.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_md}", flush=True)

    # quick counters
    for label in ("一部", "二部", "新部"):
        rows = by_dept.get(label, [])
        ok_n = sum(1 for r in rows if r.get("ok"))
        meet_n = sum(int(r.get("total_meetings") or 0) for r in rows if r.get("ok"))
        print(f"{label}: ok={ok_n}/{len(rows)} meetings={meet_n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
