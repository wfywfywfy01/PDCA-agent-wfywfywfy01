"""跨境货代运营台 sqlite 读写。"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.logistics import logibot_desk


class LogibotDeskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LOGIBOT_DATA_DIR"] = self.tmp.name
        self.db = Path(self.tmp.name) / "shipments.db"
        conn = sqlite3.connect(self.db)
        conn.execute(
            """
            CREATE TABLE shipments (
              "顺丰单号" TEXT PRIMARY KEY,
              "订单号" TEXT,
              "国际单号" TEXT,
              "快递公司" TEXT,
              "销售人员" TEXT,
              "境外收货人" TEXT,
              "目的地" TEXT,
              "签收状态" TEXT,
              "生命周期" TEXT,
              "异常" TEXT,
              "匹配级别" TEXT,
              "匹配证据" TEXT,
              "最新轨迹" TEXT,
              "备注" TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO shipments VALUES (
              'SF1','XSD1','1ZAAA','UPS','林晓','ALICE','FRANCE',
              '待人工','PENDING','','C','candidate_conflict','','一对多'
            )
            """
        )
        conn.execute(
            """
            INSERT INTO shipments VALUES (
              'SF2','XSD2','1ZBBB','DHL','周宁','BOB','GERMANY',
              '海关扣关','CUSTOMS','CUSTOMS_HOLD','A','order_no_exact','hold','扣关'
            )
            """
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        os.environ.pop("LOGIBOT_DATA_DIR", None)

    def test_desk_summary_and_review_filter(self):
        all_desk = logibot_desk.load_desk()
        self.assertTrue(all_desk["available"])
        self.assertEqual(all_desk["summary"]["total"], 2)
        self.assertEqual(all_desk["summary"]["review"], 2)
        self.assertEqual(all_desk["summary"]["exception"], 1)
        review = logibot_desk.load_desk(view="review")
        self.assertEqual(review["count"], 2)
        hold = logibot_desk.load_desk(view="exception")
        self.assertEqual(hold["count"], 1)
        self.assertEqual(hold["items"][0]["sf_tracking_no"], "SF2")

    def test_confirm_clears_review(self):
        item = logibot_desk.confirm_row("SF1", "发票一致", "测试员")
        self.assertEqual(item["match_level"], "A")
        self.assertFalse(item["needs_review"])
        self.assertEqual(item["status"], "已出国际单")
        again = logibot_desk.load_desk(view="review")
        self.assertEqual([i["sf_tracking_no"] for i in again["items"]], ["SF2"])

    def test_dealer_scope_empty(self):
        from types import SimpleNamespace

        from app.logistics.router import _scope_freight

        items, label = _scope_freight(
            [{"salesperson": "林晓", "sf_tracking_no": "SF1"}],
            SimpleNamespace(role="dealer", sales_name=""),
            None,
        )
        self.assertEqual(items, [])
        self.assertIn("不开放", label)
