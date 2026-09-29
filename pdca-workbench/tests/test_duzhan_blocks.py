# -*- coding: utf-8 -*-
"""督战官积木 schema：解析与校验单测（不碰网络与数据库）。"""
import json
import unittest

from app.duzhan_blocks import (
    BLOCK_TYPES,
    SOURCE_KEYS,
    as_str_list,
    block_schema,
    blocks_dict,
    dump_blocks,
    parse_blocks,
    validate_blocks,
)

GOOD = {
    "blocks": [
        {"type": "group", "channel_id": "850d06d0-5dd8-4a43-ad35-1cb3fcf6d484", "label": "新人小组业绩达标群"},
        {"type": "times", "slots": ["10:00", "15:00", "20:00"]},
        {"type": "people", "names": ["于冰"]},
        {"type": "source", "key": "wa_summary"},
        {"type": "rule", "text": "本档动作：核验交付物", "when": "always"},
        {"type": "condition", "key": "workday", "value": True},
        {"type": "style", "lang": "zh", "title": "每日三追进度表"},
    ]
}


def _with(**overrides) -> list:
    blocks = [dict(item) for item in GOOD["blocks"]]
    for index, item in enumerate(blocks):
        for key, value in overrides.items():
            if item["type"] == key:
                item.update(value)
    return parse_blocks({"blocks": blocks})


class ParseTests(unittest.TestCase):
    def test_parse_accepts_json_dict_and_list(self):
        self.assertEqual(len(parse_blocks(json.dumps(GOOD))), 7)
        self.assertEqual(len(parse_blocks(GOOD)), 7)
        self.assertEqual(len(parse_blocks(GOOD["blocks"])), 7)

    def test_bad_input_is_empty_not_exception(self):
        self.assertEqual(parse_blocks("不是 JSON"), [])
        self.assertEqual(parse_blocks(""), [])
        self.assertEqual(parse_blocks(None), [])
        self.assertEqual(parse_blocks({"blocks": "x"}), [])
        self.assertEqual(parse_blocks({"blocks": ["x", 3]}), [])

    def test_dump_roundtrip_keeps_order_and_chinese(self):
        blocks = parse_blocks(GOOD)
        text = dump_blocks(blocks)
        self.assertIn("新人小组业绩达标群", text)
        self.assertEqual([item.type for item in parse_blocks(text)], [item.type for item in blocks])
        self.assertEqual(blocks_dict(blocks)["blocks"][0]["type"], "group")

    def test_as_str_list_accepts_comma_and_list(self):
        self.assertEqual(as_str_list("10:00, 15:00"), ["10:00", "15:00"])
        self.assertEqual(as_str_list(["a", " b "]), ["a", "b"])
        self.assertEqual(as_str_list(None), [])


class ValidateTests(unittest.TestCase):
    def test_good_config_passes(self):
        self.assertEqual(validate_blocks(parse_blocks(GOOD), strategies=["mto"], owners=["于冰"]), [])

    def test_unknown_block_type(self):
        errors = validate_blocks(parse_blocks({"blocks": [{"type": "nope"}]}))
        self.assertTrue(errors)
        self.assertIn("nope", errors[0])

    def test_group_channel_must_be_uuid(self):
        errors = validate_blocks(_with(group={"channel_id": "c1"}))
        self.assertTrue(any("channel_id" in item for item in errors))

    def test_times_rejects_unsupported_hour(self):
        errors = validate_blocks(_with(times={"slots": ["12:00"]}))
        self.assertTrue(any("不支持" in item for item in errors))
        errors = validate_blocks(_with(times={"slots": ["9:00"]}))
        self.assertTrue(any("HH:MM" in item for item in errors))

    def test_people_outside_roster(self):
        errors = validate_blocks(parse_blocks(GOOD), owners=["邓琳莹"])
        self.assertTrue(any("于冰" in item for item in errors))
        # 传 None 表示名单未知，不做人名校验
        self.assertEqual(validate_blocks(parse_blocks(GOOD), owners=None), [])

    def test_strategy_must_be_known(self):
        blocks = parse_blocks(GOOD)
        blocks.append(parse_blocks({"blocks": [{"type": "strategy", "id": "ghost"}]})[0])
        errors = validate_blocks(blocks, strategies=["mto"])
        self.assertTrue(any("ghost" in item for item in errors))
        self.assertEqual(validate_blocks(blocks, strategies=["mto", "ghost"]), [])

    def test_ai_rule_needs_prompt(self):
        blocks = parse_blocks({"blocks": [
            {"type": "group", "channel_id": "850d06d0-5dd8-4a43-ad35-1cb3fcf6d484"},
            {"type": "times", "slots": ["10:00"]},
            {"type": "rule", "mode": "ai"},
        ]})
        errors = validate_blocks(blocks)
        self.assertTrue(any("prompt" in item for item in errors))
        blocks = parse_blocks({"blocks": [
            {"type": "group", "channel_id": "850d06d0-5dd8-4a43-ad35-1cb3fcf6d484"},
            {"type": "times", "slots": ["10:00"]},
            {"type": "rule", "mode": "ai", "prompt": "按当天数据写一句催促"},
        ]})
        self.assertEqual(validate_blocks(blocks), [])

    def test_rule_text_and_when(self):
        errors = validate_blocks(_with(rule={"text": "  "}))
        self.assertTrue(any("规则文案" in item for item in errors))
        errors = validate_blocks(_with(rule={"when": "fullmoon"}))
        self.assertTrue(any("when" in item for item in errors))

    def test_condition_value_must_be_bool(self):
        errors = validate_blocks(_with(condition={"value": "yes"}))
        self.assertTrue(any("true/false" in item for item in errors))

    def test_recipient_needs_uuid(self):
        blocks = parse_blocks({"blocks": [
            {"type": "group", "channel_id": "850d06d0-5dd8-4a43-ad35-1cb3fcf6d484"},
            {"type": "times", "slots": ["10:00"]},
            {"type": "recipient", "kind": "sms", "id": "abc"},
        ]})
        errors = validate_blocks(blocks)
        self.assertTrue(any("kind" in item for item in errors))
        self.assertTrue(any("UUID" in item for item in errors))

    def test_style_lang_and_title(self):
        self.assertTrue(any("lang" in item for item in validate_blocks(_with(style={"lang": "fr"}))))
        self.assertTrue(any("title" in item for item in validate_blocks(_with(style={"title": "  "}))))

    def test_missing_group_or_times(self):
        blocks = parse_blocks({"blocks": [{"type": "source", "key": "wa_summary"}]})
        errors = validate_blocks(blocks)
        self.assertTrue(any("group" in item for item in errors))
        self.assertTrue(any("times" in item for item in errors))
        self.assertEqual(validate_blocks([]), ["至少需要一个积木块（至少要有 group + times）"])


class SchemaTests(unittest.TestCase):
    def test_schema_covers_every_block_type(self):
        schema = block_schema()
        self.assertEqual([item["type"] for item in schema], list(BLOCK_TYPES))
        for item in schema:
            self.assertTrue(item["label"] and item["fields"])

    def test_source_options_match_module(self):
        schema = {item["type"]: item for item in block_schema()}
        options = schema["source"]["fields"][0]["options"]
        self.assertEqual(options, list(SOURCE_KEYS.keys()))


if __name__ == "__main__":
    unittest.main()
