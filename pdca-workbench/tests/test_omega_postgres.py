"""Real PostgreSQL lease and end ordering; runs only against omega_test."""
from __future__ import annotations

import json
import os
import threading
import unittest
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.main import app
from app.omega.jobs import run_once
from app.omega.models import OmegaAssignment, OmegaCase, OmegaCaseVersion, OmegaJob, OmegaReport, OmegaReview, OmegaSegment, OmegaSession, utcnow
from app.omega.realtime import _acquire, _append, _release


@unittest.skipUnless(os.environ.get("OMEGA_TEST_DATABASE_URL"), "disposable PostgreSQL URL not configured")
class OmegaPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["OMEGA_TEST_DATABASE_URL"]
        parsed = make_url(url)
        if (os.environ.get("PDCA_ENV") != "development"
                or parsed.get_backend_name() != "postgresql"
                or parsed.host not in {"127.0.0.1", "localhost"}
                or parsed.database != "omega_test"):
            raise RuntimeError("Omega PostgreSQL tests require local development omega_test database")
        cls.engine = create_engine(url, pool_pre_ping=True)
        with cls.engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if version != "017":
                raise RuntimeError(f"expected migration 017; got {version}")
        cls._clear_test_data()

    @classmethod
    def _clear_test_data(cls):
        with Session(cls.engine) as db:
            for game in db.exec(select(OmegaSession)).all():
                game.assignment_id = None
            db.flush()
            for model in (OmegaAssignment, OmegaReview, OmegaReport, OmegaJob, OmegaSegment,
                          OmegaSession, OmegaCaseVersion, OmegaCase):
                for row in db.exec(select(model)).all():
                    db.delete(row)
                db.flush()
            for user in db.exec(select(User).where(User.username.like("omega-%"))).all():
                db.delete(user)
            db.commit()

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        with Session(self.engine) as db:
            user = User(username="omega-" + uuid4().hex, role="sales", team_key="team-a",
                        hashed_password="test-only", is_active=True)
            db.add(user)
            db.flush()
            self.user_id = user.id
            self.case_id = str(uuid4())
            self.game_id = str(uuid4())
            self.job_id = str(uuid4())
            snapshot = {"public_brief": "A public payment discussion",
                        "counterparty_brief": "A buyer seeking a schedule"}
            version = OmegaCaseVersion(case_id=self.case_id, version=1,
                                       snapshot_json=json.dumps(snapshot), content_hash="x" * 64,
                                       confirmed_by=user.id)
            db.add(OmegaCase(id=self.case_id, team_key="team-a", owner_id=user.id,
                             title="PG negotiation", draft_json=json.dumps(snapshot),
                             current_version=1))
            db.flush()
            db.add(version)
            db.flush()
            db.add(OmegaSession(id=self.game_id, case_id=self.case_id,
                                case_version_id=version.id, team_key="team-a",
                                owner_id=user.id, revision=2))
            db.flush()
            db.add(OmegaSegment(session_id=self.game_id, seq=1, speaker="sales",
                                text="Can you confirm Friday?", request_key="pg-turn"))
            db.add(OmegaJob(id=self.job_id, session_id=self.game_id, kind="turn",
                            request_key="pg-turn", request_hash="x" * 64,
                            session_revision=2, priority=10))
            db.commit()

    def tearDown(self):
        self._clear_test_data()

    def test_realtime_lease_and_finished_session_on_postgres(self):
        with Session(self.engine) as db:
            db.get(OmegaJob, self.job_id).status = "cancelled"
            actor = db.get(User, self.user_id)
            db.expunge(actor)
            db.commit()
        job_id, token, _ = _acquire(self.engine, actor, self.game_id)
        with self.assertRaisesRegex(Exception, "已有实时语音连接"):
            _acquire(self.engine, actor, self.game_id)
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.game_id)
            game.status = "ended"
            db.commit()
        with self.assertRaisesRegex(ValueError, "已失效"):
            _append(self.engine, self.game_id, job_id, token, "counterparty", "Late reply")
        _release(self.engine, job_id, token, failed=False)

    def _run_blocked(self):
        called = threading.Event()
        release = threading.Event()
        result = []

        def generate(kind, messages, max_tokens):
            called.set()
            if not release.wait(10):
                raise RuntimeError("test model barrier timed out")
            return "Please send a written schedule."

        thread = threading.Thread(target=lambda: result.append(run_once(self.engine, generate=generate)))
        thread.start()
        self.assertTrue(called.wait(10), "first worker did not claim the job")
        return thread, release, result

    def test_two_workers_claim_only_once(self):
        thread, release, result = self._run_blocked()
        try:
            self.assertFalse(run_once(self.engine, generate=lambda *args: self.fail("duplicate model call")))
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [True])
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, self.job_id).status, "succeeded")
            replies = db.exec(select(OmegaSegment).where(
                OmegaSegment.session_id == self.game_id, OmegaSegment.speaker == "counterparty"
            )).all()
            self.assertEqual(len(replies), 1)

    def test_expired_lease_reclaimed_old_worker_cannot_commit(self):
        thread, release, _ = self._run_blocked()
        try:
            with Session(self.engine) as db:
                job = db.get(OmegaJob, self.job_id)
                old_token = job.lease_token
                job.lease_until = utcnow() - timedelta(seconds=1)
                db.commit()
            self.assertTrue(run_once(self.engine, generate=lambda *args: "Recovered reply"))
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        with Session(self.engine) as db:
            job = db.get(OmegaJob, self.job_id)
            self.assertEqual(job.status, "succeeded")
            self.assertEqual(job.attempts, 2)
            self.assertNotEqual(job.lease_token, old_token)
            replies = db.exec(select(OmegaSegment).where(
                OmegaSegment.session_id == self.game_id, OmegaSegment.speaker == "counterparty"
            )).all()
            self.assertEqual([part.text for part in replies], ["Recovered reply"])

    def test_finish_wins_over_late_model_reply(self):
        thread, release, _ = self._run_blocked()

        def session_override():
            with Session(self.engine) as db:
                yield db

        with Session(self.engine) as db:
            user = db.get(User, self.user_id)
            db.expunge(user)
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with patch("app.omega.router.is_enabled", return_value=True):
                client = TestClient(app, headers={"Origin": "http://testserver"})
                response = client.post(f"/api/omega/sessions/{self.game_id}/finish",
                                       json={"request_key": "pg-finish-0001"})
                self.assertEqual(response.status_code, 200, response.text)
                client.close()
        finally:
            app.dependency_overrides.clear()
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.game_id)
            self.assertEqual(game.status, "ended")
            self.assertEqual(db.get(OmegaJob, self.job_id).status, "cancelled")
            parts = db.exec(select(OmegaSegment).where(OmegaSegment.session_id == self.game_id)).all()
            self.assertEqual([part.speaker for part in parts], ["sales"])

    def test_different_request_keys_cannot_create_two_pending_turns(self):
        new_game_id = str(uuid4())
        with Session(self.engine) as db:
            version = db.exec(select(OmegaCaseVersion).where(
                OmegaCaseVersion.case_id == self.case_id)).one()
            db.add(OmegaSession(id=new_game_id, case_id=self.case_id,
                                case_version_id=version.id, team_key="team-a",
                                owner_id=self.user_id))
            db.commit()

        def session_override():
            with Session(self.engine) as db:
                yield db

        with Session(self.engine) as db:
            user = db.get(User, self.user_id)
            db.expunge(user)
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_current_user] = lambda: user
        barrier = threading.Barrier(2)
        statuses = []

        def submit(number):
            client = TestClient(app, headers={"Origin": "http://testserver"})
            barrier.wait(timeout=10)
            response = client.post(f"/api/omega/sessions/{new_game_id}/turns", json={
                "request_key": f"pg-parallel-{number:04d}", "text": f"Offer {number}",
            })
            statuses.append(response.status_code)
            client.close()

        try:
            with patch("app.omega.router.is_enabled", return_value=True):
                threads = [threading.Thread(target=submit, args=(index,)) for index in (1, 2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(sorted(statuses), [202, 409])
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment).where(
                OmegaSegment.session_id == new_game_id)).all()), 1)

    def test_turn_loaded_before_finish_cannot_append_after_finish(self):
        import app.omega.router as omega_router

        new_game_id = str(uuid4())
        with Session(self.engine) as db:
            version = db.exec(select(OmegaCaseVersion).where(
                OmegaCaseVersion.case_id == self.case_id)).one()
            db.add(OmegaSession(id=new_game_id, case_id=self.case_id,
                                case_version_id=version.id, team_key="team-a",
                                owner_id=self.user_id))
            db.commit()

        def session_override():
            with Session(self.engine) as db:
                yield db

        with Session(self.engine) as db:
            user = db.get(User, self.user_id)
            db.expunge(user)
        app.dependency_overrides[get_session] = session_override
        app.dependency_overrides[get_current_user] = lambda: user
        loaded = threading.Event()
        release = threading.Event()
        responses = []
        original = omega_router.owned_session

        def pause_after_load(db, actor, session_id):
            row = original(db, actor, session_id)
            if session_id == new_game_id:
                loaded.set()
                if not release.wait(10):
                    raise RuntimeError("test barrier timed out")
            return row

        def submit():
            client = TestClient(app, headers={"Origin": "http://testserver"})
            responses.append(client.post(f"/api/omega/sessions/{new_game_id}/turns", json={
                "request_key": "turn-after-finish", "text": "A late statement",
            }))
            client.close()

        try:
            with patch("app.omega.router.is_enabled", return_value=True), \
                 patch("app.omega.router.owned_session", side_effect=pause_after_load):
                thread = threading.Thread(target=submit)
                thread.start()
                self.assertTrue(loaded.wait(10))
                with Session(self.engine) as db:
                    game = db.get(OmegaSession, new_game_id)
                    game.status = "ended"
                    game.revision += 1
                    db.commit()
                release.set()
                thread.join(10)
                self.assertFalse(thread.is_alive())
        finally:
            release.set()
            app.dependency_overrides.clear()
        self.assertEqual(responses[0].status_code, 409, responses[0].text)
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaSegment).where(
                OmegaSegment.session_id == new_game_id)).all(), [])
