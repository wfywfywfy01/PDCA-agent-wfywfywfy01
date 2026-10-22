# -*- coding: utf-8 -*-
"""在能访问 Google 的机器上拉取 GA4，并写入 PDCA 容器里的快照。

杭州服务器访问不了 googleapis.com，也访问不了 10.140.1.83。
本脚本跑在能连 Google、且能访问 Docker API 的电脑上。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DOC_ID = "8c6bf793-8ac7-4801-bf04-551953fd789e"
CONTAINER = os.environ.get("PDCA_GROWTH_DOCKER_CONTAINER", "pdca-workbench")
REMOTE_DIR = "/app/data/runtime"


def _topics_from_sheet(payload: dict) -> str:
    """云文档智能表格 → title\\turl。"""
    sheet = next(iter(payload["workbook"]["sheets"].values()))
    cells = sheet.get("cellData") or {}
    lines = ["title\turl"]
    for key in sorted(cells, key=lambda item: int(item)):
        if key == "0":
            continue
        row = cells[key]

        def cell(col: str) -> str:
            item = row.get(col) or {}
            value = item.get("v") if isinstance(item, dict) else ""
            return "" if value is None else str(value).replace("\t", " ").replace("\n", " ").strip()

        title, url = cell("1"), cell("7")
        if not title:
            continue
        if not url.startswith("http"):
            url = ""
        lines.append(f"{title}\t{url}")
    return "\n".join(lines) + "\n"


def refresh_topics(path: Path) -> None:
    """用 vps-work 读选题表。失败就保留原文件。"""
    try:
        raw = subprocess.check_output(
            ["vps-work", "docs", "+sheet-get", "--doc-id", DOC_ID],
            stderr=subprocess.DEVNULL,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return
    text = raw.decode("utf-8") if raw[:2] != b"\xff\xfe" else raw.decode("utf-16")
    path.write_text(_topics_from_sheet(json.loads(text)), encoding="utf-8")


def push(local: Path, remote_name: str) -> None:
    subprocess.check_call(
        ["docker", "cp", str(local), f"{CONTAINER}:{REMOTE_DIR}/{remote_name}"],
        timeout=60,
    )


def main() -> None:
    from app.growth.ga4 import _live_briefing, _write_snapshot

    topics = Path(os.environ["PDCA_GROWTH_SEO_TOPICS_FILE"])
    snapshot = Path(os.environ["PDCA_GROWTH_GA4_SNAPSHOT"])
    topics.parent.mkdir(parents=True, exist_ok=True)
    refresh_topics(topics)
    os.environ["PDCA_GROWTH_GA4_SNAPSHOT"] = str(snapshot)
    payload = _live_briefing()
    payload["stale"] = False
    _write_snapshot(payload)
    push(snapshot, "ga4-snapshot.json")
    if topics.is_file():
        push(topics, "seo-topics.tsv")
    print(f"synced top={payload['top']} topics={payload['topics']} bytes={snapshot.stat().st_size}")


if __name__ == "__main__":
    main()
