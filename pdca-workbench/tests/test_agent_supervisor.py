# -*- coding: utf-8 -*-
"""主 Agent 测试：确定性路由、结构化决策解析、事实校验、运行生命周期。"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.agents.schemas import SupervisorDecision
from app.agents.supervisor_graph import (
    _parse_decision,
    build_department_summary,
    classify_intent,
    decision_with_llm,
    fact_check_summary,
    normalize_intent,
)
from app.agents import supervisor_service


class SupervisorGraphTests(unittest.TestCase):
    def test_known_queries_route_without_llm(self):
        decision = classify_intent("查一下今天谁有多少待办、闭环没有")
        self.assertIsNotNone(decision)
        self.assertEqual(decision.intent, "known_readonly_query")
        self.assertEqual(decision.actions[0].action_type, "task_stats")
        decision2 = classify_intent("生成部门早会提纲")
        self.assertEqual(decision2.intent, "department_summary")
        self.assertIsNone(classify_intent("帮我看看圣诞黑五有没有提前备货铺垫"))

    def test_parse_decision_tolerates_fences(self):
        raw = chr(96) * 3 + 'json' + chr(10) + '{"intent": "department_summary"}' + chr(10) + chr(96) * 3
        decision = _parse_decision(raw)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.intent, "department_summary")
        self.assertIsNone(_parse_decision("完全不是 JSON"))

    def test_parse_decision_validates_schema(self):
        raw = '{"intent": "department_summary", "actions": [{"action_type": "collect"}]}'
        decision = _parse_decision(raw)
        self.assertIsInstance(decision, SupervisorDecision)

    def test_llm_unavailable_falls_back_to_ask_user(self):
        """模型不可用：任务保留（ask_user），不允许吞错。"""
        with patch(
            "app.agents.llm_client.supervisor_client",
            side_effect=Exception("network down"),
        ):
            decision = decision_with_llm("帮我分析全部门圣诞铺垫")
        self.assertEqual(decision.intent, "ask_user")
        self.assertTrue(decision.unknowns)

    def test_llm_decision_path_uses_client_and_parses_json(self):
        """回归：配置就绪时必须真正调用模型并解析其 JSON（曾因 prompts 子模块导入失败静默回退）。"""
        from app.agents.prompts import load_supervisor

        self.assertTrue(load_supervisor(), "supervisor.md 必须可加载")

        class FakeClient:
            configured = True

            def chat(self, messages, max_tokens=2000, temperature=0.1):
                return {
                    "content": '{"intent": "department_summary", "summary": "ok", '
                    '"actions": [{"action_type": "collect", "target": "all"}], "unknowns": []}',
                }

        with patch(
            "app.agents.llm_client.supervisor_client", return_value=FakeClient()
        ):
            decision = decision_with_llm("生成部门总结")
        self.assertEqual(decision.intent, "department_summary")
        self.assertEqual(decision.actions[0].action_type, "collect")

    def test_normalize_intent_maps_freeform(self):
        self.assertEqual(
            normalize_intent("查询全部门未闭环待办", "查一下今天谁还有待办"),
            "known_readonly_query",
        )
        self.assertEqual(normalize_intent("生成部门早会简报"), "department_summary")
        self.assertEqual(normalize_intent("催办各群"), "group_followup")
        self.assertEqual(normalize_intent("修改扣罚规则"), "risky_action")
        # 规范值保持不变
        self.assertEqual(normalize_intent("known_readonly_query"), "known_readonly_query")
        # 无法收敛时保留原样（调用方保守处理）
        self.assertEqual(
            normalize_intent("完全看不懂的意图", "随便说点什么"), "完全看不懂的意图"
        )

    def test_fact_check_catches_unknown_person(self):
        problems = fact_check_summary("张三今天回款 500 万")
        self.assertTrue(any(item["rule"] == "unknown_person" for item in problems))

    def test_fact_check_allows_registry_person(self):
        problems = fact_check_summary("于冰今日已提交日报")
        self.assertFalse(any(item["rule"] == "unknown_person" for item in problems))

    def test_fact_check_flags_risky_terms(self):
        problems = fact_check_summary("建议给经销商 40% 折扣")
        self.assertTrue(any(item["rule"] == "risky_term_needs_source" for item in problems))

    def test_fact_check_none_as_zero_suspect(self):
        problems = fact_check_summary("WhatsApp 未覆盖，触达 0")
        self.assertTrue(any(item["rule"] == "none_as_zero_suspect" for item in problems))

    def test_build_department_summary_shape(self):
        from app.models.pdca_task import PdcaTask  # noqa: F401 注册元数据，避免依赖其他测试模块导入顺序
        from app.models.audit_log import AuditLog  # noqa: F401

        engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(engine)
        with patch("app.database.get_engine", return_value=engine), patch(
            "app.agents.outbox.get_engine", return_value=engine
        ):
            summary = build_department_summary("2026-09-17")
        engine.dispose()
        self.assertEqual(summary["date"], "2026-09-17")
        self.assertIn("open_tasks_by_owner", summary["sections"])
        self.assertIn("pending_approvals", summary["sections"])
        self.assertIn("data_unknowns", summary["sections"])


class SupervisorServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch(
            "app.agents.supervisor_service.get_engine", return_value=self.engine
        )
        self.patch_engine.start()
        self.patch_events = patch("app.agents.events.get_engine", return_value=self.engine)
        self.patch_events.start()
        self.patch_db = patch("app.database.get_engine", return_value=self.engine)
        self.patch_db.start()
        self.patch_outbox_engine = patch(
            "app.agents.outbox.get_engine", return_value=self.engine
        )
        self.patch_outbox_engine.start()
        self.patch_log = patch("app.agents.supervisor_service.log_action")
        self.patch_log.start()

    def tearDown(self):
        self.patch_log.stop()
        self.patch_outbox_engine.stop()
        self.patch_db.stop()
        self.patch_events.stop()
        self.patch_engine.stop()
        self.engine.dispose()

    def test_run_lifecycle_deterministic_route(self):
        """确定性路由不依赖 LLM：直接查询任务统计。"""
        run = supervisor_service.start_run(
            run_type="user_task",
            requested_by="manager",
            input_text="查一下今天谁有多少待办、闭环没有",
        )
        self.assertEqual(run.status, "queued")
        result = supervisor_service.execute_run(run.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["intent"], "known_readonly_query")
        self.assertIn("task_stats", result["results"])

    def test_execute_run_not_found(self):
        result = supervisor_service.execute_run(999999)
        self.assertFalse(result["ok"])
        self.assertEqual(result["detail"], "运行不存在")

    def test_collect_action_is_read_only_even_outside_shadow_mode(self):
        from app.agents.schemas import SupervisorAction

        decision = SupervisorDecision(
            intent="department_summary",
            summary="部门总结",
            actions=[SupervisorAction(action_type="collect", target="all")],
        )
        run = supervisor_service.start_run(
            run_type="user_task", requested_by="manager", input_text="部门总结"
        )
        with patch(
            "app.agents.supervisor_service.classify_intent", return_value=decision
        ), patch(
            "app.agents.supervisor_service._tool_group_state",
            return_value={"groups": [], "count": 0},
        ), patch(
            "app.agents.supervisor_service.build_department_summary",
            return_value={"summary_draft": "总结"},
        ), patch(
            "app.agents.group_service.run_group_slot"
        ) as run_group_slot:
            result = supervisor_service.execute_run(run.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["results"]["collect"]["count"], 0)
        run_group_slot.assert_not_called()

    def test_llm_readonly_query_gets_default_tools(self):
        """LLM 查询类意图即使没给白名单动作，也返回只读数据。"""
        with patch(
            "app.agents.supervisor_service.classify_intent", return_value=None
        ), patch(
            "app.agents.supervisor_service.decision_with_llm",
            return_value=SupervisorDecision(
                intent="查询全部门未闭环待办", summary="", actions=[]
            ),
        ):
            run = supervisor_service.start_run(
                run_type="user_task", requested_by="manager", input_text="查一下全部门待办"
            )
            result = supervisor_service.execute_run(run.id)
        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"], "known_readonly_query")
        for key in ("task_stats", "group_state", "slot_health"):
            self.assertIn(key, result["results"])

    def test_risky_intent_becomes_waiting_approval(self):
        """risky_action 强制进入审批门，不直接成功。"""
        with patch(
            "app.agents.supervisor_service.decision_with_llm",
            return_value=SupervisorDecision(
                intent="risky_action",
                summary="拟修改扣罚规则",
                actions=[],
                approval_required=False,
            ),
        ):
            run = supervisor_service.start_run(
                run_type="user_task", requested_by="manager", input_text="修改扣罚规则"
            )
            result = supervisor_service.execute_run(run.id)
        self.assertEqual(result["status"], "waiting_approval")

    def test_failed_run_is_recorded_and_recoverable(self):
        from app.agents.schemas import SupervisorAction

        fallback = SupervisorDecision(
            intent="known_readonly_query",
            summary="重试成功",
            actions=[SupervisorAction(action_type="task_stats", target="all")],
        )
        with patch(
            "app.agents.supervisor_service.classify_intent", return_value=None
        ), patch(
            "app.agents.supervisor_service.decision_with_llm",
            side_effect=[RuntimeError("boom"), fallback],
        ):
            run = supervisor_service.start_run(
                run_type="user_task", requested_by="manager", input_text="任意任务"
            )
            result = supervisor_service.execute_run(run.id)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "failed")
            # 失败运行可重试（状态 queued/failed 才允许再次执行）
            retry = supervisor_service.execute_run(run.id)
        self.assertTrue(retry["ok"])
        self.assertEqual(retry["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()

