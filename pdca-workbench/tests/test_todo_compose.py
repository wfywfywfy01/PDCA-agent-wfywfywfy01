# -*- coding: utf-8 -*-
"""待办提炼（同类碎片合并）单测。"""
from __future__ import annotations

import unittest

from app.models.pdca_task import PdcaTask
from app.todos.compose import _repr_title, compose_tasks


def _task(title, task_date="2026-08-17", tid=None):
    return PdcaTask(
        id=tid, task_date=task_date, title=title, owner="测试员", status="pending"
    )


class ComposeTests(unittest.TestCase):
    def test_exact_duplicates_merged(self):
        items = [
            _task("给大家写一封邮件，告知相关规则并推动落地", tid=1),
            _task("给大家写一封邮件，告知相关规则并推动落地", tid=2),
            _task("整理客户档案", tid=3),
        ]
        result = compose_tasks(items)
        self.assertEqual(len(result), 2)
        merged = [r for r in result if r["merged"]]
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["count"], 2)
        self.assertEqual(sorted(merged[0]["task_ids"]), [1, 2])

    def test_similar_fragments_merged(self):
        items = [
            _task("下班之前完善投流方案", tid=1),
            _task("完成领英投流方案整理并发给团队，以便下午组织评审", tid=2),
            _task("向工厂确认样品是否收到", tid=3),
        ]
        result = compose_tasks(items)
        merged = [r for r in result if r["merged"]]
        self.assertEqual(len(merged), 1)  # 投流方案两条合并
        self.assertEqual(merged[0]["count"], 2)
        self.assertEqual(
            merged[0]["title"], "完成领英投流方案整理并发给团队，以便下午组织评审"
        )

    def test_distinct_tasks_not_merged(self):
        items = [
            _task("给大家写一封邮件，告知相关规则并推动落地"),
            _task("跟进会议模板识别问题的排期"),
            _task("向工厂确认样品是否收到"),
        ]
        result = compose_tasks(items)
        self.assertEqual(len(result), 3)
        self.assertFalse(any(r["merged"] for r in result))

    def test_order_by_earliest_date(self):
        items = [
            _task("整理客户档案", task_date="2026-08-20"),
            _task("向工厂确认样品是否收到", task_date="2026-08-17"),
        ]
        result = compose_tasks(items)
        self.assertEqual(result[0]["title"], "向工厂确认样品是否收到")

    def test_representative_title_prefers_specific(self):
        rep = _repr_title(
            [
                _task("拉个群"),
                _task("把客户跟进表同步给商务并说明回款口径"),
            ]
        )
        self.assertEqual(rep, "把客户跟进表同步给商务并说明回款口径")


if __name__ == "__main__":
    unittest.main()
