# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine, select

from app.agents.models import AgentRun
from app.agents.router import create_agent_task, run_detail, runs_list, stats
from app.auth.models import User
from app.models.dealer_store import DealerStore
from app.models.pdca_task import PdcaTask


class AgentTeamScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(self.engine)
        self.manager = User(
            username="manager-a", hashed_password="x", role="manager",
            team_key="team-a", data_scope="team",
        )
        with Session(self.engine) as session:
            session.add(DealerStore(
                store_id="a", name="A", sales_owner="ownerA", team_key="team-a"
            ))
            session.add(DealerStore(
                store_id="b", name="B", sales_owner="ownerB", team_key="team-b"
            ))
            session.add(DealerStore(
                store_id="a2", name="A2", sales_owner="ownerA2", team_key="team-a"
            ))
            session.add(PdcaTask(task_date="2026-09-22", title="A", owner="ownerA"))
            session.add(PdcaTask(task_date="2026-09-22", title="B", owner="ownerB"))
            session.add(PdcaTask(
                task_date="2026-09-22", title="A shared", owner="ownerA & ownerA2"
            ))
            session.add(PdcaTask(
                task_date="2026-09-22", title="Mixed", owner="ownerA & ownerB"
            ))
            session.add(AgentRun(run_key="a", requested_by="manager-a", input_text="A"))
            session.add(AgentRun(run_key="b", requested_by="manager-b", input_text="B"))
            session.commit()
            self.other_run_id = session.exec(
                select(AgentRun).where(AgentRun.run_key == "b")
            ).one().id

    def tearDown(self):
        self.engine.dispose()

    def test_stats_only_contains_manager_team_owners(self):
        with patch("app.database.get_engine", return_value=self.engine), patch(
            "app.agents.supervisor_service.get_engine", return_value=self.engine
        ), patch("app.agents.router.list_outbox", return_value=[]), patch(
            "app.agents.router.all_slot_health_today", return_value=[]
        ):
            result = asyncio.run(stats(user=self.manager))
        self.assertEqual(
            {row["owner"] for row in result["task_stats"]["owners"]},
            {"ownerA", "ownerA & ownerA2"},
        )
        self.assertEqual(result["task_stats"]["total_tasks"], 2)

    def test_manager_only_sees_own_agent_runs(self):
        with patch("app.database.get_engine", return_value=self.engine), patch(
            "app.agents.supervisor_service.get_engine", return_value=self.engine
        ):
            result = asyncio.run(runs_list(limit=50, user=self.manager))
            self.assertEqual([row["requested_by"] for row in result["runs"]], ["manager-a"])
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(run_detail(self.other_run_id, user=self.manager))
        self.assertEqual(denied.exception.status_code, 404)

    def test_manager_cannot_request_full_department_summary_via_generic_task(self):
        with patch("app.database.get_engine", return_value=self.engine), patch(
            "app.agents.supervisor_service.get_engine", return_value=self.engine
        ), patch(
            "app.agents.supervisor_service.build_department_summary"
        ) as build_summary, patch("app.agents.supervisor_service.write_event"):
            with self.assertRaises(HTTPException) as denied:
                asyncio.run(create_agent_task(
                    payload={"text": "生成部门总结"}, user=self.manager
                ))
        self.assertEqual(denied.exception.status_code, 403)
        build_summary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
