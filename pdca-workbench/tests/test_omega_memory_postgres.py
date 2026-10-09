"""Memory row locks and rollback, only against an isolated local omega_test database."""
import json
import os
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, event, text, update
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

from app.auth.models import User
from app.omega.memory import apply_proposal, propose_report_memory
from app.omega.memory_models import OmegaMemoryEntry, OmegaMemoryProfile, OmegaMemoryProposal
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaSegment, OmegaSession


@unittest.skipUnless(os.environ.get("OMEGA_TEST_DATABASE_URL"), "disposable PostgreSQL URL not configured")
class OmegaMemoryPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["OMEGA_TEST_DATABASE_URL"]
        parsed = make_url(url)
        if (os.environ.get("PDCA_ENV") != "development" or parsed.get_backend_name() != "postgresql"
                or parsed.host not in {"127.0.0.1", "localhost"} or parsed.database != "omega_test"):
            raise RuntimeError("Memory tests require local development omega_test database")
        cls.engine = create_engine(url, pool_pre_ping=True, pool_size=20, max_overflow=0)
        with cls.engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "021":
                raise RuntimeError("Memory tests require migration 021")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.team = "memorypg-" + uuid4().hex[:12]
        with Session(self.engine) as db:
            user = User(username=self.team, hashed_password="test-only", role="sales", team_key=self.team)
            db.add(user)
            db.flush()
            self.user_id = user.id
            case = OmegaCase(team_key=self.team, owner_id=user.id, title="Memory PostgreSQL")
            db.add(case)
            db.flush()
            version = OmegaCaseVersion(case_id=case.id, version=1, snapshot_json="{}",
                                       content_hash="a" * 64, confirmed_by=user.id)
            db.add(version)
            db.flush()
            game = OmegaSession(case_id=case.id, case_version_id=version.id, team_key=self.team,
                                owner_id=user.id, status="ended")
            db.add(game)
            db.flush()
            segment = OmegaSegment(session_id=game.id, seq=1, speaker="sales", text="Please confirm the owner.")
            report = OmegaReport(session_id=game.id, input_hash="b" * 64, content_json="{}")
            db.add_all([segment, report])
            db.commit()
            self.case_id, self.game_id, self.report_id = case.id, game.id, report.id
            self.quote = {"segment_id": segment.id, "speaker": "sales", "start": 0,
                          "end": len(segment.text), "text": segment.text}
            proposal = self._propose(db, user, report)
            self.proposal_id = proposal.id
            self.accept_ids = [item["id"] for item in json.loads(proposal.payload_json)["items"]]
            db.commit()

    def _propose(self, db, user, report, kinds=("sales",)):
        return propose_report_memory(db, user, report, json.dumps({"items": [
            {"target_kind": kind, "section": "learning_focus", "value": "Confirm the decision owner.",
             "classification": "inference", "quotes": [self.quote]} for kind in kinds]}))

    def tearDown(self):
        with Session(self.engine) as db:
            profile_ids = select(OmegaMemoryProfile.id).where(OmegaMemoryProfile.team_key == self.team)
            db.exec(delete(OmegaMemoryEntry).where(OmegaMemoryEntry.profile_id.in_(profile_ids)))
            db.exec(delete(OmegaMemoryProposal).where(OmegaMemoryProposal.session_id == self.game_id))
            for model in (OmegaJob, OmegaReport, OmegaSegment):
                db.exec(delete(model).where(model.session_id == self.game_id))
            db.exec(delete(OmegaSession).where(OmegaSession.id == self.game_id))
            db.exec(delete(OmegaCaseVersion).where(OmegaCaseVersion.case_id == self.case_id))
            db.exec(delete(OmegaCase).where(OmegaCase.id == self.case_id))
            db.exec(delete(OmegaMemoryProfile).where(OmegaMemoryProfile.team_key == self.team))
            db.exec(delete(User).where(User.id == self.user_id))
            db.commit()

    def _concurrent(self, requests):
        barrier = threading.Barrier(len(requests))
        results = []
        def apply(request):
            try:
                with Session(self.engine) as db:
                    user = db.get(User, self.user_id)
                    barrier.wait(timeout=10)
                    result = apply_proposal(db, user, request.pop("proposal_id", self.proposal_id), **request)
                    results.append((200, result["id"]))
            except HTTPException as exc:
                results.append((exc.status_code, exc.detail))
            except Exception as exc:
                results.append((500, repr(exc)))
        threads = [threading.Thread(target=apply, args=(dict(request),)) for request in requests]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
            self.assertFalse(thread.is_alive(), "concurrent apply did not finish")
        return results

    def request(self, **changes):
        return {"request_key": "memory-pg-confirm-01", "expected_revision": 1,
                "accept_ids": self.accept_ids, "edited_values": {}, **changes}

    def test_duplicate_confirmation_has_one_effect(self):
        results = self._concurrent([self.request() for _ in range(20)])
        self.assertEqual(sorted(status for status, _ in results), [200] * 20, results)
        self.assertEqual({proposal_id for _, proposal_id in results}, {self.proposal_id})
        with Session(self.engine) as db:
            entries = db.exec(select(OmegaMemoryEntry).where(OmegaMemoryEntry.source_session_id == self.game_id)).all()
            self.assertEqual(len(entries), 1)
            self.assertEqual(db.get(OmegaMemoryProfile, entries[0].profile_id).revision, 1)

    def test_concurrent_different_payload_conflicts(self):
        results = self._concurrent([self.request(), self.request(edited_values={self.accept_ids[0]: "Seller correction."})])
        self.assertEqual(sorted(status for status, _ in results), [200, 409], results)

    def test_two_proposals_sharing_base_revision_cannot_both_apply(self):
        with Session(self.engine) as db:
            report = OmegaReport(session_id=self.game_id, input_hash="c" * 64, content_json="{}")
            db.add(report)
            db.flush()
            proposal = self._propose(db, db.get(User, self.user_id), report)
            second_id = proposal.id
            second_items = [item["id"] for item in json.loads(proposal.payload_json)["items"]]
            db.commit()
        results = self._concurrent([self.request(), self.request(proposal_id=second_id,
                         request_key="memory-pg-confirm-02", accept_ids=second_items)])
        self.assertEqual(sorted(status for status, _ in results), [200, 409], results)

    def test_second_profile_update_failure_rolls_back_first_profile_and_entries(self):
        with Session(self.engine) as db:
            db.exec(delete(OmegaMemoryProposal).where(OmegaMemoryProposal.id == self.proposal_id))
            game = db.get(OmegaSession, self.game_id)
            game.mode = "real_review"
            game.source_access_keys_json = '["memory-pg-seller"]'
            actor = db.get(User, self.user_id)
            actor.sales_name = "memory-pg-seller"
            db.get(OmegaCase, self.case_id).dealer_id = str(uuid4())
            game.context_snapshot_json = json.dumps({"dealer_id": db.get(OmegaCase, self.case_id).dealer_id})
            with patch("app.omega.memory.require_knowledge_access"), patch("app.omega.policy.require_knowledge_access"):
                proposal = self._propose(db, actor, db.get(OmegaReport, self.report_id), kinds=("sales", "dealer"))
                items = [item["id"] for item in json.loads(proposal.payload_json)["items"]]
                proposal_id = proposal.id
                db.commit()
                writes = []
                def fail_second(connection, cursor, statement, parameters, context, executemany):
                    if statement.lstrip().startswith("UPDATE omega_memory_profiles"):
                        writes.append(statement)
                        if len(writes) == 2:
                            raise RuntimeError("injected second profile update failure")
                event.listen(self.engine, "before_cursor_execute", fail_second)
                try:
                    with self.assertRaisesRegex(RuntimeError, "injected second"):
                        apply_proposal(db, actor, proposal_id, request_key="memory-pg-rollback-01",
                                       expected_revision=1, accept_ids=items, edited_values={})
                finally:
                    event.remove(self.engine, "before_cursor_execute", fail_second)
            self.assertEqual(len(writes), 2)
            self.assertEqual(db.exec(select(OmegaMemoryEntry).where(OmegaMemoryEntry.source_session_id == self.game_id)).all(), [])
            self.assertEqual([p.revision for p in db.exec(select(OmegaMemoryProfile).where(OmegaMemoryProfile.team_key == self.team)).all()], [0, 0])
            self.assertEqual(db.get(OmegaMemoryProposal, proposal_id).status, "pending")
