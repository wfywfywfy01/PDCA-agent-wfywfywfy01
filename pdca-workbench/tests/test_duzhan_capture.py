import json
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch


class ChannelHistoryCaptureTests(TestCase):
    def test_history_uses_offset_until_the_server_page_is_short(self):
        from app.duzhan_ledger import fetch_channel_history

        calls: list[tuple[int, int]] = []

        def fake_history(args, timeout):
            page_size = int(args[args.index("--limit") + 1])
            offset = int(args[args.index("--offset") + 1]) if "--offset" in args else 0
            calls.append((offset, page_size))
            size = 200 if offset == 0 else 43
            return {"ok": True, "messages": [{"id": f"message-{offset + i}"} for i in range(size)]}

        with patch("app.vertu.client.run_vertu_sync_json", side_effect=fake_history):
            messages = fetch_channel_history("synthetic-channel", "2026-10-23", "300")

        self.assertEqual(len(messages or []), 243)
        self.assertEqual(calls, [(0, 200), (200, 200)])

    def test_history_discards_a_partial_result_when_a_continuation_page_fails(self):
        from app.duzhan_ledger import fetch_channel_history

        def fake_history(args, timeout):
            offset = int(args[args.index("--offset") + 1]) if "--offset" in args else 0
            if offset:
                return None
            return {"ok": True, "messages": [{"id": f"message-{i}"} for i in range(200)]}

        with patch("app.vertu.client.run_vertu_sync_json", side_effect=fake_history):
            self.assertIsNone(fetch_channel_history("synthetic-channel", "2026-10-23", "300"))


