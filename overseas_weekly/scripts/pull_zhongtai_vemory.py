# -*- coding: utf-8 -*-
"""拉取海外中台人员本月 Vemory。"""

from __future__ import annotations

import json
import subprocess
import time
from collections import Counter
from pathlib import Path

VERTU = str(Path.home() / "AppData/Roaming/npm/vertu.cmd")
OUT = Path(__file__).resolve().parents[1] / "outputs" / "2026-07_中台_vemory.json"

# 用户指定中台名单
TARGETS = [
    (13848, "张倩"),
    (14461, "刘雪梅"),
    (12564, "刘春梅"),
    (13365, "付汪阳"),
    (14460, "Safae Ben M'hamed"),
    (14344, "王宇彤"),
]


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
            "合同",
            "清关",
            "发货",
            "售后",
        )
    ):
        return "外部会议"
    return "内部会议"


def main() -> None:
    results = []
    for i, (uid, name) in enumerate(TARGETS):
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
            results.append({"name": name, "uid": uid, "status": "error", "err": text[:160]})
            print(" error", flush=True)
            continue
        payload = json.loads(text[j:])
        ms = payload.get("meetings") or []
        cats: Counter = Counter()
        items = []
        for m in ms:
            title = m.get("name") or ""
            if any(k in title for k in ("录音连线", "内容极少", "转录内容不足", "简短开场")):
                continue
            cat = classify(title, m.get("summary") or "")
            cats[cat] += 1
            summ = (m.get("summary") or "").split("\n")[0][:140]
            items.append(
                {
                    "day": (m.get("start_time") or "")[:10],
                    "cat": cat,
                    "title": title,
                    "dur": int(m.get("duration_seconds") or 0) // 60,
                    "summary": summ,
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
        print(" ok", len(items), dict(cats), flush=True)

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)


if __name__ == "__main__":
    main()
