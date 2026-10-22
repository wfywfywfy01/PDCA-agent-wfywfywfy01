"""A failed text reply can be retried without duplicating the sales turn."""
import unittest

from sqlmodel import Session

from app.auth.models import User
from app.omega.jobs import run_once
from app.omega.models import OmegaSession
from tests import test_omega_flow


class OmegaTurnRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.flow = test_omega_flow.OmegaFlowTests()
        self.flow.setUp()
        self.addCleanup(self.flow.tearDown)
        self.client = self.flow.client
        self.engine = self.flow.engine
        case = self.client.post("/api/omega/cases", json=self.flow.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        self.session_id = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()["id"]

    def failed_turn(self):
        submitted = self.client.post(f"/api/omega/sessions/{self.session_id}/turns", json={
            "request_key": "failed-turn-001", "text": "首单库存风险怎么分担？",
        })
        self.assertEqual(submitted.status_code, 202, submitted.text)

        def fail(*_):
            raise TimeoutError("test model timeout")

        self.assertTrue(run_once(self.engine, generate=fail))
        job = submitted.json()
        self.assertEqual(self.client.get(f"/api/omega/jobs/{job['id']}").json()["status"], "failed")
        return job

    def test_retry_reuses_sales_turn_and_allows_next_turn_after_reply(self):
        failed = self.failed_turn()
        before = self.client.get(f"/api/omega/sessions/{self.session_id}").json()
        self.assertEqual(before["failed_turn_job_id"], failed["id"])
        self.assertEqual([part["speaker"] for part in before["segments"]], ["sales"])
        duplicate = self.client.post(f"/api/omega/sessions/{self.session_id}/turns", json={
            "request_key": "another-turn-001", "text": "首单库存风险怎么分担？",
        })
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

        retried = self.client.post(f"/api/omega/jobs/{failed['id']}/retry")
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["id"], failed["id"])
        again = self.client.post(f"/api/omega/jobs/{failed['id']}/retry")
        self.assertEqual(again.status_code, 202, again.text)
        self.assertTrue(run_once(self.engine, generate=lambda *_: "先明确退换条件。"))
        after = self.client.get(f"/api/omega/sessions/{self.session_id}").json()
        self.assertEqual(after["failed_turn_job_id"], "")
        self.assertEqual([(part["speaker"], part["text"]) for part in after["segments"]], [
            ("sales", "首单库存风险怎么分担？"), ("counterparty", "先明确退换条件。")])
        following = self.client.post(f"/api/omega/sessions/{self.session_id}/turns", json={
            "request_key": "next-turn-001", "text": "请给我书面承诺。",
        })
        self.assertEqual(following.status_code, 202, following.text)

    def test_retry_requires_owner_and_unchanged_session(self):
        failed = self.failed_turn()
        self.flow.current = User(id=2, username="other-team", role="sales", team_key="team-b")
        self.assertEqual(self.client.post(f"/api/omega/jobs/{failed['id']}/retry").status_code, 404)
        self.flow.current = User(id=1, username="seller-a", role="sales", team_key="team-a")
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            game.revision += 1
            db.commit()
        self.assertEqual(self.client.post(f"/api/omega/jobs/{failed['id']}/retry").status_code, 409)

    def test_manager_can_read_but_cannot_speak_retry_or_finish_for_seller(self):
        failed = self.failed_turn()
        with Session(self.engine) as db:
            db.add(User(id=2, username="manager-a", role="manager", team_key="team-a",
                        hashed_password="test-only", is_active=True))
            db.commit()
        self.flow.current = User(id=2, username="manager-a", role="manager", team_key="team-a")
        self.assertEqual(self.client.get(f"/api/omega/sessions/{self.session_id}").status_code, 200)
        self.assertEqual(self.client.post(f"/api/omega/sessions/{self.session_id}/turns", json={
            "request_key": "manager-turn-001", "text": "我替销售承诺价格。",
        }).status_code, 403)
        self.assertEqual(self.client.post(f"/api/omega/jobs/{failed['id']}/retry").status_code, 403)
        self.assertEqual(self.client.post(f"/api/omega/sessions/{self.session_id}/finish", json={
            "request_key": "manager-finish-001",
        }).status_code, 403)
        self.assertEqual(self.client.get(f"/api/omega/sessions/{self.session_id}").json()["status"], "active")

        case_id = self.client.get(f"/api/omega/sessions/{self.session_id}").json()["case_id"]
        own = self.client.post("/api/omega/sessions", json={"case_id": case_id})
        self.assertEqual(own.status_code, 201, own.text)
        own_id = own.json()["id"]
        self.assertEqual(self.client.post(f"/api/omega/sessions/{own_id}/turns", json={
            "request_key": "manager-own-turn-001", "text": "请说明您的库存顾虑。",
        }).status_code, 202)
        self.assertTrue(run_once(self.engine, generate=lambda *_: "我担心首单积压。"))
        self.assertEqual(self.client.post(f"/api/omega/sessions/{own_id}/finish", json={
            "request_key": "manager-own-finish-001",
        }).status_code, 200)

        self.flow.current = User(id=1, username="seller-a", role="sales", team_key="team-a")
        self.assertEqual(self.client.post(f"/api/omega/jobs/{failed['id']}/retry").status_code, 202)
        self.assertTrue(run_once(self.engine, generate=lambda *_: "先说明库存风险。"))
        self.assertEqual(self.client.post(f"/api/omega/sessions/{self.session_id}/finish", json={
            "request_key": "owner-finish-001",
        }).status_code, 200)

    def test_ending_after_failed_reply_keeps_transcript_but_never_scores_it(self):
        failed = self.failed_turn()
        ended = self.client.post(f"/api/omega/sessions/{self.session_id}/finish", json={
            "request_key": "end-after-failed-reply"})
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertEqual(ended.json()["status"], "ended")
        self.assertTrue(ended.json()["report_blocked"])
        self.assertIn("对手未回复", ended.json()["report_blocked_message"])
        self.assertEqual(ended.json()["pending_job_id"], "")
        self.assertEqual([part["speaker"] for part in ended.json()["segments"]], ["sales"])
        self.assertEqual(self.client.post(f"/api/omega/sessions/{self.session_id}/reports", json={
            "request_key": "report-after-failed-reply"}).status_code, 409)
        self.assertEqual(self.client.post(f"/api/omega/jobs/{failed['id']}/retry").status_code, 409)

    def test_ending_while_reply_is_queued_does_not_score_half_turn(self):
        submitted = self.client.post(f"/api/omega/sessions/{self.session_id}/turns", json={
            "request_key": "queued-turn-001", "text": "请明确售后责任。",
        })
        self.assertEqual(submitted.status_code, 202, submitted.text)
        ended = self.client.post(f"/api/omega/sessions/{self.session_id}/finish", json={
            "request_key": "end-while-queued"})
        self.assertEqual(ended.status_code, 200, ended.text)
        self.assertTrue(ended.json()["report_blocked"])
        self.assertIn("对手未回复", ended.json()["report_blocked_message"])
        self.assertEqual(ended.json()["pending_job_id"], "")
        self.assertEqual(self.client.post(f"/api/omega/sessions/{self.session_id}/reports", json={
            "request_key": "report-after-cancel"}).status_code, 409)
