# -*- coding: utf-8 -*-
"""拉取本月海外经销商一部/二部/新部 Vemory（frank 账号）。

权限：
- 逐人 odoo vemory meetings：仅本人及 HR 下属 → 一部/二部/新部会 denied
- vertu-cli vemory +meetings --scope team：本部门子树可见会议（含 owner）
本脚本以 team 列表为主，按 owner_user_id 归属三部。
"""

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
    idx = text.find("{")
    if idx < 0:
        return None
    return json.loads(text[idx:])


def load_roster() -> list[dict]:
    people: list[dict] = []
    for dept, label in DEPTS:
        code, text = run(
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


def pull_team() -> dict:
    code, text = run(
        [
            VERTU_CLI,
            "vemory",
            "+meetings",
            "--scope",
            "team",
            "--start-date",
            START,
            "--end-date",
            END,
        ]
    )
    data = parse_json(text)
    if not data or not data.get("ok", True):
        raise RuntimeError(f"team pull fail code={code}: {text[:300]}")
    return data


def probe_denied(people: list[dict], n: int = 5) -> list[str]:
    denied: list[str] = []
    for i, p in enumerate(people[:n]):
        if i:
            time.sleep(2)
        code, text = run(
            [
                VERTU,
                "odoo",
                "vemory",
                "meetings",
                "--user-id",
                str(p["user_id"]),
                "--start-date",
                START,
                "--end-date",
                END,
                "--max-meetings",
                "3",
            ]
        )
        if "没有权限" in text:
            denied.append(p["name"])
            print(f"  deny {p['name']}", flush=True)
        elif code == 0:
            print(f"  ok   {p['name']}", flush=True)
        else:
            print(f"  err  {p['name']}: {text[:80]}", flush=True)
    return denied


def main() -> int:
    print(f"window {START} ~ {END}", flush=True)
    people = load_roster()
    uid2 = {p["user_id"]: p for p in people}
    print(f"roster {len(people)}", flush=True)

    print("pull team meetings...", flush=True)
    data = pull_team()
    meetings = data.get("meetings") or []
    print(f"team total={data.get('total')} returned={len(meetings)}", flush=True)

    print("probe per-user permission (sample)...", flush=True)
    denied = probe_denied(people, n=5)

    owners = Counter((m.get("owner_user_id"), m.get("owner_name")) for m in meetings)
    target = [m for m in meetings if m.get("owner_user_id") in uid2]
    by_dept: dict[str, list] = defaultdict(list)
    for m in target:
        by_dept[uid2[m["owner_user_id"]]["dept"]].append(m)

    payload = {
        "as_of": END,
        "window": {"from": START, "to": END},
        "login": "frank.fu@vertu.cn",
        "note": (
            "逐人查询一部/二部/新部无权限；"
            "team=本部门子树可见会议，按 owner_user_id 归属三部。"
        ),
        "roster": people,
        "team_total": data.get("total"),
        "owned_by_123_count": len(target),
        "probe_denied_sample": denied,
        "owner_counts": [
            {
                "user_id": uid,
                "name": name,
                "count": c,
                "dept": uid2.get(uid, {}).get("dept", "中台/其他"),
            }
            for (uid, name), c in owners.most_common()
        ],
        "meetings_owned_by_123": target,
        "team_meetings": meetings,
    }
    out_json = OUT_DIR / f"overseas_vemory_mtd_{START}.json"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_json}", flush=True)

    lines = [
        f"# 海外经销商一部/二部/新部 Vemory · {START} ~ {END}",
        "",
        f"> 登录：frank.fu@vertu.cn · team 可见 **{data.get('total')}** 场 · "
        f"其中 owner 属一部/二部/新部 **{len(target)}** 场",
        "",
        "## 权限说明",
        "",
        "- 逐人 `vertu odoo vemory meetings --user-id`：**无权限**（frank 无 HR 下属）。",
        "- `vertu-cli vemory +meetings --scope team`：可拉本部门子树可见会议。",
        "- 下表按 **会议 owner** 归属；仅参会、非 owner 可能漏计。",
        "",
        "## 花名册",
        "",
    ]
    for label in ("一部", "二部", "新部"):
        roster = [p for p in people if p["dept"] == label]
        lines.append(f"- {label}：{len(roster)} 人 — " + "、".join(p["name"] for p in roster))
    lines.append("")

    for label in ("一部", "二部", "新部"):
        items = by_dept.get(label, [])
        roster = [p for p in people if p["dept"] == label]
        owners_c = Counter((m.get("owner_user_id"), m.get("owner_name")) for m in items)
        lines += [
            f"## {label}（花名册 {len(roster)} · owner 会议 {len(items)}）",
            "",
        ]
        if not items:
            lines += ["（team 可见列表中，本月无该部成员作为 owner 的会议）", ""]
            continue
        lines += ["| 人员 | 会议数 | 总时长(分) |", "|------|--------|-----------|"]
        for (uid, name), c in owners_c.most_common():
            dur = sum(
                int(m.get("duration_seconds") or 0)
                for m in items
                if m.get("owner_user_id") == uid
            )
            lines.append(f"| {name} | {c} | {dur // 60} |")
        lines += ["", "### 会议列表", ""]
        for m in sorted(items, key=lambda x: x.get("start_time") or "", reverse=True):
            st = (m.get("start_time") or "")[:16].replace("T", " ")
            dur = int(m.get("duration_seconds") or 0) // 60
            summ = (m.get("summary") or "").split("\n")[0][:140]
            lines.append(
                f"- **{st}** · {dur}min · {m.get('owner_name')} · {m.get('name')}"
            )
            if summ:
                lines.append(f"  - {summ}")
        lines.append("")

    other = [
        (uid, name, c)
        for (uid, name), c in owners.most_common()
        if uid not in uid2
    ]
    lines += ["## team 可见但 owner 不在三部（前 25）", ""]
    for uid, name, c in other[:25]:
        lines.append(f"- {name} (uid={uid})：{c} 场")
    lines.append("")

    out_md = OUT_DIR / f"overseas_vemory_mtd_{START}_一部二部新部.md"
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_md}", flush=True)
    print("by_dept", {k: len(v) for k, v in by_dept.items()}, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
