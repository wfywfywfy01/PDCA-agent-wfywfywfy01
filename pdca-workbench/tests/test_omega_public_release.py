"""Public release limits and account revocation through real application seams."""
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlmodel import Session, select

from app.auth.models import User
from app.omega.jobs import run_once
from app.omega.models import OmegaJob, OmegaSegment, OmegaSession
from app.omega.realtime import _acquire, _release, _send_audio, _renew_authorized, _watch_connection
from app.auth.security import create_access_token
from tests import test_omega_realtime as voice_fixture
from tests import test_omega_flow as flow_fixture


class PublicVoiceLimits(unittest.TestCase):
    setUp = voice_fixture.RealtimeSessionTests.setUp
    tearDown = voice_fixture.RealtimeSessionTests.tearDown

    def test_account_cannot_open_another_room_until_first_call_releases(self):
        first, token, _ = _acquire(self.engine, self.user, self.session_id)
        with Session(self.engine) as db:
            original = db.get(OmegaSession, self.session_id)
            second = OmegaSession(case_id=original.case_id, case_version_id=original.case_version_id,
                                  team_key=original.team_key, owner_id=original.owner_id)
            db.add(second)
            db.commit()
            second_id = second.id
        with self.assertRaises(HTTPException) as denied:
            _acquire(self.engine, self.user, second_id)
        self.assertEqual(denied.exception.status_code, 409)
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaJob)).all()), 1)
        _release(self.engine, first, token, failed=False)
        accepted, _, _ = _acquire(self.engine, self.user, second_id)
        self.assertNotEqual(accepted, first)

    def test_manager_can_read_but_cannot_speak_as_another_salesperson(self):
        manager = User(id=2, username='voice-manager', role='manager', team_key='team-a', hashed_password='unused-test')
        with Session(self.engine) as db:
            db.add(manager)
            db.commit()
            db.refresh(manager)
            db.expunge(manager)
        with self.assertRaises(HTTPException) as denied:
            _acquire(self.engine, manager, self.session_id)
        self.assertEqual(denied.exception.status_code, 403)

    def test_global_capacity_is_checked_before_claiming_another_user(self):
        _acquire(self.engine, self.user, self.session_id)
        with Session(self.engine) as db:
            db.add(User(id=2, username='another-seller', role='sales', team_key='team-a',
                        hashed_password='unused-test', must_change_password=False))
            original = db.get(OmegaSession, self.session_id)
            game = OmegaSession(case_id=original.case_id, case_version_id=original.case_version_id,
                                team_key=original.team_key, owner_id=2)
            db.add(game)
            db.commit()
            session_id = game.id
        actor = User(id=2, username='another-seller', role='sales', team_key='team-a')
        with patch.dict('os.environ', {'PDCA_OMEGA_REALTIME_MAX_CONNECTIONS': '1'}):
            with self.assertRaises(HTTPException) as denied:
                _acquire(self.engine, actor, session_id)
        self.assertEqual(denied.exception.status_code, 429)
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaJob)).all()), 1)

    def test_password_revocation_is_seen_with_a_fresh_session(self):
        job_id, token, _ = _acquire(self.engine, self.user, self.session_id)
        credential = create_access_token({'sub': self.user.username, 'pwd_v': 0})
        browser = SimpleNamespace(cookies={'pdca_token': credential},
                                  url=SimpleNamespace(path='/api/omega/realtime'),
                                  client=SimpleNamespace(host='external-test'), headers={})
        async def exercise():
            await _renew_authorized(browser, self.engine, self.session_id, job_id, token, 1)
            with Session(self.engine) as db:
                db.get(User, 1).pwd_version += 1
                db.commit()
            with self.assertRaises(HTTPException) as denied:
                await _renew_authorized(browser, self.engine, self.session_id, job_id, token, 1)
            self.assertEqual(denied.exception.status_code, 401)
        with patch('app.auth.deps.get_settings', return_value=SimpleNamespace(
                auth_mode='local', trust_proxy_headers=False, portal_mode='workbench')):
            asyncio.run(exercise())

    def test_control_messages_cannot_bypass_periodic_authentication(self):
        async def exercise():
            async def receive():
                await asyncio.sleep(.002)
                return {'type': 'websocket.receive', 'text': json.dumps({'type': 'pause'})}
            browser = SimpleNamespace(receive=receive, send_json=AsyncMock())
            control = SimpleNamespace(silence_error=None, boundary_failed=False,
                                      ending=False, handle=AsyncMock(), deadline=asyncio.get_running_loop().time()+1)
            with patch('app.omega.realtime._auth_interval_seconds', .01), \
                    patch('app.omega.realtime._renew_authorized', new=AsyncMock(
                        side_effect=HTTPException(401, 'revoked'))) as auth:
                with self.assertRaises(HTTPException):
                    await asyncio.wait_for(_send_audio(browser, SimpleNamespace(), self.engine,
                        self.session_id, 'unused', 'unused', control=control, actor_id=1), .2)
                auth.assert_awaited_once()
        asyncio.run(exercise())

    def test_watchdog_expires_even_when_provider_send_never_returns(self):
        async def exercise():
            async def blocked_send(_):
                await asyncio.Future()
            browser = SimpleNamespace(send_json=AsyncMock(), receive=AsyncMock(return_value={
                'type': 'websocket.receive', 'bytes': b'\x00\x00' * 320}))
            control = SimpleNamespace(silence_error=None, boundary_failed=False, ending=False,
                paused=False, sent_audio=lambda _: None, deadline=asyncio.get_running_loop().time()+.03)
            sending = asyncio.create_task(_send_audio(browser, SimpleNamespace(send=blocked_send),
                self.engine, self.session_id, 'unused', 'unused', control=control))
            try:
                with patch('app.omega.realtime._auth_interval_seconds', .5):
                    await asyncio.wait_for(_watch_connection(browser, self.engine,
                        self.session_id, 'unused', 'unused', 1, control), .2)
                self.assertTrue(control.ending)
                self.assertFalse(sending.done())
            finally:
                sending.cancel()
                await asyncio.gather(sending, return_exceptions=True)
        asyncio.run(exercise())

    def test_watchdog_revokes_even_when_provider_send_never_returns(self):
        async def exercise():
            browser = SimpleNamespace(send_json=AsyncMock())
            control = SimpleNamespace(ending=False, deadline=asyncio.get_running_loop().time()+1)
            with patch('app.omega.realtime._auth_interval_seconds', .01), \
                    patch('app.omega.realtime._renew_authorized', new=AsyncMock(
                        side_effect=HTTPException(401, 'revoked'))) as auth:
                with self.assertRaises(HTTPException):
                    await asyncio.wait_for(_watch_connection(browser, self.engine,
                        self.session_id, 'unused', 'unused', 1, control), .2)
                auth.assert_awaited_once()
        asyncio.run(exercise())

    def exercise_expiry(self, continuous=False):
        async def exercise():
            async def receive():
                if continuous:
                    return {'type': 'websocket.receive', 'bytes': b'\x00\x00' * 320}
                await asyncio.Future()
            browser = SimpleNamespace(receive=receive, send_json=AsyncMock())
            provider = SimpleNamespace(send=AsyncMock())
            control = SimpleNamespace(silence_error=None, boundary_failed=False,
                                      ending=False, paused=False, sent_audio=lambda _: None)
            with patch('app.omega.realtime._max_connection_seconds', .2, create=True):
                frames = await asyncio.wait_for(_send_audio(
                    browser, provider, self.engine, self.session_id, 'unused', 'unused',
                    control=control), 1)
            self.assertTrue(control.ending)
            self.assertEqual(browser.send_json.call_args.args[0]['type'], 'ending')
            self.assertEqual(frames > 0, continuous)
        asyncio.run(exercise())

    def test_idle_socket_has_a_fixed_lifetime(self):
        self.exercise_expiry()

    def test_continuous_silence_cannot_extend_socket_lifetime(self):
        self.exercise_expiry(continuous=True)