class MtoAttachmentCaptureTests(TestCase):
    def test_quoted_image_attachment_is_counted_and_sent_to_ocr(self):
        from app.duzhan_ledger import parse_mto_images
        from app.mto_ocr import review_mto_images

        messages = [
            {
                "id": "reply-1",
                "message_type": "text",
                "sender_user_id": 7,
                "quote_snapshot": {
                    "id": "quoted-1",
                    "message_type": "image",
                    "sender_user_id": 7,
                    "attachment": {
                        "id": "attachment-1",
                        "attachment_type": "image",
                        "mime_type": "image/png",
                        "name": "synthetic-mto.png",
                        "url": "/synthetic/mto.png",
                    },
                },
            }
        ]

        count, names = parse_mto_images(messages, 7)
        self.assertEqual((count, names), (1, ["synthetic-mto.png"]))
        with patch("app.mto_ocr.get_settings", return_value=SimpleNamespace(qwen_api_key="unit-test")), \
             patch("app.mto_ocr.download_ocr_delete", return_value={"wan": 40, "raw_ok": True, "qualifies": True}) as ocr, \
             patch("app.mto_ocr.summarize_quotes", return_value=(1, ["synthetic-mto.png"])):
            reviewed, reviewed_names, quotes = review_mto_images(messages, 7, max_images=4)
        self.assertEqual((reviewed, reviewed_names, len(quotes)), (1, ["synthetic-mto.png"], 1))
        ocr.assert_called_once_with("/synthetic/mto.png")

    def test_same_image_hash_is_counted_once_across_forwarded_messages(self):
        from app.duzhan_ledger import parse_mto_images

        messages = [
            {
                "sender_user_id": 7,
                "attachments": [{
                    "id": f"attachment-{index}",
                    "sha256": "same-image-content",
                    "attachment_type": "image",
                    "url": f"/synthetic/copy-{index}.png",
                }],
            }
            for index in range(2)
        ]

        self.assertEqual(parse_mto_images(messages, 7)[0], 1)

    def test_quoted_image_from_another_sender_is_not_attributed_to_replier(self):
        from app.duzhan_ledger import parse_mto_images

        messages = [{
            "sender_user_id": 7,
            "quote_snapshot": {
                "sender_user_id": 8,
                "attachment": {
                    "id": "other-owner-image",
                    "attachment_type": "image",
                    "url": "/synthetic/other.png",
                },
            },
        }]

        self.assertEqual(parse_mto_images(messages, 7)[0], 0)

    def test_recall_event_with_image_metadata_is_not_counted(self):
        from app.duzhan_ledger import parse_mto_images

        messages = [{
            "message_type": "recall",
            "sender_user_id": 7,
            "attachments": [{
                "id": "recalled-image",
                "attachment_type": "image",
                "url": "/synthetic/recalled.png",
            }],
        }]

        self.assertEqual(parse_mto_images(messages, 7)[0], 0)

    def test_successful_attachment_ocr_is_reused_across_collection_slots(self):
        from app import mto_ocr

        messages = [
            {
                "id": "message-1",
                "message_type": "image",
                "sender_user_id": 7,
                "attachments": [
                    {
                        "id": "attachment-1",
                        "sha256": "synthetic-sha256",
                        "attachment_type": "image",
                        "name": "synthetic-mto.png",
                        "url": "/synthetic/mto.png",
                    }
                ],
            }
        ]
        quote = {"model": "Synthetic Model", "wan": 40, "raw_ok": True, "qualifies": True}
        with patch.dict(mto_ocr._OCR_RESULT_CACHE, {}, clear=True), \
             patch.object(mto_ocr, "get_settings", return_value=SimpleNamespace(qwen_api_key="unit-test")), \
             patch.object(mto_ocr, "download_ocr_delete", return_value=quote) as ocr:
            first = mto_ocr.review_mto_images(messages, 7, max_images=4)
            second = mto_ocr.review_mto_images(messages, 7, max_images=4)

        self.assertEqual(first, second)
        ocr.assert_called_once_with("/synthetic/mto.png")

    def test_cache_upgrade_reuses_complete_legacy_mto_but_rechecks_ambiguous_image(self):
        from app import mto_ocr

        complete_att = {"id": "complete", "url": "/complete.png"}
        ambiguous_att = {"id": "ambiguous", "url": "/ambiguous.png"}
        cached = {
            "id:complete": {"model": "Legacy MTO", "wan": 40, "raw_ok": True},
            "id:ambiguous": {"model": "Legacy text", "wan": None, "raw_ok": True},
        }
        classified = {
            "ocr_contract_version": 2,
            "document_type": "sales_report",
            "performance_basis": "booked_sales",
            "visible_text": "Sales report",
            "raw_ok": False,
            "wan": None,
        }
        with patch.dict(mto_ocr._OCR_RESULT_CACHE, cached, clear=True), \
             patch.object(mto_ocr, "get_settings", return_value=SimpleNamespace(qwen_api_key="unit-test")), \
             patch.object(mto_ocr, "download_ocr_delete", return_value=classified) as ocr:
            complete = mto_ocr.review_mto_attachment(complete_att)
            ambiguous = mto_ocr.review_mto_attachment(ambiguous_att)

        self.assertEqual(complete["document_type"], "mto_quote")
        self.assertEqual(complete["ocr_contract_version"], 2)
        self.assertEqual(ambiguous["document_type"], "sales_report")
        ocr.assert_called_once_with("/ambiguous.png")

    def test_incomplete_ocr_stays_pending_and_is_retried(self):
        from app import mto_ocr

        messages = [{
            "message_type": "image",
            "sender_user_id": 7,
            "attachments": [{
                "id": "incomplete-attachment",
                "attachment_type": "image",
                "url": "/synthetic/incomplete.png",
            }],
        }]
        incomplete = {"model": "Synthetic Model", "wan": None, "raw_ok": True, "qualifies": False}
        with patch.dict(mto_ocr._OCR_RESULT_CACHE, {}, clear=True), \
             patch.object(mto_ocr, "get_settings", return_value=SimpleNamespace(qwen_api_key="unit-test")), \
             patch.object(mto_ocr, "download_ocr_delete", return_value=incomplete) as ocr:
            first = mto_ocr.review_mto_images(messages, 7, max_images=4)
            second = mto_ocr.review_mto_images(messages, 7, max_images=4)

        self.assertIsNone(first[0])
        self.assertIsNone(second[0])
        self.assertEqual(ocr.call_count, 2)

    def test_partial_results_keep_their_original_attachment_name(self):
        from app.mto_ocr import finalize_mto_review

        attachments = [
            {"id": "a", "name": "a.png"},
            {"id": "b", "name": "b.png"},
        ]
        success = {"model": "Synthetic", "wan": 40, "raw_ok": True, "qualifies": True}

        count, _names, quotes = finalize_mto_review(
            attachments,
            [None, success],
            False,
            qwen_enabled=True,
        )

        self.assertIsNone(count)
        self.assertEqual(quotes[0]["file"], "b.png")

    def test_single_ocr_result_exposes_payment_evidence_without_changing_mto_amount(self):
        from app.duzhan_ledger import image_performance_facts
        from app.mto_ocr import parse_quote_text

        row = parse_quote_text(
            '{"document_type":"payment_receipt","model":"","total_usd":null,'
            '"performance_amount":45000,"performance_currency":"USD",'
            '"performance_basis":"paid_not_received",'
            '"visible_text":"Payment sent, bank receipt"}'
        )
        row.update(source_message_id="message-1", source_attachment_id="attachment-1")
        slips, intents, pending = image_performance_facts([row], "2026-10-23")

        self.assertEqual(row["document_type"], "payment_receipt")
        self.assertIsNone(row["wan"])
        self.assertEqual(row["performance_wan"], 31.9)
        self.assertEqual((len(slips), intents, pending), (1, [], []))
        self.assertEqual(slips[0]["review_status"], "pending")
        self.assertEqual(slips[0]["source_message_id"], "message-1")

    def test_amount_only_image_without_business_basis_stays_pending(self):
        from app.duzhan_ledger import image_performance_facts
        from app.mto_ocr import parse_quote_text

        row = parse_quote_text(
            '{"document_type":"payment_receipt","performance_amount":45000,'
            '"performance_currency":"USD","performance_basis":"unknown",'
            '"visible_text":"USD 45,000"}'
        )
        slips, intents, pending = image_performance_facts([row], "2026-10-23")

        self.assertEqual((slips, intents), ([], []))
        self.assertEqual(len(pending), 1)

    def test_image_performance_rejects_invalid_model_amounts(self):
        from app.duzhan_ledger import image_performance_facts
        from app.mto_ocr import parse_quote_text

        for invalid in ("NaN", "Infinity", -1, True):
            with self.subTest(invalid=invalid):
                row = parse_quote_text(json.dumps({
                    "document_type": "payment_receipt",
                    "performance_amount": invalid,
                    "performance_currency": "USD",
                    "performance_basis": "paid_not_received",
                    "visible_text": "Payment receipt",
                }))
                slips, intents, pending = image_performance_facts([row], "2026-10-23")

                self.assertIsNone(row["performance_amount"])
                self.assertIsNone(row["performance_currency"])
                self.assertEqual((len(slips), intents, pending), (1, [], []))
                self.assertEqual(slips[0]["amount_text"], "")

        empty = parse_quote_text('{"document_type":"other"}')
        self.assertIsNone(empty["performance_amount"])
        self.assertIsNone(empty["performance_currency"])
        self.assertIsNone(empty["performance_basis"])
        self.assertIsNone(empty["visible_text"])

    def test_mto_amount_rejects_invalid_model_numbers(self):
        from app.mto_ocr import parse_quote_text

        for invalid in ("NaN", "Infinity", -1, True):
            with self.subTest(invalid=invalid):
                row = parse_quote_text(json.dumps({
                    "document_type": "mto_quote",
                    "model": "Synthetic Model",
                    "total_usd": invalid,
                }))
                self.assertIsNone(row["usd"])
                self.assertIsNone(row["wan"])

    def test_payment_classification_uses_the_existing_single_qwen_call(self):
        from app.mto_ocr import ocr_image_bytes

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "choices": [{
                        "finish_reason": "length",
                        "message": {"content": (
                            '{"document_type":"payment_receipt",'
                            '"performance_amount":45000,"performance_currency":"USD",'
                            '"performance_basis":"paid_not_received",'
                            '"visible_text":"Payment sent"}'
                        )},
                    }]
                }

        settings = SimpleNamespace(
            qwen_base_url="https://synthetic.invalid",
            qwen_api_key="unit-test",
            qwen_model="synthetic-model",
            qwen_ca_bundle="",
        )
        with patch("app.mto_ocr.get_settings", return_value=settings), \
             patch("app.mto_ocr.httpx.post", return_value=Response()) as post:
            row = ocr_image_bytes(b"synthetic-image", "image/jpeg")

        self.assertEqual(row["document_type"], "payment_receipt")
        post.assert_called_once()


