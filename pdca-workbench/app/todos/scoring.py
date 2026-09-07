# -*- coding: utf-8 -*-
"""三源印证规则打分：对每条未完成待办聚合 回复/日报/Vemory 三类证据打分。

规则（0-100，v1 规则版，后续可升级 AI 语义打分）：
- Vemory/状态 done                        → 100（已完成）
- 回复含「完成」类信号                      → 90（待复核）
- 回复含「推进」类信号                      → 70
- 回复含「阻塞」类信号                      → 40（阻塞可见）
- 已认领（群领取）无有效回复                → 30
- 未认领                                  → 10
- 逾期且未认领、无回复                     → 0
- 逾期 > 3 天再减 10（下限 0）
日报证据来自部门日报接口（report +department）：近 3 天日报中出现待办标题
或所属项目的跟进记录 → +20（上限 100）；无日报数据标记 unavailable。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.statuses import is_done as _is_done
from app.todos.evidence import (
    fetch_department_reports,
    has_followup,
    report_text_for,
)
from app.todos.owners import split_owners

DONE_WORDS = ("完成", "已完成", "搞定", "做完", "done", "finished", "closed")
PROGRESS_WORDS = ("推进", "进展", "进行中", "in progress", "处理中", "做了")
BLOCKED_WORDS = ("阻塞", "卡住", "卡在", "blocked", "受阻", "做不了")


def _reply_signal(reply_text: str) -> Optional[str]:
    text = (reply_text or "").casefold()
    if not text:
        return None
    if any(word in text for word in DONE_WORDS):
        return "done"
    if any(word in text for word in BLOCKED_WORDS):
        return "blocked"
    if any(word in text for word in PROGRESS_WORDS):
        return "progress"
    return "reply"


def score_task(
    task: PdcaTask,
    today: str,
    daily_hit: Optional[bool] = None,
) -> dict:
    """单条待办三源打分；返回 {"score", "evidence"}。"""
    evidence = {
        "vemory": "done" if _is_done(task.status) else "open",
        "reply": _reply_signal(task.reply_text) if task.replied_at else None,
        "daily": "hit" if daily_hit else ("miss" if daily_hit is False else "unavailable"),
    }
    if _is_done(task.status):
        return {"score": 100, "evidence": evidence}
    if evidence["reply"] == "done":
        score = 90
    elif evidence["reply"] == "progress":
        score = 70
    elif evidence["reply"] == "blocked":
        score = 40
    elif evidence["reply"]:
        score = 50
    elif task.claimed_at:
        score = 30
    else:
        score = 10
    # 日报跟进证据加分
    if daily_hit and score < 100:
        score = min(100, score + 20)
    # 逾期惩罚
    if task.task_date and task.task_date < today:
        overdue_days = (
            datetime.strptime(today, "%Y-%m-%d")
            - datetime.strptime(task.task_date, "%Y-%m-%d")
        ).days
        if overdue_days > 3:
            score = max(0, score - 10)
        if overdue_days > 7 and score < 40:
            score = max(0, score - 20)
        if overdue_days > 3 and not task.claimed_at and not evidence["reply"]:
            score = 0
    return {"score": score, "evidence": evidence}


def run_scoring(today: Optional[str] = None, dry_run: bool = False) -> dict:
    """对全部未完成待办跑一轮三源打分，落库 score/score_at。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    # 日报证据窗口：今天往前 3 天（含今天），一次拉全公司日报按姓名聚合
    dates = [
        (today_dt - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)
    ]
    report_corpus = fetch_department_reports(dates)
    rows = []
    with Session(get_engine()) as session:
        rows = list(
            session.exec(
                select(PdcaTask).where(PdcaTask.owner != "")
            ).all()
        )
        project_name_by_id = {
            p.id: p.name for p in session.exec(select(TodoProject)).all()
        }
    scored = 0
    buckets = {"100": 0, ">=70": 0, ">=40": 0, ">=20": 0, "<20": 0}
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        for row in rows:
            if _is_done(row.status):
                continue
            reports = []
            for part in split_owners(row.owner):
                text = report_text_for(part, report_corpus)
                if text is not None:
                    reports.append(text)
            daily_hit: Optional[bool] = None
            if reports:
                project_name = project_name_by_id.get(row.project_id) or ""
                daily_hit = bool(
                    any(has_followup(row.title, report) for report in reports)
                    or (
                        project_name
                        and any(has_followup(project_name, report) for report in reports)
                    )
                )
            result = score_task(row, today, daily_hit=daily_hit)
            if not dry_run:
                row.score = result["score"]
                row.score_at = now
                row.updated_at = datetime.utcnow()
                session.add(row)
            scored += 1
            if result["score"] >= 100:
                buckets["100"] += 1
            elif result["score"] >= 70:
                buckets[">=70"] += 1
            elif result["score"] >= 40:
                buckets[">=40"] += 1
            elif result["score"] >= 20:
                buckets[">=20"] += 1
            else:
                buckets["<20"] += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    logger.info("待办打分完成: {}", buckets)
    return {"date": today, "scored": scored, "buckets": buckets, "dry_run": dry_run}