class PublicWorkerRevocation(unittest.TestCase):
    setUp = flow_fixture.OmegaFlowTests.setUp
    tearDown = flow_fixture.OmegaFlowTests.tearDown

    def queue_turn(self):
        case = self.client.post('/api/omega/cases', json=flow_fixture.OmegaFlowTests.case_body()).json()
        self.client.post(f"/api/omega/cases/{case['id']}/confirm").raise_for_status()
        game = self.client.post('/api/omega/sessions', json={'case_id': case['id']}).json()
        job = self.client.post(f"/api/omega/sessions/{game['id']}/turns", json={
            'request_key': 'public-revocation', 'text': '请先确认下一步。'}).json()
        return job['id']

    def deactivate(self):
        with Session(self.engine) as db:
            db.get(User, 1).is_active = False
            db.commit()

    def assert_unpublished(self, job_id):
        with Session(self.engine) as db:
            self.assertEqual(db.get(OmegaJob, job_id).status, 'failed')
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 1)

    def test_disabled_account_cannot_start_queued_model_call(self):
        job_id = self.queue_turn()
        self.deactivate()
        calls = []
        def generate(*args):
            calls.append(args)
            return '这条回复不能执行。'
        run_once(self.engine, generate=generate)
        self.assertEqual(calls, [])
        self.assert_unpublished(job_id)

    def test_disabled_account_cannot_publish_inflight_model_reply(self):
        job_id = self.queue_turn()
        def generate(*_):
            self.deactivate()
            return '这条回复不能发布。'
        run_once(self.engine, generate=generate)
        self.assert_unpublished(job_id)


