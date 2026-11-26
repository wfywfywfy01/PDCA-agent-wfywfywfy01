import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.workbench_sources import SalesQuery, VemoryQuery, _sales, _vemory


class VerifiedWorkbenchSourcesTest(unittest.TestCase):
    def test_personal_sales_token_must_belong_to_verified_vps_user(self):
        query = SalesQuery(kind="ainative-sales", report="reach", start="2026-11-20", end="2026-11-26")
        target = {"rows": [{"subject_type": "employee", "exact_match": True, "employee_id": 23}]}
        with (
            patch.dict(os.environ, {"PDCA_WORKBENCH_AISALES_VPS_TOKEN": ""}),
            patch("app.workbench_sources.get_settings", return_value=SimpleNamespace(aisales_mcp_token="fixture")),
            patch("app.duzhan_ledger.mcp_call", side_effect=[target, {"rows": [], "permission_scope": {"mapped_local_user_id": 24}}]) as call,
        ):
            with self.assertRaises(HTTPException) as denied:
                _sales(query, 123)
            self.assertEqual(denied.exception.status_code, 403)
            self.assertEqual([item.args[0] for item in call.call_args_list], ["business.resolve_subject", "business.catalog"])
            self.assertTrue(all("vps_user_id" not in item.args[1] for item in call.call_args_list))

    def test_meeting_lookup_uses_only_unique_vps_binding(self):
        query = VemoryQuery(kind="vemory-todos", start="2026-11-20", end="2026-11-26")
        roster = [{"vpsUserId": 123, "vemoryUserId": 10}, {"vpsUserId": 124, "vemoryUserId": 11}]
        with (
            patch.dict(os.environ, {"VEMORY_OPENAPI_KEY": "fixture"}),
            patch("app.workbench_sources.load_vemory_users", return_value=roster),
            patch("app.workbench_sources.fetch_vemory_todos", return_value=[]) as fetch,
        ):
            with self.assertRaises(HTTPException) as denied:
                _vemory(query, 999)
            self.assertEqual(denied.exception.status_code, 403)
            fetch.assert_not_called()
            self.assertEqual(_vemory(query, 123)["total"], 0)
            self.assertEqual(fetch.call_args.args[0], roster[0])
