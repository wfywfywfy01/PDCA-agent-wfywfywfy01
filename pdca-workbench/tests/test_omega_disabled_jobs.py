"""Disabled owners cannot start or publish queued Omega model work."""
import json
import unittest

from sqlmodel import Session, select

from app.auth.models import User
from app.omega.jobs import run_once
from app.omega.memory_models import OmegaMemoryProposal
from app.omega.models import OmegaJob, OmegaReport, OmegaSegment
from app.omega.reports import WEIGHTS
from tests import test_omega_flow


class DisabledOwnerJobTests(unittest.TestCase):
    @staticmethod
    def _disable(engine):
        with Session(engine) as db:
            db.get(User, 1).is_active = False
            db.commit()

    def _queue(self, flow, kind):
        client = flow.client
        case = client.post("/api/omega/cases", json=flow.case_body()).json()
        client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        session_id = game["id"]
        turn = client.post(f"/api/omega/sessions/{session_id}/turns", json={
            "request_key": "disabled-owner-turn", "text": "请确认付款日期。",
        })
        self.assertEqual(turn.status_code, 202, turn.text)
        if kind == "turn":
            return turn.json()["id"], session_id

        self.assertTrue(run_once(flow.engine, generate=lambda *_: "我会再确认。"))
        ended = client.post(f"/api/omega/sessions/{session_id}/finish", json={
            "request_key": "disabled-owner-finish",
        })
        self.assertEqual(ended.status_code, 200, ended.text)
        report_id = ended.json()["pending_job_id"]
        self.assertTrue(report_id)
        if kind == "report":
            return report_id, session_id

        report = {"outcome": {"status": "unverified", "reason": "未确认结果", "quotes": []},
                  "dimensions": [{"key": key, "score": None, "reason": "证据不足", "quotes": []}
                                 for key in WEIGHTS]}
        self.assertTrue(run_once(flow.engine, generate=lambda *_: json.dumps(report, ensure_ascii=False)))
        with Session(flow.engine) as db:
            job = db.exec(select(OmegaJob).where(
                OmegaJob.session_id == session_id, OmegaJob.kind == "memory")).one()
            self.assertEqual(job.status, "queued")
            return job.id, session_id

    @staticmethod
    def _generated(kind):
        if kind == "turn":
            return "请先发书面时间表。"
        if kind == "memory":
            return '{"items":[]}'
        return json.dumps({
            "outcome": {"status": "unverified", "reason": "未确认结果", "quotes": []},
            "dimensions": [{"key": key, "score": None, "reason": "证据不足", "quotes": []}
                           for key in WEIGHTS],
        }, ensure_ascii=False)

    def _exercise(self, kind, *, disable_during_call):
        flow = test_omega_flow.OmegaFlowTests()
        flow.setUp()
        try:
            job_id, session_id = self._queue(flow, kind)
            calls = []
            if not disable_during_call:
                self._disable(flow.engine)

            def generate(actual_kind, *_):
                calls.append(actual_kind)
                if disable_during_call:
                    self._disable(flow.engine)
                return self._generated(kind)

            self.assertTrue(run_once(flow.engine, generate=generate))
            self.assertEqual(calls, [kind] if disable_during_call else [])
            with Session(flow.engine) as db:
                job = db.get(OmegaJob, job_id)
                self.assertEqual(job.status, "failed")
                self.assertFalse(job.result_id)
                if kind == "turn":
                    self.assertEqual([row.speaker for row in db.exec(select(OmegaSegment).where(
                        OmegaSegment.session_id == session_id)).all()], ["sales"])
                elif kind == "report":
                    self.assertEqual(db.exec(select(OmegaReport).where(
                        OmegaReport.session_id == session_id)).all(), [])
                else:
                    self.assertEqual(db.exec(select(OmegaMemoryProposal).where(
                        OmegaMemoryProposal.session_id == session_id)).all(), [])
        finally:
            flow.tearDown()

    def test_queued_work_for_disabled_owner_never_calls_model(self):
        for kind in ("turn", "report", "memory"):
            with self.subTest(kind=kind):
                self._exercise(kind, disable_during_call=False)

    def test_model_result_is_discarded_if_owner_is_disabled_during_call(self):
        for kind in ("turn", "report", "memory"):
            with self.subTest(kind=kind):
                self._exercise(kind, disable_during_call=True)


if __name__ == "__main__":
    unittest.main()