class PublicProviderIdleErrors(unittest.TestCase):
    setUp = voice_fixture.RealtimeSessionTests.setUp
    tearDown = voice_fixture.RealtimeSessionTests.tearDown

    def test_known_idle_code_has_fixed_message_without_provider_text(self):
        from app.omega.realtime import _receive_doubao_audio
        for code in (45000003, '45000003'):
            with self.subTest(code=code):
                provider = SimpleNamespace(recv=AsyncMock(return_value=json.dumps({
                    'type': 'error', 'error': {'code': code, 'message': 'PRIVATE_UPSTREAM_MESSAGE'}})))
                with self.assertRaisesRegex(ValueError, '超过10分钟未交谈') as caught:
                    asyncio.run(_receive_doubao_audio(SimpleNamespace(), provider, self.engine,
                        self.session_id, 'unused', 'unused'))
                self.assertNotIn('PRIVATE_UPSTREAM_MESSAGE', str(caught.exception))

    def test_other_errors_and_malformed_error_keep_generic_failure(self):
        from app.omega.realtime import _receive_doubao_audio
        for error in ({'code': 55000001}, {'code': '450000030'}, {'code': 45000003.0},
                      {'code': True}, None, [], '45000003'):
            with self.subTest(error=error):
                provider = SimpleNamespace(recv=AsyncMock(return_value=json.dumps({
                    'type': 'error', 'error': error, 'message': 'PRIVATE_UPSTREAM_MESSAGE'})))
                with self.assertRaisesRegex(RuntimeError, '豆包实时语音处理失败'):
                    asyncio.run(_receive_doubao_audio(SimpleNamespace(), provider, self.engine,
                        self.session_id, 'unused', 'unused'))

    def exercise_idle_failure(self, *, unfinished=False):
        from app.omega.realtime import _append
        previous, token, _ = _acquire(self.engine, self.user, self.session_id)
        _append(self.engine, self.session_id, previous, token, 'sales', '请确认审批负责人。')
        _append(self.engine, self.session_id, previous, token, 'counterparty', '先说明库存风险。')
        _release(self.engine, previous, token, failed=False)

        class Provider:
            def __init__(self, idle):
                self.idle = idle
                self.events = asyncio.Queue()
            async def __aenter__(self): return self
            async def __aexit__(self, *_): return None
            async def send(self, raw):
                event = json.loads(raw)
                if event['type'] == 'session.create':
                    self.events.put_nowait({'type': 'session.created'})
                elif event['type'] == 'input_audio_buffer.append' and self.idle:
                    self.idle = False
                    self.events.put_nowait({'type': 'error', 'error': {
                        'code': 45000003, 'message': 'PRIVATE_UPSTREAM_MESSAGE'}})
                elif event['type'] == 'session.close':
                    self.events.put_nowait({'type': 'session.closed'})
            async def recv(self): return json.dumps(await self.events.get())

        async def authorize(*_): return self.user
        first, second = Provider(True), Provider(False)
        with patch('app.omega.realtime.is_enabled', return_value=True), \
                patch('app.omega.realtime.ws_user', side_effect=authorize), \
                patch('app.omega.realtime.connect', side_effect=[first, second]), \
                patch.dict('os.environ', {'PDCA_OMEGA_REALTIME_PROVIDER': 'doubao',
                                         'PDCA_DOUBAO_REALTIME_API_KEY': 'synthetic-test-only'}):
            url = f'/api/omega/sessions/{self.session_id}/realtime'
            with self.client.websocket_connect(url, headers={'Origin': 'http://testserver'}) as socket:
                ready = socket.receive_json(); self.assertEqual(ready['type'], 'ready')
                socket.send_bytes(b"\x20\x00" * 320 if unfinished else bytes(640))
                failure = socket.receive_json(); self.assertEqual(failure['type'], 'error')
                self.assertIn('超过10分钟未交谈', failure['message'])
                self.assertNotIn('PRIVATE_UPSTREAM_MESSAGE', failure['message'])
                self.assertEqual(socket.receive_json()['type'], 'closed')
            with Session(self.engine) as db:
                jobs = db.exec(select(OmegaJob).where(OmegaJob.kind == 'realtime')).all()
                self.assertEqual(sorted(job.status for job in jobs), ['failed', 'succeeded'])
                self.assertEqual(db.get(OmegaSession, self.session_id).status, 'active')
                self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)
                if unfinished:
                    from app.omega.router import require_complete_voice_tail
                    self.assertTrue(any(job.error == '语音尾稿未完成，请检查逐字稿后重新演练' for job in jobs))
                    with self.assertRaises(HTTPException) as blocked:
                        require_complete_voice_tail(db, db.get(OmegaSession, self.session_id))
                    self.assertEqual(blocked.exception.status_code, 409)
                    return
            with self.client.websocket_connect(url, headers={'Origin': 'http://testserver'}) as socket:
                resumed = socket.receive_json();self.assertEqual(resumed['type'], 'ready')
                self.assertGreater(resumed['audio_epoch'], ready['audio_epoch'])
                socket.send_text('stop')
                self.assertEqual(socket.receive_json()['type'], 'closed')
            with Session(self.engine) as db:
                self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)
                self.assertEqual(db.get(OmegaSession, self.session_id).status, 'active')

    def test_idle_failure_preserves_saved_segments_and_manual_reconnect_revalidates_epoch(self):
        self.exercise_idle_failure()

    def test_idle_failure_with_unfinished_pcm_still_blocks_report(self):
        self.exercise_idle_failure(unfinished=True)
