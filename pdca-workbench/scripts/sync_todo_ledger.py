# -*- coding: utf-8 -*-
"""待办台账同步：把 pdca_tasks 的闭环状态写入 VPS 智能表格。

表结构（A 列起）：事项 | 板块项目 | 负责人 | 最近催办 | 是否领取 |
领取时间 | 结束时间 | 进度(回复) | 得分
- 文档 ID：PDCA_TODO_LEDGER_DOC_ID 环境变量；首次创建时写回
  todo_group_state.ledger_doc_id / ledger_sheet_id。
- 幂等：每次全量重写数据区（表头 + 行），行数上限 500。
用法：python scripts/sync_todo_ledger.py [--dry-run] [--create]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from app.database import check_db_connection, get_engine, init_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.models.pdca_task import PdcaTask  # noqa: E402
from app.models.todo_group_state import TodoGroupState  # noqa: E402
from app.statuses import is_done as _is_done  # noqa: E402
from app.todos.owners import split_owners  # noqa: E402
from app.todos.reply_signals import classify_reply  # noqa: E402
from app.vertu.client import run_vertu_sync, run_vertu_sync_json  # noqa: E402

HEADERS = [
    "事项", "板块项目", "OKR", "负责人", "最近催办", "是否领取",
    "领取时间", "结束时间", "进度(回复)", "得分",
]

MAX_DATA_ROWS = 500


def get_existing_doc() -> tuple[str, str]:
    """只读返回已有台账位置；不会创建文档或修改数据库。"""
    doc_id = os.environ.get("PDCA_TODO_LEDGER_DOC_ID", "").strip()
    sheet_id = "sheet-1"
    if not doc_id:
        with Session(get_engine()) as session:
            states = {
                row.key: row.value
                for row in session.exec(
                    select(TodoGroupState).where(
                        TodoGroupState.key.in_(["ledger_doc_id", "ledger_sheet_id"])
                    )
                ).all()
            }
        doc_id = states.get("ledger_doc_id", "")
        sheet_id = states.get("ledger_sheet_id", sheet_id) or sheet_id
    return doc_id, sheet_id


def get_or_create_doc(create: bool = False) -> tuple[str, str]:
    """返回台账位置；仅显式 --create 时允许创建外部文档。"""
    doc_id, sheet_id = get_existing_doc()
    if doc_id:
        return doc_id, sheet_id
    if not create:
        raise RuntimeError("未配置 PDCA_TODO_LEDGER_DOC_ID；如需首次创建请显式使用 --create")
    payload = run_vertu_sync_json(
        ["docs", "+create", "--type", "sheet", "--title", "PDCA 待办台账"],
        timeout=30.0,
    )
    doc = (payload or {}).get("doc") if isinstance(payload, dict) else None
    if not isinstance(doc, dict) or not doc.get("id"):
        raise RuntimeError("创建台账智能表格失败")
    doc_id = doc["id"]
    with Session(get_engine()) as session:
        for key, value in (("ledger_doc_id", doc_id), ("ledger_sheet_id", "sheet-1")):
            row = session.exec(
                select(TodoGroupState).where(TodoGroupState.key == key)
            ).first()
            if row is None:
                session.add(TodoGroupState(key=key, value=value))
            else:
                row.value = value
                session.add(row)
        session.commit()
    return doc_id, "sheet-1"


def _state_int(key: str) -> int:
    with Session(get_engine()) as session:
        row = session.exec(select(TodoGroupState).where(TodoGroupState.key == key)).first()
    try:
        return max(int(row.value), 0) if row else 0
    except (TypeError, ValueError):
        return 0


def _set_state_value(key: str, value: str) -> None:
    with Session(get_engine()) as session:
        row = session.exec(select(TodoGroupState).where(TodoGroupState.key == key)).first()
        if row is None:
            session.add(TodoGroupState(key=key, value=value))
        else:
            row.value = value
            row.updated_at = datetime.utcnow()
            session.add(row)
        session.commit()


def build_updates(rows: list[list[str]], previous_row_count: int = 0) -> list[dict[str, str]]:
    """生成完整矩形覆盖；历史多余行以空值清除，超限则整体拒绝。"""
    if len(rows) > MAX_DATA_ROWS:
        raise RuntimeError(f"台账数据 {len(rows)} 行超过安全上限 {MAX_DATA_ROWS}，未写入")
    clear_count = max(previous_row_count - len(rows), 0)
    matrix = [HEADERS] + rows + [[""] * len(HEADERS) for _ in range(clear_count)]
    return [
        {"cell": f"{chr(65 + col)}{row_index + 1}", "value": value}
        for row_index, row in enumerate(matrix)
        for col, value in enumerate(row)
    ]


def build_rows(today: str) -> list[list[str]]:
    """按得分升序输出行（低分/风险在上）。催办排除名单不进台账。"""
    skip_names = {
        name.strip().casefold()
        for name in get_settings().todo_remind_skip_owners
        if name.strip()
    }
    with Session(get_engine()) as session:
        rows = list(session.exec(select(PdcaTask)).all())
        project_names = {}
        project_okrs = {}
        from app.models.todo_project import TodoProject

        for proj in session.exec(select(TodoProject)).all():
            project_names[proj.id] = proj.name
            project_okrs[proj.id] = proj.okr_title or ""
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=7)).strftime(
        "%Y-%m-%d"
    )
    out = []
    for row in rows:
        if _is_done(row.status) and (row.task_date or "") < cutoff:
            continue  # 7 天前已完成的进历史，不进台账
        active_parts = [
            part for part in split_owners(row.owner)
            if part.casefold() not in skip_names
        ]
        if not active_parts:
            continue  # 负责人全部在催办排除名单里 → 不进台账
        project = project_names.get(row.project_id, "") if row.project_id else ""
        okr = row.okr_title or (project_okrs.get(row.project_id, "") if row.project_id else "")
        done = _is_done(row.status)
        reply_signal = classify_reply(row.reply_text) if row.replied_at else None
        progress = ""
        if done:
            progress = "已完成"
        elif reply_signal == "done":
            progress = "完成(待核)"
        elif reply_signal == "blocked":
            progress = "阻塞"
        elif row.replied_at:
            progress = "有回复"
        out.append(
            [
                row.title,
                project,
                okr,
                row.owner,
                row.last_reminded_at.strftime("%m-%d %H:%M") if row.last_reminded_at else "",
                "是" if row.claimed_at else "否",
                row.claimed_at.strftime("%m-%d %H:%M") if row.claimed_at else "",
                (row.replied_at or row.updated_at).strftime("%m-%d %H:%M") if done else "",
                progress,
                str(row.score) if row.score is not None else "",
            ]
        )
    out.sort(key=lambda cells: (int(cells[9]) if cells[9].isdigit() else 999, cells[1], cells[2]))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--create", action="store_true", help="首次运行时显式创建外部台账")
    args = parser.parse_args(argv)

    if not check_db_connection():
        print("无法连接 PostgreSQL")
        return 1

    if not args.dry_run:
        init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    rows = build_rows(today)
    if args.dry_run:
        doc_id, sheet_id = get_existing_doc()
        updates = build_updates(rows)
        doc_id = doc_id or "(未配置)"
        print(f"dry-run: doc={doc_id} sheet={sheet_id} rows={len(rows)} updates={len(updates)}")
        for row in rows[:8]:
            print("  ", " | ".join(row))
        return 0

    # 真实同步才允许创建外部文档及写状态。
    doc_id, sheet_id = get_or_create_doc(create=args.create)
    previous_row_count = _state_int("ledger_row_count")
    updates = build_updates(rows, previous_row_count)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="pdca-ledger-", encoding="utf-8",
        delete=False,
    ) as handle:
        json.dump(updates, handle, ensure_ascii=False)
        tmp = Path(handle.name)
    try:
        code, stdout, stderr = run_vertu_sync(
            [
                "docs", "+sheet-set-cells",
                "--doc-id", doc_id,
                "--sheet", sheet_id,
                "--updates-file", str(tmp),
            ],
            timeout=120.0,
        )
    finally:
        tmp.unlink(missing_ok=True)
    if code != 0:
        print("台账写入失败:", (stderr or stdout)[:200])
        return 1
    _set_state_value("ledger_row_count", str(len(rows)))
    print(f"台账已同步：doc={doc_id} 行={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
