# -*- coding: utf-8 -*-
"""
按月聚合 weekly JSON 报告。

用法:
  python aggregate_monthly.py --month 2026-06
  python aggregate_monthly.py --write-db
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_writer import upsert_monthly
from report_io import iter_weekly_json_files, read_json, team_reports_root, write_json, write_markdown


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="聚合 Cursor 团队月报")
    parser.add_argument("--month", default="", help="月份标签，如 2026-06")
    parser.add_argument("--username", default="", help="仅聚合指定用户")
    parser.add_argument("--write-db", action="store_true", help="同步写入 PostgreSQL")
    return parser.parse_args()


def resolve_month(args: argparse.Namespace) -> str:
    """解析目标月份。"""
    if args.month:
        return args.month
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")


def list_usernames(filter_username: str = "") -> list[str]:
    """列出 weekly 目录下的用户名。"""
    if filter_username:
        return [filter_username]
    weekly_root = team_reports_root() / "weekly"
    if not weekly_root.exists():
        return []
    return sorted(path.name for path in weekly_root.iterdir() if path.is_dir())


def aggregate_user_month(username: str, month_label: str) -> dict[str, Any]:
    """聚合单个用户的月报。"""
    weekly_files = iter_weekly_json_files(team_reports_root() / "weekly" / username)
    selected: list[dict[str, Any]] = []
    for file_path in weekly_files:
        report = read_json(file_path)
        week_start = report.get("week_start", "")
        if week_start.startswith(month_label):
            selected.append(report)

    total_sessions = sum(item.get("total_sessions", 0) for item in selected)
    total_turns = sum(item.get("total_turns", 0) for item in selected)
    topic_counter: Counter[str] = Counter()
    weekly_breakdown: list[dict[str, Any]] = []

    for report in sorted(selected, key=lambda item: item.get("week_start", "")):
        weekly_breakdown.append(
            {
                "week_label": report.get("week_label", ""),
                "week_start": report.get("week_start", ""),
                "week_end": report.get("week_end", ""),
                "total_sessions": report.get("total_sessions", 0),
                "total_turns": report.get("total_turns", 0),
                "weekly_summary": report.get("weekly_summary", ""),
            }
        )
        for topic in report.get("top_topics", []):
            topic_counter[topic] += 1

    if weekly_breakdown:
        monthly_summary = "\n".join(
            f"- {item['week_label']}：{item['weekly_summary'].splitlines()[0][:100]}"
            for item in weekly_breakdown
        )
    else:
        monthly_summary = "本月暂无 Cursor 周报记录。"

    return {
        "month": month_label,
        "user": username,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "total_sessions": total_sessions,
        "total_turns": total_turns,
        "weekly_breakdown": weekly_breakdown,
        "top_topics": [topic for topic, _ in topic_counter.most_common(12)],
        "monthly_summary": monthly_summary,
    }


def render_monthly_markdown(report: dict[str, Any]) -> str:
    """渲染月报 Markdown。"""
    lines = [
        f"# Cursor 月报 — {report['user']} — {report['month']}",
        "",
        f"- 会话数：{report['total_sessions']}",
        f"- 对话轮次：{report['total_turns']}",
        "",
        "## 本月摘要",
        "",
        report.get("monthly_summary", ""),
        "",
        "## 高频主题",
        "",
    ]
    for topic in report.get("top_topics", []):
        lines.append(f"- {topic}")
    lines.extend(["", "## 每周分布", ""])
    for item in report.get("weekly_breakdown", []):
        lines.append(
            f"- {item['week_label']}：{item['total_sessions']} 会话 / {item['total_turns']} 轮次"
        )
    return "\n".join(lines)


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    month_label = resolve_month(args)
    usernames = list_usernames(args.username.strip())

    for username in usernames:
        report = aggregate_user_month(username, month_label)
        out_dir = team_reports_root() / "monthly" / username
        json_path = out_dir / f"{month_label}.json"
        md_path = out_dir / f"{month_label}.md"
        write_json(json_path, report)
        write_markdown(md_path, render_monthly_markdown(report))
        if args.write_db:
            upsert_monthly(report)
        print(f"已生成月报: {json_path}")


if __name__ == "__main__":
    main()
