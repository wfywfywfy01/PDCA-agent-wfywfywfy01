"""Pause recovery races; isolated SQLite and mock transports, never real audio."""
import asyncio
import json
import unittest
from unittest.mock import patch

from sqlmodel import Session, select

import tests.test_omega_coaching as coaching_fixture
from app.auth.models import User
from app.omega.models import OmegaJob, OmegaSegment, OmegaSession
from app.omega.realtime import VoiceControl, _receive_doubao_audio, _release, realtime_session


class Browser:
    def __init__(self):
        self.events, self.audio = [], []
        self.started, self.saved = asyncio.Event(), asyncio.Event()

    async def send_json(self, event):
        self.events.append(event)
        if event["type"] == "interrupt":
            self.started.set()
        if event["type"] == "segment":
            self.saved.set()

    async def send_bytes(self, audio):
        self.audio.append(audio)

    async def accept(self):
        pass

    async def close(self, **kwargs):
        pass

    async def receive(self):
        await asyncio.Event().wait()


class Provider:
    def __init__(self):
        self.queue = asyncio.Queue()

    async def send(self, raw):
        pass

    async def recv(self):
        return json.dumps(await self.queue.get())


class PauseRecoveryTests(unittest.TestCase):
    setUp = coaching_fixture.CoachingTests.setUp
    tearDown = coaching_fixture.CoachingTests.tearDown

    async def control(self, control, browser, provider, action):
        with patch("app.omega.realtime.provider_name", return_value="doubao"):
            await control.handle(browser, provider, {"type": "control", "action": action,
                "request_key": "recovery-" + action, "audio_epoch": control.epoch + 1})

    def receiver(self, control, browser, provider):
        return asyncio.create_task(_receive_doubao_audio(browser, provider, self.engine,
            self.session_id, self.job_id, self.token, control=control))

    def test_old_final_cannot_certify_fresh_resumed_pcm_or_lose_its_transcript(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            browser, provider = Browser(), Provider()
            control.sent_audio(b"\0\x20")
            receiving = self.receiver(control, browser, provider)
            resuming = tail = None
            try:
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.started", "item_id": "old"})
                await asyncio.wait_for(browser.started.wait(), 1)
                await self.control(control, browser, provider, "pause")
                resuming = asyncio.create_task(self.control(control, browser, provider, "resume"))
                await asyncio.sleep(.05)
                # Match the browser: fresh PCM starts only once the server opens its gate.
                sent_fresh = not control.paused
                if sent_fresh:
                    control.sent_audio(b"\0\x30")
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.completed",
                                         "item_id": "old", "text": "Old public utterance"})
                await asyncio.wait_for(browser.saved.wait(), 1)
                await asyncio.wait_for(resuming, 2)
                if not sent_fresh:
                    control.sent_audio(b"\0\x30")
                await control.start_silence(provider)
                tail = asyncio.create_task(control.wait_input_tail())
                await asyncio.sleep(1.1)
                self.assertFalse(tail.done(), "Old final incorrectly certified the resumed PCM")
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.started", "item_id": "new"})
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.completed",
                                         "item_id": "new", "text": "Fresh resumed utterance"})
                await asyncio.wait_for(tail, 2)
                await control.stop_silence()
                _release(self.engine, self.job_id, self.token, failed=False,
                    incomplete=control.tail_incomplete or bool(control.active_inputs)
                    or bool(control.pending_input and control.pending_nonzero))
                with Session(self.engine) as db:
                    self.assertEqual([part.text for part in db.exec(select(OmegaSegment).order_by(OmegaSegment.seq))],
                                     ["Old public utterance", "Fresh resumed utterance"])
                    self.assertEqual(db.get(OmegaJob, self.job_id).status, "succeeded")
            finally:
                await asyncio.gather(control.stop_silence(), return_exceptions=True)
                tasks = [task for task in (receiving, resuming, tail) if task is not None]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run(exercise())

    def test_delayed_pre_pause_started_cannot_revive_old_audio_after_resume(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            browser, provider = Browser(), Provider()
            control.sent_audio(b"\0\x20")
            receiving = self.receiver(control, browser, provider)
            resuming = None
            try:
                await self.control(control, browser, provider, "pause")
                resuming = asyncio.create_task(self.control(control, browser, provider, "resume"))
                await asyncio.sleep(.05)
                # The accepted pre-pause PCM has not received an ASR identity until now.
                for event in [
                    {"type": "conversation.item.input_audio_transcription.started", "item_id": "late-old"},
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "late-old", "text": "Pre-pause public speech"},
                    {"type": "response.output_audio.started", "response_id": "old-reply", "question_id": "late-old"},
                    {"type": "response.output_text.done", "text": "Old reply"},
                    {"type": "response.output_audio.delta", "delta": "ACA="},
                    {"type": "response.output_audio.done"},
                ]:
                    await provider.queue.put(event)
                await asyncio.wait_for(browser.saved.wait(), 1)
                await asyncio.wait_for(resuming, 2)
                # Even a further late output frame must stay blocked after the ACK.
                await provider.queue.put({"type": "response.output_audio.delta", "response_id": "old-reply",
                                         "question_id": "late-old", "delta": "ACA="})
                await provider.queue.put({"type": "session.closed"})
                await asyncio.wait_for(receiving, 1)
                self.assertEqual(control.state, "listening")
                self.assertEqual(browser.audio, [])
                with Session(self.engine) as db:
                    self.assertEqual([part.text for part in db.exec(select(OmegaSegment))], ["Pre-pause public speech"])
            finally:
                await asyncio.gather(control.stop_silence(), return_exceptions=True)
                tasks = [task for task in (receiving, resuming) if task is not None]
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.run(exercise())

    async def failed_keepalive_session(self, *, provider_closes, cancel_after=None):
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            game.voice_state = "coaching"
            db.commit()
        class FailingProvider:
            def __init__(self):
                self.calls = 0
            async def send(self, raw):
                self.calls += 1
                if self.calls > 1:
                    raise RuntimeError("Synthetic zero PCM transport failure")
            async def recv(self):
                if provider_closes:
                    await asyncio.sleep(.15)
                    return json.dumps({"type": "session.closed"})
                await asyncio.Event().wait()
        provider = FailingProvider()
        class Connection:
            async def __aenter__(self):
                return provider
            async def __aexit__(self, *args):
                pass
        async def user(*args):
            return self.user
        async def handshake(*args):
            pass
        browser = Browser()
        with Session(self.engine) as db, \
             patch("app.omega.realtime.is_enabled", return_value=True), \
             patch("app.omega.realtime._trusted_origin", return_value=True), \
             patch("app.omega.realtime.ws_user", side_effect=user), \
             patch("app.omega.realtime.provider_name", return_value="doubao"), \
             patch("app.omega.realtime.configured", return_value=True), \
             patch("app.omega.realtime._acquire", return_value=(self.job_id, self.token, "Synthetic role")), \
             patch("app.omega.realtime.connect", return_value=Connection()), \
             patch("app.omega.realtime._doubao_handshake", side_effect=handshake), \
             patch.dict("os.environ", {"PDCA_DOUBAO_REALTIME_API_KEY": "synthetic-no-network"}):
            if cancel_after is None:
                await asyncio.wait_for(realtime_session(browser, self.session_id, db), 5)
            else:
                running = asyncio.create_task(realtime_session(browser, self.session_id, db))
                await asyncio.sleep(cancel_after)
                running.cancel()
                await asyncio.wait_for(running, 1)
        self.assertGreater(provider.calls, 1)
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, self.job_id).status, "failed")
        if cancel_after is None:
            self.assertIn("error", [event["type"] for event in browser.events])

    def test_zero_pcm_send_failure_cannot_be_recorded_as_success_on_normal_close(self):
        asyncio.run(self.failed_keepalive_session(provider_closes=True))

    def test_zero_pcm_send_failure_ends_session_when_provider_receive_stalls(self):
        asyncio.run(self.failed_keepalive_session(provider_closes=False))

    def test_request_cancellation_cannot_erase_known_zero_pcm_send_failure(self):
        asyncio.run(self.failed_keepalive_session(provider_closes=False, cancel_after=.15))

    def test_empty_asr_final_rechecks_disabled_owner_before_closing_tail(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
            browser, provider = Browser(), Provider()
            control.sent_audio(b"\0\x20")
            receiving = self.receiver(control, browser, provider)
            try:
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.started", "item_id": "empty-final"})
                await asyncio.wait_for(browser.started.wait(), 1)
                with Session(self.engine) as db:
                    owner = db.get(User, self.user.id)
                    owner.is_active = False
                    db.commit()
                await provider.queue.put({"type": "conversation.item.input_audio_transcription.completed", "item_id": "empty-final"})
                await provider.queue.put({"type": "session.closed"})
                with self.assertRaisesRegex(ValueError, "创建者账号已失效"):
                    await asyncio.wait_for(receiving, 1)
                self.assertTrue(control.active_inputs)
                self.assertTrue(control.pending_nonzero)
            finally:
                if not receiving.done():
                    receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
        asyncio.run(exercise())
