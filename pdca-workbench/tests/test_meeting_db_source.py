# -*- coding: utf-8 -*-
"""P2：会议读取侧切 DB（meeting_records 转正）单测。"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.meeting import router
from app.models import sync as sync_module
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

    def test_empty_range_returns_none_for_snapshot_fallback(self):
        with Session(self.engine) as session:
            payload = router._db_meetings("2026-01-01", "2026-01-31", "", session)
        self.assertIsNone(payload)

    def test_vemory_sync_uses_atomic_idempotent_upsert(self):
        raw = {
            "id": "V1",
            "name": "真实客户会议",
            "start_time": "2026-08-18T10:00:00+08:00",
            "duration_seconds": 1500,
            "owner_name": "何海文",
        }
        updated = {**raw, "name": "真实客户会议（更新）", "duration_seconds": 1800}
        with patch.object(sync_module, "get_engine", return_value=self.engine), patch.object(
            sync_module.vemory_api,
            "list_dealer_meetings",
            new=AsyncMock(side_effect=[([raw], None), ([updated], None)]),
        ):
            self.assertEqual(sync_module.sync_meetings("2026-08-18"), 1)
            count = sync_module.sync_meetings("2026-08-18")
        self.assertEqual(count, 1)
        with Session(self.engine) as session:
            rows = session.exec(
                select(MeetingRecord).where(MeetingRecord.external_id == "V1")
            ).all()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.external_id, "V1")
        self.assertEqual(row.title, "真实客户会议（更新）")
        self.assertEqual(row.duration_minutes, 30)
        self.assertEqual(row.meeting_type, "unknown")
        self.assertEqual(row.source, "vemory")
        self.assertIn("何海文", row.participants_json)

    def test_complete_vemory_sync_removes_cancelled_vemory_snapshot_only(self):
        with Session(self.engine) as session:
            session.add(MeetingRecord(
                meeting_date="2026-08-18", external_id="cancelled-vemory", source="vemory",
            ))
            session.commit()
        with patch.object(sync_module, "get_engine", return_value=self.engine), patch.object(
            sync_module.vemory_api,
            "list_dealer_meetings",
            new=AsyncMock(return_value=([], None)),
        ):
            self.assertEqual(sync_module.sync_meetings("2026-08-18"), 0)
        with Session(self.engine) as session:
            ids = {row.external_id for row in session.exec(select(MeetingRecord)).all()}
        self.assertNotIn("cancelled-vemory", ids)
        self.assertIn("M1", ids)

    def test_vemory_sync_failure_keeps_existing_snapshot(self):
        with patch.object(sync_module, "get_engine", return_value=self.engine), patch.object(
            sync_module.vemory_api,
            "list_dealer_meetings",
            new=AsyncMock(return_value=([], "upstream unavailable")),
        ):
            with self.assertRaises(RuntimeError):
                sync_module.sync_meetings("2026-08-18")
        with Session(self.engine) as session:
            row = session.get(MeetingRecord, 1)
        self.assertEqual(row.title, "经销商拜访 A")


if __name__ == "__main__":
    unittest.main()
