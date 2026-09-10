from __future__ import annotations

import tempfile
import unittest
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from app.auth.models import User
from app.auth.security import hash_password, verify_password
from app.database import get_session
from app.main import app
from app.models.daily_report import DailyReport
from app.models.dealer_store import DealerStore
from app.models.dealer_assignment import DealerAssignment
from app.models.logistics import LogisticsShipment
from app.models.pdca_task import PdcaTask
from app.models.customer_profile import CustomerProfile
from app.models.walkin_daily_report import WalkinDailyReport


class AuthAndWriteFlowTests(unittest.TestCase):
    """Exercise real auth and representative writes without external services."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        repo_root = Path(__file__).resolve().parents[2]
        database_path = Path(self.temp_dir.name) / "pdca-test.sqlite"
        self.engine = create_engine(
            f"sqlite:///{database_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        SQLModel.metadata.create_all(self.engine)

        self.settings = SimpleNamespace(
            auth_mode="local",
            trust_proxy_headers=False,
            secure_cookies=False,
            portal_mode="walkin",
            trusted_proxy_ips=set(),
            trust_proxy_role_header=False,
            allow_sqlite_fallback=False,

            access_token_expire_minutes=60,
            secret_key="test-secret-key-that-is-long-enough-for-jwt",
            algorithm="HS256",
            vps_login_url="https://example.invalid",
            max_reported_revenue_usd=5_000_000,
            revenue_review_threshold_usd=1_000_000,
            repo_root=repo_root,
            scripts_dir=(
                repo_root
                / "data_platform"
                / "data_role_pdca_mvp"
                / "scripts"
            ),
            mvp_root=Path(self.temp_dir.name) / "mvp",
            config_dir=Path(self.temp_dir.name) / "config",
        )
        self.patches = ExitStack()
        for target in (
            "app.main.get_settings",
            "app.auth.deps.get_settings",
            "app.auth.router.get_settings",
            "app.auth.security.get_settings",
            "app.legacy.bridge.get_settings",
        ):
            self.patches.enter_context(patch(target, return_value=self.settings))
        # Audit logs and legacy-form DB mirrors must use the same temporary DB.
        self.patches.enter_context(patch("app.audit.get_engine", return_value=self.engine))
        self.patches.enter_context(patch("app.models.writes.get_engine", return_value=self.engine))

        def override_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        self.client = TestClient(app, headers={"Origin": "http://testserver"})
        self._seed_data()

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.patches.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _seed_data(self):
        password = hash_password("Correct-password-123")
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        username="admin",
                        hashed_password=password,
                        role="admin",
                        display_name="Admin",
                        data_scope="all",
                        must_change_password=False,
                    ),
                    User(
                        username="forced-admin",
                        hashed_password=password,
                        role="admin",
                        display_name="Forced Admin",
                        must_change_password=True,
                    ),
                    User(
                        username="viewer",
                        hashed_password=password,
                        role="viewer",
                        display_name="Viewer",
                        must_change_password=False,
                    ),
                    User(
                        username="sales",
                        hashed_password=password,
                        role="sales",
                        display_name="Sales",
                        sales_name="Alice Sales",
                        owner_key="alice-owner",
                        data_scope="self",
                        must_change_password=False,
                    ),
                    User(
                        username="dealer",
                        hashed_password=password,
                        role="dealer",
                        display_name="Dealer",
                        dealer_id="store-a",
                        must_change_password=False,
                    ),
                    User(
                        username="sales-bob",
                        hashed_password=password,
                        role="sales",
                        display_name="Bob",
                        sales_name="Bob Sales",
                        owner_key="bob-owner",
                        data_scope="self",
                        must_change_password=False,
                    ),
                    DealerStore(
                        store_id="store-a",
                        name="Dealer A",
                        sales_owner="alice-owner",
                        team_key="overseas",
                        is_active=True,
                    ),
                    DealerStore(
                        store_id="store-b",
                        name="Dealer B",
                        sales_owner="bob-owner",
                        team_key="overseas",
                        is_active=True,
                    ),
                ]
            )
            session.commit()
            sales = session.exec(select(User).where(User.username == "sales")).one()
            bob = session.exec(select(User).where(User.username == "sales-bob")).one()
            session.add_all([
                DealerAssignment(user_id=sales.id, store_id="store-a"),
                DealerAssignment(user_id=bob.id, store_id="store-b"),
            ])
            session.commit()

    def _login(self, username: str, password: str = "Correct-password-123"):
        return self.client.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )

    def test_login_success_and_failure(self):
        failed = self._login("viewer", "wrong-password")
        self.assertEqual(failed.status_code, 401)
        self.assertNotIn("pdca_token", failed.cookies)

        success = self._login("viewer")
        self.assertEqual(success.status_code, 200)
        self.assertEqual(success.json()["user"]["username"], "viewer")
        self.assertFalse(success.json()["must_change_password"])
        self.assertTrue(success.cookies.get("pdca_token"))

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["role"], "viewer")

    def test_logout_revokes_current_access_token(self):
        success = self._login("viewer")
        token = success.json().get("access_token", "")
        self.assertTrue(token)

        logout = self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200)

        me = self.client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(me.status_code, 401)


    def test_public_vps_probe_does_not_expose_server_session(self):
        with patch("app.auth.vps_identity.fetch_vps_me_payload") as fetch_vps:
            response = self.client.get("/api/auth/vps-check")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["ok"])
        fetch_vps.assert_not_called()

    def test_forced_password_change_blocks_business_api_then_rotates_token(self):
        login = self._login("forced-admin")
        self.assertEqual(login.status_code, 200)
        self.assertTrue(login.json()["must_change_password"])

        blocked = self.client.get("/api/admin/diagnostics")
        self.assertEqual(blocked.status_code, 403)

        changed = self.client.post(
            "/api/auth/change-password",
            json={
                "old_password": "Correct-password-123",
                "new_password": "Changed-password-456",
            },
        )
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(changed.json()["ok"])

        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertFalse(me.json()["must_change_password"])
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.username == "forced-admin")).one()
            self.assertEqual(user.pwd_version, 1)
            self.assertFalse(user.must_change_password)
            self.assertTrue(verify_password("Changed-password-456", user.hashed_password))

    def test_representative_role_guards_return_401_and_403(self):
        anonymous = self.client.get("/api/admin/diagnostics")
        self.assertEqual(anonymous.status_code, 401)

        self.assertEqual(self._login("viewer").status_code, 200)
        forbidden = self.client.get("/api/admin/diagnostics")
        self.assertEqual(forbidden.status_code, 403)

        write_forbidden = self.client.post(
            "/api/walkin-metrics",
            json={
                "report_date": "2024-01-02",
                "dealer_id": "store-a",
                "dealer_name": "Dealer A",
            },
        )
        self.assertEqual(write_forbidden.status_code, 403)

    def test_questionnaire_write_saves_file_and_database_mirror(self):
        self.assertEqual(self._login("admin").status_code, 200)
        questionnaire_path = Path(self.temp_dir.name) / "2024-01-02_questionnaire.md"

        def save_questionnaire(date_text: str, form: dict[str, list[str]]):
            answer = (form.get("answer", [""])[0] or "").strip()
            questionnaire_path.write_text(
                f"# Questionnaire {date_text}\n\n{answer}\n",
                encoding="utf-8",
            )

        with (
            patch(
                "app.pdca.post_router.bridge.save_questionnaire",
                side_effect=save_questionnaire,
            ),
            patch(
                "app.pdca.post_router.bridge.questionnaire_path",
                return_value=questionnaire_path,
            ),
        ):
            response = self.client.post(
                "/questionnaire?date=2024-01-02",
                data={"answer": "Customer follow-up completed"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertTrue(questionnaire_path.is_file())
        self.assertIn("Customer follow-up completed", questionnaire_path.read_text(encoding="utf-8"))
        with Session(self.engine) as session:
            row = session.exec(
                select(DailyReport).where(
                    DailyReport.report_date == "2024-01-02",
                    DailyReport.report_type == "questionnaire",
                )
            ).one()
            self.assertIn("Customer follow-up completed", row.content)
            self.assertEqual(row.file_path, str(questionnaire_path))

    def test_logistics_write_saves_file_and_database_record(self):
        self.assertEqual(self._login("sales").status_code, 200)
        logistics_path = Path(self.temp_dir.name) / "logistics.csv"

        def append_logistics(date_text: str, form: dict[str, list[str]]):
            fields = [
                date_text,
                (form.get("tracking_number", [""])[0] or "").strip(),
                (form.get("salesperson", [""])[0] or "").strip(),
            ]
            logistics_path.write_text(",".join(fields) + "\n", encoding="utf-8")

        with patch(
            "app.pdca.post_router.bridge.append_logistics",
            side_effect=append_logistics,
        ):
            response = self.client.post(
                "/logistics?date=2024-01-02",
                data={
                    "tracking_number": "TRACK-TEST-001",
                    "carrier": "DHL",
                    "customer": "Customer A",
                    "ship_date": "2024-01-02",
                    "expected_status": "in_transit",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertIn("Alice Sales", logistics_path.read_text(encoding="utf-8"))
        with Session(self.engine) as session:
            row = session.exec(
                select(LogisticsShipment).where(
                    LogisticsShipment.tracking_number == "TRACK-TEST-001"
                )
            ).one()
            self.assertEqual(row.salesperson, "Alice Sales")
            self.assertEqual(row.customer, "Customer A")

    def test_walkin_write_persists_daily_metrics(self):
        self.assertEqual(self._login("dealer").status_code, 200)
        response = self.client.post(
            "/api/walkin-metrics",
            json={
                "report_date": "2024-01-02",
                "dealer_id": "store-a",
                "dealer_name": "Dealer A",
                "walkin_visits": 7,
                "cross_visits": 2,
                "online_visits": 3,
                "recruit_visits": 1,
                "existing_visits": 4,
                "touch_count": 9,
                "use_count": 5,
                "wechat_add_count": 6,
                "deal_count": 2,
                "deal_amount_yuan": 1280.5,
                "notes": "test-only submission",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        with Session(self.engine) as session:
            row = session.exec(
                select(WalkinDailyReport).where(
                    WalkinDailyReport.report_date == "2024-01-02",
                    WalkinDailyReport.dealer_id == "store-a",
                )
            ).one()
            self.assertEqual(row.submitted_by, "dealer")
            self.assertEqual(row.total_visits, 17)
            self.assertEqual(row.deal_count, 2)
            self.assertEqual(row.deal_amount_yuan, 1280.5)

    def test_walkin_write_uses_canonical_active_store_and_valid_date(self):
        self.assertEqual(self._login("dealer").status_code, 200)
        response = self.client.post(
            "/api/walkin-metrics",
            json={
                "report_date": "2024-01-03",
                "dealer_id": "store-a",
                "dealer_name": "Forged Dealer Name",
            },
        )
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as session:
            row = session.exec(
                select(WalkinDailyReport).where(
                    WalkinDailyReport.report_date == "2024-01-03",
                    WalkinDailyReport.dealer_id == "store-a",
                )
            ).one()
            self.assertEqual(row.dealer_name, "Dealer A")
            store = session.exec(select(DealerStore).where(DealerStore.store_id == "store-a")).one()
            store.is_active = False
            session.add(store)
            session.commit()

        inactive = self.client.post(
            "/api/walkin-metrics",
            json={"report_date": "2024-01-04", "dealer_id": "store-a", "dealer_name": "Dealer A"},
        )
        self.assertEqual(inactive.status_code, 422)
        invalid_date = self.client.post(
            "/api/walkin-metrics",
            json={"report_date": "2024-99-99", "dealer_id": "store-a", "dealer_name": "Dealer A"},
        )
        self.assertEqual(invalid_date.status_code, 422)

    def test_admin_can_deactivate_dealer_after_store_is_disabled(self):
        with Session(self.engine) as session:
            store = session.exec(select(DealerStore).where(DealerStore.store_id == "store-a")).one()
            store.is_active = False
            session.add(store)
            session.commit()
        self.assertEqual(self._login("admin").status_code, 200)
        response = self.client.patch("/api/admin/users/dealer", json={"is_active": False})
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as session:
            dealer = session.exec(select(User).where(User.username == "dealer")).one()
            self.assertFalse(dealer.is_active)

    def test_admin_can_preview_a_users_effective_permissions(self):
        self.assertEqual(self._login("admin").status_code, 200)
        response = self.client.get("/api/admin/users/sales/effective-permissions")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "username": "sales",
            "role": "sales",
            "is_active": True,
            "scope": {
                "mode": "self",
                "team_key": "",
                "store_ids": ["store-a"],
                "dealer_names": ["Dealer A"],
                "owner_keys": ["alice-owner", "Alice Sales"],
            },
            "modules": {
                "workbench": "scoped",
                "customers": "scoped",
                "logistics": "scoped",
                "meetings": "scoped",
                "tasks": "scoped",
                "walkin": "scoped",
                "admin": "none",
            },
            "warnings": [],
        })
        self.assertEqual(self.client.patch("/api/admin/users/sales", json={"sales_name": ""}).status_code, 200)
        incomplete = self.client.get("/api/admin/users/sales/effective-permissions").json()
        self.assertIn("销售账号未配置物流来源名称，物流仅可查看", incomplete["warnings"])
        self.assertEqual(incomplete["modules"]["logistics"], "read-only")

        dealer = self.client.get("/api/admin/users/dealer/effective-permissions")
        self.assertEqual(dealer.status_code, 200)
        self.assertEqual(dealer.json()["modules"], {
            "workbench": "none",
            "customers": "none",
            "logistics": "none",
            "meetings": "none",
            "tasks": "none",
            "walkin": "scoped",
            "admin": "none",
        })
        self.assertEqual(self.client.patch("/api/admin/users/dealer", json={"is_active": False}).status_code, 200)
        inactive = self.client.get("/api/admin/users/dealer/effective-permissions")
        self.assertEqual(set(inactive.json()["modules"].values()), {"none"})

        self.client.post("/api/auth/logout")
        self.assertEqual(self._login("sales").status_code, 200)
        denied = self.client.get("/api/admin/users/sales/effective-permissions")
        self.assertEqual(denied.status_code, 403)

    def test_admin_cannot_disable_or_demote_the_current_account(self):
        self.assertEqual(self._login("admin").status_code, 200)
        disabled = self.client.patch("/api/admin/users/admin", json={"is_active": False})
        demoted = self.client.patch("/api/admin/users/admin", json={"role": "viewer"})
        scoped_down = self.client.patch("/api/admin/users/admin", json={"data_scope": "none"})
        self.assertEqual(disabled.status_code, 400)
        self.assertEqual(demoted.status_code, 400)
        self.assertEqual(scoped_down.status_code, 400)

    def test_sales_accounts_cannot_read_or_write_each_others_stores(self):
        with Session(self.engine) as session:
            session.add(WalkinDailyReport(
                report_date="2024-01-02", dealer_id="store-b", dealer_name="Dealer B",
                walkin_visits=9, submitted_by="sales-bob",
            ))
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        stores = self.client.get("/api/my-stores")
        self.assertEqual([row["store_id"] for row in stores.json()], ["store-a"])
        denied_read = self.client.get("/api/walkin-metrics?month=2024-01&dealer_id=store-b")
        self.assertEqual(denied_read.status_code, 403)
        denied_write = self.client.post("/api/walkin-metrics", json={
            "report_date": "2024-01-02", "dealer_id": "store-b", "dealer_name": "Dealer B",
        })
        self.assertEqual(denied_write.status_code, 403)

    def test_sales_cannot_overwrite_same_title_task_owned_by_another_salesperson(self):
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date="2024-01-02", title="Call customer",
                owner="Bob Sales", status="done",
            ))
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        response = self.client.post("/api/task-center/tasks", json={
            "task_date": "2024-01-02", "title": "Call customer",
        })
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as session:
            rows = session.exec(select(PdcaTask).where(
                PdcaTask.task_date == "2024-01-02",
                PdcaTask.title == "Call customer",
            )).all()
        self.assertEqual([(row.owner, row.status) for row in rows], [
            ("Bob Sales", "done"), ("Alice Sales", "pending"),
        ])

    def test_sales_cannot_patch_unassigned_task_or_clear_owner(self):
        with Session(self.engine) as session:
            unassigned = PdcaTask(task_date="2024-01-02", title="Unassigned", owner="")
            own = PdcaTask(task_date="2024-01-02", title="Own", owner="Alice Sales")
            session.add_all([unassigned, own])
            session.commit()
            session.refresh(unassigned)
            session.refresh(own)
            unassigned_id, own_id = unassigned.id, own.id
        self.assertEqual(self._login("sales").status_code, 200)
        self.assertEqual(
            self.client.patch(f"/api/task-center/tasks/{unassigned_id}", json={"status": "done"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.patch(f"/api/task-center/tasks/{own_id}", json={"owner": ""}).status_code,
            403,
        )

    def test_sales_cannot_overwrite_another_salespersons_tracking_number(self):
        with Session(self.engine) as session:
            session.add(LogisticsShipment(
                record_date="2024-01-01", tracking_number="TRACK-SHARED",
                salesperson="Bob Sales", customer="Bob customer",
            ))
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        with patch("app.legacy.bridge.append_logistics"):
            response = self.client.post("/api/logistics/shipments", json={
                "tracking_number": "TRACK-SHARED", "customer": "Alice customer",
                "ship_date": "2024-01-02",
            })
        self.assertEqual(response.status_code, 403)
        with patch("app.legacy.bridge.append_logistics"):
            legacy = self.client.post("/logistics?date=2024-01-02", data={
                "tracking_number": "TRACK-SHARED", "customer": "Alice customer",
                "ship_date": "2024-01-02",
            })
        self.assertEqual(legacy.status_code, 403)
        with Session(self.engine) as session:
            row = session.exec(select(LogisticsShipment).where(
                LogisticsShipment.tracking_number == "TRACK-SHARED"
            )).one()
        self.assertEqual((row.salesperson, row.customer), ("Bob Sales", "Bob customer"))

    def test_team_manager_cannot_overwrite_shipment_outside_team(self):
        with Session(self.engine) as session:
            session.add_all([
                User(
                    username="manager", hashed_password=hash_password("Correct-password-123"),
                    role="manager", display_name="Manager", data_scope="team",
                    team_key="overseas", must_change_password=False,
                ),
                LogisticsShipment(
                    record_date="2024-01-01", tracking_number="TRACK-OTHER-TEAM",
                    salesperson="Charlie Sales", customer="Charlie customer",
                ),
            ])
            session.commit()
        self.assertEqual(self._login("manager").status_code, 200)
        response = self.client.post("/api/logistics/shipments", json={
            "tracking_number": "TRACK-OTHER-TEAM", "salesperson": "Charlie Sales",
            "customer": "Manager overwrite", "ship_date": "2024-01-02",
        })
        self.assertEqual(response.status_code, 403)
        with Session(self.engine) as session:
            row = session.exec(select(LogisticsShipment).where(
                LogisticsShipment.tracking_number == "TRACK-OTHER-TEAM"
            )).one()
        self.assertEqual(row.customer, "Charlie customer")

    def test_sales_cannot_claim_csv_only_tracking_number(self):
        csv_dir = self.settings.mvp_root / "inputs" / "logistics"
        csv_dir.mkdir(parents=True)
        (csv_dir / "2024-01-01_tracking.csv").write_text(
            "tracking_number,salesperson,customer\nTRACK-CSV-ONLY,Bob Sales,Bob customer\n",
            encoding="utf-8",
        )
        self.assertEqual(self._login("sales").status_code, 200)
        with patch("app.logistics.service.get_settings", return_value=self.settings):
            response = self.client.post("/api/logistics/shipments", json={
                "tracking_number": "TRACK-CSV-ONLY", "customer": "Alice takeover",
                "ship_date": "2024-01-02",
            })
        self.assertEqual(response.status_code, 403)
        with Session(self.engine) as session:
            self.assertIsNone(session.exec(select(LogisticsShipment).where(
                LogisticsShipment.tracking_number == "TRACK-CSV-ONLY"
            )).first())

    def test_sales_alias_can_update_own_canonicalized_shipment(self):
        self.settings.config_dir.mkdir(parents=True)
        (self.settings.config_dir / "sales_aliases.csv").write_text(
            "raw_sales,canonical_sales\nRAWLINA,Lina\n", encoding="utf-8",
        )
        with Session(self.engine) as session:
            sales_user = session.exec(select(User).where(User.username == "sales")).one()
            sales_user.sales_name = "RAWLINA"
            session.add(sales_user)
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        with patch("app.logistics.service.get_settings", return_value=self.settings):
            first = self.client.post("/api/logistics/shipments", json={
                "tracking_number": "TRACK-LINA", "customer": "First",
                "ship_date": "2024-01-02",
            })
            second = self.client.post("/api/logistics/shipments", json={
                "tracking_number": "TRACK-LINA", "customer": "Updated",
                "ship_date": "2024-01-02",
            })
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        with Session(self.engine) as session:
            row = session.exec(select(LogisticsShipment).where(
                LogisticsShipment.tracking_number == "TRACK-LINA"
            )).one()
        self.assertEqual((row.salesperson, row.customer), ("Lina", "Updated"))

    def test_sales_cannot_update_same_named_customer_in_another_team(self):
        with Session(self.engine) as session:
            session.add_all([
                CustomerProfile(team="yang-jingjing", dealer_name="Same customer", owner="Alice Sales"),
                CustomerProfile(team="bob-team", dealer_name="Same customer", owner="Bob Sales", next_action="Bob original"),
            ])
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        with patch("app.database.get_engine", return_value=self.engine):
            response = self.client.put("/api/signalseller/customers", json={
                "team": "bob-team", "dealer_name": "Same customer",
                "next_action": "Alice overwrite",
            })
        self.assertEqual(response.status_code, 403)
        with Session(self.engine) as session:
            row = session.exec(select(CustomerProfile).where(CustomerProfile.team == "bob-team")).one()
        self.assertEqual(row.next_action, "Bob original")

    def test_sales_updates_only_owned_customer_when_same_team_has_duplicate_name(self):
        with Session(self.engine) as session:
            session.add_all([
                CustomerProfile(
                    team="yang-jingjing", dealer_name="Shared name",
                    owner="Bob Sales", next_action="Bob original",
                ),
                CustomerProfile(
                    team="yang-jingjing", dealer_name="Shared name",
                    owner="Alice Sales", next_action="Alice original",
                ),
            ])
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        with patch("app.database.get_engine", return_value=self.engine):
            response = self.client.put("/api/signalseller/customers", json={
                "team": "yang-jingjing", "dealer_name": "Shared name",
                "next_action": "Alice updated",
            })
        self.assertEqual(response.status_code, 200)
        with Session(self.engine) as session:
            rows = session.exec(select(CustomerProfile).where(
                CustomerProfile.dealer_name == "Shared name"
            )).all()
        self.assertEqual(
            {row.owner: row.next_action for row in rows},
            {"Bob Sales": "Bob original", "Alice Sales": "Alice updated"},
        )

    def test_scoped_sellin_rejects_unsupported_non_month_period_without_guessing(self):
        self.assertEqual(self._login("sales").status_code, 200)
        response = self.client.get("/api/dashboard/sell-in?date=2024-01-02&period=day")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["amount"])
        self.assertEqual(payload["state"], "missing")
        self.assertIn("仅支持月度", payload["note"])

    def test_task_api_rejects_unknown_status_and_priority(self):
        with Session(self.engine) as session:
            row = PdcaTask(task_date="2024-01-02", title="Own", owner="Alice Sales")
            session.add(row)
            session.commit()
            session.refresh(row)
            task_id = row.id
        self.assertEqual(self._login("sales").status_code, 200)
        self.assertEqual(
            self.client.patch(f"/api/task-center/tasks/{task_id}", json={"status": "anything"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.post("/api/task-center/tasks", json={
                "task_date": "2024-01-02", "title": "Invalid priority", "priority": "anything",
            }).status_code,
            422,
        )

    def test_retrying_task_create_does_not_reset_completed_task(self):
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date="2024-01-02", title="Already complete",
                owner="Alice Sales", status="done", priority="high",
            ))
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        response = self.client.post("/api/task-center/tasks", json={
            "task_date": "2024-01-02", "title": "Already complete",
            "priority": "normal",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["idempotent"])
        with Session(self.engine) as session:
            row = session.exec(select(PdcaTask).where(
                PdcaTask.title == "Already complete"
            )).one()
        self.assertEqual((row.status, row.priority), ("done", "high"))

    def test_legacy_task_create_does_not_reset_completed_task(self):
        with Session(self.engine) as session:
            session.add(PdcaTask(
                task_date="2024-01-02", title="Legacy complete",
                owner="Alice Sales", status="done", priority="high",
            ))
            session.commit()
        self.assertEqual(self._login("admin").status_code, 200)
        with patch("app.legacy.bridge.append_todo"):
            response = self.client.post("/todos?date=2024-01-02", data={
                "title": "Legacy complete", "owner": "Alice Sales",
                "status": "pending", "priority": "normal",
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            row = session.exec(select(PdcaTask).where(
                PdcaTask.title == "Legacy complete"
            )).one()
        self.assertEqual((row.status, row.priority), ("done", "high"))

    def test_today_workbench_reports_only_current_scope_and_truth_state(self):
        with Session(self.engine) as session:
            sales = session.exec(select(User).where(User.username == "sales")).one()
            session.add(DealerStore(
                store_id="me005", name="Dar Al Sabaek", sales_owner="alice-owner",
                team_key="overseas", is_active=True,
            ))
            session.add(DealerAssignment(user_id=sales.id, store_id="me005"))
            session.add_all([
                WalkinDailyReport(report_date="2024-01-01", dealer_id="me005", dealer_name="Dar Al Sabaek", walkin_visits=0),
                WalkinDailyReport(report_date="2024-01-02", dealer_id="me005", dealer_name="Dar Al Sabaek", walkin_visits=99),
                WalkinDailyReport(report_date="2024-01-01", dealer_id="store-b", dealer_name="Dealer B", walkin_visits=12),
            ])
            session.commit()
        self.assertEqual(self._login("sales").status_code, 200)
        response = self.client.get("/api/workbench/today?date=2024-01-02")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["scope"]["store_ids"], ["store-a", "me005"])
        self.assertEqual(payload["closure"]["report_date"], "2024-01-01")
        self.assertEqual(payload["facts"]["walkin_reported"]["value"], 1)
        self.assertEqual(payload["facts"]["walkin_visits"]["value"], 0)
        self.assertTrue(payload["closure"]["complete"])

    def test_admin_today_uses_the_canonical_six_store_roster(self):
        self.assertEqual(self._login("admin").status_code, 200)
        with patch("app.logistics.service.load_shipments", return_value=([], "available")):
            response = self.client.get("/api/workbench/today?date=2024-01-02")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["closure"]["report_date"], "2024-01-01")
        self.assertEqual(payload["closure"]["expected"], 6)
        self.assertEqual(payload["facts"]["walkin_missing"]["value"], 6)

    def test_inactive_store_history_is_kept_but_excluded_from_current_reporting(self):
        with Session(self.engine) as session:
            session.add(DealerStore(
                store_id="inactive-store",
                name="Inactive Store",
                team_key="overseas",
                is_active=False,
            ))
            session.add(WalkinDailyReport(
                report_date="2024-01-05",
                dealer_id="inactive-store",
                dealer_name="Inactive Store",
                walkin_visits=99,
                deal_amount_yuan=9999,
            ))
            session.commit()

        self.assertEqual(self._login("admin").status_code, 200)
        listed = self.client.get("/api/walkin-metrics?month=2024-01")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["count"], 0)
        summary = self.client.get("/api/walkin-metrics/summary?month=2024-01")
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["record_count"], 0)
        today = self.client.get("/api/workbench/today?date=2024-01-05")
        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["facts"]["walkin_visits"]["value"], 0)

    def test_walkin_get_rebuilds_payload_from_database_without_monthly_json(self):
        with Session(self.engine) as session:
            session.add(
                WalkinDailyReport(
                    report_date="2024-01-02",
                    dealer_id="store-a",
                    dealer_name="Dealer A",
                    walkin_visits=7,
                    cross_visits=2,
                    online_visits=3,
                    recruit_visits=1,
                    existing_visits=4,
                    touch_count=9,
                    use_count=5,
                    wechat_add_count=6,
                    deal_count=2,
                    deal_amount_yuan=1280.5,
                    submitted_by="dealer",
                )
            )
            session.commit()

        # Exercise the real legacy no-bundle response, but point every source
        # path at an empty temporary tree so the test cannot read repo data or
        # generate a walkin-YYYY-MM.json file.
        from app.legacy import bridge

        legacy = bridge.wb()
        builder = legacy.build_walkin_api_payload
        self.assertIsNotNone(builder)
        workbench_data = sys.modules[builder.__module__]
        empty_data = Path(self.temp_dir.name) / "walkin-data"
        empty_raw = Path(self.temp_dir.name) / "data-raw"
        empty_data.mkdir()
        empty_raw.mkdir()
        missing_bundle = empty_data / "walkin-2024-01.json"

        with (
            patch.object(workbench_data, "WALKIN_DATA", empty_data),
            patch.object(workbench_data, "BUILD_WALKIN", Path(self.temp_dir.name) / "missing-builder.py"),
            patch.object(workbench_data, "DATA_RAW", empty_raw),
            patch.object(workbench_data, "DATA_SOURCES", Path(self.temp_dir.name) / "missing-sources.json"),
            patch.object(workbench_data, "VN_METRICS", empty_data / "missing-vietnam.json"),
            patch.object(workbench_data, "VN_COLLECT", empty_data / "missing-collect.json"),
        ):
            self.assertFalse(missing_bundle.exists())
            self.assertEqual(self._login("dealer").status_code, 200)
            response = self.client.get(
                "/api/walkin?month=2024-01&date=2024-01-31"
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(missing_bundle.exists())
        payload = response.json()
        self.assertEqual(payload["meta"]["storeCount"], 1)
        self.assertNotIn("unavailable", payload["meta"]["dataSources"])
        self.assertIn("dealer_store_db", payload["meta"]["dataSources"])
        self.assertIn("five_kit_db", payload["meta"]["dataSources"])

        self.assertEqual(len(payload["stores"]), 1)
        store = payload["stores"][0]
        self.assertEqual(store["id"], "store-a")
        self.assertEqual(
            store["fiveKit"],
            {
                "walkin": 7,
                "cross": 2,
                "online": 3,
                "recruit": 1,
                "existing": 4,
                "total": 17,
            },
        )
        self.assertEqual(store["walkinPeople"], 17)
        self.assertAlmostEqual(store["avgAddRate"], 6 / 17, places=4)
        self.assertAlmostEqual(store["avgTouchRate"], 9 / 17, places=4)
        self.assertAlmostEqual(store["avgUseRate"], 5 / 17, places=4)


if __name__ == "__main__":
    unittest.main()
