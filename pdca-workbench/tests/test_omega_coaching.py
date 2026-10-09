"""Private coaching boundaries; no physical microphone or provider calls."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.omega import memory_models  # noqa: F401; register immutable source foreign keys
from app.omega.models import OmegaCase, OmegaCaseVersion, OmegaJob, OmegaSegment, OmegaSession
from app.omega.coaching_models import OmegaCoachHint
from app.omega.coaching import queue_hint, run_once
from app.omega.schemas import Participant
from app.omega.realtime import VoiceControl, _acquire, _append, _receive_doubao_audio, _release, _send_audio, _speak_multi_turn


class CoachingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'coach.sqlite'}")
        SQLModel.metadata.create_all(self.engine)
        self.user = User(id=1, username="coach-owner", team_key="team-a", role="sales")
        with Session(self.engine) as db:
            db.add(User(**self.user.model_dump(), hashed_password="test-only"))
            case = OmegaCase(team_key="team-a", owner_id=1, title="Synthetic coaching")
            db.add(case)
            db.flush()
            version = OmegaCaseVersion(case_id=case.id, version=1, confirmed_by=1,
                content_hash="x" * 64, snapshot_json=json.dumps({
                    "seller_private": "PRIVATE_LIMIT", "public_brief": "Synthetic negotiation"}))
            db.add(version)
            db.flush()
            game = OmegaSession(case_id=case.id, case_version_id=version.id,
                                team_key="team-a", owner_id=1)
            db.add(game)
            db.commit()
            self.session_id = game.id
        self.job_id, self.token, _ = _acquire(self.engine, self.user, self.session_id)

    def tearDown(self):
        self.engine.dispose()
        self.temp.cleanup()

    def pause(self):
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            game.voice_state = "coaching"
            game.audio_epoch = 2
            db.commit()

    def test_hint_requires_pause_and_owner_and_is_idempotent(self):
        with Session(self.engine) as db:
            with self.assertRaises(HTTPException):
                queue_hint(db, self.user, self.session_id, "hint-one")
        self.pause()
        with Session(self.engine) as db:
            outsider = User(id=2, username="same-team", team_key="team-a", role="manager")
            with self.assertRaises(HTTPException):
                queue_hint(db, outsider, self.session_id, "hint-one")
            first = queue_hint(db, self.user, self.session_id, "hint-one")
            again = queue_hint(db, self.user, self.session_id, "hint-one")
            self.assertEqual(first.id, again.id)

    def test_hint_private_and_finish_race_discards_result(self):
        self.pause()
        with Session(self.engine) as db:
            queue_hint(db, self.user, self.session_id, "hint-one")
        prompts = []
        def generate(kind, messages, limit):
            prompts.append(messages)
            return "PRIVATE_COACH_ADVICE"
        self.assertTrue(run_once(self.engine, generate=generate))
        self.assertIn("PRIVATE_LIMIT", json.dumps(prompts))
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaSegment)).all(), [])
            self.assertEqual(db.exec(select(OmegaCoachHint)).one().text, "PRIVATE_COACH_ADVICE")
            queue_hint(db, self.user, self.session_id, "hint-two")
        def finish_during_generate(*_):
            with Session(self.engine) as db:
                game = db.get(OmegaSession, self.session_id)
                game.status = "ended"
                db.commit()
            return "LATE_PRIVATE_ADVICE"
        self.assertTrue(run_once(self.engine, generate=finish_during_generate))
        with Session(self.engine) as db:
            second = db.exec(select(OmegaCoachHint).where(OmegaCoachHint.request_key == "hint-two")).one()
            self.assertEqual(second.status, "cancelled")
            self.assertEqual(second.text, "")

    def test_pause_after_interrupt_drops_pcm_then_resume_keeps_scene(self):
        owner = self
        class Browser:
            def __init__(self):
                self.messages = iter([
                    {"type": "websocket.receive", "text": json.dumps({"type": "control",
                        "action": "pause", "request_key": "pause-one", "audio_epoch": 3})},
                    {"type": "websocket.receive", "bytes": b"\0\0"},
                    {"type": "websocket.receive", "text": json.dumps({"type": "control",
                        "action": "resume", "request_key": "resume-one", "audio_epoch": 4})},
                    {"type": "websocket.receive", "bytes": b"\0\0"},
                    {"type": "websocket.receive", "text": "stop"},
                ])
                self.events = []
            async def receive(self):
                return next(self.messages)
            async def send_json(self, event):
                self.events.append(event)
        class Provider:
            def __init__(self):
                self.sent = []
            async def send(self, event):
                self.sent.append(json.loads(event))
        browser, provider = Browser(), Provider()
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.interrupt()
        with patch("app.omega.realtime.provider_name", return_value="doubao"):
            frames = asyncio.run(_send_audio(browser, provider, self.engine,
                self.session_id, self.job_id, self.token, control=control))
        self.assertEqual(frames, 1)
        self.assertEqual(sum(event["type"] == "input_audio_buffer.append" for event in provider.sent), 1)
        self.assertEqual([event["state"] for event in browser.events if event["type"] == "state"],
                         ["pausing", "coaching", "resuming", "listening"])
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            self.assertEqual(game.audio_epoch, 4)
            self.assertEqual(game.voice_state, "listening")
            self.assertEqual(len(db.exec(select(OmegaSession)).all()), 1)

    def test_old_control_retry_is_durable_and_does_not_pause_again(self):
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        class Browser:
            def __init__(self):
                self.events = []
            async def send_json(self, event):
                self.events.append(event)
        class Provider:
            def __init__(self):
                self.sent = []
            async def send(self, raw):
                self.sent.append(json.loads(raw))
        browser, provider = Browser(), Provider()
        async def exercise():
            pause = {"type": "control", "action": "pause", "request_key": "pause-repeat", "audio_epoch": 2}
            await control.handle(browser, provider, pause)
            await control.handle(browser, provider, {"type": "control", "action": "resume",
                "request_key": "resume-repeat", "audio_epoch": 3})
            await control.handle(browser, provider, pause)
        asyncio.run(exercise())
        self.assertEqual(control.state, "listening")
        self.assertEqual(control.epoch, 3)
        self.assertEqual(browser.events[-1], {"type": "state", "state": "coaching",
                                              "audio_epoch": 2, "request_key": "pause-repeat"})
        self.assertEqual(sum(event["type"] == "response.cancel" for event in provider.sent), 2)

    def test_pause_allocates_server_epoch_after_interrupt_collision_and_retry(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
            control.interrupt()
            class Browser:
                events = []
                async def send_json(self, event):
                    self.events.append(event)
            class Provider:
                async def send(self, raw):
                    pass
            browser, provider = Browser(), Provider()
            pause = {"type": "control", "action": "pause", "request_key": "interrupt-collision", "audio_epoch": 2}
            await control.handle(browser, provider, pause)
            self.assertEqual((control.state, control.epoch), ("coaching", 3))
            await control.handle(browser, provider, pause)
            self.assertEqual((control.state, control.epoch), ("coaching", 3))
            await control.handle(browser, provider, {"type": "control", "action": "resume",
                "request_key": "collision-resume", "audio_epoch": 4})
            with self.assertRaises(ValueError):
                await control.handle(browser, provider, {"type": "control", "action": "resume",
                    "request_key": "old-resume", "audio_epoch": 3})
            self.assertEqual(browser.events[-1]["audio_epoch"], 4)
        asyncio.run(exercise())

    def test_tail_timeout_is_persisted_as_incomplete_instead_of_success(self):
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.active_inputs.add("unfinished-input")
        control.input_final.clear()
        async def timeout(coroutine, seconds):
            coroutine.close()
            raise TimeoutError
        with patch("app.omega.realtime.asyncio.wait_for", side_effect=timeout):
            with self.assertRaisesRegex(ValueError, "语音尾稿未完成"):
                asyncio.run(control.wait_input_tail())
        _release(self.engine, self.job_id, self.token, failed=False, incomplete=control.tail_incomplete)
        with Session(self.engine) as db:
            job = db.get(OmegaJob, self.job_id)
            self.assertEqual(job.status, "failed")
            self.assertEqual(job.error, "语音尾稿未完成，请检查逐字稿后重新演练")
            self.assertEqual(db.get(OmegaSession, self.session_id).voice_state, "error")

    def test_participant_cannot_claim_reserved_sales_identity(self):
        for identity in ("sales", "SALES", "Sales"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                Participant(id=identity, name="Synthetic person", is_primary=True)
        self.assertEqual(Participant(id="sales_rep", name="Synthetic person").id, "sales_rep")

    def test_durable_segment_identity_rejects_unknown_and_duplicate(self):
        first = _append(self.engine, self.session_id, self.job_id, self.token, "sales",
                        "Synthetic question", speaker_id="sales", turn_id="turn-1", provider_event_id="asr-1")
        again = _append(self.engine, self.session_id, self.job_id, self.token, "sales",
                        "Synthetic question", speaker_id="sales", turn_id="turn-1", provider_event_id="asr-1")
        self.assertEqual(first["id"], again["id"])
        with self.assertRaises(ValueError):
            _append(self.engine, self.session_id, self.job_id, self.token, "counterparty",
                    "Fake boss approval", speaker_id="unknown", turn_id="turn-1", provider_event_id="reply-1")

    def test_paused_receiver_discards_late_audio_captions_and_public_transcript(self):
        self.pause()
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        class Browser:
            def __init__(self):
                self.audio, self.events = [], []
            async def send_json(self, event):
                self.events.append(event)
            async def send_bytes(self, audio):
                self.audio.append(audio)
        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "response.output_audio.delta", "response_id": "old", "delta": "AAA="},
                    {"type": "response.output_text.done", "response_id": "old", "text": "LATE_PUBLIC"},
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "old-asr",
                     "text": "PRIVATE_COACH_QUESTION"},
                    {"type": "session.closed"},
                ])
            async def recv(self):
                return json.dumps(next(self.events))
        browser = Browser()
        asyncio.run(_receive_doubao_audio(browser, Provider(), self.engine, self.session_id,
                                         self.job_id, self.token, control=control))
        self.assertEqual((browser.audio, browser.events), ([], []))
        control.state = "listening"
        self.assertFalse(control.accepts("old"))
        self.assertFalse(control.accepts("unseen-before-new-input"))
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaSegment)).all(), [])

    def test_failed_coach_keeps_pause_and_reconnect_preserves_mute(self):
        self.pause()
        with Session(self.engine) as db:
            queue_hint(db, self.user, self.session_id, "failed-hint")
        def fail(*_):
            raise RuntimeError("test-only provider failure")
        self.assertTrue(run_once(self.engine, generate=fail))
        _release(self.engine, self.job_id, self.token, failed=True)
        job, token, role = _acquire(self.engine, self.user, self.session_id)
        control = VoiceControl(self.engine, self.session_id, job, token)
        self.assertTrue(control.paused)
        self.assertNotIn("PRIVATE_LIMIT", role)
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaCoachHint)).one().status, "failed")
            self.assertEqual(db.get(OmegaSession, self.session_id).voice_state, "coaching")

    def test_resume_rechecks_disabled_owner_and_ended_session(self):
        self.pause()
        class Browser:
            async def send_json(self, event):
                pass
        class Provider:
            def __init__(self):
                self.sent = []
            async def send(self, raw):
                self.sent.append(raw)
        for change in ("disabled", "ended"):
            with Session(self.engine) as db:
                game = db.get(OmegaSession, self.session_id)
                game.status = "ended" if change == "ended" else "active"
                db.get(User, 1).is_active = change != "disabled"
                db.commit()
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
            provider = Provider()
            with self.assertRaises(ValueError):
                asyncio.run(control.handle(Browser(), provider, {"type": "control", "action": "resume",
                    "request_key": f"resume-{change}", "audio_epoch": 3}))
            self.assertEqual(provider.sent, [])

    def test_two_valid_people_can_reply_once_per_sales_turn(self):
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            version = db.get(OmegaCaseVersion, game.case_version_id)
            snapshot = json.loads(version.snapshot_json)
            snapshot["participants"] = [{"id": "procurement", "is_primary": True}, {"id": "finance"}]
            version.snapshot_json = json.dumps(snapshot)
            db.commit()
        _append(self.engine, self.session_id, self.job_id, self.token, "sales", "Synthetic question",
                speaker_id="sales", turn_id="turn-1", provider_event_id="sales-one")
        for person in ("procurement", "finance"):
            _append(self.engine, self.session_id, self.job_id, self.token, "counterparty", "Conditional only",
                    speaker_id=person, turn_id="turn-1", provider_event_id=f"reply-{person}")
        with self.assertRaises(ValueError):
            _append(self.engine, self.session_id, self.job_id, self.token, "counterparty", "Duplicate person",
                    speaker_id="finance", turn_id="turn-1", provider_event_id="reply-finance-two")
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 3)

    def multi_turn(self):
        people = [{"id": "buyer", "name": "采购", "role": "采购", "is_primary": True},
                  {"id": "finance", "name": "小王", "role": "财务", "is_primary": False},
                  {"id": "boss", "name": "老板", "role": "经理", "is_primary": False}]
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            version = db.get(OmegaCaseVersion, game.case_version_id)
            snapshot = json.loads(version.snapshot_json)
            snapshot["participants"] = people
            version.snapshot_json = json.dumps(snapshot)
            db.commit()
        _append(self.engine, self.session_id, self.job_id, self.token, "sales", "小王，财务付款安排如何",
                speaker_id="sales", turn_id="multi-turn", provider_event_id="multi-sales")
        with Session(self.engine) as db:
            revision = db.get(OmegaSession, self.session_id).revision
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.turn_id = "multi-turn"
        return control, revision

    def test_independent_role_socket_binds_identity_before_audio_and_rejects_other_response(self):
        control, revision = self.multi_turn()
        class Browser:
            def __init__(self):
                self.audio, self.events = [], []
            async def send_json(self, event):
                self.events.append(event)
            async def send_bytes(self, audio):
                self.audio.append(audio)
        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "session.created"},
                    {"type": "response.output_audio.started", "response_id": "bound", "question_id": "tts-one"},
                    {"type": "response.output_audio.delta", "response_id": "wrong", "question_id": "tts-other", "delta": "AAA="},
                    {"type": "response.output_audio.delta", "delta": "AAA="},
                    {"type": "response.output_audio.done", "response_id": "bound", "question_id": "tts-one"},
                    {"type": "session.closed"},
                ])
                self.sent = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def send(self, event):
                self.sent.append(json.loads(event))
            async def recv(self):
                return json.dumps(next(self.events))
        browser, provider = Browser(), Provider()
        with patch("app.omega.realtime.connect", return_value=provider), \
                patch.dict("os.environ", {"PDCA_DOUBAO_REALTIME_API_KEY": "test-only"}):
            asyncio.run(_speak_multi_turn(browser, control, "multi-turn", revision, control.epoch,
                                         generate=lambda *_: "我是老板，我批准。"))
        self.assertEqual(browser.audio, [b"\0\0"])
        audio = next(event for event in browser.events if event["type"] == "audio")
        self.assertEqual((audio["speaker_id"], audio["turn_id"]), ("finance", "multi-turn"))
        self.assertEqual(provider.sent[0]["session"]["audio"]["output"]["voice"], "zh_male_yunzhou_jupiter_bigtts")
        with Session(self.engine) as db:
            reply = db.exec(select(OmegaSegment).where(OmegaSegment.speaker == "counterparty")).one()
            self.assertEqual(reply.speaker_id, "finance")
            self.assertEqual(reply.text, "我是老板，我批准。")

    def test_late_multi_model_result_is_discarded_after_interrupt(self):
        control, revision = self.multi_turn()
        def late(*_):
            control.epoch += 1
            return "STALE_MODEL_REPLY"
        with patch("app.omega.realtime.connect") as connection:
            asyncio.run(_speak_multi_turn(None, control, "multi-turn", revision, control.epoch, generate=late))
        connection.assert_not_called()
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 1)

    def test_native_doubao_delta_without_ids_uses_verified_started_identity(self):
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.sent_audio(b"\0\x20")
        class Browser:
            def __init__(self):
                self.events, self.audio = [], []
            async def send_json(self, event):
                self.events.append(event)
            async def send_bytes(self, chunk):
                self.audio.append(chunk)
        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "conversation.item.input_audio_transcription.started", "item_id": "native-asr"},
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "native-asr",
                     "text": "Synthetic question"},
                    {"type": "response.output_audio.started", "response_id": "native-reply", "question_id": "native-asr"},
                    {"type": "response.output_text.done", "text": "Synthetic reply"},
                    {"type": "response.output_audio.delta", "delta": "AAA="},
                    {"type": "response.output_audio.done"},
                    {"type": "session.closed"},
                ])
            async def recv(self):
                return json.dumps(next(self.events))
        browser = Browser()
        asyncio.run(_receive_doubao_audio(browser, Provider(), self.engine, self.session_id,
            self.job_id, self.token, control=control))
        self.assertEqual(browser.audio, [b"\0\0"])
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)

    def run_controlled_receiver(self, events):
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        class Browser:
            def __init__(self):
                self.events, self.audio = [], []
            async def send_json(self, event):
                self.events.append(event)
            async def send_bytes(self, chunk):
                self.audio.append(chunk)
        browser = Browser()
        class Provider:
            def __init__(self):
                self.events = iter(events)
            async def send(self, raw):
                pass
            async def recv(self):
                event = next(self.events)
                if isinstance(event, str):
                    if event == "pcm":
                        control.sent_audio(b"\0\x20")
                        return await self.recv()
                    await control.handle(browser, self, {"type": "control", "action": event,
                        "request_key": f"receiver-{event}", "audio_epoch": control.epoch + 1})
                    return await self.recv()
                return json.dumps(event)
        asyncio.run(_receive_doubao_audio(browser, Provider(), self.engine, self.session_id,
            self.job_id, self.token, control=control))
        return browser

    def test_pre_pause_accepted_asr_tail_is_saved_in_original_turn(self):
        browser = self.run_controlled_receiver([
            "pcm",
            {"type": "conversation.item.input_audio_transcription.started", "item_id": "pre-pause-input"},
            "pause",
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "pre-pause-input",
             "text": "Accepted public utterance before pause"},
            {"type": "session.closed"},
        ])
        self.assertEqual(browser.audio, [])
        self.assertFalse(any(event["type"] == "caption" for event in browser.events))
        with Session(self.engine) as db:
            part = db.exec(select(OmegaSegment)).one()
            self.assertEqual(part.speaker, "sales")
            self.assertEqual(part.text, "Accepted public utterance before pause")
            self.assertEqual(db.get(OmegaSession, self.session_id).voice_state, "coaching")

    def test_pcm_sent_before_pause_authorizes_delayed_asr_started(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
            paused = asyncio.Event()
            class Browser:
                def __init__(self):
                    self.events, self.audio = [], []
                    self.messages = iter([{"type": "websocket.receive", "bytes": b"\0\0"},
                        {"type": "websocket.receive", "text": json.dumps({"type": "control", "action": "pause",
                         "request_key": "delayed-asr-pause", "audio_epoch": 2})},
                        {"type": "websocket.receive", "text": "stop"}])
                async def receive(self):
                    return next(self.messages)
                async def send_json(self, event):
                    self.events.append(event)
                    if event.get("state") == "coaching":
                        paused.set()
                async def send_bytes(self, chunk):
                    self.audio.append(chunk)
            class Provider:
                def __init__(self):
                    self.events = iter([
                        {"type": "conversation.item.input_audio_transcription.started", "item_id": "late-start"},
                        {"type": "conversation.item.input_audio_transcription.completed", "item_id": "late-start",
                         "text": "Public PCM accepted before pause"}, {"type": "session.closed"}])
                    self.sent = []
                async def send(self, raw):
                    self.sent.append(json.loads(raw))
                async def recv(self):
                    await paused.wait()
                    return json.dumps(next(self.events))
            browser, provider = Browser(), Provider()
            sent, _ = await asyncio.gather(_send_audio(browser, provider, self.engine, self.session_id,
                self.job_id, self.token, control=control), _receive_doubao_audio(browser, provider,
                self.engine, self.session_id, self.job_id, self.token, control=control))
            self.assertEqual(sent, 1)
            self.assertEqual(browser.audio, [])
            self.assertFalse(any(event["type"] in {"caption", "interrupt"} for event in browser.events))
            with Session(self.engine) as db:
                part = db.exec(select(OmegaSegment)).one()
                self.assertEqual(part.text, "Public PCM accepted before pause")
                self.assertEqual(part.speaker_id, "sales")
        asyncio.run(exercise())

    def test_confirmed_pause_drains_delayed_started_before_configuration_ack(self):
        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            committed, configured = asyncio.Event(), asyncio.Event()
            class Browser:
                def __init__(self):
                    self.events, self.audio = [], []
                async def send_json(self, event):
                    self.events.append(event)
                async def send_bytes(self, chunk):
                    self.audio.append(chunk)
            class Provider:
                def __init__(self):
                    self.step, self.sent = 0, []
                async def send(self, raw):
                    event = json.loads(raw)
                    self.sent.append(event["type"])
                    if event["type"] == "input_audio_buffer.commit":
                        committed.set()
                    elif event["type"] == "session.update":
                        configured.set()
                async def recv(self):
                    await committed.wait()
                    self.step += 1
                    if self.step == 1:
                        return json.dumps({"type": "input_audio_buffer.committed"})
                    if self.step == 2:
                        await asyncio.sleep(.05)
                        return json.dumps({"type": "conversation.item.input_audio_transcription.started", "item_id": "confirmed-tail"})
                    if self.step == 3:
                        return json.dumps({"type": "conversation.item.input_audio_transcription.completed", "item_id": "confirmed-tail",
                                           "text": "Public PCM accepted before pause"})
                    if self.step == 4:
                        await configured.wait()
                        return json.dumps({"type": "session.updated"})
                    await asyncio.Event().wait()
            browser, provider = Browser(), Provider()
            control.sent_audio(b"\0\x20")
            receiving = asyncio.create_task(_receive_doubao_audio(browser, provider, self.engine,
                self.session_id, self.job_id, self.token, control=control))
            try:
                await control.handle(browser, provider, {"type": "control", "action": "pause",
                    "request_key": "confirmed-tail-pause", "audio_epoch": 2})
            finally:
                receiving.cancel()
                await asyncio.gather(receiving, return_exceptions=True)
            self.assertEqual(control.state, "coaching")
            self.assertIsNone(control.pending_input)
            self.assertFalse(control.active_inputs)
            self.assertEqual(browser.audio, [])
            with Session(self.engine) as db:
                self.assertEqual(db.exec(select(OmegaSegment)).one().text, "Public PCM accepted before pause")
        asyncio.run(exercise())

    def test_unknown_asr_final_does_not_certify_pending_nonzero_pcm(self):
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.sent_audio(b"\0\x20")
        class Browser:
            async def send_json(self, event):
                pass
        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "unknown-input", "text": "UNKNOWN_FINAL"},
                    {"type": "session.closed"},
                ])
            async def recv(self):
                return json.dumps(next(self.events))
        asyncio.run(_receive_doubao_audio(Browser(), Provider(), self.engine, self.session_id,
            self.job_id, self.token, control=control))
        self.assertEqual(control.final_pcm_frames, 0)
        self.assertTrue(control.pending_nonzero)
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaSegment)).all(), [])

    def _close_native_input(self, boundary, *, second_input=False, second_final=True,
                            first_final=True, input_pcm=True):
        from app.omega.realtime import realtime_session

        async def exercise():
            control = VoiceControl(self.engine, self.session_id, self.job_id, self.token, confirmed=True)
            owner = self

            class Browser:
                def __init__(self):
                    self.queue, self.events, self.sent_second = asyncio.Queue(), [], False
                    self.queue.put_nowait({"type": "websocket.receive", **(
                        {"bytes": b"\0\x20"} if input_pcm else {"text": "stop"})})

                async def accept(self):
                    pass

                async def close(self):
                    pass

                async def receive(self):
                    return await self.queue.get()

                async def send_json(self, event):
                    self.events.append(event)
                    if event["type"] == "interrupt" and second_input and not self.sent_second:
                        self.sent_second = True
                        self.queue.put_nowait({"type": "websocket.receive", "bytes": b"\0\x40"})
                    if event["type"] == "segment" and event["segment"]["text"] == "First public sentence":
                        # Both real utterances precede the first final; zero PCM follows it.
                        self.queue.put_nowait({"type": "websocket.receive", "bytes": bytes(640)})
                        self.queue.put_nowait({"type": "websocket.receive", "text": "stop" if boundary == "stop"
                            else json.dumps({"type": "control", "action": "pause", "request_key": "protocol-pause",
                                             "audio_epoch": control.epoch + 1})})
                    if boundary == "pause" and event.get("state") in {"coaching", "error"}:
                        self.queue.put_nowait({"type": "websocket.receive", "text": "stop"})

            browser = Browser()

            class Provider:
                def __init__(self):
                    self.queue, self.sent, self.frames, self.flushed = asyncio.Queue(), [], 0, False

                async def __aenter__(self):
                    return self

                async def __aexit__(self, *_):
                    pass

                def emit(self, kind, **fields):
                    self.queue.put_nowait(json.dumps({"type": kind, **fields}))

                async def recv(self):
                    return await self.queue.get()

                async def send(self, raw):
                    kind = json.loads(raw)["type"]
                    self.sent.append(kind)
                    if kind == "session.create":
                        self.emit("session.created")
                    elif kind == "input_audio_buffer.append":
                        self.frames += 1
                        if self.frames == 1:
                            self.emit("conversation.item.input_audio_transcription.started", item_id="first")
                            if not first_final:
                                browser.queue.put_nowait({"type": "websocket.receive", "text": "stop"})
                        if first_final and self.frames == (2 if second_input else 1):
                            self.emit("conversation.item.input_audio_transcription.completed", item_id="first",
                                      text="First public sentence")
                    elif kind in {"input_audio_buffer.commit", "input_audio_mute.commit"}:
                        if kind == "input_audio_buffer.commit":
                            self.emit("input_audio_buffer.committed")
                        if not self.flushed:
                            self.flushed = True
                            if not first_final:
                                self.emit("conversation.item.input_audio_transcription.completed", item_id="first",
                                          text="First public sentence")
                            elif second_input:
                                self.emit("conversation.item.input_audio_transcription.started", item_id="second")
                                if second_final:
                                    self.emit("conversation.item.input_audio_transcription.completed", item_id="second",
                                              text="Second public sentence")
                    elif kind == "session.update":
                        self.emit("session.updated")
                    elif kind == "session.close":
                        self.emit("session.closed")

            provider = Provider()
            wait_for = asyncio.wait_for
            tail_deadlines = []

            async def wait_with_tail_timeout(awaitable, seconds):
                frame = getattr(awaitable, "cr_frame", None)
                if not second_final and frame and frame.f_locals.get("self") is control.input_final:
                    # Exercise the production eight-second failure path without waiting eight seconds.
                    owner.assertGreater(seconds, 6)
                    owner.assertLessEqual(seconds, 8)
                    tail_deadlines.append(seconds)
                    awaitable.close()
                    raise TimeoutError
                return await wait_for(awaitable, seconds)

            async def authorize(*_):
                return owner.user

            with patch("app.omega.realtime.is_enabled", return_value=True), \
                 patch("app.omega.realtime._trusted_origin", return_value=True), \
                 patch("app.omega.realtime.ws_user", side_effect=authorize), \
                 patch("app.omega.realtime._acquire", return_value=(self.job_id, self.token, "Synthetic role")), \
                 patch("app.omega.realtime.VoiceControl", return_value=control), \
                 patch("app.omega.realtime.connect", return_value=provider), \
                 patch("app.omega.realtime.asyncio.wait_for", side_effect=wait_with_tail_timeout), \
                 patch.dict("os.environ", {"PDCA_OMEGA_REALTIME_PROVIDER": "doubao",
                                           "PDCA_DOUBAO_REALTIME_API_KEY": "test-only"}):
                with Session(self.engine) as db:
                    await realtime_session(browser, self.session_id, db)
            return control, provider.sent, browser.events, tail_deadlines

        return asyncio.run(exercise())

    def _assert_second_tail(self, boundary, *, final=True):
        control, _, _, deadlines = self._close_native_input(boundary, second_input=True, second_final=final)
        with Session(self.engine) as db:
            parts = db.exec(select(OmegaSegment).order_by(OmegaSegment.seq)).all()
            self.assertEqual([part.text for part in parts], ["First public sentence"]
                             + (["Second public sentence"] if final else []))
            self.assertEqual(db.get(OmegaJob, self.job_id).status, "succeeded" if final else "failed")
        self.assertEqual(control.tail_incomplete, not final)
        self.assertEqual(bool(control.active_inputs), not final)
        if not final:
            self.assertTrue(deadlines)

    def test_pause_saves_delayed_second_real_input_after_first_final_and_zero_pcm(self):
        self._assert_second_tail("pause")

    def test_stop_saves_delayed_second_real_input_after_first_final_and_zero_pcm(self):
        self._assert_second_tail("stop")

    def test_pause_fails_when_delayed_second_real_input_has_no_final(self):
        self._assert_second_tail("pause", final=False)

    def test_stop_fails_when_delayed_second_real_input_has_no_final(self):
        self._assert_second_tail("stop", final=False)

    def test_first_input_without_prior_final_still_commits_on_stop(self):
        control, sent, _, _ = self._close_native_input("stop", first_final=False)
        self.assertIn("input_audio_buffer.commit", sent)
        self.assertFalse(control.tail_incomplete)

    def test_stop_without_any_pcm_closes_without_commit_or_mute(self):
        _, sent, _, _ = self._close_native_input("stop", input_pcm=False)
        self.assertNotIn("input_audio_buffer.commit", sent)
        self.assertNotIn("input_audio_mute.commit", sent)
        self.assertIn("session.close", sent)

    def test_asr_after_resume_without_new_browser_pcm_cannot_create_a_turn(self):
        self.pause()
        browser = self.run_controlled_receiver([
            "resume",
            {"type": "conversation.item.input_audio_transcription.started", "item_id": "unsolicited-input"},
            {"type": "conversation.item.input_audio_transcription.completed", "item_id": "unsolicited-input", "text": "STALE_INPUT"},
            {"type": "response.output_audio.started", "response_id": "unsolicited-reply", "question_id": "unsolicited-input"},
            {"type": "response.output_audio.delta", "delta": "AAA="},
            {"type": "response.output_audio.done"}, {"type": "session.closed"},
        ])
        self.assertEqual(browser.audio, [])
        with Session(self.engine) as db:
            self.assertEqual(db.exec(select(OmegaSegment)).all(), [])

    def test_unseen_old_reply_after_resume_cannot_bind_to_new_input_epoch(self):
        browser = self.run_controlled_receiver([
            "pcm",
            {"type": "conversation.item.input_audio_transcription.started", "question_id": "old-q"},
            {"type": "conversation.item.input_audio_transcription.completed", "question_id": "old-q",
             "item_id": "old-input", "text": "First public input"},
            "pause", "resume",
            "pcm",
            {"type": "conversation.item.input_audio_transcription.started", "question_id": "new-q"},
            {"type": "conversation.item.input_audio_transcription.completed", "question_id": "new-q",
             "item_id": "new-input", "text": "New public input"},
            {"type": "response.output_audio.started", "question_id": "old-q", "response_id": "late-old-r"},
            {"type": "response.output_text.done", "question_id": "old-q", "response_id": "late-old-r", "text": "STALE_REPLY"},
            {"type": "response.output_audio.delta", "question_id": "old-q", "response_id": "late-old-r", "delta": "AAA="},
            {"type": "response.output_audio.done", "question_id": "old-q", "response_id": "late-old-r"},
            {"type": "response.output_audio.started", "question_id": "new-q", "response_id": "fresh-r"},
            {"type": "response.output_text.done", "question_id": "new-q", "response_id": "fresh-r", "text": "FRESH_REPLY"},
            {"type": "response.output_audio.delta", "question_id": "new-q", "response_id": "fresh-r", "delta": "ACA="},
            {"type": "response.output_audio.done", "question_id": "new-q", "response_id": "fresh-r"},
            {"type": "session.closed"},
        ])
        self.assertEqual(browser.audio, [b"\0\x20"])
        with Session(self.engine) as db:
            replies = db.exec(select(OmegaSegment).where(OmegaSegment.speaker == "counterparty")).all()
            self.assertEqual([part.text for part in replies], ["FRESH_REPLY"])
