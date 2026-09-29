"""Omega realtime protocol and access regression checks."""
from __future__ import annotations

import unittest
import base64
import json
import tempfile
import asyncio
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.auth.deps import get_current_user
from app.auth.security import create_access_token
from app.config import get_settings
from app.database import get_session
from app.main import app
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaJob, OmegaSegment, OmegaSession
from app.omega.realtime import _acquire, _append, _receive_audio, _release, _renew
from app.omega.realtime import _provider_url


class RealtimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(self.temp.name) / "realtime.sqlite"
        self.engine = create_engine(f"sqlite:///{path.as_posix()}",
                                    connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self.user = User(id=1, username="voice-seller", role="sales", team_key="team-a")
        with Session(self.engine) as db:
            db.add(User(id=1, username="voice-seller", role="sales", team_key="team-a",
                        hashed_password="test-only", is_active=True,
                        must_change_password=False))
            case = OmegaCase(team_key="team-a", owner_id=1, title="Realtime",
                             draft_json=json.dumps({"public_brief": "Known account details",
                                                    "counterparty_brief": "Customer wants a plan"}))
            db.add(case)
            db.flush()
            version = OmegaCaseVersion(case_id=case.id, version=1,
                                       snapshot_json=case.draft_json, content_hash="x" * 64,
                                       confirmed_by=1)
            db.add(version)
            db.flush()
            game = OmegaSession(case_id=case.id, case_version_id=version.id,
                                team_key="team-a", owner_id=1)
            db.add(game)
            db.commit()
            self.session_id = game.id

        def override():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_session] = override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    def test_one_stream_and_frozen_transcript(self):
        job_id, token, role = _acquire(self.engine, self.user, self.session_id)
        self.assertNotIn("seller_private", role)
        with self.assertRaises(HTTPException) as duplicate:
            _acquire(self.engine, self.user, self.session_id)
        self.assertEqual(duplicate.exception.status_code, 409)
        _renew(self.engine, self.session_id, job_id, token)
        first = _append(self.engine, self.session_id, job_id, token, "sales", "Can you pay Friday?")
        second = _append(self.engine, self.session_id, job_id, token, "counterparty", "Friday works.")
        self.assertEqual((first["seq"], second["seq"]), (1, 2))
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            game.status = "ended"
            db.commit()
        with self.assertRaises(ValueError):
            _append(self.engine, self.session_id, job_id, token, "sales", "Late statement")
        _release(self.engine, job_id, token, failed=False)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, job_id).status, "succeeded")
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)

    def test_authenticated_stop_releases_stream_before_reconnect(self):
        first_job, _, _ = _acquire(self.engine, self.user, self.session_id)
        url = f"/api/omega/sessions/{self.session_id}/realtime/stop"
        app.dependency_overrides[get_current_user] = lambda: User(
            id=2, username="outsider", role="sales", team_key="other-team")
        with patch("app.omega.realtime.is_enabled", return_value=True):
            rejected = self.client.post(url, headers={"Origin": "http://testserver"})
            self.assertEqual(rejected.status_code, 404)
            app.dependency_overrides[get_current_user] = lambda: self.user
            accepted = self.client.post(url, headers={"Origin": "http://testserver"})
            self.assertEqual(accepted.status_code, 200)
            repeated = self.client.post(url, headers={"Origin": "http://testserver"})
            self.assertEqual(repeated.status_code, 200)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, first_job).status, "succeeded")
        second_job, _, _ = _acquire(self.engine, self.user, self.session_id)
        self.assertNotEqual(first_job, second_job)

    def test_cross_origin_socket_is_rejected(self):
        from starlette.websockets import WebSocketDisconnect

        with patch("app.omega.realtime.is_enabled", return_value=True):
            with self.assertRaises(WebSocketDisconnect) as rejected:
                with self.client.websocket_connect(
                    f"/api/omega/sessions/{self.session_id}/realtime",
                    headers={"Origin": "https://outside.example"},
                ):
                    pass
        self.assertEqual(rejected.exception.code, 1008)

    def test_spa_document_allows_microphone_after_client_side_navigation(self):
        for path in ("/app", "/app/omega"):
            response = self.client.get(path)
            self.assertIn("microphone=(self)", response.headers["permissions-policy"])
        response = self.client.get("/api/omega/status")
        self.assertIn("microphone=()", response.headers["permissions-policy"])

    def test_missing_provider_credentials_reports_error_without_lease(self):
        async def authorize(*_):
            return self.user

        with patch("app.omega.realtime.is_enabled", return_value=True), \
             patch("app.omega.realtime.ws_user", side_effect=authorize), \
             patch("app.omega.realtime.configured", return_value=False):
            with self.client.websocket_connect(
                f"/api/omega/sessions/{self.session_id}/realtime",
                headers={"Origin": "http://testserver"},
            ) as socket:
                self.assertIn("尚未配置", socket.receive_json()["message"])
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaJob)).all(), [])

    def test_cookie_authentication_on_real_websocket_path(self):
        token = create_access_token({"sub": "voice-seller"})
        with patch.object(get_settings(), "auth_mode", "local"), \
             patch("app.omega.realtime.is_enabled", return_value=True), \
             patch("app.omega.realtime.configured", return_value=False):
            with self.client.websocket_connect(
                f"/api/omega/sessions/{self.session_id}/realtime",
                headers={"Origin": "http://testserver"},
            ) as socket:
                self.assertIn("未登录", socket.receive_json()["message"])
            self.client.cookies.set("pdca_token", token)
            with self.client.websocket_connect(
                f"/api/omega/sessions/{self.session_id}/realtime",
                headers={"Origin": "http://testserver"},
            ) as socket:
                self.assertIn("尚未配置", socket.receive_json()["message"])

    def test_mock_provider_streams_audio_and_persists_final_words(self):
        class Provider:
            def __init__(self):
                self.queue = asyncio.Queue()
                self.audio_sent = False
                self.queue.put_nowait(json.dumps({"type": "session.created"}))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def send(self, frame):
                event = json.loads(frame)
                if event["type"] == "session.update":
                    self.role = event["session"]["instructions"]
                    self.queue.put_nowait(json.dumps({"type": "session.updated"}))
                elif event["type"] == "input_audio_buffer.append" and not self.audio_sent:
                    self.audio_sent = True
                    self.input_audio = base64.b64decode(event["audio"])
                    for item in (
                        {"type": "conversation.item.input_audio_transcription.delta",
                         "item_id": "user-1", "text": "Can you pay", "stash": " Friday?"},
                        {"type": "conversation.item.input_audio_transcription.completed",
                         "item_id": "user-1", "transcript": "Can you pay Friday?"},
                        {"type": "response.created", "response": {"id": "reply-1"}},
                        {"type": "response.audio_transcript.delta", "response_id": "reply-1",
                         "item_id": "bot-1", "delta": "Friday works."},
                        {"type": "response.audio.delta", "response_id": "reply-1",
                         "delta": base64.b64encode(b"\x00\x20").decode()},
                        {"type": "response.audio_transcript.done", "response_id": "reply-1",
                         "item_id": "bot-1", "transcript": "Friday works."},
                        {"type": "response.done", "response": {"id": "reply-1", "status": "completed"}},
                        {"type": "input_audio_buffer.speech_started"},
                    ):
                        self.queue.put_nowait(json.dumps(item))

            async def recv(self):
                return await self.queue.get()

        async def authorize(*_):
            return self.user

        provider = Provider()
        with patch("app.omega.realtime.is_enabled", return_value=True), \
             patch("app.omega.realtime.ws_user", side_effect=authorize), \
             patch("app.omega.realtime.configured", return_value=True), \
             patch("app.omega.realtime.connect", return_value=provider) as connect_mock, \
             patch.dict("os.environ", {"PDCA_QWEN_REALTIME_WORKSPACE_ID": "test-space",
                                    "PDCA_QWEN_REALTIME_API_KEY": "test-only"}):
            with self.client.websocket_connect(
                f"/api/omega/sessions/{self.session_id}/realtime",
                headers={"Origin": "http://testserver"},
            ) as socket:
                self.assertEqual(socket.receive_json(), {"type": "ready"})
                socket.send_bytes(b"\x00\x00" * 320)
                segments = []
                audio = None
                for _ in range(8):
                    message = socket.receive()
                    if message.get("bytes"):
                        audio = message["bytes"]
                    elif message.get("text"):
                        event = json.loads(message["text"])
                        if event.get("type") == "segment":
                            segments.append(event["segment"])
                    if len(segments) == 2 and audio:
                        break
                self.assertEqual([part["speaker"] for part in segments],
                                 ["sales", "counterparty"])
                self.assertEqual(audio, b"\x00\x20")
                self.assertEqual(socket.receive_json(), {"type": "interrupt"})
                socket.send_text("stop")
        headers = connect_mock.call_args.kwargs["additional_headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-only")
        self.assertIn("model=qwen-audio-3.1-realtime-plus", connect_mock.call_args.args[0])
        self.assertIn("counterparty", provider.role)
        self.assertEqual(provider.input_audio, b"\x00\x00" * 320)
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)

    def test_provider_url_rejects_invalid_workspace_id(self):
        with patch.dict("os.environ", {"PDCA_QWEN_REALTIME_WORKSPACE_ID": "other.host/path"}):
            with self.assertRaisesRegex(ValueError, "业务空间 ID"):
                _provider_url()

    def test_reconnect_replays_recent_completed_turns(self):
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
        _append(self.engine, self.session_id, job_id, token, "sales", "Can you pay Friday?")
        _append(self.engine, self.session_id, job_id, token, "counterparty", "Friday works.")
        _release(self.engine, job_id, token, failed=False)
        _, _, role = _acquire(self.engine, self.user, self.session_id)
        self.assertIn("Can you pay Friday?", role)
        self.assertIn("Friday works.", role)
        self.assertNotIn("seller_private", role)

    def test_interrupted_reply_is_not_saved_or_played(self):
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)

        class Browser:
            def __init__(self):
                self.events = []
                self.audio = []

            async def send_json(self, event):
                self.events.append(event)

            async def send_bytes(self, audio):
                self.audio.append(audio)

        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "conversation.item.input_audio_transcription.completed",
                     "item_id": "user-1", "transcript": "Can you pay Friday?"},
                    {"type": "response.created", "response": {"id": "reply-1"}},
                    {"type": "response.audio_transcript.delta", "response_id": "reply-1",
                     "item_id": "bot-1", "delta": "Friday"},
                    {"type": "input_audio_buffer.speech_started"},
                    {"type": "response.audio.delta", "response_id": "reply-1",
                     "delta": base64.b64encode(b"\x00\x20").decode()},
                    {"type": "response.audio_transcript.done", "response_id": "reply-1",
                     "item_id": "bot-1", "transcript": "Friday works."},
                    {"type": "response.done", "response": {"id": "reply-1", "status": "cancelled"}},
                ])
                self.sent = []

            async def recv(self):
                try:
                    return json.dumps(next(self.events))
                except StopIteration:
                    raise EOFError from None

            async def send(self, event):
                self.sent.append(json.loads(event))

        browser, provider = Browser(), Provider()
        with self.assertRaises(EOFError):
            asyncio.run(_receive_audio(browser, provider, self.engine,
                                       self.session_id, job_id, token))
        self.assertEqual(provider.sent, [])
        self.assertIn({"type": "interrupt"}, browser.events)
        self.assertEqual(browser.audio, [])
        with Session(self.engine) as db:
            self.assertEqual([part.speaker for part in db.exec(select(OmegaSegment)).all()],
                             ["sales"])
