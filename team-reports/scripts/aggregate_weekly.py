# -*- coding: utf-8 -*-
"""
按周聚合 daily JSON 报告。

用法:
  python aggregate_weekly.py --week 2026-W24
  python aggregate_weekly.py --date 2026-06-12
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_writer import upsert_weekly
from report_io import (
    iter_daily_json_files,
    read_json,
    team_reports_root,
    write_json,
    write_markdown,
)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="聚合 Cursor 团队周报")
    parser.add_argument("--week", default="", help="ISO 周标签，如 2026-W24")
    parser.add_argument("--date", default="", help="任意日期，自动定位所在周")
    parser.add_argument("--username", default="", help="仅聚合指定用户")
    parser.add_argument("--write-db", action="store_true", help="同步写入 PostgreSQL")
    return parser.parse_args()


def iso_week_label(target: date) -> str:
    """生成 ISO 周标签。"""
    year, week, _ = target.isocalendar()
    return f"{year}-W{week:02d}"


def week_range(target: date) -> tuple[date, date]:
    """返回 ISO 周的起止日期（周一至周日）。"""
    start = target - timedelta(days=target.weekday())
    end = start + timedelta(days=6)
    return start, end


def resolve_week(args: argparse.Namespace) -> tuple[str, date, date]:
    """解析目标周。"""
    if args.week:
        year_str, week_str = args.week.split("-W")
        year = int(year_str)
        week = int(week_str)
        start = date.fromisocalendar(year, week, 1)
        end = date.fromisocalendar(year, week, 7)
        return iso_week_label(start), start, end

    if args.date:
        if args.date.lower() == "today":
            target = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        else:
            target = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target = datetime.now(ZoneInfo("Asia/Shanghai")).date()

    start, end = week_range(target)
    return iso_week_label(start), start, end


def aggregate_user_week(
    username: str,
    week_start: date,
    week_end: date,
    week_label: str,
) -> dict[str, Any]:
    """聚合单个用户的周报。"""
    daily_files = iter_daily_json_files(team_reports_root() / "daily" / username)
    selected: list[dict[str, Any]] = []
    for file_path in daily_files:
        report = read_json(file_path)
        report_date = datetime.strptime(report["date"], "%Y-%m-%d").date()
        if week_start <= report_date <= week_end:
            selected.append(report)

    total_sessions = sum(item.get("total_sessions", 0) for item in selected)
    total_turns = sum(item.get("total_turns", 0) for item in selected)
    topic_counter: Counter[str] = Counter()
    files_counter: Counter[str] = Counter()
    daily_breakdown: list[dict[str, Any]] = []

    for report in sorted(selected, key=lambda item: item["date"]):
        daily_breakdown.append(
            {
                "date": report["date"],
                "total_sessions": report.get("total_sessions", 0),
                "total_turns": report.get("total_turns", 0),
                "daily_summary": report.get("daily_summary", ""),
            }
        )
        for topic in report.get("key_topics", []):
            topic_counter[topic] += 1
        for file_path in report.get("all_files_modified", []):
            files_counter[file_path] += 1

    if daily_breakdown:
        weekly_summary = "\n".join(
            f"- {item['date']}：{item['daily_summary'].splitlines()[0][:100]}"
            for item in daily_breakdown
        )
    else:
        weekly_summary = "本周暂无 Cursor 日报记录。"

    return {
        "week_label": week_label,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "user": username,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "total_sessions": total_sessions,
        "total_turns": total_turns,
        "daily_breakdown": daily_breakdown,
        "top_topics": [topic for topic, _ in topic_counter.most_common(10)],
        "top_files": [path for path, _ in files_counter.most_common(10)],
        "weekly_summary": weekly_summary,
    }


def render_weekly_markdown(report: dict[str, Any]) -> str:
    """渲染周报 Markdown。"""
    lines = [
        f"# Cursor 周报 — {report['user']} — {report['week_label']}",
        "",
        f"- 周期：{report['week_start']} ~ {report['week_end']}",
        f"- 会话数：{report['total_sessions']}",
        f"- 对话轮次：{report['total_turns']}",
        "",
        "## 本周摘要",
        "",
        report.get("weekly_summary", ""),
        "",
        "## 高频主题",
        "",
    ]
    for topic in report.get("top_topics", []):
        lines.append(f"- {topic}")
    lines.extend(["", "## 每日分布", ""])
    for item in report.get("daily_breakdown", []):
        lines.append(
            f"- {item['date']}：{item['total_sessions']} 会话 / {item['total_turns']} 轮次"
        )
    return "\n".join(lines)


def list_usernames(filter_username: str = "") -> list[str]:
    """列出 daily 目录下的用户名。"""
    if filter_username:
        return [filter_username]
    daily_root = team_reports_root() / "daily"
    if not daily_root.exists():
        return []
    return sorted(path.name for path in daily_root.iterdir() if path.is_dir())


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    week_label, week_start, week_end = resolve_week(args)
    usernames = list_usernames(args.username.strip())

    for username in usernames:
        report = aggregate_user_week(username, week_start, week_end, week_label)
        out_dir = team_reports_root() / "weekly" / username
        json_path = out_dir / f"{week_label}.json"
        md_path = out_dir / f"{week_label}.md"
        write_json(json_path, report)
        write_markdown(md_path, render_weekly_markdown(report))
        if args.write_db:
            upsert_weekly(report)
        print(f"已生成周报: {json_path}")


if __name__ == "__main__":
    main()
