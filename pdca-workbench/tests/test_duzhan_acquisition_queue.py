from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user
from app.duzhan_admin import router as duzhan


class AcquisitionQueueTests(TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(duzhan.router)
        self.client = TestClient(app)
        self.path = "/api/duzhan-agents/acquisition-queue"
        self.role = "admin"
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=self.role)
        self.settings = SimpleNamespace(
            acquisition_supervision_url="https://acquisition.example.test",
            acquisition_supervision_token="x" * 32,
        )

    def test_authorization_and_opt_in(self):
        with patch.object(duzhan, "get_settings", return_value=self.settings) as settings:
            self.role = "sales"
            self.assertEqual(self.client.get(self.path).status_code, 403)
            settings.assert_not_called()
            self.role = "admin"
            self.settings.acquisition_supervision_url = "http://acquisition.example.test"
            self.assertEqual(self.client.get(self.path).status_code, 503)

    def test_admin_gets_only_supervision_fields(self):
        item = {
            "owner_user_id": 42,
            "stage": "replied",
            "next_action": "安排演示",
            "next_due_at": "2026-11-03T00:00:00Z",
        }
        owner = {"owner_user_id": 42, "owner_name": "Sales"}
        data = {"items": [item], "by_owner": [owner], "truncated": False}
        url = self.settings.acquisition_supervision_url + "/api/integrations/sales-supervision"
        upstream = httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"ok": True, "data": {
                **data,
                "items": [{**item, "email": "hidden@example.test"}],
                "by_owner": [{**owner, "internal_note": "hidden"}],
            }},
        )
        with (
            patch.object(duzhan, "get_settings", return_value=self.settings),
            patch.object(duzhan.httpx, "AsyncClient") as client,
        ):
            get = AsyncMock(return_value=upstream)
            client.return_value.__aenter__.return_value.get = get
            response = self.client.get(self.path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), data)
        self.assertEqual(response.headers["cache-control"], "no-store")
        get.assert_awaited_once_with(
            url, headers={"Authorization": f"Bearer {self.settings.acquisition_supervision_token}"},
            params={"source_limit": 100, "source_offset": 0, "reply_limit": 100, "reply_offset": 0},
        )

    def upstream(self, data, status=200):
        return httpx.Response(status, request=httpx.Request("GET", "https://acquisition.example.test"),
                              json={"ok": True, "data": data})

    def read(self, data, query="", status=200):
        with (patch.object(duzhan, "get_settings", return_value=self.settings),
              patch.object(duzhan.httpx, "AsyncClient") as client):
            get = AsyncMock(return_value=self.upstream(data, status))
            client.return_value.__aenter__.return_value.get = get
            response = self.client.get(self.path + query)
            client.assert_called_once_with(timeout=10, follow_redirects=False, trust_env=False)
        return response, get

    def source_data(self):
        at = "2026-11-17T00:00:00Z"
        counts = dict(records=310, open=310, completed=0, actionable=310, overdue=0,
                      unaccepted=310, no_progress=310, missing_due=0,
                      missing_next_action=0, pending_reply=0, reply_processing=0)
        reference = dict(id=7, status="pending", group_id="group", message_id="message",
                         dispatch_message_id="dispatch", occurred_at=at,
                         reason_codes=["task_missing"], body_text="PRIVATE BODY")
        source = dict(task_id=12, display_name="Synthetic source", route="partner_site",
                      source_system="report_catalog", report_id="qa-report",
                      owner_user_id=4, owner_name="QA sales", status="pending", stage="pending",
                      accepted_at=None, last_progress_at=None, last_progress=None,
                      company_id=None, customer_stage=None, customer_stage_status="unlinked",
                      customer_stage_event_id=None, customer_stage_at=None, next_due_at=at,
                      next_action="Verify source", overdue=False, unaccepted=True, no_progress=True,
                      missing_due=False, missing_next_action=False, pending_reply=False,
                      reply_processing=False, signals=["unaccepted", "no_progress"],
                      pending_reply_count=0, processing_reply_count=0, pending_replies=[],
                      pending_replies_truncated=False, stored_outreach_hold=False,
                      outreach_hold_status="not_checked", raw_source_context={"email": "private@example.test"})
        return dict(items=[], by_owner=[], truncated=False, as_of=at,
                    totals=dict(open=0, actionable=0, unstarted=0, overdue=0, replied_open=0),
                    source_tasks=dict(as_of=at, unit="source_task", total=310, limit=1, offset=0,
                                      has_more=True, totals=counts,
                                      by_owner=[dict(owner_user_id=4, owner_name="QA sales", **counts)],
                                      items=[source], secret="PRIVATE SECRET"),
                    owner_pending_replies=dict(as_of=at, unit="vps_message", total=1, limit=100,
                                               offset=0, has_more=False,
                                               by_owner=[dict(owner_user_id=4, owner_name="QA sales", pending=1, received=0)],
                                               items=[dict(reference, owner_user_id=4, owner_name="QA sales")]))

    def test_source_tasks_and_unselected_messages_keep_distinct_units_and_privacy(self):
        response, _ = self.read(self.source_data())
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["source_tasks"]["total"], 310)
        self.assertEqual(data["source_tasks"]["unit"], "source_task")
        self.assertEqual(data["owner_pending_replies"]["unit"], "vps_message")
        self.assertEqual(data["totals"]["open"], 0)
        self.assertIsNone(data["source_tasks"]["items"][0]["company_id"])
        self.assertIsNone(data["source_tasks"]["items"][0]["customer_stage"])
        self.assertEqual(data["source_tasks"]["items"][0]["outreach_hold_status"], "not_checked")
        self.assertNotIn("PRIVATE", response.text)
        self.assertNotIn("private@example.test", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_independent_pagination_is_forwarded_without_owner_scope(self):
        response, get = self.read(self.source_data(), "?source_limit=1&source_offset=200&reply_limit=5&reply_offset=10&owner_ids=999")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get.call_args.kwargs["params"],
                         dict(source_limit=1, source_offset=200, reply_limit=5, reply_offset=10))

    def test_invalid_or_duplicate_pagination_does_not_call_upstream(self):
        with patch.object(duzhan.httpx, "AsyncClient") as client:
            for query in ("?source_limit=101", "?source_offset=-1", "?reply_limit=0",
                          "?reply_offset=1000001", "?source_limit=1&source_limit=2"):
                self.assertIn(self.client.get(self.path + query).status_code, (400, 422))
            client.assert_not_called()

    def test_progress_origin_and_hold_are_preserved_without_raw_messages(self):
        data = self.source_data()
        task = data["source_tasks"]["items"][0]
        task.update(stored_outreach_hold=True, outreach_hold_status="held")
        task["last_progress"] = dict(id=8, at="2026-11-17T00:00:00Z", source=None, stage="contacted",
                                     note="PRIVATE NOTE", origin=dict(group_id="qa-group", message_id="qa-reply",
                                     dispatch_message_id="qa-dispatch", occurred_at="2026-11-17T00:00:00Z", body="PRIVATE BODY"))
        response, _ = self.read(data)
        self.assertEqual(response.status_code, 200)
        result = response.json()["source_tasks"]["items"][0]
        self.assertTrue(result["stored_outreach_hold"])
        self.assertEqual(result["outreach_hold_status"], "held")
        self.assertIsNone(result["last_progress"]["source"])
        self.assertEqual(result["last_progress"]["origin"]["message_id"], "qa-reply")
        self.assertNotIn("PRIVATE", response.text)

    def test_wrong_units_and_unaware_timestamps_are_unavailable_not_zero(self):
        for field, bad in (("unit", "company"), ("as_of", "2026-11-17T00:00:00")):
            data = self.source_data()
            data["source_tasks"][field] = bad
            response, _ = self.read(data)
            self.assertEqual(response.status_code, 502)
            self.assertNotIn("PRIVATE", response.text)

    def test_missing_source_block_stays_unavailable(self):
        response, _ = self.read(dict(items=[], by_owner=[], truncated=False))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("source_tasks", response.json())
        self.assertNotIn("owner_pending_replies", response.json())

    def test_upstream_failure_is_not_returned_as_empty_success(self):
        response, _ = self.read({"secret": "PRIVATE"}, status=401)
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("PRIVATE", response.text)

    def test_url_credentials_and_query_are_rejected(self):
        with (patch.object(duzhan, "get_settings", return_value=self.settings),
              patch.object(duzhan.httpx, "AsyncClient") as client):
            for url in ("https://user:password@example.test", "https://example.test?token=secret", "https://example.test/#fragment"):
                self.settings.acquisition_supervision_url = url
                self.assertEqual(self.client.get(self.path).status_code, 503)
            client.assert_not_called()
