# -*- coding: utf-8 -*-
"""岗位 SOP 收敛引擎单测。"""
from __future__ import annotations

import unittest

from app.todos.sop import classify_todo


class SopClassifyTests(unittest.TestCase):
    def _exec(self, **kw):
        return classify_todo(**kw)["executor"]

    def test_person_mention_delegation(self):
        r = classify_todo("让海文写一封邮件，说明印度独代谈判条件")
        self.assertEqual(r["executor"], "何海文")
        self.assertEqual(r["position"], "海外经销商销售")

    def test_person_mention_wins_over_domain_default(self):
        r = classify_todo("让海文准备 PI 报价给客户")
        self.assertEqual(r["executor"], "何海文")  # 点名指派覆盖岗位默认人
        self.assertEqual(r["position"], "海外商务")  # 但岗位域标注为商务

    def test_manager_scope(self):
        r = classify_todo("安排招聘面试新的经销商销售")
        self.assertEqual(r["executor"], "刘春梅")
        self.assertEqual(r["position"], "海外经销商主管")

    def test_manager_coordination(self):
        r = classify_todo("跨组协调资源推进开业")
        self.assertEqual(r["position"], "海外经销商主管")
        self.assertEqual(r["executor"], "刘春梅")

    def test_business_default(self):
        r = classify_todo("给客户发 PI 确认交期和 SWIFT 账号")
        self.assertEqual(r["executor"], "冯磊")

    def test_logistics_no_person(self):
        r = classify_todo("安排备货发货，准备好 UN38.3 证书")
        self.assertEqual(r["position"], "海外物流")
        self.assertEqual(r["executor"], "")  # 三人分工相同，无信号不定人

    def test_logistics_with_speaker(self):
        r = classify_todo(
            "安排备货发货", speaker="鲜娜"
        )
        self.assertEqual(r["position"], "海外物流")
        self.assertEqual(r["executor"], "鲜娜")

    def test_data_default(self):
        r = classify_todo("核对本月提成和看板数据")
        self.assertEqual(r["executor"], "付汪阳")

    def test_agent_anchor_sales(self):
        r = classify_todo("跟进 VMG 的订单")
        self.assertEqual(r["executor"], "于冰")
        self.assertEqual(r["position"], "海外经销商销售")

    def test_region_anchor_sales(self):
        r = classify_todo("越南门店的开业活动准备")
        self.assertEqual(r["executor"], "于冰")

    def test_ambiguous_region_iraq_unresolved(self):
        r = classify_todo("伊拉克客户跟进", participant="Lina")
        self.assertEqual(r["position"], "海外经销商销售")
        # 区域歧义 → 回退销售参与者；输出 IM 规范名
        self.assertEqual(r["executor"], "DEHDAHOUMAIMA")

    def test_hire_shop_staff_is_sales_not_manager(self):
        r = classify_todo("招聘店员，要求有奢侈品销售经验")
        self.assertEqual(r["position"], "海外经销商销售")
        self.assertNotEqual(r["executor"], "刘春梅")

    def test_speaker_fallback(self):
        r = classify_todo("准备周会材料", speaker="尤文静")
        self.assertEqual(r["position"], "unclassified")
        self.assertEqual(r["executor"], "尤文静")

    def test_homophone_alias_yutong(self):
        # 会议纪要常把「宇彤」写成「雨桐」，应识别为王宇彤
        r = classify_todo("让雨桐完成备货和标签相关准备")
        self.assertEqual(r["executor"], "王宇彤")

    def test_unmatched(self):
        r = classify_todo("催九六二零机器款项")
        self.assertEqual(r["position"], "unclassified")
        self.assertEqual(r["executor"], "")

    def test_latin_tokens(self):
        r = classify_todo("prepare the PI and check SWIFT for customer")
        self.assertEqual(r["executor"], "冯磊")

    def test_ai_keyword_word_boundary(self):
        r = classify_todo("安排 AI 工具使用培训")
        self.assertEqual(r["executor"], "付汪阳")

    def test_boss_alias_wangyang(self):
        r = classify_todo("把这个使用记录发给汪洋")
        self.assertEqual(r["executor"], "付汪阳")

    def test_self_mention_not_delegation(self):
        # 参与者自称不算指派，取下一个被点名人
        r = classify_todo("我来催海文交周报", participant="刘春梅")
        self.assertEqual(r["executor"], "何海文")


if __name__ == "__main__":
    unittest.main()
