# -*- coding: utf-8 -*-
"""P2：会议读取侧切 DB（meeting_records 转正）单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app.meeting import router
from app.models.meeting import MeetingRecord


class MeetingDbSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{Path(self.temp_dir.name) / 't.sqlite'}"
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add(
                MeetingRecord(
                    meeting_date="2026-08-18",
                    external_id="M1",
                    title="经销商拜访 A",
                    meeting_type="external",
                    bucket="customer",
                    duration_minutes=45,
                    brief="首次拜访",
                    todos_json=json.dumps(
                        [{"title": "发报价单", "owner": "何海文"}], ensure_ascii=False
                    ),
                    participants_json=json.dumps(
                        [{"name": "何海文"}, {"name": "客户A"}], ensure_ascii=False
                    ),
                )
            )
            session.add(
                MeetingRecord(
                    meeting_date="2026-08-19",
                    external_id="M2",
                    title="内部周会",
                    meeting_type="internal",
                    bucket="report",
                    duration_minutes=60,
                    brief="周例会",
                    todos_json="[]",
                    participants_json="[]",
                )
            )
            session.commit()

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_db_payload_shape_and_summary(self):
        with Session(self.engine) as session:
            payload = router._db_meetings("2026-08-18", "2026-08-19", "", session)
        self.assertIsNotNone(payload)
        self.assertEqual(len(payload["meetings"]), 2)
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["external"], 1)
        self.assertEqual(payload["summary"]["internal"], 1)
        self.assertEqual(payload["summary"]["todo_count"], 1)
        self.assertEqual(payload["counts"]["customer"], 1)
        self.assertEqual(payload["counts"]["report"], 1)
        first = payload["meetings"][0]
        self.assertEqual(first["id"], "M1")
        self.assertEqual(first["todos"][0]["owner"], "何海文")

    def test_name_filter_matches_participants(self):
        with Session(self.engine) as session:
            payload = router._db_meetings("2026-08-01", "2026-08-31", "何海文", session)
        self.assertEqual(len(payload["meetings"]), 1)
        self.assertEqual(payload["meetings"][0]["id"], "M1")

    def test_empty_range_returns_none_for_bridge_fallback(self):
        with Session(self.engine) as session:
            payload = router._db_meetings("2026-01-01", "2026-01-31", "", session)
        self.assertIsNone(payload)


if __name__ == "__main__":
    unittest.main()
