# -*- coding: utf-8 -*-
"""群认领采集与三源印证打分单测。"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from app.models.pdca_task import PdcaTask
from app.todos.claims import CLAIM_PATTERNS
from app.todos.scoring import score_task


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


if __name__ == "__main__":
    unittest.main()