class MtoVisionFreshnessTests(TestCase):
    def test_owner_cache_is_invalidated_when_new_messages_arrive(self):
        from app.agents import mto_vision_service as vision

        def fake_review(messages, sender_id, **kwargs):
            del sender_id, kwargs
            count = len(messages or [])
            return count, [], []

        settings = SimpleNamespace(qwen_api_key="unit-test", mto_ocr_max_images=8)
        metrics = {"mto_daily_count": 4, "mto_min_wan": 30, "source": "saved"}
        with patch.dict(vision._cache, {}, clear=True), \
             patch.object(vision, "_owner_metrics", return_value=metrics), \
             patch.object(vision, "_vision_with_metrics", side_effect=lambda payload, _metrics: payload), \
             patch.object(vision, "get_settings", return_value=settings), \
             patch.object(vision, "write_event"), \
             patch("app.mto_ocr.review_mto_images", side_effect=fake_review) as review:
            first = vision.review_owner_images("测试负责人", [], 7, day="2026-10-23")
            second = vision.review_owner_images(
                "测试负责人",
                [{"id": "new-message", "message_type": "image", "sender_user_id": 7}],
                7,
                day="2026-10-23",
            )

        self.assertEqual(first["count"], 0)
        self.assertEqual(second["count"], 1)
        self.assertEqual(review.call_count, 2)

    def test_incomplete_review_is_retried_instead_of_cached(self):
        from app.agents import mto_vision_service as vision

        settings = SimpleNamespace(qwen_api_key="unit-test", mto_ocr_max_images=8)
        metrics = {"mto_daily_count": 4, "mto_min_wan": 30, "source": "saved"}
        with patch.dict(vision._cache, {}, clear=True), \
             patch.object(vision, "_owner_metrics", return_value=metrics), \
             patch.object(vision, "get_settings", return_value=settings), \
             patch.object(vision, "write_event"), \
             patch("app.mto_ocr.review_mto_images", side_effect=[(None, [], []), (0, [], [])]) as review:
            failed = vision.review_owner_images("测试负责人", [], 7, day="2026-10-23")
            recovered = vision.review_owner_images("测试负责人", [], 7, day="2026-10-23")

        self.assertIsNone(failed["count"])
        self.assertEqual(recovered["count"], 0)
        self.assertEqual(review.call_count, 2)

    def test_detail_history_failure_is_pending_instead_of_failed_goal(self):
        from app import duzhan_ledger as ledger
        from app.agents import mto_vision_service as vision

        owner = SimpleNamespace(
            display="测试负责人",
            group="测试部门",
            im_user_id=7,
            follow_channel_id="synthetic-channel",
        )
        metrics = {"mto_daily_count": 4, "mto_min_wan": 30, "source": "saved"}
        with patch.dict(vision._cache, {}, clear=True), \
             patch.object(vision, "_owner_metrics", return_value=metrics), \
             patch.object(ledger, "OWNERS", (owner,)), \
             patch.object(ledger, "_history_ids", return_value=["synthetic-channel"]), \
             patch.object(ledger, "fetch_channel_history", return_value=None):
            result = vision.review_owner_detail("测试负责人", "2026-10-23")

        self.assertFalse(result["complete"])
        self.assertIsNone(result["goal_met"])


