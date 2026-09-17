# -*- coding: utf-8 -*-
"""C转B 20:00 WhatsApp 晚追。"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from app.ctob import (
    CtobOwner,
    classify_lead,
    infer_blockers,
    parse_cohort,
    parse_wa_chats,
    parse_wa_summary,
    render_brief,
    run_ctob,
)

OWNER = CtobOwner("张心言", "776e2a94-884a-45dd-aab5-566e15e6b521", 31)

CUSTOMERS = {
    "rows": [
        {
            "row_type": "summary",
            "reached_customer_count": 21,
            "replied_customer_count": 5,
            "outbound_message_count": 52,
            "inbound_message_count": 28,
            "new_customer_count": 4,
            "is_complete": True,
        },
        {
            "row_type": "detail",
            "customer_nickname": "S 9.7 静默耳机 澳大利亚 Kieu",
            "country": "澳大利亚",
            "outbound_message_count": 14,
            "inbound_message_count": 17,
            "replied": True,
            "touched": True,
            "last_message_time": "2026-09-16 14:42:27",
        },
        {
            "row_type": "detail",
            "customer_nickname": "9.13弃单Asma Aktar美国",
            "country": "美国",
            "outbound_message_count": 14,
            "inbound_message_count": 17,
            "replied": True,
            "touched": True,
            "last_message_time": "2026-09-16 08:29:00",
        },
        {
            "row_type": "detail",
            "customer_nickname": "汽车预售 迪拜线索",
            "country": "阿联酋",
            "outbound_message_count": 3,
            "inbound_message_count": 0,
            "replied": False,
            "touched": True,
            "last_message_time": "2026-09-16 14:59:15",
        },
        {
            "row_type": "detail",
            "customer_nickname": "160***1900",
            "country": "美国",
            "outbound_message_count": 1,
            "inbound_message_count": 1,
            "replied": True,
            "touched": True,
            "last_message_time": "2026-09-16 14:58:17",
        },
    ]
}

COHORT = {
    "summary": {
        "new_customer_count": 4,
        "has_chat_count": 4,
        "has_reply_count": 0,
        "in_intent_pipeline_count": 0,
    },
    "rows": [
        {
            "customer_display_name": "918***3361",
            "has_chat": True,
            "has_reply": False,
            "outbound_message_count": 1,
            "inbound_message_count": 0,
            "stage": "not_in_intent_ledger",
            "latest_progress": None,
        },
        {
            "customer_display_name": "官网询盘 印度",
            "has_chat": True,
            "has_reply": False,
            "outbound_message_count": 1,
            "inbound_message_count": 0,
            "stage": "not_in_intent_ledger",
            "latest_progress": None,
        },
    ],
}


class CtobTests(unittest.TestCase):
    def test_classify_car_and_ctob_not_headset(self):
        self.assertEqual(classify_lead("汽车预售 迪拜线索"), "汽车")
        self.assertEqual(classify_lead("9.13弃单Asma"), "转B")
        self.assertEqual(classify_lead("手机维修店也卖手机/想做"), "转B")
        self.assertEqual(classify_lead("S 9.7 静默耳机 Kieu"), "C端")
        self.assertEqual(classify_lead("160***1900"), "未标")

    def test_parse_keeps_focus_drops_headset(self):
        summary = parse_wa_summary(CUSTOMERS)
        chats = parse_wa_chats(CUSTOMERS)
        names = [item["name"] for item in chats]
        self.assertEqual(summary["reached"], 21)
        self.assertEqual(summary["car"], 1)
        self.assertEqual(summary["ctob"], 1)
        self.assertEqual(summary["other"], 2)
        self.assertIn("9.13弃单Asma Aktar美国", names)
        self.assertIn("汽车预售 迪拜线索", names)
        self.assertNotIn("S 9.7 静默耳机 澳大利亚 Kieu", names)
        self.assertEqual(chats[0]["rounds"], 14)

    def test_blockers_focus_only(self):
        chats = parse_wa_chats(CUSTOMERS)
        cohort = parse_cohort(COHORT)
        lines = infer_blockers(chats, cohort)
        self.assertTrue(any("客户在等回复" in item for item in lines))
        self.assertTrue(any("等客户回" in item for item in lines))
        self.assertTrue(lines[0].startswith("9.13弃单"))
        self.assertEqual(cohort["focus_new"], 1)
        self.assertTrue(any("官网询盘" in item for item in lines))
        self.assertFalse(any("918" in item for item in lines))

    def test_brief_has_support_and_no_triple_chase(self):
        text = render_brief(
            OWNER,
            "2026-09-16",
            parse_wa_summary(CUSTOMERS),
            parse_wa_chats(CUSTOMERS),
            parse_cohort(COHORT),
        )
        self.assertIn("@张心言", text)
        self.assertIn("[转B]", text)
        self.assertIn("[汽车]", text)
        self.assertIn("14轮", text)
        self.assertIn("先回人", text)
        self.assertNotIn("工时估算", text)
        self.assertNotIn("Kieu", text)
        self.assertNotIn("静默耳机", text)
        self.assertNotIn("10:00", text)
        self.assertNotIn("红榜", text)

    def test_weekend_skip(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        saturday = datetime(2026, 9, 19, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("app.ctob.push_duzhan_message") as push:
            result = run_ctob("2026-09-19", saturday)
        self.assertEqual(result.get("skipped"), "weekend")
        push.assert_not_called()


if __name__ == "__main__":
    unittest.main()
