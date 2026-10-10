"""Context-bounded ASR terms retain raw evidence; no model or network calls."""
import asyncio
import json
import unittest

from sqlmodel import Session, select

import tests.test_omega_coaching as fixture
from app.omega.context import coach_messages
from app.omega.models import OmegaSegment, OmegaSession
from app.omega.realtime import VoiceControl, _append, _receive_doubao_audio
from app.omega.reports import WEIGHTS, verify_quote


class TranscriptionTests(unittest.TestCase):
    setUp = fixture.CoachingTests.setUp
    tearDown = fixture.CoachingTests.tearDown

    def context(self, **fields):
        with Session(self.engine) as db:
            game = db.get(OmegaSession, self.session_id)
            game.context_snapshot_json = json.dumps(fields, ensure_ascii=False)
            db.commit()

    def append(self, raw, *, event=None):
        identity = ({"speaker_id": "sales", "turn_id": "turn-" + event,
                     "provider_event_id": event} if event else {})
        return _append(self.engine, self.session_id, self.job_id, self.token, "sales", raw, **identity)

    def stored(self, part):
        with Session(self.engine) as db:
            return db.get(OmegaSegment, part["id"]).model_dump()

    def test_first_order_term_corrects_only_anchored_negotiation_phrase_and_retains_raw(self):
        self.context(title="自主实测：代理首单谈判", public_brief="双方商谈首单，商务条件未确认。")
        for raw in ("周经理，今天先不急着订手单。", "周经理，今天先不急着定手单。"):
            with self.subTest(raw=raw):
                part = self.append(raw)
                self.assertEqual(part["text"], raw.replace("手单", "首单"))
                self.assertEqual(part["asr_original"], raw)
                self.assertEqual(self.stored(part)["asr_original"], raw)

    def test_trial_order_term_uses_previous_public_words_and_remains_trial_order(self):
        self.append("先做小批量试单评估。")
        raw = "把市单周转量、动销支持和库存处理方案写成待审批文件。"
        part = self.append(raw)
        self.assertEqual(part["text"], raw.replace("市单周转量", "试单周转量"))
        self.assertEqual(self.stored(part)["asr_original"], raw)

    def test_missing_item_term_uses_previous_public_words(self):
        self.append("请列出缺项，逐项确认。")
        raw = "您当天回确项清单。"
        part = self.append(raw)
        self.assertEqual(part["text"], "您当天回缺项清单。")
        self.assertEqual(self.stored(part)["asr_original"], raw)

    def test_terms_without_public_context_are_unchanged(self):
        self.context(public_brief="普通销售训练，尚未提供细节。")
        for raw in ("今天先不急着订手单。", "把市单周转量写好。", "您当天回确项清单。"):
            with self.subTest(raw=raw):
                self.assertEqual(self.append(raw)["text"], raw)

    def test_private_goal_and_memory_terms_cannot_trigger_correction(self):
        self.context(public_brief="普通销售训练，尚未提供细节。",
                     seller_private="首单，试单，缺项都是私有背景。",
                     goal={"success_condition": "首单、试单、缺项"},
                     memory_context={"sales": "首单、试单、缺项"})
        raw = "今天订手单，把市单周转量和确项清单写好。"
        self.assertEqual(self.append(raw)["text"], raw)

    def test_legitimate_manual_order_and_trial_order_are_not_globally_replaced(self):
        self.context(title="首单谈判", public_brief="讨论首单、试单和缺项。")
        for raw in ("请把手单录入系统，试单测试由我负责。", "先人工定手单，再讨论首单。",
                    "手单不是首单。", "今天先不急着订试单。", "这不是试单，是首单。"):
            with self.subTest(raw=raw):
                self.assertEqual(self.append(raw)["text"], raw)

    def test_correction_preserves_numbers_dates_money_units_and_negation(self):
        self.context(stage_summary="本场讨论首单可行性。")
        raw = "今天先不急着订手单，不承诺2026-10-12付款￥123,456.78或20台，未经审批不能降价5%。"
        self.assertEqual(self.append(raw)["text"], raw.replace("手单", "首单"))

    def test_raw_whitespace_is_retained_while_display_text_is_trimmed(self):
        self.context(title="首单谈判")
        raw = "  今天不急着订手单。\n"
        part = self.append(raw)
        self.assertEqual(part["text"], "今天不急着订首单。")
        self.assertEqual(self.stored(part)["asr_original"], raw)

    def test_replay_is_compared_with_raw_before_later_context_changes(self):
        first = self.append("今天不急着订手单。", event="replayed-asr")
        self.append("本场只是首单谈判。")
        replay = self.append("今天不急着订手单。", event="replayed-asr")
        self.assertEqual(replay, first)
        self.assertEqual(replay["text"], "今天不急着订手单。")
        with Session(self.engine) as db:
            self.assertEqual(len(db.exec(select(OmegaSegment)).all()), 2)

    def test_different_raw_with_same_normalized_meaning_is_still_a_replay_conflict(self):
        self.context(title="首单谈判")
        self.append("今天不急着订手单。", event="conflicting-asr")
        with self.assertRaisesRegex(ValueError, "重复事件"):
            self.append("今天不急着订首单。", event="conflicting-asr")

    def test_counterparty_text_is_never_asr_corrected(self):
        self.context(title="首单谈判")
        self.append("请先说明流程。")
        part = _append(self.engine, self.session_id, self.job_id, self.token,
                       "counterparty", "请先人工定手单。")
        self.assertEqual(part["text"], "请先人工定手单。")
        self.assertEqual(self.stored(part)["asr_original"], "")

    def test_report_quotes_use_exact_normalized_text_and_reject_raw_substitution(self):
        self.context(title="首单谈判")
        raw = "今天不急着订手单。"
        part = self.append(raw)
        messages = coach_messages({}, [part], WEIGHTS)
        quote = json.loads(messages[1]["content"])["quote_candidates"][0]
        self.assertEqual(quote["text"], "今天不急着订首单。")
        self.assertTrue(verify_quote(quote, {part["id"]: part}))
        self.assertFalse(verify_quote({**quote, "text": raw}, {part["id"]: part}))

    def receive_replayed_final(self, second_raw):
        self.context(title="首单谈判")
        control = VoiceControl(self.engine, self.session_id, self.job_id, self.token)
        control.sent_audio(b"\0\x20")
        class Browser:
            def __init__(self):
                self.events = []
            async def send_json(self, event):
                self.events.append(event)
        class Provider:
            def __init__(self):
                self.events = iter([
                    {"type": "conversation.item.input_audio_transcription.started", "item_id": "replayed-input"},
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "replayed-input", "text": "今天不急着订手单。"},
                    {"type": "conversation.item.input_audio_transcription.completed", "item_id": "replayed-input", "text": second_raw},
                    {"type": "session.closed"},
                ])
            async def recv(self):
                return json.dumps(next(self.events))
        browser = Browser()
        asyncio.run(_receive_doubao_audio(browser, Provider(), self.engine, self.session_id,
            self.job_id, self.token, control=control))
        return browser

    def test_receiver_replay_has_one_normalized_segment(self):
        browser = self.receive_replayed_final("今天不急着订手单。")
        segments = [event["segment"] for event in browser.events if event["type"] == "segment"]
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0]["text"], "今天不急着订首单。")

    def test_receiver_rejects_conflicting_raw_for_same_provider_id(self):
        with self.assertRaisesRegex(ValueError, "重复事件"):
            self.receive_replayed_final("今天不急着订首单。")