class MtoCollectionSchedulingTests(TestCase):
    def test_collection_round_robins_production_sized_batches(self):
        from app import duzhan_ledger as ledger

        def owner_messages(owner: str):
            return [
                {
                    "id": f"{owner}-message-{index}",
                    "message_type": "image",
                    "sender_user_id": index + 1,
                    "attachments": [
                        {
                            "id": f"{owner}-attachment-{index}",
                            "attachment_type": "image",
                            "name": f"{owner}-{index}.png",
                            "url": f"/synthetic/{owner}/{index}.png",
                        }
                    ],
                }
                for index in range({"a": 4, "b": 8, "c": 4}[owner])
            ]

        inputs = [
            ("owner-a", owner_messages("a"), None),
            ("owner-b", owner_messages("b"), None),
            ("owner-c", owner_messages("c"), None),
        ]
        scheduled: list[str] = []

        def fake_deadline(func, items, workers, label, timeout):
            del workers, label, timeout
            scheduled.extend(item[0] for item in items)
            results = [func(item) for item in items]
            results[12:] = [None] * (len(results) - 12)
            return results

        quote = {"model": "Synthetic", "wan": 40, "raw_ok": True, "qualifies": True}
        with patch.object(ledger, "_parallel_map_deadline", side_effect=fake_deadline), \
             patch("app.mto_ocr.review_mto_attachment", return_value=quote):
            reviewed = ledger._review_mto_inputs(
                inputs,
                quota_by_owner={"owner-a": 4, "owner-b": 8, "owner-c": 4},
                max_images=8,
                workers=2,
                budget=30,
                qwen_enabled=True,
            )

        self.assertEqual(scheduled[:12], ["owner-a", "owner-b", "owner-c"] * 4)
        self.assertEqual(reviewed["owner-a"][0], 4)
        self.assertIsNone(reviewed["owner-b"][0])
        self.assertEqual(len(reviewed["owner-b"][2]), 4)
        self.assertEqual(reviewed["owner-c"][0], 4)
