# -*- coding: utf-8 -*-
"""督战证据日报 CLI（固定测试流程）：收集全部证据 → 单文件 HTML 到「督战官文件」目录。

实现体在 app/evidence_report.py（同一份代码也给 07:30 定时任务用）。
只读，不发任何消息。

    python scripts/evidence_report.py --day 2026-09-18
    python scripts/evidence_report.py --day 2026-09-18 --no-images
    python scripts/evidence_report.py --day 2026-09-18 --images 40 --out D:/x.html

约定：早上 8 点那份由容器定时任务生成到 data/exports/evidence/，
本机计划任务再拉一份到「督战官文件」目录（scripts/pull_evidence_to_desktop.ps1）。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app import evidence_report  # noqa: E402 — 需要先补 sys.path


def drop_dir() -> Path:
    """督战官产出物目录（2026-09-23 用户指定：一律不准放桌面）。

    可用 PDCA_DROP_DIR 覆盖，支持 {month} 占位符；默认跟随当月目录。
    """
    month = datetime.now().month
    env = os.environ.get("PDCA_DROP_DIR", "").strip()
    if env:
        return Path(env.replace("{month}", str(month)))
    return Path(r"D:\Vertu\data\excel\26年数据") / f"{month}月" / "部门工作画像" / "督战官文件"


def main() -> int:
    parser = argparse.ArgumentParser(description="督战证据日报（HTML，只读）")
    parser.add_argument("--day", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d"))
    parser.add_argument("--out", default="")
    parser.add_argument("--images", type=int, default=24, help="最多内嵌多少张 MTO 原图")
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    evidence_report.load_env_file()
    limit = 0 if args.no_images else max(args.images, 0)
    ledger = evidence_report.collect(args.day, limit)
    html_text = evidence_report.build_html(args.day, ledger)
    out = Path(args.out) if args.out else drop_dir() / f"督战证据_{args.day}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    print(f"HTML: {out} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"人数 {len(ledger.get('people') or [])}｜耗时 {ledger.get('_elapsed')} 秒")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())