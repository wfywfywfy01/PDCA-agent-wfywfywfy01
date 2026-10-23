"""Native provider generation boundaries with non-speech microphone samples."""
import asyncio
import base64
import json
import unittest
from unittest.mock import patch

from sqlmodel import Session, select

import tests.test_omega_coaching as fixture
from app.auth.models import User
from app.omega.models import OmegaJob, OmegaSegment
from app.omega import realtime as realtime_module
from app.omega.realtime import DoubaoStream, VoiceControl, _receive_doubao_audio, realtime_session
from app.omega.router import VOICE_TAIL_INCOMPLETE


class VoiceBoundaryTests(unittest.TestCase):
    setUp = fixture.CoachingTests.setUp
    tearDown = fixture.CoachingTests.tearDown

    async def exercise(self, *, late_final=False, missing_final=False, revoke=False,
                       missing_close=False, stop_only=False, reuse_ids=False,
                       commit_required=False, commit_ack_only=False,
                       finalized_before_close=False, fail_new_handshake=False):
        owner = self
        transports = []

        class Provider:
            def __init__(self, generation):
                self.generation = generation
                self.events = asyncio.Queue()
                self.sent = []
                self.roles = []
                self.spoken = False
                self.closed = False

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                self.closed = True

            async def send(self, raw):
                event = json.loads(raw)
                self.sent.append(event['type'])
                if event['type'] == 'session.create':
                    self.roles.append(event['session']['instructions'])
                    self.events.put_nowait({'type': 'session.created'})
                elif event['type'] == 'input_audio_buffer.commit':
                    self.events.put_nowait({'type': 'input_audio_buffer.committed'})
                    if commit_required and not commit_ack_only:
                        self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.completed',
                                                'item_id': 'unfinished', 'text': 'Accepted unfinished public speech'})
                elif event['type'] == 'session.close':
                    if self.generation == 0 and (late_final or missing_final):
                        self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.started', 'item_id': 'late-old'})
                        if late_final:
                            self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'late-old', 'text': 'Accepted old public speech'})
                            self.events.put_nowait({'type': 'response.output_audio.started', 'response_id': 'old-reply', 'question_id': 'late-old'})
                            self.events.put_nowait({'type': 'response.output_audio.delta', 'delta': 'ACA='})
                    if revoke:
                        with Session(owner.engine) as db:
                            db.get(User, owner.user.id).is_active = False
                            db.commit()
                    if not missing_close:
                        self.events.put_nowait({'type': 'session.closed'})
                elif event['type'] == 'input_audio_buffer.append':
                    pcm = base64.b64decode(event['audio'])
                    if finalized_before_close and not self.spoken and any(pcm):
                        self.spoken = True
                        self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.started',
                                                'item_id': 'finished-before-close'})
                        self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.completed',
                                                'item_id': 'finished-before-close', 'text': 'Accepted public speech'})
                        return
                    if commit_required and self.generation == 0:
                        if not self.spoken and any(pcm):
                            self.spoken = True
                            self.events.put_nowait({'type': 'conversation.item.input_audio_transcription.started',
                                                    'item_id': 'unfinished'})
                        return
                    if pcm != b'\x20\x00' * 320 or self.spoken:
                        return
                    self.spoken = True
                    input_id = 'late-old' if reuse_ids else 'fresh'
                    response_id = 'old-reply' if reuse_ids else 'fresh-reply'
                    for item in (
                        {'type': 'conversation.item.input_audio_transcription.started', 'item_id': input_id},
                        {'type': 'conversation.item.input_audio_transcription.completed', 'item_id': input_id, 'text': 'Fresh public speech'},
                        {'type': 'response.output_audio.started', 'response_id': response_id, 'question_id': input_id},
                        {'type': 'response.output_text.done', 'text': 'Fresh opponent reply'},
                        {'type': 'response.output_audio.delta', 'delta': 'ADA='},
                        {'type': 'response.output_audio.done'},
                    ):
                        self.events.put_nowait(item)

            async def recv(self):
                return json.dumps(await self.events.get())

        class Browser:
            def __init__(self):
                self.cookies = {}
                self.incoming = asyncio.Queue()
                self.events, self.audio = [], []
                self.boundary_triggered = False

            async def accept(self):
                pass

            async def close(self, **_):
                pass

            async def receive(self):
                return await self.incoming.get()

            async def send_bytes(self, pcm):
                self.audio.append(pcm)
                self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop'})

            async def send_json(self, event):
                self.events.append(event)
                if event['type'] == 'ready':
                    self.incoming.put_nowait({'type': 'websocket.receive', 'bytes': b'\x01\x00' * 320})
                    if not commit_required:
                        self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop' if stop_only else json.dumps({'type': 'control', 'action': 'pause', 'request_key': 'boundary-pause', 'audio_epoch': 2})})
                elif event['type'] == 'interrupt' and commit_required and not self.boundary_triggered:
                    self.boundary_triggered = True
                    self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop' if stop_only else json.dumps({'type': 'control', 'action': 'pause', 'request_key': 'boundary-pause', 'audio_epoch': event['audio_epoch'] + 1})})
                elif event.get('request_key') == 'boundary-pause' and event.get('state') == 'coaching':
                    self.incoming.put_nowait({'type': 'websocket.receive', 'text': json.dumps({'type': 'control', 'action': 'resume', 'request_key': 'boundary-resume', 'audio_epoch': event['audio_epoch'] + 1})})
                elif event.get('request_key') == 'boundary-resume' and event.get('state') == 'listening':
                    self.incoming.put_nowait({'type': 'websocket.receive', 'bytes': b'\x20\x00' * 320})
                    if reuse_ids:
                        self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop'})
                elif event.get('state') == 'error':
                    self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop'})

        def connection(*args, **kwargs):
            provider = Provider(len(transports))
            transports.append(provider)
            return provider

        async def authorize(*_):
            return self.user

        original_handshake = realtime_module._doubao_handshake

        async def handshake(provider, role, **kwargs):
            if fail_new_handshake and len(transports) > 1:
                raise RuntimeError('Sensitive upstream response')
            await original_handshake(provider, role, **kwargs)

        browser = Browser()
        with Session(self.engine) as db, \
             patch('app.omega.realtime.is_enabled', return_value=True), \
             patch('app.omega.realtime._trusted_origin', return_value=True), \
             patch('app.omega.realtime.ws_user', side_effect=authorize), \
             patch('app.omega.realtime._acquire', return_value=(self.job_id, self.token, 'Synthetic public role')), \
             patch('app.omega.realtime.connect', side_effect=connection), \
             patch('app.omega.realtime._doubao_handshake', side_effect=handshake), \
             patch('app.omega.realtime.logger.warning') as logged, \
             patch.dict('os.environ', {'PDCA_OMEGA_REALTIME_PROVIDER': 'doubao', 'PDCA_DOUBAO_REALTIME_API_KEY': 'synthetic-no-network'}):
            await asyncio.wait_for(realtime_session(browser, self.session_id, db), 20)
        if commit_ack_only:
            self.assertIn(('tail_incomplete', 'asr_tail'), [call.args[1:3] for call in logged.call_args_list
                if call.args and str(call.args[0]).startswith('Omega realtime stream ended')])
        with Session(self.engine) as db:
            job = db.get(OmegaJob, self.job_id)
            saved = list(db.exec(select(OmegaSegment).order_by(OmegaSegment.seq)))
            if fail_new_handshake:
                self.assertEqual(job.status, 'failed')
                self.assertEqual(len(transports), 2)
                self.assertEqual([part.text for part in saved], ['Accepted public speech'])
                self.assertEqual(job.error, '')
                self.assertEqual(browser.audio, [])
            elif missing_final or revoke or missing_close or commit_ack_only:
                self.assertEqual(job.status, 'failed')
                self.assertEqual(len(transports), 1)
                self.assertEqual(browser.audio, [])
                if finalized_before_close and missing_close:
                    self.assertEqual([part.text for part in saved], ['Accepted public speech'])
                    self.assertEqual(job.error, VOICE_TAIL_INCOMPLETE)
            elif stop_only:
                self.assertEqual(job.status, 'succeeded')
                self.assertEqual(len(transports), 1)
                self.assertEqual(browser.audio, [])
                self.assertEqual([p.text for p in saved], ['Accepted unfinished public speech'] if commit_required else [])
            else:
                self.assertEqual(job.status, 'succeeded')
                self.assertEqual(len(transports), 2)
                self.assertEqual(browser.audio, [b'\x00\x30'])
                self.assertEqual([p.text for p in saved],
                    (['Accepted unfinished public speech'] if commit_required else ['Accepted old public speech'] if late_final else []) + ['Fresh public speech', 'Fresh opponent reply'])
                self.assertNotIn('PRIVATE_LIMIT', transports[1].roles[0])
                if late_final:
                    self.assertIn('Accepted old public speech', transports[1].roles[0])
        self.assertTrue(all(p.closed for p in transports))
        self.assertTrue(all('response.cancel' not in p.sent for p in transports))
        self.assertEqual(sum(p.sent.count('input_audio_buffer.commit') for p in transports), 1)

    def test_stop_commits_identified_speech_and_saves_final_before_close(self):
        asyncio.run(self.exercise(commit_required=True, stop_only=True))

    def test_stop_commits_overlap_pcm_after_first_asr_final(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
            control.sent_audio(b"\x01\x00")
            control.active_inputs.add("first-input")
            control.sent_audio(b"\x02\x00")
            control.active_inputs.clear()
            self.assertTrue(control.overlap_pcm)

            stream = DoubaoStream(lambda: None)

            class Provider:
                def __init__(self):
                    self.sent = []

                async def send(self, raw):
                    kind = json.loads(raw)["type"]
                    self.sent.append(kind)
                    if kind == "session.close":
                        stream.closed.set()

            stream.provider = Provider()

            async def settled_tail():
                pass

            with patch.object(control, "wait_asr_tail", side_effect=settled_tail):
                await stream.finish_input(control)
            self.assertEqual(stream.provider.sent, ["input_audio_buffer.commit", "session.close"])

        asyncio.run(exercise())

    def test_resume_commits_identified_speech_before_opening_new_stream(self):
        asyncio.run(self.exercise(commit_required=True))

    def test_commit_ack_without_identified_final_still_fails(self):
        asyncio.run(self.exercise(commit_required=True, commit_ack_only=True, stop_only=True))

    def test_non_speech_pcm_resumes_only_after_old_stream_closed_and_new_stream_ready(self):
        asyncio.run(self.exercise())

    def test_late_old_speech_is_saved_before_boundary_and_old_audio_never_replays(self):
        asyncio.run(self.exercise(late_final=True))

    def test_known_asr_without_final_still_fails_and_never_opens_new_stream(self):
        asyncio.run(self.exercise(missing_final=True))

    def test_owner_revocation_at_stream_boundary_prevents_resume(self):
        asyncio.run(self.exercise(revoke=True))

    def test_missing_close_ack_cannot_clear_unknown_microphone_samples(self):
        asyncio.run(self.exercise(missing_close=True))

    def test_missing_close_ack_marks_tail_incomplete_after_asr_finished(self):
        asyncio.run(self.exercise(missing_close=True, finalized_before_close=True))

    def test_new_handshake_failure_after_close_ack_does_not_mark_tail_incomplete(self):
        asyncio.run(self.exercise(finalized_before_close=True, fail_new_handshake=True))

    def test_non_speech_stop_requires_close_ack_and_invents_no_transcript(self):
        asyncio.run(self.exercise(stop_only=True))

    def test_new_stream_can_reuse_old_input_and_reply_ids_without_losing_turn(self):
        asyncio.run(self.exercise(late_final=True, reuse_ids=True))

    def test_resume_budget_covers_tail_close_and_new_handshake(self):
        async def exercise():
            owner = self

            class Provider:
                def __init__(self):
                    self.events = asyncio.Queue()

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_):
                    pass

                async def send(self, raw):
                    kind = json.loads(raw)["type"]
                    if kind == "session.create":
                        owner.assertFalse(control.pending_nonzero,
                                          "Acknowledged old tail must not become a false incomplete report")
                    if kind in {"session.close", "session.create"}:
                        async def acknowledge():
                            await asyncio.sleep(.06)
                            self.events.put_nowait(json.dumps({"type":
                                "session.closed" if kind == "session.close" else "session.created"}))
                        asyncio.create_task(acknowledge())

                async def recv(self):
                    return await self.events.get()

            class Browser:
                def __init__(self):
                    self.events = []

                async def send_json(self, event):
                    self.events.append(event)

            original_wait_for = asyncio.wait_for

            async def compressed_budget(awaitable, timeout):
                # Real substeps may take 8s ASR + 5s close + 10s handshake.
                return await original_wait_for(awaitable, timeout / 100 if timeout >= 12 else timeout)

            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            control._save("coaching")
            control.sent_audio(b"\0\x20")
            stream = DoubaoStream(Provider)
            await stream.__aenter__()
            browser = Browser()
            receiving = asyncio.create_task(stream.recv())
            try:
                async def tail():
                    await asyncio.sleep(.08)
                with patch.object(control, "wait_asr_tail", side_effect=tail), \
                     patch("app.omega.realtime.provider_name", return_value="doubao"), \
                     patch("app.omega.realtime.asyncio.wait_for", side_effect=compressed_budget):
                    await control.handle(browser, stream, {"type": "control", "action": "resume",
                        "request_key": "resume-slow-boundary", "audio_epoch": 2})
                self.assertEqual(control.state, "listening")
                self.assertEqual(browser.events[-1]["state"], "listening")
            finally:
                receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
                await stream.__aexit__(None, None, None)

        asyncio.run(exercise())

    def test_resume_failure_logs_phase_and_category_without_provider_text(self):
        class FailingStream(DoubaoStream):
            async def finish_input(self, control, *, restart=False):
                self.boundary_phase = "handshake"
                raise RuntimeError("sensitive provider response")

        class Browser:
            def __init__(self):
                self.events = []

            async def send_json(self, event):
                self.events.append(event)

        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            control._save("coaching")
            browser = Browser()
            with patch("app.omega.realtime.provider_name", return_value="doubao"), \
                 patch("app.omega.realtime.logger.warning") as warning:
                await control.handle(browser, FailingStream(lambda: None),
                    {"type": "control", "action": "resume", "request_key": "resume-log",
                     "audio_epoch": 2})
            self.assertEqual(browser.events[-1]["state"], "error")
            self.assertEqual(warning.call_args.args[1:], ("resume", "handshake", "RuntimeError"))
            self.assertNotIn("sensitive provider response", str(warning.call_args))

        asyncio.run(exercise())

    def test_cancelled_rotation_retries_old_transport_close_during_cleanup(self):
        async def exercise():
            closing = asyncio.Event()

            class Provider:
                def __init__(self):
                    self.events = asyncio.Queue()
                    self.close_calls = 0
                    self.closed = False

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_):
                    self.close_calls += 1
                    if self.close_calls == 1:
                        closing.set()
                        await asyncio.Event().wait()
                    self.closed = True

                async def send(self, raw):
                    if json.loads(raw)['type'] == 'session.close':
                        self.events.put_nowait({'type': 'session.closed'})

                async def recv(self):
                    return json.dumps(await self.events.get())

            class Browser:
                async def send_json(self, event):
                    pass

            provider = Provider()
            stream = DoubaoStream(lambda: provider)
            await stream.__aenter__()
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            receiving = asyncio.create_task(_receive_doubao_audio(Browser(), stream, self.engine,
                self.session_id, self.job_id, self.token, control=control))
            rotating = asyncio.create_task(stream.finish_input(control, restart=True))
            try:
                await asyncio.wait_for(closing.wait(), 2)
                rotating.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await rotating
                await asyncio.wait_for(stream.__aexit__(None, None, None), 1)
                self.assertEqual(provider.close_calls, 2)
                self.assertTrue(provider.closed)
                self.assertFalse(stream.entered)
                self.assertTrue(control.boundary_failed)
                self.assertFalse(stream.reopened.is_set())
            finally:
                for task in (receiving, rotating):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(receiving, rotating, return_exceptions=True)
                await asyncio.wait_for(stream.__aexit__(None, None, None), 1)
        asyncio.run(exercise())

    def test_cancelled_outer_exit_can_retry_transport_close(self):
        async def exercise():
            closing = asyncio.Event()

            class Provider:
                def __init__(self):
                    self.close_calls, self.closed = 0, False

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_):
                    self.close_calls += 1
                    if self.close_calls == 1:
                        closing.set()
                        await asyncio.Event().wait()
                    self.closed = True

            provider = Provider()
            stream = DoubaoStream(lambda: provider)
            await stream.__aenter__()
            exiting = asyncio.create_task(stream.__aexit__(None, None, None))
            try:
                await asyncio.wait_for(closing.wait(), 1)
                exiting.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await exiting
                await asyncio.wait_for(stream.__aexit__(None, None, None), 1)
                self.assertEqual(provider.close_calls, 2)
                self.assertTrue(provider.closed)
                self.assertFalse(stream.entered)
            finally:
                if not exiting.done():
                    exiting.cancel()
                await asyncio.gather(exiting, return_exceptions=True)
                await asyncio.wait_for(stream.__aexit__(None, None, None), 1)
        asyncio.run(exercise())
