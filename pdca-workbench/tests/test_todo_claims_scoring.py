# -*- coding: utf-8 -*-
"""群认领采集与三源印证打分单测。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.models.pdca_task import PdcaTask
from app.todos.claims import CLAIM_PATTERNS
from app.todos.scoring import run_scoring, score_task


def _task(**kwargs) -> PdcaTask:
    defaults = {
        "task_date": "2026-09-05",
        "title": "测试待办",
        "owner": "测试员",
        "status": "pending",
    }
    defaults.update(kwargs)
    return PdcaTask(**defaults)


class ClaimPatternTests(unittest.TestCase):
    def test_claim_keywords(self):
        for text in ("领取", "认领", "收到", "已领", "确认收到", "claim", "收到待办"):
            self.assertIsNotNone(CLAIM_PATTERNS.search(text), text)
        for text in ("好的", "ok啦", "在忙", "1"):
            self.assertIsNone(CLAIM_PATTERNS.search(text), text)


class ScoringTests(unittest.TestCase):
    def test_done_scores_100(self):
        task = _task(status="done")
        self.assertEqual(score_task(task, "2026-09-07")["score"], 100)

    def test_reply_done_scores_90(self):
        task = _task(reply_text="第1条完成", replied_at=datetime.utcnow())
        self.assertEqual(score_task(task, "2026-09-07")["score"], 90)

    def test_reply_progress_scores_70(self):
        task = _task(reply_text="在推进了", replied_at=datetime.utcnow())
        self.assertEqual(score_task(task, "2026-09-07")["score"], 70)

    def test_reply_blocked_scores_40(self):
        task = _task(reply_text="被卡住了", replied_at=datetime.utcnow())
        self.assertEqual(score_task(task, "2026-09-07")["score"], 40)

    def test_claimed_without_reply_scores_30(self):
        task = _task(claimed_at=datetime.utcnow())
        self.assertEqual(score_task(task, "2026-09-07")["score"], 30)

    def test_unclaimed_scores_10(self):
        self.assertEqual(score_task(_task(), "2026-09-07")["score"], 10)

    def test_overdue_unclaimed_unreplied_scores_0(self):
        task = _task(task_date="2026-08-20")
        self.assertEqual(score_task(task, "2026-09-07")["score"], 0)

    def test_overdue_more_than_3_days_deducts(self):
        task = _task(task_date="2026-08-20", reply_text="推进中", replied_at=datetime.utcnow())
        result = score_task(task, "2026-09-07")
        # 70 基础分 - 10（逾期>3）- 20（逾期>7 且 <40? 70-10=60 不触发第二条）
        self.assertEqual(result["score"], 60)

    def test_daily_hit_bonus(self):
        task = _task(reply_text="推进中", replied_at=datetime.utcnow())
        result = score_task(task, "2026-09-07", daily_hit=True)
        self.assertEqual(result["score"], 90)  # 70 + 20 上限 100

    def test_daily_miss_no_bonus(self):
        task = _task(reply_text="推进中", replied_at=datetime.utcnow())
        result = score_task(task, "2026-09-07", daily_hit=False)
        self.assertEqual(result["score"], 70)
        self.assertEqual(result["evidence"]["daily"], "miss")

    def test_daily_unavailable_marker(self):
        result = score_task(_task(), "2026-09-07", daily_hit=None)
        self.assertEqual(result["evidence"]["daily"], "unavailable")


class RunScoringTests(unittest.TestCase):
    """run_scoring 集成：日报证据接入后落库 score/score_at。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "scoring-test.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.todos.scoring.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_reports = patch(
            "app.todos.scoring.fetch_department_reports", return_value={}
        )
        self.mock_reports = self.patch_reports.start()

    def tearDown(self):
        self.patch_reports.stop()
        self.patch_engine.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed(self, **kwargs) -> int:
        defaults = {
            "task_date": "2026-09-05",
            "title": "测试待办",
            "owner": "测试员",
            "status": "pending",
        }
        defaults.update(kwargs)
        with Session(self.engine) as session:
            row = PdcaTask(**defaults)
            session.add(row)
            session.commit()
            session.refresh(row)
            return row.id

    def test_daily_evidence_bonus_persisted(self):
        corpus = {"测试员": {"user_id": 99, "texts": ["推进迈凯伦配件报价整理"]}}
        self.mock_reports.return_value = corpus
        id1 = self._seed(
            title="推进迈凯伦配件报价",
            reply_text="在推进了",
            replied_at=datetime.utcnow(),
        )
        id2 = self._seed(title="完全无关的事项")
        id3 = self._seed(title="已完成事项", status="done")
        result = run_scoring(today="2026-09-07")
        self.assertEqual(result["scored"], 2)  # done 跳过
        with Session(self.engine) as session:
            t1 = session.get(PdcaTask, id1)
            t2 = session.get(PdcaTask, id2)
            t3 = session.get(PdcaTask, id3)
        self.assertEqual(t1.score, 90)  # 70 回复推进 + 20 日报证据
        self.assertIsNotNone(t1.score_at)
        self.assertEqual(t2.score, 10)  # 日报 miss 不加分
        self.assertIsNone(t3.score)

    def test_scoring_without_report_data_unavailable(self):
        id1 = self._seed(reply_text="推进中", replied_at=datetime.utcnow())
        result = run_scoring(today="2026-09-07")
        self.assertEqual(result["scored"], 1)
        with Session(self.engine) as session:
            t1 = session.get(PdcaTask, id1)
        self.assertEqual(t1.score, 70)  # 无日报数据：不加分也不报错

    def test_combined_owner_daily_evidence(self):
        # 「A&B」合并负责人：任一人的日报命中即算日报证据
        corpus = {"测试员": {"user_id": 99, "texts": ["推进迈凯伦配件报价整理"]}}
        self.mock_reports.return_value = corpus
        id1 = self._seed(title="推进迈凯伦配件报价", owner="测试员&测试员B")
        run_scoring(today="2026-09-07")
        with Session(self.engine) as session:
            t1 = session.get(PdcaTask, id1)
        self.assertEqual(t1.score, 30)  # 10 未认领 + 20 日报证据


if __name__ == "__main__":
    unittest.main()
