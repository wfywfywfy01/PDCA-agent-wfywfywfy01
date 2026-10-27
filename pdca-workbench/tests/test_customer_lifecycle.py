"""Business gates and atomic evidence review using an isolated database."""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.models.dealer_store import DealerStore  # noqa: F401
from app.models.dealer_assignment import DealerAssignment  # noqa: F401
from app.customer_lifecycle.router import router


class CustomerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'lifecycle.sqlite'}",
                                    connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            db.add_all([
                User(id=1, username="seller-a", hashed_password="test", role="sales", team_key="A"),
                User(id=2, username="manager-a", hashed_password="test", role="manager", team_key="A"),
                User(id=3, username="seller-b", hashed_password="test", role="sales", team_key="B"),
                User(id=4, username="seller-a2", hashed_password="test", role="sales", team_key="A"),
            ])
            db.commit()
        self.current_id = 1
        app = FastAPI()
        app.include_router(router)

        def session():
            with Session(self.engine) as db:
                yield db

        def current_user():
            # Authentication is mocked; the service must re-read this user in the DB.
            return User(id=self.current_id, username="stale", role="admin", hashed_password="test")

        app.dependency_overrides[get_session] = session
        app.dependency_overrides[get_current_user] = current_user
        self.client = TestClient(app)
        self.base = "/api/customer-lifecycle"
        self.customer = self.create()
        self.path = self.base + "/customers/" + self.customer["id"]

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.temp.cleanup()

    def create(self, **changes):
        body = dict(name="Example company", owner_user_id=self.current_id, route=2, entity_verified=True,
                    source_note="人工核对历史账户研究记录，尚未自动接入来源")
        body.update(changes)
        response = self.client.post(self.base + "/customers", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def propose(self, **changes):
        body = dict(source_system="manual", event_id="event-1", occurred_at="2026-10-01T12:00:00Z",
                    summary="客户与销售确认下次会议。", proposed_stage="contacted")
        body.update(changes)
        response = self.client.post(self.path + "/proposals", json=body)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def review(self, proposal, version=1, key="confirm-key-1", action="confirm"):
        return self.client.post(self.path + f"/proposals/{proposal['id']}/{action}",
                                json=dict(expected_version=version, request_key=key))

    def qualify(self):
        response = self.client.patch(self.path, json=dict(expected_version=1, entity_verified=True,
            decision_maker="Purchasing lead", need="Pilot order", next_action="Review proposal",
            due_at="2026-11-01T10:00:00+08:00"))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["customer"]["version"]

    def test_same_name_stays_distinct_and_mapping_is_exact(self):
        other = self.create()
        self.assertNotEqual(other["id"], self.customer["id"])
        body = {"namespace": "aisales.sg.customer", "external_id": "external-001"}
        self.assertEqual(self.client.post(self.path + "/identities", json=body).status_code, 201)
        self.assertEqual(self.client.post(self.path + "/identities", json=body).status_code, 201)
        conflict = self.client.post(self.base + f"/customers/{other['id']}/identities", json=body)
        self.assertEqual(conflict.status_code, 409)
        result = self.client.get(self.base + "/customers", params=body).json()
        self.assertEqual([r["id"] for r in result["items"]], [self.customer["id"]])

    def test_external_ingest_requires_mapping_and_does_not_confirm(self):
        body = dict(source_system="ai_sales", event_id="sg:event-12", occurred_at="2026-10-01T12:00:00Z",
                    summary="Customer replied", proposed_stage="contacted", external_namespace="aisales.sg.customer",
                    external_id="C12", source_message_id="message-12")
        self.assertEqual(self.client.post(self.path + "/proposals", json=body).status_code, 422)
        self.client.post(self.path + "/identities", json={"namespace": body["external_namespace"], "external_id": "C12"})
        first = self.client.post(self.path + "/proposals", json=body)
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(first.json()["status"], "pending")
        duplicate = self.client.post(self.path + "/proposals", json=body)
        self.assertEqual(duplicate.json()["id"], first.json()["id"])
        changed_id = {**body, "event_id": "random-new-event-id"}
        self.assertEqual(self.client.post(self.path + "/proposals", json=changed_id).status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["customer"]["stage"], "pending")
        body["summary"] = "different payload"
        self.assertEqual(self.client.post(self.path + "/proposals", json=body).status_code, 409)

    def test_confirm_atomic_idempotent_and_version_checked(self):
        proposal = self.propose()
        response = self.review(proposal)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["customer"]["stage"], "contacted")
        self.assertEqual(response.json()["customer"]["version"], 2)
        retry = self.review(proposal)
        self.assertEqual(retry.status_code, 200, retry.text)
        self.assertEqual(len([r for r in retry.json()["audit"] if r["action"] == "proposal_confirmed"]), 1)
        pending = self.propose(event_id="event-2", proposed_stage="intent", occurred_at="2026-10-02T12:00:00Z")
        self.assertEqual(self.review(pending, key="confirm-key-2").status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["customer"]["version"], 2)
        self.assertEqual(self.review(pending, version=2, key="confirm-key-2").status_code, 200)

    def test_old_or_regressive_events_cannot_overwrite(self):
        self.review(self.propose(proposed_stage="intent"))
        old = self.propose(event_id="old-event", occurred_at="2026-09-30T12:00:00Z", proposed_stage="qualified")
        self.assertEqual(self.review(old, version=2, key="confirm-old-1").status_code, 409)
        lower = self.propose(event_id="new-lower", occurred_at="2026-10-02T12:00:00Z", proposed_stage="lead")
        self.assertEqual(self.review(lower, version=2, key="confirm-lower").status_code, 409)
        self.assertEqual(self.client.get(self.path).json()["customer"]["stage"], "intent")

    def test_reject_is_terminal_and_audited(self):
        proposal = self.propose()
        result = self.review(proposal, action="reject")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["customer"]["stage"], "pending")
        self.assertEqual(self.review(proposal, version=2, key="different-key").status_code, 409)
        self.assertEqual(self.review(proposal, action="reject").status_code, 200)

    def test_scope_and_current_role_cannot_be_bypassed_by_body(self):
        self.current_id = 4
        self.assertEqual(self.client.get(self.path).status_code, 404)
        self.assertEqual(self.client.get(self.base + "/customers").json()["items"], [])
        self.assertEqual(self.client.post(self.base + "/customers", json={"name": "X", "owner_user_id": 1}).status_code, 403)
        self.current_id = 2
        self.assertEqual(self.client.get(self.path).status_code, 200)
        self.assertEqual(self.client.patch(self.path, json={"expected_version": 1, "owner_user_id": 3}).status_code, 403)
        with Session(self.engine) as db:
            user = db.get(User, 2)
            user.data_scope = "none"
            db.add(user)
            db.commit()
        self.assertEqual(self.client.get(self.path).status_code, 403)

    def test_qualified_requires_confirmed_business_fields(self):
        proposal = self.propose(proposed_stage="qualified")
        self.assertEqual(self.review(proposal).status_code, 422)
        version = self.qualify()
        accepted = self.review(proposal, version=version)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["customer"]["due_at"].endswith("+00:00"))
        self.assertEqual(self.client.patch(self.path, json={"expected_version": 3, "need": ""}).status_code, 422)

    def test_unverified_entity_cannot_enter_business_stages(self):
        self.client.patch(self.path, json={"expected_version": 1, "entity_verified": False})
        proposal = self.propose(proposed_stage="lead")
        self.assertEqual(self.review(proposal, version=2).status_code, 422)
        self.assertEqual(self.client.get(self.path).json()["customer"]["stage"], "pending")

    def test_orders_and_payments_require_separate_finance_review(self):
        version = self.qualify()
        statement = self.propose(proposed_stage="ordered", summary="群消息说已经下单")
        self.assertEqual(self.review(statement, version=version).status_code, 422)
        order_body = dict(kind="order", namespace="erp.orders", external_id="O123", amount="123.45", currency="USD",
                          document_ref="erp://orders/O123", occurred_at="2026-10-01T10:00:00Z")
        order = self.client.post(self.path + "/business-links", json=order_body)
        self.assertEqual(order.status_code, 201, order.text)
        order_id = order.json()["id"]
        proposed = self.propose(event_id="order-evidence", proposed_stage="ordered", business_link_id=order_id)
        self.assertEqual(self.review(proposed, version=version, key="order-confirm").status_code, 422)
        finance_body = dict(request_key="verify-order-key", note="已按原订单凭证核对主体、金额与币种")
        self.assertEqual(self.client.post(self.path + f"/business-links/{order_id}/verify", json=finance_body).status_code, 403)
        self.current_id = 2
        result = self.client.post(self.path + f"/business-links/{order_id}/verify", json=finance_body)
        self.assertEqual(result.status_code, 200, result.text)
        self.current_id = 1
        self.assertEqual(self.review(proposed, version=version, key="order-confirm").status_code, 200)
        paid = self.propose(event_id="paid-message", proposed_stage="paid", occurred_at="2026-10-02T12:00:00Z")
        self.assertEqual(self.review(paid, version=3, key="paid-confirm").status_code, 422)
        payment_body = {**order_body, "kind": "payment", "namespace": "erp.receipts", "external_id": "R123",
                        "order_link_id": order_id, "document_ref": "erp://receipts/R123", "occurred_at": "2026-10-02T10:00:00Z"}
        payment = self.client.post(self.path + "/business-links", json=payment_body)
        self.assertEqual(payment.status_code, 201, payment.text)
        payment_id = payment.json()["id"]
        self.current_id = 2
        self.assertEqual(self.client.post(self.path + f"/business-links/{payment_id}/verify",
            json={"request_key": "verify-payment-key", "note": "已核对收款流水及订单核销关联"}).status_code, 200)
        self.current_id = 1
        complete = self.propose(event_id="paid-evidence", proposed_stage="paid", occurred_at="2026-10-02T12:00:00Z", business_link_id=payment_id)
        response = self.review(complete, version=3, key="paid-confirm-complete")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["customer"]["stage"], "paid")

    def test_business_amount_is_a_decimal_string_in_http_responses(self):
        response = self.client.post(self.path + "/business-links", json={
            "kind": "order", "namespace": "erp.orders", "external_id": "decimal-order",
            "amount": "100.10", "currency": "USD", "document_ref": "erp://orders/decimal-order",
            "occurred_at": "2026-10-01T10:00:00Z"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertIsInstance(response.json()["amount"], str)
        self.assertEqual(response.json()["amount"], "100.10")
        amount = self.client.get(self.path).json()["business_links"][0]["amount"]
        self.assertIsInstance(amount, str)
        self.assertEqual(amount, "100.10")

    def test_untrusted_fields_and_naive_dates_rejected(self):
        bad = self.client.post(self.path + "/proposals", json=dict(source_system="manual", event_id="e", summary="text",
            occurred_at="2026-10-01T10:00:00", proposed_stage="lead", manual_confirmation=True))
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(self.client.patch(self.path, json={"expected_version": 1, "stage": "paid"}).status_code, 422)

    def test_assisted_routes_deduplicate_but_never_repeat_primary(self):
        response = self.client.patch(self.path, json={"expected_version": 1, "assisted_routes": [1, 1, 3]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["customer"]["assisted_routes"], [1, 3])
        self.assertEqual(self.client.patch(self.path, json={"expected_version": 2, "route": 3}).status_code, 422)

    def test_route_assignment_requires_human_source_note(self):
        response = self.client.post(self.base + "/customers", json={"name": "Unattributed", "owner_user_id": 1, "route": 5})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.patch(self.path, json={"expected_version": 1, "source_note": ""}).status_code, 422)
        self.assertTrue(self.client.get(self.path).json()["customer"]["source_note"])
