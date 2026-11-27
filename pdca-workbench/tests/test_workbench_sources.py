import os
import unittest
import httpx
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.workbench_sources import SalesQuery, VemoryQuery, WhatsAppAccounts, WhatsAppQuery, _sales, _vemory


class VerifiedWorkbenchSourcesTest(unittest.TestCase):
    def test_whatsapp_uses_live_resolver_principal_and_waits_for_slow_reads(self):
        query = WhatsAppAccounts(kind="ainative-whatsapp-accounts", page=1)
        identity = {"rows": [{"subject_type": "employee", "exact_match": True, "employee_id": 23}],
                    "permission_scope": {"mapped_local_user_id": 23}}
        payload = {"rows": [], "pagination": {"has_more": False}, "query_context": {
            "subject": {"employee_id": 23}, "filters": {"platform": "WhatsApp"}}}
        with (
            patch.dict(os.environ, {"PDCA_WORKBENCH_AISALES_VPS_TOKEN": ""}),
            patch("app.workbench_sources.get_settings", return_value=SimpleNamespace(aisales_mcp_token="fixture")),
            patch("app.duzhan_ledger.mcp_call", side_effect=[identity, payload, identity, httpx.ReadTimeout("timeout")]) as call,
        ):
            self.assertEqual(_sales(query, 123)["rows"], [])
            self.assertEqual([c.args[0] for c in call.call_args_list], ["business.resolve_subject", "business.query"])
            self.assertGreater(call.call_args.kwargs["read_timeout"], 40)
            identity["permission_scope"]["mapped_local_user_id"] = 24
            with self.assertRaises(HTTPException) as forbidden:
                _sales(query, 123)
            self.assertEqual(forbidden.exception.status_code, 403)
            with self.assertRaises(HTTPException) as slow:
                _sales(query, 123)
            self.assertEqual(slow.exception.status_code, 504)

    def test_bound_accounts_use_employee_mapping_and_refuse_another_owner(self):
        query = WhatsAppAccounts(kind="ainative-whatsapp-accounts", page=1)
        identity = {"rows": [{"subject_type": "employee", "exact_match": True, "employee_id": 23}]}
        account = {"row_type": "detail", "platform": "WhatsApp", "employee_id": 23, "account_id": "wa-1",
                   "account_name": "Office", "status": "启用", "remark": "private"}
        payload = {"rows": [{"row_type": "summary"}, account], "is_complete": True, "total_is_exact": True,
                   "pagination": {"has_more": False}, "query_context": {
                       "subject": {"employee_id": 23}, "filters": {"platform": "WhatsApp"}}}
        with patch.dict(os.environ, {"PDCA_WORKBENCH_AISALES_VPS_TOKEN": "fixture"}), patch(
                "app.duzhan_ledger.mcp_call", side_effect=[identity, payload, identity, payload]) as call:
            result = _sales(query, 123)
            self.assertEqual(result["rows"], [{"账号编号": "wa-1", "账号": "Office", "状态": "启用"}])
            self.assertEqual(call.call_args.args[1]["subject"], {"employee_id": 23})
            self.assertEqual(call.call_args.args[1]["vps_user_id"], 123)
            account["employee_id"] = 24
            with self.assertRaises(HTTPException):
                _sales(query, 123)

    def test_whatsapp_messages_use_verified_subject_and_only_return_scoped_chat_fields(self):
        query = WhatsAppQuery(kind="ainative-whatsapp", start="2026-11-20", end="2026-11-26",
                              customerRef="ref-one", accountId="wa-1", page=2)
        employee = {"rows": [{"subject_type": "employee", "exact_match": True, "employee_id": 23}]}
        message = {"row_type": "detail", "platform": "WhatsApp", "customer_ref": "ref-one", "id": "message-1",
                   "content": "fixture reply", "direction": "inbound", "time": "2026-11-25 12:01:00",
                   "multimodal": {"media_url": "https://example.invalid"}, "customer_id": "fixture-private-id"}
        payload = {"rows": [{"row_type": "summary"}, {**message, "customer_ref": "ref-newly-signed"},
                            {**message, "platform": "微信"}],
                   "source_sync_at": "2026-11-26 12:00:00", "is_complete": True,
                   "query_context": {"subject": {"employee_id": 23}, "filters": {
                       "platform": "WhatsApp", "account_id": "wa-1", "customer_ref": "ref-redacted-by-service"}},
                   "pagination": {"has_more": True}}
        with (
            patch.dict(os.environ, {"PDCA_WORKBENCH_AISALES_VPS_TOKEN": "fixture"}),
            patch("app.duzhan_ledger.mcp_call", side_effect=[employee, payload]) as call,
        ):
            result = _sales(query, 123)
        name, args = call.call_args.args
        self.assertEqual(name, "business.get_evidence")
        self.assertEqual(args["vps_user_id"], 123)
        self.assertEqual(args["subject"], {"employee_id": 23})
        self.assertEqual(args["filters"], {"platform": "WhatsApp", "page": 2, "page_size": 40, "account_id": "wa-1",
                                           "customer_ref": "ref-one"})
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["消息"], "fixture reply")
        self.assertEqual(result["rows"][0]["客户引用"], "ref-one")
        self.assertNotIn("multimodal", result["rows"][0])
        self.assertNotIn("customer_id", result["rows"][0])
        self.assertEqual(result["hasMore"], True)
        with (
            patch.dict(os.environ, {"PDCA_WORKBENCH_AISALES_VPS_TOKEN": "fixture"}),
            patch("app.duzhan_ledger.mcp_call", side_effect=[employee, {**payload, "query_context": {}}]),
        ):
            with self.assertRaises(HTTPException) as denied:
                _sales(query, 123)
        self.assertEqual(denied.exception.status_code, 502)

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
