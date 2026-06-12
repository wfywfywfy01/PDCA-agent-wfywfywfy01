# -*- coding: utf-8 -*-
"""
一键发布日报：解析 transcripts -> 写 JSON/Markdown -> 写入 PostgreSQL -> 可选 git push。

用法:
  python publish_daily.py --date today
  python publish_daily.py --date 2026-06-12 --git-push
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from db_writer import upsert_daily
from parse_transcripts import (
    build_daily_report,
    collect_session_files,
    discover_transcripts_dir,
    infer_topics,
    merge_session_parts,
    parse_session_file,
    resolve_target_date,
)
from report_io import daily_dir, get_username, render_daily_markdown, team_reports_root, write_json, write_markdown


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="发布 Cursor 团队日报")
    parser.add_argument("--date", default="today", help="目标日期")
    parser.add_argument("--workspace", default="", help="工作区路径")
    parser.add_argument("--username", default="", help="用户名")
    parser.add_argument("--timezone", default="Asia/Shanghai", help="时区")
    parser.add_argument("--git-push", action="store_true", help="提交并 push 到远程仓库")
    parser.add_argument("--skip-db", action="store_true", help="跳过 PostgreSQL 写入")
    return parser.parse_args()


def refine_summary_with_ai(report: dict) -> dict:
    """
    精炼 daily_summary，过滤噪音会话，输出主管可读格式。
    Skill 运行时 Agent 可进一步覆盖 daily_summary 字段。
    """
    raw_sessions = report.pop("_raw_sessions", [])

    skip_markers = ("去水印", "未命名会话")
    useful_sessions = []
    for session in raw_sessions:
        summary = session.get("summary", "")
        if session.get("turns", 0) == 0 and summary == "未命名会话":
            continue
        if any(marker in summary for marker in skip_markers):
            continue
        useful_sessions.append(session)

    if useful_sessions:
        bullets = []
        for session in useful_sessions[:8]:
            summary = session.get("summary", "未命名任务")
            tools = ", ".join(session.get("tools_used", [])[:5]) or "无"
            files = session.get("files_touched", [])
            bullets.append(
                f"- 【{summary[:60]}】工具: {tools}；涉及文件: {len(files)} 个；状态: {session.get('outcome', 'unknown')}"
            )
        report["daily_summary"] = "今日 Cursor 工作摘要：\n" + "\n".join(bullets)
        report["key_topics"] = infer_topics(
            *[session.get("summary", "") for session in useful_sessions]
        )
    elif raw_sessions:
        report["daily_summary"] = "今日 Cursor 会话较少，或未形成可汇总的主线任务。"
    else:
        report["daily_summary"] = "今日未检测到 Cursor 会话记录。"

    return report


def git_push(report_paths: list[Path] | None = None) -> None:
    """提交并推送 team-reports 备份。"""
    from git_sync import git_sync

    month_label = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    if report_paths:
        first = report_paths[0].as_posix().replace("\\", "/")
        message = f"chore(team-reports): daily report {first}"
    else:
        message = f"chore(team-reports): sync daily {month_label}"
    git_sync(message, push=True)


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    target_date = resolve_target_date(args.date, args.timezone)
    username = args.username.strip() or get_username()
    transcripts_dir = discover_transcripts_dir(args.workspace)

    sessions = []
    for main_file, subagent_files in collect_session_files(transcripts_dir):
        main_parsed = parse_session_file(main_file, target_date, args.timezone)
        extra_parsed = [
            parse_session_file(path, target_date, args.timezone)
            for path in subagent_files
        ]
        extra_parsed = [item for item in extra_parsed if item]
        merged = merge_session_parts(main_parsed, extra_parsed)
        if merged:
            sessions.append(merged)

    report = build_daily_report(
        sessions,
        target_date,
        username,
        args.timezone,
        Path(args.workspace).resolve() if args.workspace else team_reports_root().parent,
    )
    report = refine_summary_with_ai(report)

    out_dir = daily_dir(username)
    json_path = out_dir / f"{target_date.isoformat()}.json"
    md_path = out_dir / f"{target_date.isoformat()}.md"
    write_json(json_path, report)
    write_markdown(md_path, render_daily_markdown(report))

    if not args.skip_db:
        upsert_daily(report)

    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False))

    if args.git_push:
        git_push([json_path, md_path])


if __name__ == "__main__":
    main()
