"""Bound realtime capacity and duration across rooms and stalled transports."""
import asyncio
import base64
import json
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth.models import User
from app.omega.models import OmegaJob, OmegaSegment, OmegaSession
from app.omega.real import _transcript
from app.omega.realtime import VoiceControl, _acquire, _append, _release, _watch_connection, realtime_session
from app.omega.router import finish_session, session_view, submit_turn
from app.omega.schemas import OperationRequest, TurnRequest
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

    def test_long_voice_transcript_survives_old_120_segment_limit_and_still_has_hard_cap(self):
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
        with Session(self.engine) as db:
            for seq in range(1, 400):
                db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                    speaker="sales" if seq % 2 else "counterparty",
                                    text="test", provider_event_id=f"old-{seq}"))
            db.commit()
        last = _append(self.engine, self.session_id, job_id, token, "sales", "stock risk")
        self.assertEqual(last["seq"], 400)
        with self.assertRaisesRegex(ValueError, "逐字稿上限"):
            _append(self.engine, self.session_id, job_id, token,
                    "counterparty", "next response")

    def test_import_uses_same_hard_transcript_cap(self):
        utterance = {"speaker": "seller", "text": "stock risk"}
        self.assertEqual(len(_transcript({"transcript": [utterance] * 400})), 400)
        with self.assertRaises(HTTPException) as denied:
            _transcript({"transcript": [utterance] * 401})
        self.assertEqual(denied.exception.status_code, 413)

    def test_text_turn_rejects_voice_capacity_reached(self):
        with Session(self.engine) as db:
            for seq in range(1, 361):
                db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                    speaker="sales" if seq % 2 else "counterparty",
                                    text="test", provider_event_id=f"text-{seq}"))
            db.commit()
            with self.assertRaises(HTTPException) as denied:
                submit_turn(self.session_id,
                            TurnRequest(request_key="capacity-text", text="stock risk"),
                            self.user, db)
        self.assertEqual(denied.exception.status_code, 409)

    def test_character_stop_reserves_two_maximum_tail_segments(self):
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
        with Session(self.engine) as db:
            for seq, size in enumerate((4000, 4000, 3999), 1):
                db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                    speaker="sales" if seq % 2 else "counterparty",
                                    text="x" * size, provider_event_id=f"headroom-{seq}"))
            db.commit()
        control = VoiceControl(self.engine, self.session_id, job_id, token, confirmed=True)
        _append(self.engine, self.session_id, job_id, token, "counterparty", "y" * 4000,
                capacity_control=control)
        self.assertEqual(control.capacity_level, 2)
        _append(self.engine, self.session_id, job_id, token, "sales", "z" * 4000,
                capacity_control=control)
        last = _append(self.engine, self.session_id, job_id, token,
                       "counterparty", "w" * 4000, capacity_control=control)
        self.assertEqual(last["seq"], 6)
        with self.assertRaisesRegex(ValueError, "逐字稿上限"):
            _append(self.engine, self.session_id, job_id, token, "sales", "too late")

    def test_capacity_warning_and_orderly_end_before_hard_cap(self):
        class Browser:
            def __init__(self):
                self.events = []

            async def send_json(self, event):
                self.events.append(event)

        async def exercise():
            job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
            control = VoiceControl(self.engine, self.session_id, job_id, token, confirmed=True)
            control.deadline = asyncio.get_running_loop().time() + 200
            browser = Browser()
            with Session(self.engine) as db:
                for seq in range(1, 320):
                    db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                        speaker="sales" if seq % 2 else "counterparty",
                                        text="test", provider_event_id=f"warning-{seq}"))
                db.commit()
            with patch("app.omega.realtime._renew"):
                watcher = asyncio.create_task(_watch_connection(
                    browser, self.engine, self.session_id, job_id, token, control))
                await asyncio.sleep(0)
                _append(self.engine, self.session_id, job_id, token, "counterparty",
                        "customer reply", capacity_control=control)
                await asyncio.sleep(.02)
                self.assertEqual([event["type"] for event in browser.events], ["ending_soon"])
                with Session(self.engine) as db:
                    for seq in range(321, 360):
                        db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                            speaker="sales" if seq % 2 else "counterparty",
                                            text="test", provider_event_id=f"ending-{seq}"))
                    db.commit()
                _append(self.engine, self.session_id, job_id, token, "counterparty",
                        "customer reply", capacity_control=control)
                await asyncio.wait_for(watcher, .3)
            self.assertTrue(control.ending)
            self.assertEqual([event["type"] for event in browser.events],
                             ["ending_soon", "ending"])
            self.assertIn("逐字稿", browser.events[-1]["message"])
            _release(self.engine, job_id, token, failed=False)
            with Session(self.engine) as db:
                self.assertTrue(session_view(db, db.get(OmegaSession, self.session_id))
                                ["voice_capacity_reached"])
            with self.assertRaises(HTTPException) as denied:
                _acquire(self.engine, self.user, self.session_id)
            self.assertEqual(denied.exception.status_code, 409)
            with Session(self.engine) as db:
                ended = finish_session(self.session_id,
                                       OperationRequest(request_key="capacity-finish"),
                                       self.user, db)
            self.assertEqual(ended["status"], "ended")
            self.assertTrue(ended["pending_job_id"])
            self.assertFalse(ended["report_partial"])

        asyncio.run(exercise())

    def test_capacity_watchdog_drains_provider_and_queues_full_report(self):
        class Provider:
            def __init__(self):
                self.events = asyncio.Queue()
                self.input_seen = self.flushed = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                pass

            async def send(self, raw):
                event = json.loads(raw)
                if event["type"] == "session.create":
                    self.events.put_nowait(json.dumps({"type": "session.created"}))
                elif event["type"] == "input_audio_buffer.append":
                    if any(base64.b64decode(event["audio"])):
                        self.input_seen = True
                    elif self.input_seen and not self.flushed:
                        self.flushed = True
                        for item in (
                            {"type": "conversation.item.input_audio_transcription.started",
                             "item_id": "final-sales"},
                            {"type": "conversation.item.input_audio_transcription.completed",
                             "item_id": "final-sales", "text": "最后确认交期。"},
                            {"type": "response.output_text.done", "response_id": "final-reply",
                             "question_id": "final-sales", "text": "交期已确认。"},
                            {"type": "response.output_audio.done", "response_id": "final-reply",
                             "question_id": "final-sales"},
                        ):
                            self.events.put_nowait(json.dumps(item))
                elif event["type"] == "session.close":
                    self.events.put_nowait(json.dumps({"type": "session.closed"}))

            async def recv(self):
                return await self.events.get()

        class Browser:
            def __init__(self):
                self.cookies = {}
                self.incoming = asyncio.Queue()
                self.events = []

            async def accept(self):
                pass

            async def close(self, **_):
                pass

            async def receive(self):
                return await self.incoming.get()

            async def send_json(self, event):
                self.events.append(event["type"])
                if event["type"] == "ready":
                    for payload in (b"\x01\x00" * 320, b"\x00\x00" * 320):
                        self.incoming.put_nowait({"type": "websocket.receive", "bytes": payload})

            async def send_bytes(self, *_):
                pass

        async def authorize(*_):
            return self.user

        with Session(self.engine) as db:
            for seq in range(1, 359):
                db.add(OmegaSegment(session_id=self.session_id, seq=seq,
                                    speaker="sales" if seq % 2 else "counterparty",
                                    text="test", provider_event_id=f"prior-{seq}"))
            db.commit()

        async def exercise():
            browser = Browser()
            provider = Provider()
            with Session(self.engine) as db, \
                 patch("app.omega.realtime.is_enabled", return_value=True), \
                 patch("app.omega.realtime._trusted_origin", return_value=True), \
                 patch("app.omega.realtime.ws_user", side_effect=authorize), \
                 patch("app.omega.realtime.connect", return_value=provider), \
                 patch.dict("os.environ", {"PDCA_OMEGA_REALTIME_PROVIDER": "doubao",
                                         "PDCA_DOUBAO_REALTIME_API_KEY": "synthetic-no-network"}):
                await asyncio.wait_for(realtime_session(browser, self.session_id, db), 6)
            self.assertIn("ending", browser.events)
            self.assertIn("closed", browser.events)

        asyncio.run(exercise())
        with Session(self.engine) as db:
            job = db.exec(select(OmegaJob).where(OmegaJob.kind == "realtime")).one()
            self.assertEqual(job.status, "succeeded")
            self.assertEqual(job.error, "")
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 360)
            ended = finish_session(self.session_id, OperationRequest(request_key="capacity-report"),
                                   self.user, db)
            self.assertEqual(ended["status"], "ended")
            self.assertTrue(ended["pending_job_id"])
            self.assertFalse(ended["report_partial"])

    def test_watchdog_starts_drain_before_hard_deadline(self):
        class Browser:
            def __init__(self):
                self.events = []

            async def send_json(self, event):
                self.events.append(event)

        async def exercise():
            loop = asyncio.get_running_loop()
            control = SimpleNamespace(deadline=loop.time() + .25, ending=False)
            browser = Browser()
            started = loop.time()
            with patch("app.omega.realtime._max_connection_seconds", .25), \
                 patch("app.omega.realtime._watchdog_drain_grace_seconds", .1, create=True), \
                 patch("app.omega.realtime._auth_interval_seconds", .5):
                await _watch_connection(browser, self.engine, self.session_id,
                                        "synthetic-job", "synthetic-token", control)
            elapsed = loop.time() - started
            self.assertTrue(control.ending)
            self.assertEqual(browser.events[0]["type"], "ending")
            self.assertIn("接近时长上限", browser.events[0]["message"])
            self.assertGreater(elapsed, .1)
            self.assertLess(elapsed, .22, "The old hard deadline leaves no tail-drain grace")

        asyncio.run(exercise())

    def test_watchdog_warns_once_before_automatic_end(self):
        class Browser:
            def __init__(self):
                self.events = []

            async def send_json(self, event):
                self.events.append(event)

        async def exercise():
            loop = asyncio.get_running_loop()
            control = SimpleNamespace(deadline=loop.time() + .25, ending=False)
            browser = Browser()
            with patch("app.omega.realtime._max_connection_seconds", .25), \
                 patch("app.omega.realtime._watchdog_warning_seconds", .16, create=True), \
                 patch("app.omega.realtime._watchdog_drain_grace_seconds", .04), \
                 patch("app.omega.realtime._renew"), \
                 patch("app.omega.realtime._auth_interval_seconds", .5):
                await _watch_connection(browser, self.engine, self.session_id,
                                        "synthetic-job", "synthetic-token", control)
            self.assertEqual([event["type"] for event in browser.events],
                             ["ending_soon", "ending"])
            self.assertEqual(browser.events[0]["seconds_remaining"], .16)

        asyncio.run(exercise())

    def test_watchdog_still_drains_if_browser_cannot_receive_ending(self):
        class Browser:
            async def send_json(self, event):
                raise RuntimeError("browser closed")

        async def exercise():
            loop = asyncio.get_running_loop()
            control = SimpleNamespace(deadline=loop.time() + .08, ending=False)
            with patch("app.omega.realtime._max_connection_seconds", .08), \
                 patch("app.omega.realtime._watchdog_drain_grace_seconds", .04), \
                 patch("app.omega.realtime._renew"), \
                 patch("app.omega.realtime._auth_interval_seconds", .5):
                await _watch_connection(Browser(), self.engine, self.session_id,
                                        "synthetic-job", "synthetic-token", control)
            self.assertTrue(control.ending)

        asyncio.run(exercise())

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
                self.assertIn("语音尾稿未完成", job.error)

        asyncio.run(exercise())
