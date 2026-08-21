# -*- coding: utf-8 -*-
"""从 Vemory 抽取 W3 工作事项（客户/面试/内部/培训）。"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "outputs" / "_w3_work_from_vemory.json"
REPO = Path(__file__).resolve().parents[2]


def classify(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("面试", "interview", "候选人", "招聘")):
        return "面试"
    if any(
        k in text
        for k in ("培训", "training", "onboarding", "cursor", "ai工具", "五件套", "mars")
    ):
        return "培训"
    if any(
        k in text
        for k in (
            "周会",
            "晨会",
            "例会",
            "对齐",
            "复盘",
            "sop",
            "vps",
            "内部",
            "部门会议",
            "team meeting",
            "治理",
            "规范",
        )
    ):
        return "内部"
    return "客户"


def junk(title: str, dur: int) -> bool:
    if dur >= 400:
        return True
    return any(
        k in title
        for k in (
            "录音连线",
            "内容极少",
            "转录内容不足",
            "简短开场",
            "空会议",
            "信息不足",
            "开场寒暄",
            "New Recording",
        )
    )


def main() -> None:
    items = []

    # 一二新部
    p1 = REPO / "data_raw" / "overseas_123_vemory_liu_2026-07-01.json"
    d1 = json.loads(p1.read_text(encoding="utf-8"))
    for r in d1.get("results") or []:
        if not r.get("ok"):
            continue
        name = r.get("name")
        for m in r.get("meetings") or []:
            day = (m.get("start_time") or "")[:10]
            if not ("2026-07-13" <= day <= "2026-07-19"):
                continue
            title = m.get("name") or ""
            dur = int(m.get("duration_seconds") or 0) // 60
            if junk(title, dur):
                continue
            summary = m.get("summary") or ""
            items.append(
                {
                    "person": name,
                    "dept": r.get("dept"),
                    "day": day,
                    "dur": dur,
                    "cat": classify(title, summary),
                    "title": title,
                    "brief": summary.split("\n")[0][:200],
                }
            )

    # 中台逐人
    p2 = Path(__file__).resolve().parents[1] / "outputs" / "2026-07_中台_vemory.json"
    for r in json.loads(p2.read_text(encoding="utf-8")):
        if r.get("status") != "ok":
            continue
        name = r.get("name")
        for m in r.get("items") or []:
            day = m.get("day") or ""
            if not ("2026-07-13" <= day <= "2026-07-19"):
                continue
            title = m.get("title") or ""
            dur = int(m.get("dur") or 0)
            if junk(title, dur):
                continue
            brief = m.get("summary") or ""
            items.append(
                {
                    "person": name,
                    "dept": "中台",
                    "day": day,
                    "dur": dur,
                    "cat": classify(title, brief),
                    "title": title,
                    "brief": brief[:200],
                }
            )

    # 三部尤文静
    p3 = Path(__file__).resolve().parents[1] / "outputs" / "2026-07_三部_vemory.json"
    for r in json.loads(p3.read_text(encoding="utf-8")):
        if r.get("status") != "ok":
            continue
        name = r.get("name")
        for m in r.get("items") or []:
            day = m.get("day") or ""
            if not ("2026-07-13" <= day <= "2026-07-19"):
                continue
            title = m.get("title") or ""
            dur = int(m.get("dur") or 0)
            if junk(title, dur):
                continue
            items.append(
                {
                    "person": name,
                    "dept": "三部",
                    "day": day,
                    "dur": dur,
                    "cat": m.get("cat") or classify(title, ""),
                    "title": title,
                    "brief": "",
                }
            )

    # team owner 刘春梅/付汪阳
    team = json.loads(
        (REPO / "data_raw" / "overseas_vemory_mtd_2026-07-01.json").read_text(encoding="utf-8")
    )
    want = {12564: "刘春梅", 13365: "付汪阳"}
    for m in team.get("team_meetings") or []:
        uid = m.get("owner_user_id")
        if uid not in want:
            continue
        day = (m.get("start_time") or "")[:10]
        if not ("2026-07-13" <= day <= "2026-07-19"):
            continue
        title = m.get("name") or ""
        dur = int(m.get("duration_seconds") or 0) // 60
        if junk(title, dur):
            continue
        summary = m.get("summary") or ""
        items.append(
            {
                "person": want[uid],
                "dept": "中台",
                "day": day,
                "dur": dur,
                "cat": classify(title, summary),
                "title": title,
                "brief": summary.split("\n")[0][:200],
            }
        )

    seen = set()
    uniq = []
    for it in items:
        k = (it["person"], it["day"], it["title"][:80])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(it)

    by: dict[str, list] = defaultdict(list)
    for it in uniq:
        by[it["person"]].append(it)
    for arr in by.values():
        arr.sort(key=lambda x: x["day"] or "", reverse=True)

    OUT.write_text(json.dumps(dict(by), ensure_ascii=False, indent=2), encoding="utf-8")
    print("people", len(by), "items", len(uniq), "->", OUT)
    for person, arr in sorted(by.items(), key=lambda x: -len(x[1])):
        print(person, len(arr))


if __name__ == "__main__":
    main()
