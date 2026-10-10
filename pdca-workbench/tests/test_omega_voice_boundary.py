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
from app.omega.realtime import DoubaoStream, VoiceControl, _receive_doubao_audio, realtime_session


class VoiceBoundaryTests(unittest.TestCase):
    setUp = fixture.CoachingTests.setUp
    tearDown = fixture.CoachingTests.tearDown

    async def exercise(self, *, late_final=False, missing_final=False, revoke=False,
                       missing_close=False, stop_only=False, reuse_ids=False):
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
                self.incoming = asyncio.Queue()
                self.events, self.audio = [], []

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
                    self.incoming.put_nowait({'type': 'websocket.receive', 'text': 'stop' if stop_only else json.dumps({'type': 'control', 'action': 'pause', 'request_key': 'boundary-pause', 'audio_epoch': 2})})
                elif event.get('request_key') == 'boundary-pause' and event.get('state') == 'coaching':
                    self.incoming.put_nowait({'type': 'websocket.receive', 'text': json.dumps({'type': 'control', 'action': 'resume', 'request_key': 'boundary-resume', 'audio_epoch': 3})})
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

        browser = Browser()
        with Session(self.engine) as db, \
             patch('app.omega.realtime.is_enabled', return_value=True), \
             patch('app.omega.realtime._trusted_origin', return_value=True), \
             patch('app.omega.realtime.ws_user', side_effect=authorize), \
             patch('app.omega.realtime._acquire', return_value=(self.job_id, self.token, 'Synthetic public role')), \
             patch('app.omega.realtime.connect', side_effect=connection), \
             patch.dict('os.environ', {'PDCA_OMEGA_REALTIME_PROVIDER': 'doubao', 'PDCA_DOUBAO_REALTIME_API_KEY': 'synthetic-no-network'}):
            await asyncio.wait_for(realtime_session(browser, self.session_id, db), 20)
        with Session(self.engine) as db:
            job = db.get(OmegaJob, self.job_id)
            saved = list(db.exec(select(OmegaSegment).order_by(OmegaSegment.seq)))
            if missing_final or revoke or missing_close:
                self.assertEqual(job.status, 'failed')
                self.assertEqual(len(transports), 1)
                self.assertEqual(browser.audio, [])
            elif stop_only:
                self.assertEqual(job.status, 'succeeded')
                self.assertEqual(len(transports), 1)
                self.assertEqual(browser.audio, [])
                self.assertEqual(saved, [])
            else:
                self.assertEqual(job.status, 'succeeded')
                self.assertEqual(len(transports), 2)
                self.assertEqual(browser.audio, [b'\x00\x30'])
                self.assertEqual([p.text for p in saved],
                    (['Accepted old public speech'] if late_final else []) + ['Fresh public speech', 'Fresh opponent reply'])
                self.assertNotIn('PRIVATE_LIMIT', transports[1].roles[0])
                if late_final:
                    self.assertIn('Accepted old public speech', transports[1].roles[0])
        self.assertTrue(all(p.closed for p in transports))
        self.assertTrue(all('response.cancel' not in p.sent and 'input_audio_buffer.commit' not in p.sent for p in transports))

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

    def test_non_speech_stop_requires_close_ack_and_invents_no_transcript(self):
        asyncio.run(self.exercise(stop_only=True))

    def test_new_stream_can_reuse_old_input_and_reply_ids_without_losing_turn(self):
        asyncio.run(self.exercise(late_final=True, reuse_ids=True))

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
