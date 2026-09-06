# -*- coding: utf-8 -*-
"""《事项跟进表》导入：三大板块 → 手动项目；子任务 → 待办（按人拆分）。

数据源：data/sept_followup_table.json（由 xlsx 转换，日期/负责人已规范化）。
幂等：项目按 key（fup-car/fup-newbie/fup-senior）；待办按
source='followup-table' + title + owner 去重，已存在只刷新截止日与项目，
不动状态；多人负责的待办按人拆分（每人收到自己的催办）。

用法（在 pdca-workbench 目录）：
    python scripts/import_followup_table.py           # 实际导入
    python scripts/import_followup_table.py --dry-run # 只统计预览，不改库
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from app.database import check_db_connection, get_engine, init_db  # noqa: E402
from app.models.pdca_task import PdcaTask  # noqa: E402
from app.models.todo_project import TodoProject  # noqa: E402

SOURCE_TAG = "followup-table"
DATA_FILE = ROOT / "scripts" / "sept_followup_table.json"

PROJECT_COORDINATORS = {
    "fup-car": "谢涛",
    "fup-newbie": "邓琳莹",
    "fup-senior": "刘春梅",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不改库")
    args = parser.parse_args()

    if not DATA_FILE.exists():
        print(f"数据文件不存在: {DATA_FILE}")
        return 1
    payload = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    specs = payload["projects"]
    items = payload["items"]

    if not check_db_connection():
        print("无法连接 PostgreSQL，请设置 PDCA_DATABASE_URL 后重试")
        return 1

    # 先确保 schema 补丁（如 todo_projects.kind）已应用，再导入
    init_db()

    projects_created = 0
    projects_updated = 0
    tasks_created = 0
    tasks_updated = 0
    by_owner: dict[str, int] = defaultdict(int)

    with Session(get_engine()) as session:
        existing_projects = {
            row.key: row
            for row in session.exec(
                select(TodoProject).where(
                    TodoProject.key.in_([p["key"] for p in specs])
                )
            ).all()
        }
        projects: dict[str, TodoProject] = {}
        for spec in specs:
            row = existing_projects.get(spec["key"])
            coordinator = PROJECT_COORDINATORS.get(spec["key"], "")
            if row is None:
                row = TodoProject(
                    key=spec["key"],
                    name=spec["name"],
                    kind="manual",
                    status="新建",
                    executors="[]",
                    coordinator=coordinator,
                )
                session.add(row)
                session.flush()
                projects_created += 1
            else:
                row.name = spec["name"]
                row.coordinator = coordinator
                session.add(row)
                projects_updated += 1
            projects[spec["key"]] = row

        existing_tasks = {
            (row.title, row.owner): row
            for row in session.exec(
                select(PdcaTask).where(PdcaTask.source == SOURCE_TAG)
            ).all()
        }
        seen_new: set[tuple] = set()
        skipped_no_owner = 0
        for section_key, section_items in items.items():
            project = projects.get(section_key)
            if project is None:
                continue
            for item in section_items:
                owners = item.get("owners") or []
                if not owners:
                    skipped_no_owner += 1
                    continue
                title = item["title"]
                for owner in owners:
                    key = (title, owner)
                    row = existing_tasks.get(key)
                    if row is None and key not in seen_new:
                        row = PdcaTask(
                            task_date=item["task_date"],
                            title=title,
                            owner=owner,
                            status="pending",
                            priority="normal",
                            source=SOURCE_TAG,
                            meeting_name=item.get("group", ""),
                            project_id=project.id,
                        )
                        session.add(row)
                        seen_new.add(key)
                        tasks_created += 1
                    elif row is not None:
                        row.task_date = item["task_date"]
                        row.project_id = project.id
                        row.meeting_name = item.get("group", "")
                        session.add(row)
                        tasks_updated += 1
                    by_owner[owner] += 1

        # 项目成员（executors 展示用）
        owners_by_project: dict[int, set] = defaultdict(set)
        for row in session.exec(
            select(PdcaTask).where(PdcaTask.source == SOURCE_TAG)
        ).all():
            if row.owner and row.project_id:
                owners_by_project[row.project_id].add(row.owner.strip())
        for spec in specs:
            row = projects[spec["key"]]
            executors = json.dumps(
                sorted(owners_by_project.get(row.id, set())), ensure_ascii=False
            )
            if row.executors != executors:
                row.executors = executors
                session.add(row)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    total_groups = sum(len(v) for v in items.values())
    print(f"项目：新建 {projects_created} / 刷新 {projects_updated}")
    print(
        f"待办：新建 {tasks_created} / 刷新 {tasks_updated}"
        f"（共 {total_groups} 组、按人拆分 {sum(by_owner.values())} 条、"
        f"无负责人跳过 {skipped_no_owner} 条）"
    )
    print("按负责人分布：")
    for name, count in sorted(by_owner.items(), key=lambda kv: -kv[1]):
        print(f"  {count:3d}  {name}")
    print("模式：" + ("dry-run（未落库）" if args.dry_run else "已提交"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
