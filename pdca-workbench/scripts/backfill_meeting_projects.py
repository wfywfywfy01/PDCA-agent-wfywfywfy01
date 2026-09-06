# -*- coding: utf-8 -*-
"""存量待办回填：把未挂项目的待办收敛到项目（关键词优先，会议主题兜底）。

幂等：已有 project_id 的行不动，可反复执行。
执行环境：pdca-workbench 目录（读 .env 的 PDCA_DATABASE_URL）。

用法：
    python scripts/backfill_meeting_projects.py           # 实际回填
    python scripts/backfill_meeting_projects.py --dry-run # 只统计不动库
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from app.database import check_db_connection, get_engine, init_db  # noqa: E402
from app.models.pdca_task import PdcaTask  # noqa: E402
from app.models.todo_project import TodoProject  # noqa: E402
from app.todos.projects import (  # noqa: E402
    auto_close_meeting_projects,
    ensure_meeting_project,
    ensure_projects,
    match_project,
    refresh_meeting_project_members,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不改库")
    args = parser.parse_args()

    if not check_db_connection():
        print("无法连接 PostgreSQL，请设置 PDCA_DATABASE_URL 后重试")
        return 1

    # 先确保 schema 补丁（如 todo_projects.kind）已应用，再回填
    init_db()

    with Session(get_engine()) as session:
        project_by_key, _ = ensure_projects(session)
        rows = list(
            session.exec(select(PdcaTask).where(PdcaTask.project_id.is_(None))).all()
        )
        by_kind: dict[str, int] = {"keyword": 0, "meeting": 0, "left": 0}
        for row in rows:
            rule = match_project(row.title)
            pid = None
            if rule and rule["key"] in project_by_key:
                pid = project_by_key[rule["key"]].id
                by_kind["keyword"] += 1
            elif row.source == "vemory" and row.meeting_name:
                project = ensure_meeting_project(session, row.meeting_name)
                if project is not None:
                    if project.status == "已闭环":
                        project.status = "跟进中"
                    pid = project.id
                    by_kind["meeting"] += 1
            if pid is None:
                by_kind["left"] += 1
                continue
            row.project_id = pid
            session.add(row)
        members_updated = refresh_meeting_project_members(session)
        projects_closed = auto_close_meeting_projects(session)
        meeting_total = len(
            list(
                session.exec(
                    select(TodoProject).where(TodoProject.kind == "meeting")
                ).all()
            )
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(f"未挂项目待办 {len(rows)} 行：")
    print(f"  → 关键词项目 {by_kind['keyword']} 行")
    print(f"  → 会议主题项目 {by_kind['meeting']} 行（会议项目共 {meeting_total} 个）")
    print(f"  → 保持散单 {by_kind['left']} 行")
    print(
        f"会议项目成员刷新 {members_updated} 个 / 自动闭环 {projects_closed} 个"
    )
    print("模式：" + ("dry-run（未落库）" if args.dry_run else "已提交"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
