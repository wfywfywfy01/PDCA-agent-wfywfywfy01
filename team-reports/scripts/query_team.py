# -*- coding: utf-8 -*-
"""
主管侧查询 CLI（按组织架构过滤可见范围）。

用法:
  python query_team.py --scope
  python query_team.py --status
  python query_team.py --today
  python query_team.py --viewer May --ranking --month 2026-06
  python query_team.py --user Viki --week
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_config import db_cursor
from permissions import assert_can_view, describe_scope, get_visible_usernames, load_team_members
from report_io import get_username


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="查询 Cursor 团队日报（带权限过滤）")
    parser.add_argument("--viewer", default="", help="查看者 username，默认读取本地 user.json")
    parser.add_argument("--scope", action="store_true", help="查看当前账号可见范围")
    parser.add_argument("--today", action="store_true", help="查看可见范围内今日摘要")
    parser.add_argument("--user", default="", help="指定用户名")
    parser.add_argument("--week", action="store_true", help="查看本周详情")
    parser.add_argument("--month", default="", help="指定月份，如 2026-06")
    parser.add_argument("--ranking", action="store_true", help="查看工作量排行")
    parser.add_argument("--topics", action="store_true", help="查看高频主题")
    parser.add_argument("--status", action="store_true", help="查看可见范围内提交状态")
    parser.add_argument("--date", default="", help="指定日期 YYYY-MM-DD")
    return parser.parse_args()


def resolve_viewer(args: argparse.Namespace) -> str:
    """解析查看者身份。"""
    viewer = args.viewer.strip() or get_username()
    return viewer


def fetch_rows(query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """执行查询并返回结果。"""
    with db_cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def print_table(title: str, headers: list[str], rows: list[tuple[Any, ...]]) -> None:
    """打印简单表格。"""
    print(f"\n== {title} ==")
    if not rows:
        print("（无数据）")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    header_line = " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers))
    print(header_line)
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(str(cell).ljust(widths[i]) for i, cell in enumerate(row)))


def cmd_scope(viewer: str) -> None:
    """打印查看者权限范围。"""
    info = describe_scope(viewer)
    print(f"\n查看者: {info['viewer']}")
    print(f"角色: {info['role_label']} ({info['role']})")
    print(f"可见人数: {info['visible_count']}")
    print("可见成员:", ", ".join(info["visible_usernames"]))


def cmd_today(viewer: str, args: argparse.Namespace) -> None:
    """查询可见范围内今日摘要。"""
    target = args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    visible = get_visible_usernames(viewer)
    rows = fetch_rows(
        """
        SELECT username, total_sessions, total_turns, daily_summary
        FROM daily_reports
        WHERE report_date = %s
          AND username = ANY(%s)
        ORDER BY total_turns DESC, username
        """,
        (target, visible),
    )
    print_table(f"{viewer} 可见 · {target} 摘要", ["用户", "会话数", "轮次", "摘要"], rows)


def cmd_user_week(viewer: str, args: argparse.Namespace) -> None:
    """查询某人本周详情。"""
    if not args.user:
        raise ValueError("请使用 --user 指定用户名")
    assert_can_view(viewer, args.user)
    rows = fetch_rows(
        """
        SELECT report_date, total_sessions, total_turns, daily_summary
        FROM daily_reports
        WHERE username = %s
          AND report_date >= date_trunc('week', CURRENT_DATE)::date
        ORDER BY report_date
        """,
        (args.user,),
    )
    print_table(f"{args.user} 本周详情", ["日期", "会话数", "轮次", "摘要"], rows)


def cmd_ranking(viewer: str, args: argparse.Namespace) -> None:
    """查询月度工作量排行（可见范围）。"""
    month_label = args.month or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    visible = get_visible_usernames(viewer)
    rows = fetch_rows(
        """
        SELECT username, SUM(total_sessions) AS sessions, SUM(total_turns) AS turns
        FROM daily_reports
        WHERE to_char(report_date, 'YYYY-MM') = %s
          AND username = ANY(%s)
        GROUP BY username
        ORDER BY turns DESC, sessions DESC, username
        """,
        (month_label, visible),
    )
    print_table(f"{viewer} 可见 · {month_label} 工作量排行", ["用户", "会话数", "轮次"], rows)


def cmd_topics(viewer: str, args: argparse.Namespace) -> None:
    """查询可见范围内高频主题。"""
    visible = get_visible_usernames(viewer)
    if args.week:
        rows = fetch_rows(
            """
            SELECT topic, COUNT(*) AS freq
            FROM (
                SELECT unnest(key_topics) AS topic
                FROM daily_reports
                WHERE report_date >= date_trunc('week', CURRENT_DATE)::date
                  AND username = ANY(%s)
            ) t
            GROUP BY topic
            ORDER BY freq DESC, topic
            LIMIT 15
            """,
            (visible,),
        )
        print_table(f"{viewer} 可见 · 本周高频主题", ["主题", "次数"], rows)
        return

    month_label = args.month or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    rows = fetch_rows(
        """
        SELECT topic, COUNT(*) AS freq
        FROM (
            SELECT unnest(key_topics) AS topic
            FROM daily_reports
            WHERE to_char(report_date, 'YYYY-MM') = %s
              AND username = ANY(%s)
        ) t
        GROUP BY topic
        ORDER BY freq DESC, topic
        LIMIT 15
        """,
        (month_label, visible),
    )
    print_table(f"{viewer} 可见 · {month_label} 高频主题", ["主题", "次数"], rows)


def cmd_status(viewer: str, args: argparse.Namespace) -> None:
    """查看可见范围内提交状态。"""
    target = args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    members = get_visible_usernames(viewer)
    if not members:
        raise ValueError("可见成员列表为空")

    rows = fetch_rows(
        """
        SELECT username, total_sessions, total_turns, LEFT(daily_summary, 80)
        FROM daily_reports
        WHERE report_date = %s
          AND username = ANY(%s)
        """,
        (target, members),
    )
    submitted = {row[0]: row for row in rows}
    table_rows: list[tuple[Any, ...]] = []
    for username in members:
        if username in submitted:
            _, sessions, turns, summary = submitted[username]
            table_rows.append((username, "已提交", sessions, turns, summary))
        else:
            table_rows.append((username, "未提交", 0, 0, ""))

    print_table(
        f"{viewer} 可见 · {target} 提交状态",
        ["用户", "状态", "会话数", "轮次", "摘要"],
        table_rows,
    )


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    viewer = resolve_viewer(args)

    if args.scope:
        cmd_scope(viewer)
    elif args.status:
        cmd_status(viewer, args)
    elif args.today or (args.date and not args.user):
        cmd_today(viewer, args)
    elif args.user and args.week:
        cmd_user_week(viewer, args)
    elif args.ranking:
        cmd_ranking(viewer, args)
    elif args.topics or args.week:
        cmd_topics(viewer, args)
    else:
        cmd_scope(viewer)


if __name__ == "__main__":
    main()
