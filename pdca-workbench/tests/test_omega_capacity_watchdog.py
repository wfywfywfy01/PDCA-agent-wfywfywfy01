"""Bound realtime capacity and duration across rooms and stalled transports."""
import asyncio
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth.models import User
from app.omega.models import OmegaJob, OmegaSession
from app.omega.realtime import _acquire, _release, realtime_session
from tests import test_omega_realtime as realtime_fixture


class RealtimeCapacityTests(unittest.TestCase):
    setUp = realtime_fixture.RealtimeSessionTests.setUp
    tearDown = realtime_fixture.RealtimeSessionTests.tearDown

    def another_room(self, owner_id=1):
        with Session(self.engine) as db:
            original = db.get(OmegaSession, self.session_id)
            if owner_id != 1:
                db.add(User(id=owner_id, username=f"seller-{owner_id}", role="sales",
                            team_key="team-a", hashed_password="test-only",
                            must_change_password=False))
            room = OmegaSession(case_id=original.case_id,
                                case_version_id=original.case_version_id,
                                team_key=original.team_key, owner_id=owner_id)
            db.add(room)
            db.commit()
            return room.id

    def test_one_account_cannot_hold_two_rooms(self):
        other = self.another_room()
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
        with self.assertRaises(HTTPException) as denied:
            _acquire(self.engine, self.user, other)
        self.assertEqual(denied.exception.status_code, 409)
        _release(self.engine, job_id, token, failed=False)
        accepted, _, _ = _acquire(self.engine, self.user, other)
        self.assertNotEqual(accepted, job_id)

    def test_global_limit_is_atomic_across_rooms(self):
        other = self.another_room(owner_id=2)
        entered = Event()
        from app.omega import realtime
        original_role = realtime._session_voice_role

        def slow_role(db, game):
            if game.id == self.session_id:
                entered.set()
                time.sleep(.2)
            return original_role(db, game)

        def first():
            return _acquire(self.engine, self.user, self.session_id)

        def second():
            self.assertTrue(entered.wait(2))
            return _acquire(self.engine, User(id=2, username="seller-2"), other)

        with patch.dict("os.environ", {"PDCA_OMEGA_REALTIME_MAX_CONNECTIONS": "1"}), \
             patch("app.omega.realtime._session_voice_role", side_effect=slow_role), \
             ThreadPoolExecutor(max_workers=2) as pool:
            one = pool.submit(first)
            two = pool.submit(second)
            claimed = one.result(timeout=5)
            with self.assertRaises(HTTPException) as denied:
                two.result(timeout=5)
        self.assertEqual(denied.exception.status_code, 429)
        with Session(self.engine) as db:
            active = db.exec(select(OmegaJob).where(OmegaJob.kind == "realtime",
                                                       OmegaJob.status == "running")).all()
            self.assertEqual(len(active), 1)
        _release(self.engine, claimed[0], claimed[1], failed=False)

    def test_invalid_capacity_fails_closed(self):
        with patch.dict("os.environ", {"PDCA_OMEGA_REALTIME_MAX_CONNECTIONS": "none"}):
            with self.assertRaises(HTTPException) as denied:
                _acquire(self.engine, self.user, self.session_id)
        self.assertEqual(denied.exception.status_code, 503)

    def test_stalled_provider_still_closes_with_incomplete_tail(self):
        owner = self

        class Provider:
            def __init__(self):
                self.events = asyncio.Queue()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def send(self, raw):
                if json.loads(raw)["type"] == "session.create":
                    self.events.put_nowait(json.dumps({"type": "session.created"}))
                else:
                    await asyncio.Future()

            async def recv(self):
                return await self.events.get()

            async def finish_input(self, control):
                await asyncio.Future()

        class Browser:
            def __init__(self):
                self.cookies = {}
                self.incoming = asyncio.Queue()
                self.events = []
                self.closed = False

            async def accept(self):
                pass

            async def close(self, **_):
                self.closed = True

            async def receive(self):
                return await self.incoming.get()

            async def send_json(self, item):
                self.events.append(item)
                if item["type"] == "ready":
                    self.incoming.put_nowait({"type": "websocket.receive",
                                              "bytes": b"\x01\x00" * 320})

            async def send_bytes(self, *_):
                pass

        async def authorize(*_):
            return owner.user

        async def exercise():
            browser = Browser()
            provider = Provider()
            with Session(self.engine) as db, \
                 patch("app.omega.realtime.is_enabled", return_value=True), \
                 patch("app.omega.realtime._trusted_origin", return_value=True), \
                 patch("app.omega.realtime.ws_user", side_effect=authorize), \
                 patch("app.omega.realtime.DoubaoStream", return_value=provider), \
                 patch("app.omega.realtime._max_connection_seconds", .08, create=True), \
                 patch("app.omega.realtime._auth_interval_seconds", .01, create=True), \
                 patch("app.omega.realtime._drain_timeout_seconds", .08, create=True), \
                 patch.dict("os.environ", {"PDCA_OMEGA_REALTIME_PROVIDER": "doubao",
                                         "PDCA_DOUBAO_REALTIME_API_KEY": "synthetic-no-network"}):
                await asyncio.wait_for(realtime_session(browser, self.session_id, db), 1)
            self.assertTrue(browser.closed)
            self.assertIn("ending", [item["type"] for item in browser.events])
            with Session(self.engine) as db:
                job = db.exec(select(OmegaJob).where(OmegaJob.kind == "realtime")).one()
                self.assertEqual(job.status, "failed")
                self.assertTrue(job.error)

        asyncio.run(exercise())
