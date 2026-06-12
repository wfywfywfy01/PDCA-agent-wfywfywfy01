# -*- coding: utf-8 -*-
"""
将日报/周报/月报 JSON 写入 PostgreSQL。

用法:
  python db_writer.py --file ../daily/张三/2026-06-12.json --type daily
  python db_writer.py --stdin --type daily
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_config import db_cursor
from report_io import read_json


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="写入 Cursor 团队日报到 PostgreSQL")
    parser.add_argument("--file", default="", help="JSON 文件路径")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读取 JSON")
    parser.add_argument(
        "--type",
        choices=["daily", "weekly", "monthly"],
        default="daily",
        help="报告类型",
    )
    return parser.parse_args()


def load_payload(args: argparse.Namespace) -> dict[str, Any]:
    """加载 JSON 数据。"""
    if args.stdin:
        return json.loads(sys.stdin.read())
    if args.file:
        return read_json(Path(args.file))
    raise ValueError("必须指定 --file 或 --stdin")


def upsert_daily(report: dict[str, Any]) -> None:
    """写入或更新日报。"""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_reports (
                report_date, username, generated_at, total_sessions, total_turns,
                daily_summary, key_topics, files_modified, raw_json, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s::jsonb, NOW()
            )
            ON CONFLICT (report_date, username)
            DO UPDATE SET
                generated_at = EXCLUDED.generated_at,
                total_sessions = EXCLUDED.total_sessions,
                total_turns = EXCLUDED.total_turns,
                daily_summary = EXCLUDED.daily_summary,
                key_topics = EXCLUDED.key_topics,
                files_modified = EXCLUDED.files_modified,
                raw_json = EXCLUDED.raw_json,
                updated_at = NOW()
            """,
            (
                report["date"],
                report["user"],
                report.get("generated_at"),
                report.get("total_sessions", 0),
                report.get("total_turns", 0),
                report.get("daily_summary", ""),
                report.get("key_topics", []),
                report.get("all_files_modified", []),
                json.dumps(report, ensure_ascii=False),
            ),
        )

        cur.execute(
            "DELETE FROM sessions WHERE report_date = %s AND username = %s",
            (report["date"], report["user"]),
        )
        for session in report.get("sessions", []):
            cur.execute(
                """
                INSERT INTO sessions (
                    report_date, username, session_id, summary, topics, turns,
                    tools_used, files_touched, outcome, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, NOW()
                )
                ON CONFLICT (report_date, username, session_id)
                DO UPDATE SET
                    summary = EXCLUDED.summary,
                    topics = EXCLUDED.topics,
                    turns = EXCLUDED.turns,
                    tools_used = EXCLUDED.tools_used,
                    files_touched = EXCLUDED.files_touched,
                    outcome = EXCLUDED.outcome,
                    updated_at = NOW()
                """,
                (
                    report["date"],
                    report["user"],
                    session.get("id", ""),
                    session.get("summary", ""),
                    session.get("topics", []),
                    session.get("turns", 0),
                    session.get("tools_used", []),
                    session.get("files_touched", []),
                    session.get("outcome", "unknown"),
                ),
            )


def upsert_weekly(report: dict[str, Any]) -> None:
    """写入或更新周报。"""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO weekly_reports (
                week_start, week_end, week_label, username, summary,
                total_sessions, total_turns, top_topics, raw_json, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s::jsonb, NOW()
            )
            ON CONFLICT (week_label, username)
            DO UPDATE SET
                week_start = EXCLUDED.week_start,
                week_end = EXCLUDED.week_end,
                summary = EXCLUDED.summary,
                total_sessions = EXCLUDED.total_sessions,
                total_turns = EXCLUDED.total_turns,
                top_topics = EXCLUDED.top_topics,
                raw_json = EXCLUDED.raw_json,
                updated_at = NOW()
            """,
            (
                report["week_start"],
                report["week_end"],
                report["week_label"],
                report["user"],
                report.get("weekly_summary", ""),
                report.get("total_sessions", 0),
                report.get("total_turns", 0),
                report.get("top_topics", []),
                json.dumps(report, ensure_ascii=False),
            ),
        )


def upsert_monthly(report: dict[str, Any]) -> None:
    """写入或更新月报。"""
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO monthly_reports (
                month_label, username, summary, total_sessions, total_turns,
                top_topics, raw_json, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s::jsonb, NOW()
            )
            ON CONFLICT (month_label, username)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                total_sessions = EXCLUDED.total_sessions,
                total_turns = EXCLUDED.total_turns,
                top_topics = EXCLUDED.top_topics,
                raw_json = EXCLUDED.raw_json,
                updated_at = NOW()
            """,
            (
                report["month"],
                report["user"],
                report.get("monthly_summary", ""),
                report.get("total_sessions", 0),
                report.get("total_turns", 0),
                report.get("top_topics", []),
                json.dumps(report, ensure_ascii=False),
            ),
        )


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    payload = load_payload(args)

    if args.type == "daily":
        upsert_daily(payload)
    elif args.type == "weekly":
        upsert_weekly(payload)
    else:
        upsert_monthly(payload)

    print(f"已写入 PostgreSQL: type={args.type}")


if __name__ == "__main__":
    main()
