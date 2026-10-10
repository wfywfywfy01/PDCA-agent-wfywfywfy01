"""Omega behavior through authenticated HTTP routes and a disposable database."""
from __future__ import annotations

import tempfile
import unittest
import json
import io
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.main import app
from app.omega.models import OmegaJob, OmegaWorkerHeartbeat, utcnow


class OmegaFlowTests(unittest.TestCase):
    @staticmethod
    def case_body():
        return {
            "title": "测试回款谈判", "public_brief": "讨论一笔测试账款。",
            "seller_private": "PRIVATE_BOTTOM_LINE",
            "counterparty_brief": "要求明确交付日期。",
            "goal": {
                "outcome_type": "payment_commitment",
                "success_condition": "对方书面确认付款时间",
                "ideal": "当场确认", "minimum": "确认时间表",
                "hard_limits": ["不降低价格"], "amount_minor": 10000,
                "currency": "USD", "due_date": "2026-10-05",
            },
        }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "omega.sqlite"
        self.engine = create_engine(
            f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False}
        )
        SQLModel.metadata.create_all(self.engine)
        self.current = User(id=1, username="seller-a", role="sales", team_key="team-a")
        with Session(self.engine) as db:
            db.add(User(id=1, username="seller-a", role="sales", team_key="team-a",
                        hashed_password="test-only", is_active=True))
            db.commit()

        def session_override():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_current_user] = lambda: self.current
        self.flag = patch("app.omega.router.is_enabled", return_value=True)
        self.flag.start()
        self.client = TestClient(app, headers={"Origin": "http://testserver"})

    def tearDown(self):
        self.client.close()
        self.flag.stop()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    def test_team_case_is_created_and_visible_to_team(self):
        created = self.client.post("/api/omega/cases", json=self.case_body())
        self.assertEqual(created.status_code, 201, created.text)
        case_id = created.json()["id"]
        self.current = User(id=2, username="seller-b", role="sales", team_key="team-a")
        visible = self.client.get("/api/omega/cases")
        self.assertEqual(visible.status_code, 200, visible.text)
        self.assertEqual([row["id"] for row in visible.json()], [case_id])
        self.current = User(id=3, username="seller-c", role="sales", team_key="team-b")
        self.assertEqual(self.client.get(f"/api/omega/cases/{case_id}").status_code, 404)

    def test_seller_can_repractice_only_from_own_report(self):
        from app.omega.models import OmegaReport

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        source = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        with Session(self.engine) as db:
            report = OmegaReport(session_id=source["id"], input_hash="test-report",
                                 content_json=json.dumps({"score_weights": {"objections": 10},
                                     "dimensions": [{"key": "objections", "score": 4}]}))
            db.add(report)
            db.add(User(id=3, username="seller-b", role="sales", team_key="team-a",
                        hashed_password="test-only", is_active=True))
            db.commit()
            report_id = report.id
        payload = {"case_id": case["id"], "assignee_id": 1,
                   "source_report_id": report_id, "target_dimension": "objections",
                   "pass_percent": 70, "instructions": "先问清客户的交付顾虑"}
        self.assertEqual(self.client.post("/api/omega/assignments", json={
            **payload, "source_report_id": None}).status_code, 403)
        self.assertEqual(self.client.post("/api/omega/assignments", json={
            **payload, "assignee_id": 3}).status_code, 403)
        self.current = User(id=3, username="seller-b", role="sales", team_key="team-a")
        self.assertEqual(self.client.post("/api/omega/assignments", json={
            **payload, "assignee_id": 3}).status_code, 403)
        self.current = User(id=1, username="seller-a", role="sales", team_key="team-a")
        created = self.client.post("/api/omega/assignments", json=payload)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["baseline"]["percent"], 40)
        attempt = self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": created.json()["id"]})
        self.assertEqual(attempt.status_code, 201, attempt.text)
        self.assertEqual(attempt.json()["case_version_id"], source["case_version_id"])
        self.client.post(f"/api/omega/sessions/{attempt.json()['id']}/turns", json={
            "request_key": "focused-turn", "text": "请说说您的交付顾虑。"}).raise_for_status()
        from app.omega.jobs import run_once
        prompts = []
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, limit:
                                 prompts.append(messages[0]["content"]) or "交付时间仍不明确。"))
        self.assertIn("Keep one stated objection active", prompts[0])
        self.assertNotIn("PRIVATE_BOTTOM_LINE", prompts[0])

    def test_targeted_buyer_prompt_uses_skill_without_private_report_text(self):
        from app.omega.context import actor_messages
        from app.omega.realtime import _voice_role

        snapshot = {**self.case_body(), "buyer_objections": ["交付时间不明确"]}
        for role in (actor_messages(snapshot, [], focus="objections")[0]["content"],
                     _voice_role(snapshot, focus="objections")):
            self.assertIn("Keep one stated objection active", role)
            self.assertIn("交付时间不明确", role)
            self.assertNotIn("PRIVATE_BOTTOM_LINE", role)

    def test_unauthenticated_requests_and_cross_origin_write_are_rejected(self):
        del app.dependency_overrides[get_current_user]
        self.assertEqual(self.client.get("/api/omega/cases").status_code, 401)
        self.assertEqual(self.client.get("/api/omega/status").status_code, 401)
        self.assertEqual(self.client.post("/api/omega/cases", json=self.case_body()).status_code, 401)
        app.dependency_overrides[get_current_user] = lambda: self.current
        outside = self.client.post("/api/omega/cases", json=self.case_body(),
                                   headers={"Origin": "https://outside.example"})
        self.assertEqual(outside.status_code, 403, outside.text)
        self.assertEqual(self.client.get("/api/omega/cases").json(), [])

    def test_ai_draft_analysis_only_returns_a_reviewable_draft(self):
        from app.omega.draft_assist import parse_extraction

        extracted = parse_extraction(json.dumps({
            "title": "经销商回款谈判", "public_brief": "讨论到期货款。",
            "counterparty_brief": "对方希望延期付款。",
            "dealer_id": "unapproved-source", "score_weights": {"outcome": 100},
            "goal": {"outcome_type": "payment_commitment",
                     "success_condition": "确认书面付款时间表", "amount_major": 10000},
        }, ensure_ascii=False))
        self.assertEqual(extracted["goal"]["amount_major"], "10000")
        self.assertEqual(extracted["goal"]["hard_limits"], [])
        self.assertNotIn("due_date", extracted["goal"])
        self.assertNotIn("dealer_id", extracted)
        self.assertNotIn("score_weights", extracted)

        with patch("app.omega.draft_assist.available", return_value=True), patch(
            "app.omega.draft_assist.analyze", new_callable=AsyncMock,
            return_value={"draft": extracted},
        ) as generator:
            response = self.client.post("/api/omega/case-draft/analyze", json={
                "text": "明天和客户谈回款"
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["draft"], extracted)
            generator.assert_awaited_once()
        self.assertEqual(self.client.get("/api/omega/cases").json(), [])
        self.assertEqual(self.client.post("/api/omega/case-draft/analyze",
                                          json={"text": "  "}).status_code, 422)
        self.assertEqual(self.client.post("/api/omega/case-draft/analyze",
                                          json={"text": "虚构场景：经销商希望延期付款，需要确认书面付款时间。"},
                                          headers={"Origin": "https://outside.example"}).status_code, 403)

    def test_team_reader_cannot_modify_another_sellers_case_or_session(self):
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        self.current = User(id=2, username="seller-b", role="sales", team_key="team-a")
        self.assertEqual(self.client.get(f"/api/omega/sessions/{game['id']}").status_code, 200)
        self.assertEqual(self.client.post(f"/api/omega/sessions/{game['id']}/finish",
                                          json={"request_key": "foreign-finish-01"}).status_code, 403)
        changed = self.case_body()
        changed["revision"] = 2
        self.assertEqual(self.client.patch(f"/api/omega/cases/{case['id']}", json=changed).status_code, 403)

    def test_confirmed_case_edit_creates_new_version_without_changing_old_session(self):
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        first = self.client.post(f"/api/omega/cases/{case['id']}/confirm").json()
        old = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        changed = self.case_body()
        changed["goal"]["minimum"] = "书面承诺下周付款"
        changed["revision"] = case["revision"] + 1
        edit = self.client.patch(f"/api/omega/cases/{case['id']}", json=changed)
        self.assertEqual(edit.status_code, 200, edit.text)
        self.assertEqual(self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/omega/cases/{case['id']}", json=changed).status_code, 409)
        second = self.client.post(f"/api/omega/cases/{case['id']}/confirm")
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["version"], 2)
        self.assertNotEqual(first["content_hash"], second.json()["content_hash"])
        self.assertEqual(old["case_version_id"], first["id"])
        old_again = self.client.get(f"/api/omega/sessions/{old['id']}").json()
        self.assertEqual(old_again["case_snapshot"]["goal"]["minimum"], "确认时间表")
        new = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        self.assertEqual(new["case_version_id"], second.json()["id"])

    def test_voice_turn_retains_original_transcription(self):
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        sent = self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "voice-unique-0001", "text": "付款日期是五号",
            "source": "voice", "asr_original": "付款日期是四号",
        })
        self.assertEqual(sent.status_code, 202, sent.text)
        part = self.client.get(f"/api/omega/sessions/{game['id']}").json()["segments"][0]
        self.assertEqual(part["source"], "voice")
        self.assertEqual(part["asr_original"], "付款日期是四号")

    def test_vemory_import_requires_mapped_source_and_deduplicates(self):
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        meeting = {"id": "meeting-001", "owner_name": "Alice", "start_time": "2026-09-22T10:00:00+08:00",
                   "transcript_segments": [{"speaker": "Alice", "text": "Can you pay Friday?"},
                                           {"speaker": "Buyer", "text": "I can confirm Friday."}]}
        body = {"case_id": case["id"], "meeting_id": "meeting-001",
                "speaker_map": {"Alice": "sales", "Buyer": "counterparty"}}
        with patch("app.omega.real.vemory_api.meeting_detail", new=AsyncMock(return_value=(meeting, None))):
            self.assertEqual(self.client.post("/api/omega/real-imports", json=body).status_code, 403)
            self.current = User(id=1, username="seller-a", role="admin", team_key="team-a")
            self.assertEqual(self.client.post("/api/omega/real-imports", json={**body,
                "speaker_map": {"Alice": "sales"}}).status_code, 422)
            first = self.client.post("/api/omega/real-imports", json=body)
            again = self.client.post("/api/omega/real-imports", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(again.status_code, 201, again.text)
        self.assertEqual(first.json()["id"], again.json()["id"])
        self.assertEqual(first.json()["goal_timing"], "post")
        self.assertEqual(first.json()["status"], "ended")
        self.current = User(id=3, username="seller-c", role="sales", team_key="team-b")
        self.assertEqual(self.client.get(f"/api/omega/sessions/{first.json()['id']}").status_code, 404)

    def test_same_meeting_and_goal_in_another_case_stays_in_that_case(self):
        meeting = {"id": "meeting-shared", "owner_name": "Alice",
                   "start_time": "2026-09-22T10:00:00+08:00",
                   "transcript_segments": [
                       {"speaker": "Alice", "text": "Can you pay Friday?"},
                       {"speaker": "Buyer", "text": "I can confirm Friday."},
                   ]}
        mapping = {"Alice": "sales", "Buyer": "counterparty"}
        self.current = User(id=1, username="seller-a", role="admin", team_key="team-a")
        first_case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{first_case['id']}/confirm").raise_for_status()
        second_case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{second_case['id']}/confirm").raise_for_status()
        with patch("app.omega.real.vemory_api.meeting_detail", new=AsyncMock(return_value=(meeting, None))):
            first = self.client.post("/api/omega/real-imports", json={
                "case_id": first_case["id"], "meeting_id": meeting["id"], "speaker_map": mapping,
            })
            second = self.client.post("/api/omega/real-imports", json={
                "case_id": second_case["id"], "meeting_id": meeting["id"], "speaker_map": mapping,
            })
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertEqual(second.json()["case_id"], second_case["id"])
        self.assertNotEqual(first.json()["id"], second.json()["id"])

    def test_import_rechecks_case_after_vemory_fetch(self):
        from app.omega.models import OmegaCase

        self.current = User(id=1, username="seller-a", role="admin", team_key="team-a")
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        meeting = {"id": "meeting-edit-race", "owner_name": "Alice",
                   "transcript_segments": [
                       {"speaker": "Alice", "text": "Please confirm."},
                       {"speaker": "Buyer", "text": "I can confirm."},
                   ]}

        async def fetch_then_edit(_):
            with Session(self.engine) as other:
                row = other.get(OmegaCase, case["id"])
                row.revision += 1
                other.commit()
            return meeting, None

        with patch("app.omega.real.vemory_api.meeting_detail", new=AsyncMock(side_effect=fetch_then_edit)):
            imported = self.client.post("/api/omega/real-imports", json={
                "case_id": case["id"], "meeting_id": meeting["id"],
                "speaker_map": {"Alice": "sales", "Buyer": "counterparty"},
            })
        self.assertEqual(imported.status_code, 409, imported.text)

    def test_post_meeting_goal_cannot_receive_outcome_achievement_score(self):
        from app.omega.reports import WEIGHTS, validate_report
        claim = {"outcome": {"status": "achieved", "reason": "Later promise", "quotes": []},
                 "dimensions": [{"key": name, "score": None, "reason": "No evidence", "quotes": []}
                                for name in WEIGHTS]}
        claim["dimensions"][0]["score"] = 20
        checked = validate_report(json.dumps(claim), [], goal_timing="post")
        self.assertEqual(checked["outcome"]["status"], "unverified")
        self.assertIsNone(checked["dimensions"][0]["score"])
        self.assertIsNone(checked["score"]["total"])

    def test_transcribe_requires_valid_audio_and_returns_reviewable_text(self):
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)
        adapter = SimpleNamespace(configured=True, recognize=lambda *args, **kwargs:
                                  SimpleNamespace(text="下周五", confidence=0.8, needs_manual_review=True))
        with patch("app.omega.voice.get_settings", return_value=SimpleNamespace(asr_enabled=True)), \
             patch("app.omega.voice.DoubaoFlashAsr", return_value=adapter):
            rejected = self.client.post("/api/omega/transcribe", content=b"bad", headers={"Content-Type": "audio/wav"})
            accepted = self.client.post("/api/omega/transcribe", content=output.getvalue(), headers={"Content-Type": "audio/wav"})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["text"], "下周五")
        self.assertTrue(accepted.json()["needs_manual_review"])

    def test_revoked_source_access_blocks_queued_model_and_reads(self):
        from app.omega.jobs import run_once
        from app.models.dealer_store import DealerStore
        from app.models.dealer_assignment import DealerAssignment
        from uuid import uuid4

        dealer_id = str(uuid4())
        with Session(self.engine) as db:
            db.add(DealerStore(store_id="test-store", name="Test store", team_key="team-a",
                               knowledge_dealer_id=dealer_id))
            db.add(DealerAssignment(user_id=1, store_id="test-store"))
            db.commit()
        body = self.case_body()
        body["dealer_id"] = dealer_id
        case = self.client.post("/api/omega/cases", json=body)
        self.assertEqual(case.status_code, 201, case.text)
        case_id = case.json()["id"]
        self.client.post(f"/api/omega/cases/{case_id}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case_id}).json()
        job = self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "revoked-source-001", "text": "Can you confirm Friday?",
        }).json()
        with Session(self.engine) as db:
            assignment = db.exec(select(DealerAssignment)).one()
            assignment.is_active = False
            db.commit()
        called = []
        self.assertTrue(run_once(self.engine, generate=lambda *args: called.append(True)))
        self.assertEqual(called, [])
        self.assertEqual(self.client.get(f"/api/omega/cases/{case_id}").status_code, 403)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, job["id"]).status, "failed")

    def test_revoked_source_access_during_model_blocks_result_save(self):
        from app.omega.jobs import run_once
        from app.omega.models import OmegaSegment
        from app.models.dealer_store import DealerStore
        from app.models.dealer_assignment import DealerAssignment
        from uuid import uuid4

        dealer_id = str(uuid4())
        with Session(self.engine) as db:
            db.add(DealerStore(store_id="model-store", name="Model store", team_key="team-a",
                               knowledge_dealer_id=dealer_id))
            db.add(DealerAssignment(user_id=1, store_id="model-store"))
            db.commit()
        body = self.case_body()
        body["dealer_id"] = dealer_id
        case = self.client.post("/api/omega/cases", json=body).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        job = self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "revoke-during-model", "text": "Can you confirm Friday?",
        }).json()

        def generate(*_):
            with Session(self.engine) as db:
                assignment = db.exec(select(DealerAssignment)).one()
                assignment.is_active = False
                db.commit()
            return "Please send a written schedule."

        self.assertTrue(run_once(self.engine, generate=generate))
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, job["id"]).status, "failed")
            replies = db.exec(select(OmegaSegment).where(
                OmegaSegment.session_id == game["id"],
                OmegaSegment.speaker == "counterparty",
            )).all()
            self.assertEqual(replies, [])

    def test_readiness_requires_model_and_live_worker(self):
        with patch.dict("os.environ", {
            "PDCA_SUPERVISOR_PROVIDER": "https://model.example.test",
            "PDCA_SUPERVISOR_MODEL": "test-model", "PDCA_SUPERVISOR_API_KEY": "test-only",
        }):
            self.assertFalse(self.client.get("/api/omega/status").json()["ready"])
            with Session(self.engine) as db:
                db.add(OmegaWorkerHeartbeat(worker_id="worker-test", last_seen=utcnow()))
                db.commit()
            self.assertTrue(self.client.get("/api/omega/status").json()["ready"])

    def test_retries_do_not_duplicate_turn_and_report_requires_ended_session(self):
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        confirmed = self.client.post(f"/api/omega/cases/{case['id']}/confirm")
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        created = self.client.post("/api/omega/sessions", json={"case_id": case["id"]})
        self.assertEqual(created.status_code, 201, created.text)
        session_id = created.json()["id"]
        body = {"request_key": "turn-unique-0001", "text": "Can you confirm Friday?"}
        first = self.client.post(f"/api/omega/sessions/{session_id}/turns", json=body)
        again = self.client.post(f"/api/omega/sessions/{session_id}/turns", json=body)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(again.json(), first.json())
        busy = self.client.post(f"/api/omega/sessions/{session_id}/turns", json={"request_key": "turn-unique-0002", "text": "Another statement"})
        self.assertEqual(busy.status_code, 409)
        ended = self.client.post(f"/api/omega/sessions/{session_id}/finish", json={"request_key": "finish-unique-01"})
        self.assertEqual(ended.status_code, 200, ended.text)
        report = self.client.post(f"/api/omega/sessions/{session_id}/reports", json={"request_key": "report-unique-01"})
        self.assertEqual(report.status_code, 202, report.text)
        details = self.client.get(f"/api/omega/sessions/{session_id}")
        self.assertEqual(details.status_code, 200)
        self.assertEqual([(part["speaker"], part["text"]) for part in details.json()["segments"]], [("sales", body["text"])])

    def test_worker_keeps_private_limit_from_counterparty_and_saves_reply(self):
        from app.omega.jobs import run_once

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        queued = self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "turn-unique-1001", "text": "Can you pay on Friday?",
        }).json()
        seen = []

        def generate(kind, messages, max_tokens):
            seen.append((kind, json.dumps(messages)))
            return "Please send me a written schedule."

        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(seen[0][0], "turn")
        self.assertNotIn("PRIVATE_BOTTOM_LINE", seen[0][1])
        self.assertEqual(self.client.get(f"/api/omega/jobs/{queued['id']}").json()["status"], "succeeded")
        details = self.client.get(f"/api/omega/sessions/{game['id']}").json()
        self.assertEqual([part["speaker"] for part in details["segments"]], ["sales", "counterparty"])

    def test_report_rejects_fabricated_quote(self):
        from app.omega.jobs import run_once

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "turn-unique-2001", "text": "Can you pay on Friday?",
        }).raise_for_status()
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, max_tokens: "Maybe next week."))
        self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={"request_key": "finish-unique-02"}).raise_for_status()
        report_job = self.client.post(f"/api/omega/sessions/{game['id']}/reports", json={"request_key": "report-unique-02"}).json()
        from app.omega.reports import WEIGHTS
        fabricated = {"outcome": {"status": "unverified", "reason": "No commitment"},
                      "dimensions": [{"key": key, "score": None, "reason": "No evidence", "quotes": []}
                                     for key in WEIGHTS]}
        fabricated["dimensions"][0].update({
            "score": 20, "reason": "He said it",
            "quotes": [{"segment_id": "made-up", "speaker": "sales", "start": 0, "end": 10,
                        "text": "I have paid"}],
        })
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, max_tokens: json.dumps(fabricated)))
        self.assertEqual(self.client.get(f"/api/omega/jobs/{report_job['id']}").json()["status"], "queued")
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, max_tokens: json.dumps(fabricated)))
        failed = self.client.get(f"/api/omega/jobs/{report_job['id']}").json()
        self.assertEqual(failed["status"], "failed")
        self.assertIn("引文", failed["error"])

    def test_report_retries_missing_sales_quote_once(self):
        from app.omega.jobs import run_once
        from app.omega.reports import WEIGHTS

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        utterance = "Can you confirm a date?"
        self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "turn-missing-quote", "text": utterance}).raise_for_status()
        self.assertTrue(run_once(self.engine, generate=lambda *_: "I need a plan."))
        self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={"request_key": "finish-missing-quote"}).raise_for_status()
        queued = self.client.post(f"/api/omega/sessions/{game['id']}/reports", json={
            "request_key": "report-missing-quote"}).json()
        calls = []
        segment = self.client.get(f"/api/omega/sessions/{game['id']}").json()["segments"][0]

        def generate(kind, *_):
            if kind == "report_audit":
                return json.dumps({"consistent": True, "issues": []})
            if kind == "practice":
                return json.dumps({"next_practice": "先核对客户拒绝确认日期的原因，再商定可验证的时间表。"})
            calls.append(True)
            dimensions = [{"key": key, "score": None, "reason": "No evidence", "quotes": []}
                          for key in WEIGHTS]
            dimensions[1].update(score=6, reason="Asked about date", quotes=[] if len(calls) == 1 else [{
                "segment_id": segment["id"], "speaker": "sales", "start": 0,
                "end": len(utterance), "text": utterance}])
            return json.dumps({"outcome": {"status": "unverified", "reason": "No commitment", "quotes": []},
                               "dimensions": dimensions})

        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(self.client.get(f"/api/omega/jobs/{queued['id']}").json()["status"], "queued")
        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(self.client.get(f"/api/omega/jobs/{queued['id']}").json()["status"], "succeeded")
        self.assertEqual(len(calls), 2)

    def test_incomplete_scorecard_is_retried_once_without_publishing_it(self):
        from app.omega.jobs import run_once
        from app.omega.reports import WEIGHTS

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "turn-scorecard-retry", "text": "Can you confirm a date?",
        }).raise_for_status()
        self.assertTrue(run_once(self.engine, generate=lambda *_: "I need a plan."))
        self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={"request_key": "finish-scorecard-retry"}).raise_for_status()
        queued = self.client.post(f"/api/omega/sessions/{game['id']}/reports", json={"request_key": "report-scorecard-retry"}).json()
        calls = []

        def generate(kind, *_):
            if kind == "report_audit":
                return json.dumps({"consistent": True, "issues": []})
            calls.append(True)
            return json.dumps({"outcome": {"status": "unverified", "reason": "No commitment", "quotes": []},
                               "dimensions": [] if len(calls) == 1 else [
                                   {"key": name, "score": None, "reason": "No evidence", "quotes": []}
                                   for name in WEIGHTS]})

        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertEqual(self.client.get(f"/api/omega/jobs/{queued['id']}").json()["status"], "queued")
        self.assertTrue(run_once(self.engine, generate=generate))
        completed = self.client.get(f"/api/omega/jobs/{queued['id']}").json()
        self.assertEqual(completed["status"], "succeeded", completed)
        self.assertEqual(len(calls), 2)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, queued["id"]).attempts, 2)

    def test_valid_report_shows_coverage_and_manager_review(self):
        from app.omega.jobs import run_once
        from app.omega.reports import WEIGHTS

        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        utterance = "Can you pay on Friday?"
        self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            "request_key": "turn-unique-3001", "text": utterance,
        }).raise_for_status()
        run_once(self.engine, generate=lambda kind, messages, max_tokens: "I will check.")
        segment = self.client.get(f"/api/omega/sessions/{game['id']}").json()["segments"][0]
        self.client.post(f"/api/omega/sessions/{game['id']}/finish", json={"request_key": "finish-unique-03"}).raise_for_status()
        job = self.client.post(f"/api/omega/sessions/{game['id']}/reports", json={"request_key": "report-unique-03"}).json()
        report = {"outcome": {"status": "unverified", "reason": "No date", "quotes": []},
                  "dimensions": [{"key": key, "score": None, "reason": "No evidence", "quotes": []}
                                 for key in WEIGHTS]}
        report["dimensions"][1].update({
            "score": 8, "reason": "Asked for date", "quotes": [{
                "segment_id": segment["id"], "speaker": "sales", "start": 0,
                "end": len(utterance), "text": utterance,
            }],
        })
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, max_tokens: json.dumps(
            {"consistent": True, "issues": []} if kind == "report_audit" else
            {"next_practice": "先核对付款审批流程，再确认书面时间表。"} if kind == "practice" else report)))
        job_state = self.client.get(f"/api/omega/jobs/{job['id']}").json()
        self.assertEqual(job_state["status"], "succeeded", job_state)
        report_id = job_state["result_id"]
        shown = self.client.get(f"/api/omega/reports/{report_id}")
        self.assertEqual(shown.status_code, 200, shown.text)
        self.assertEqual(shown.json()["content"]["score"], {
            "earned": 8, "available": 12, "coverage_percent": 12, "total": None,
        })
        self.current = User(id=2, username="manager-a", role="manager", team_key="team-a")
        reviewed = self.client.post(f"/api/omega/reports/{report_id}/reviews", json={
            "comment": "需要确认书面时间表", "next_practice": "练习锁定日期",
        })
        self.assertEqual(reviewed.status_code, 201, reviewed.text)
        self.current = User(id=3, username="manager-b", role="manager", team_key="team-b")
        self.assertEqual(self.client.get(f"/api/omega/reports/{report_id}").status_code, 404)

    def test_report_to_assignment_to_repeat_uses_frozen_scorecard(self):
        from app.omega.jobs import run_once
        from app.omega.reports import WEIGHTS

        body = self.case_body()
        body.update(buyer_name="Alex", buyer_role="Buyer", buyer_emotion="skeptical",
                    buyer_objections=["Delivery date"],
                    score_weights={**WEIGHTS, "outcome": 22, "information": 15})
        invalid = {**body, "score_weights": {**body["score_weights"], "information": 21}}
        self.assertEqual(self.client.post("/api/omega/cases", json=invalid).status_code, 422)
        case = self.client.post("/api/omega/cases", json=body).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()

        def complete_report(game_id, score):
            utterance = "Can you explain the delivery concern?"
            self.client.post(f"/api/omega/sessions/{game_id}/turns", json={
                "request_key": f"turn-{game_id}", "text": utterance,
            }).raise_for_status()
            seen = []
            self.assertTrue(run_once(self.engine, generate=lambda kind, messages, limit:
                                     seen.append(json.dumps(messages)) or "Please confirm the schedule."))
            self.assertIn("Alex", seen[0])
            segment = self.client.get(f"/api/omega/sessions/{game_id}").json()["segments"][0]
            self.client.post(f"/api/omega/sessions/{game_id}/finish",
                             json={"request_key": f"finish-{game_id}"}).raise_for_status()
            job = self.client.post(f"/api/omega/sessions/{game_id}/reports",
                                   json={"request_key": f"report-{game_id}"}).json()
            content = {"outcome": {"status": "unverified", "reason": "No written promise", "quotes": []},
                       "dimensions": [{"key": key, "score": None, "reason": "No evidence", "quotes": []}
                                      for key in WEIGHTS]}
            content["dimensions"][1].update(score=score, reason="Asked about delivery",
                quotes=[{"segment_id": segment["id"], "speaker": "sales", "start": 0,
                         "end": len(utterance), "text": utterance}])
            self.assertTrue(run_once(self.engine, generate=lambda kind, messages, limit: json.dumps(
                {"consistent": True, "issues": []} if kind == "report_audit" else
                {"next_practice": "先复述交付顾虑，再约定负责人和书面答复时间。"} if kind == "practice" else content)))
            state = self.client.get(f"/api/omega/jobs/{job['id']}").json()
            self.assertEqual(state["status"], "succeeded", state)
            return state["result_id"]

        original = self.client.post("/api/omega/sessions", json={"case_id": case["id"]}).json()
        source_report_id = complete_report(original["id"], 10)
        self.assertEqual(self.client.get(f"/api/omega/reports/{source_report_id}").json()
                         ["content"]["score_weights"]["information"], 15)
        self.current = User(id=2, username="manager-a", role="manager", team_key="team-a")
        created = self.client.post("/api/omega/assignments", json={
            "case_id": case["id"], "assignee_id": 1, "source_report_id": source_report_id,
            "target_dimension": "information", "pass_percent": 67,
            "instructions": "Ask about delivery before negotiating payment",
        })
        self.assertEqual(created.status_code, 201, created.text)
        assignment = created.json()
        self.assertEqual(assignment["baseline"]["percent"], 67)
        self.assertEqual(assignment["status"], "pending")
        self.current = User(id=3, username="seller-b", role="sales", team_key="team-a")
        self.assertEqual(self.client.get(f"/api/omega/assignments/{assignment['id']}").status_code, 404)
        self.assertEqual(self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": assignment["id"]}).status_code, 404)
        self.current = User(id=1, username="seller-a", role="sales", team_key="team-a")
        revised = self.case_body()
        revised["revision"] = case["revision"] + 1
        revised["goal"]["minimum"] = "new scenario version"
        self.client.patch(f"/api/omega/cases/{case['id']}", json=revised).raise_for_status()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        attempt = self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": assignment["id"]})
        self.assertEqual(attempt.status_code, 201, attempt.text)
        self.assertEqual(attempt.json()["case_version_id"], original["case_version_id"])
        complete_report(attempt.json()["id"], 10)
        progress = self.client.get(f"/api/omega/assignments/{assignment['id']}").json()
        self.assertEqual(progress["status"], "in_progress")
        self.assertEqual(progress["attempts"][0]["result"]["percent"], 67)
        self.assertFalse(progress["attempts"][0]["passed"])
        repeat = self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": assignment["id"]})
        self.assertEqual(repeat.status_code, 201, repeat.text)
        complete_report(repeat.json()["id"], 12)
        progress = self.client.get(f"/api/omega/assignments/{assignment['id']}").json()
        self.assertEqual(progress["status"], "passed")
        self.assertEqual(progress["attempts"][1]["result"]["percent"], 80)

    def test_real_vemory_report_can_assign_only_to_source_authorized_seller(self):
        from app.omega.jobs import run_once
        from app.omega.reports import WEIGHTS

        with Session(self.engine) as db:
            db.get(User, 1).sales_name = "Alice"
            db.add(User(id=3, username="seller-b", role="sales", team_key="team-a",
                        hashed_password="test-only", is_active=True))
            db.commit()
        self.current = User(id=1, username="seller-a", role="sales", team_key="team-a",
                            sales_name="Alice")
        case = self.client.post("/api/omega/cases", json=self.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        meeting = {"id": "meeting-practice-source", "owner_name": "Alice",
                   "start_time": "2026-10-05T10:00:00+08:00", "transcript_segments": [
                       {"speaker": "Alice", "text": "Can you confirm the delivery concern?"},
                       {"speaker": "Buyer", "text": "We need a delivery date first."}]}
        with patch("app.omega.real.vemory_api.meeting_detail", new=AsyncMock(return_value=(meeting, None))):
            imported = self.client.post("/api/omega/real-imports", json={
                "case_id": case["id"], "meeting_id": meeting["id"],
                "speaker_map": {"Alice": "sales", "Buyer": "counterparty"}})
        self.assertEqual(imported.status_code, 201, imported.text)
        game = imported.json()
        self.assertEqual(game["mode"], "real_review")
        job = self.client.post(f"/api/omega/sessions/{game['id']}/reports",
                               json={"request_key": "real-report-001"}).json()
        phrase = game["segments"][0]["text"]
        content = {"outcome": {"status": "unverified", "reason": "No commitment", "quotes": []},
                   "dimensions": [{"key": key, "score": None, "reason": "No evidence", "quotes": []}
                                  for key in WEIGHTS]}
        content["dimensions"][4].update(score=4, reason="Asked one question",
            quotes=[{"segment_id": game["segments"][0]["id"], "speaker": "sales",
                     "start": 0, "end": len(phrase), "text": phrase}])
        self.assertTrue(run_once(self.engine, generate=lambda kind, messages, limit: json.dumps(
            {"consistent": True, "issues": []} if kind == "report_audit" else
            {"next_practice": "先确认哪项交付风险仍未解决，再约定具体的核对动作。"} if kind == "practice" else content)))
        report_id = self.client.get(f"/api/omega/jobs/{job['id']}").json()["result_id"]
        self.assertTrue(report_id)
        self.current = User(id=2, username="manager-a", role="manager", team_key="team-a")
        payload = {"case_id": case["id"], "source_report_id": report_id,
                   "target_dimension": "objections", "assignee_id": 3}
        self.assertEqual(self.client.post("/api/omega/assignments", json=payload).status_code, 404)
        payload["assignee_id"] = 1
        assigned = self.client.post("/api/omega/assignments", json=payload)
        self.assertEqual(assigned.status_code, 201, assigned.text)
        self.assertEqual(assigned.json()["baseline"]["percent"], 40)
        self.current = User(id=1, username="seller-a", role="sales", team_key="team-a",
                            sales_name="Alice")
        repeat = self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": assigned.json()["id"]})
        self.assertEqual(repeat.status_code, 201, repeat.text)
        self.assertEqual(repeat.json()["assignment_id"], assigned.json()["id"])
        queued = self.client.post(f"/api/omega/sessions/{repeat.json()['id']}/turns", json={
            "request_key": "assigned-revocation-01", "text": "Can we discuss delivery?",
        })
        self.assertEqual(queued.status_code, 202, queued.text)
        with Session(self.engine) as db:
            db.get(User, 1).sales_name = ""
            db.commit()
        self.current.sales_name = ""
        model_calls = []
        self.assertTrue(run_once(self.engine, generate=lambda *args: model_calls.append(True)))
        self.assertEqual(model_calls, [])
        self.assertEqual(self.client.get(f"/api/omega/jobs/{queued.json()['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/omega/assignments/{assigned.json()['id']}").status_code, 404)
        self.assertEqual(self.client.get(f"/api/omega/sessions/{repeat.json()['id']}").status_code, 404)
        self.assertEqual(self.client.post("/api/omega/sessions", json={
            "case_id": case["id"], "assignment_id": assigned.json()["id"]}).status_code, 404)


class OmegaReportGenerationTests(unittest.TestCase):
    def test_report_next_practice_is_readable_when_model_returns_an_object(self):
        from app.omega.reports import WEIGHTS, validate_report

        report = {"outcome": {"status": "unverified", "reason": "No evidence", "quotes": []},
                  "dimensions": [{"key": name, "score": None, "reason": "No evidence", "quotes": []}
                                 for name in WEIGHTS],
                  "next_practice": {"动作": "先问客户最担心哪个交付节点。", "引用": []}}
        checked = validate_report(json.dumps(report, ensure_ascii=False), [])
        self.assertEqual(checked["next_practice"], "先问客户最担心哪个交付节点。")

    def test_coach_supplies_exact_quote_candidates(self):
        from app.omega.context import coach_messages
        from app.omega.reports import WEIGHTS

        segment = {"id": "segment-1", "speaker": "sales", "text": "请确认培训时间。"}
        messages = coach_messages({}, [segment], WEIGHTS)
        prompt = json.loads(messages[1]["content"])
        self.assertEqual(prompt["quote_candidates"], [{
            "segment_id": segment["id"], "speaker": "sales",
            "start": 0, "end": len(segment["text"]), "text": segment["text"],
        }])
        self.assertIn("quote_candidates", messages[0]["content"])
        self.assertIn("只给一项下轮可练的具体动作", messages[0]["content"])

    def test_long_voice_turn_gets_short_exact_quote_candidates(self):
        from app.omega.context import coach_messages
        from app.omega.reports import WEIGHTS, verify_quote

        text = "这段谈话与付款无关。" * 80 + "第一笔款最早哪天能付？"
        prompt = json.loads(coach_messages({}, [{"id": "long-turn", "speaker": "sales", "text": text}],
                                           WEIGHTS)[1]["content"])
        candidates = prompt["quote_candidates"]
        self.assertGreater(len(candidates), 1)
        self.assertTrue(all(len(quote["text"]) <= 160 and verify_quote(quote, {
            "long-turn": {"id": "long-turn", "speaker": "sales", "text": text}}) for quote in candidates))
        self.assertTrue(any("第一笔款最早哪天能付" in quote["text"] for quote in candidates))

    def test_deepseek_structured_jobs_use_json_with_kind_specific_thinking(self):
        from app.omega.jobs import _default_generate

        settings = {"PDCA_SUPERVISOR_PROVIDER": "https://api.deepseek.com",
                    "PDCA_SUPERVISOR_MODEL": "deepseek-flash",
                    "PDCA_SUPERVISOR_API_KEY": "test-only"}
        for kind, limit in (("report", 16384), ("report_audit", 16384),
                            ("practice", 4096), ("memory", 4000)):
            with self.subTest(kind=kind), patch.dict("os.environ", settings), \
                    patch("app.omega.jobs.httpx.post") as post:
                post.return_value.json.return_value = {
                    "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}]}
                self.assertEqual(_default_generate(kind, [{"role": "user", "content": "JSON"}], limit), "{}")
                payload = post.call_args.kwargs["json"]
                if kind == "memory":
                    self.assertEqual(payload["thinking"], {"type": "disabled"})
                    self.assertNotIn("reasoning_effort", payload)
                else:
                    self.assertEqual(payload["thinking"], {"type": "enabled"})
                    self.assertEqual(payload["reasoning_effort"], "high")
                self.assertEqual(payload["response_format"], {"type": "json_object"})
                self.assertEqual(payload["max_tokens"], limit)
                self.assertNotIn("temperature", payload)
                self.assertEqual(post.call_args.kwargs["timeout"], 30 if kind == "practice" else 90)

    def test_deepseek_text_jobs_disable_thinking_without_forcing_json(self):
        from app.omega.jobs import _default_generate

        settings = {"PDCA_SUPERVISOR_PROVIDER": "https://api.deepseek.com",
                    "PDCA_SUPERVISOR_MODEL": "deepseek-flash",
                    "PDCA_SUPERVISOR_API_KEY": "test-only"}
        for kind, limit in (("coach_hint", 600), ("turn", 1500), ("draft", 1800)):
            with self.subTest(kind=kind), patch.dict("os.environ", settings), \
                    patch("app.omega.jobs.httpx.post") as post:
                text = "模拟回答：先确认下一步负责人。"
                post.return_value.json.return_value = {"choices": [{"finish_reason": "stop",
                    "message": {"content": "  " + text + "\n"}}]}
                self.assertEqual(_default_generate(kind, [{"role": "user", "content": "测试"}], limit), text)
                payload = post.call_args.kwargs["json"]
                self.assertEqual(payload["thinking"], {"type": "disabled"})
                self.assertNotIn("response_format", payload)
                self.assertNotIn("temperature", payload)
                self.assertEqual(payload["max_tokens"], limit)
                self.assertEqual(post.call_args.kwargs["timeout"], 20)
                post.return_value.raise_for_status.assert_called_once()

    def test_generate_rejects_truncated_output_even_when_body_is_nonempty(self):
        from app.omega.jobs import _default_generate

        settings = {"PDCA_SUPERVISOR_PROVIDER": "https://api.deepseek.com",
                    "PDCA_SUPERVISOR_MODEL": "deepseek-flash",
                    "PDCA_SUPERVISOR_API_KEY": "test-only"}
        for kind in ("coach_hint", "turn", "draft", "report", "memory"):
            with self.subTest(kind=kind), patch.dict("os.environ", settings), \
                    patch("app.omega.jobs.httpx.post") as post:
                post.return_value.json.return_value = {"choices": [{"finish_reason": "length",
                    "message": {"content": "模拟回答未完成"}}]}
                with self.assertRaisesRegex(RuntimeError, "模型输出被截断"):
                    _default_generate(kind, [{"role": "user", "content": "测试"}], 600)

    def test_generate_does_not_publish_reasoning_without_final_body(self):
        from app.omega.jobs import _default_generate

        settings = {"PDCA_SUPERVISOR_PROVIDER": "https://api.deepseek.com",
                    "PDCA_SUPERVISOR_MODEL": "deepseek-flash",
                    "PDCA_SUPERVISOR_API_KEY": "test-only"}
        with patch.dict("os.environ", settings), patch("app.omega.jobs.httpx.post") as post:
            post.return_value.json.return_value = {"choices": [{"finish_reason": "stop",
                "message": {"content": None, "reasoning_content": "模拟推理，没有最终正文"}}]}
            with self.assertRaisesRegex(RuntimeError, "模型没有返回正文"):
                _default_generate("coach_hint", [{"role": "user", "content": "测试"}], 600)
