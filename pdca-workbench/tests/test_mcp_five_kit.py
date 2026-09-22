# -*- coding: utf-8 -*-
"""门店五件套 MCP 权限隔离单测。"""
from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import User
from app.auth.scope import DataScope
from app.models.dealer_store import DealerStore
from app.models.walkin_daily_report import WalkinDailyReport
from app.mcp_five_kit import _allowed_store_ids, _require_scope, _Identity


def _user(role: str, username: str = "u1") -> User:
    return User(username=username, role=role)


def _identity(role: str) -> _Identity:
    return _Identity(kind="user", role=role, username="u1", user=_user(role))


class ScopeUnitTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "five-kit-scope.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_require_scope_rejects_cross_store(self):
        with self.assertRaises(PermissionError):
            _require_scope("sea02a", {"sea01a"})
        _require_scope("sea01a", {"sea01a"})      # 本店放行
        _require_scope("sea02a", None)             # 管理员不限

    def test_allowed_store_ids_follows_data_scope(self):
        with Session(self.engine) as session:
            bound = DataScope(mode="bound", store_ids=("sea01a",), dealer_names=("D1",), owner_keys=("o1",))
            with patch("app.mcp_five_kit.resolve_data_scope", return_value=bound):
                self.assertEqual(_allowed_store_ids(_identity("dealer"), session), {"sea01a"})
            unrestricted = DataScope(mode="all", store_ids=(), dealer_names=(), owner_keys=())
            with patch("app.mcp_five_kit.resolve_data_scope", return_value=unrestricted):
                self.assertIsNone(_allowed_store_ids(_identity("admin"), session))
            empty = DataScope(mode="none", store_ids=(), dealer_names=(), owner_keys=())
            with patch("app.mcp_five_kit.resolve_data_scope", return_value=empty):
                self.assertEqual(_allowed_store_ids(_identity("dealer"), session), set())

    def test_service_key_identity_scoping(self):
        """服务密钥：admin/manager 全量；sales/dealer 按 owner_key 绑定门店；未绑定 fail-closed。"""
        with Session(self.engine) as session:
            session.add(DealerStore(store_id="sea01a", name="新加坡店", sales_owner="April",
                                    is_active=True))
            session.commit()
            self.assertIsNone(
                _allowed_store_ids(_Identity(kind="service", role="admin"), session)
            )
            self.assertEqual(
                _allowed_store_ids(
                    _Identity(kind="service", role="sales", owner_key="April"), session
                ),
                {"sea01a"},
            )
            self.assertEqual(
                _allowed_store_ids(_Identity(kind="service", role="dealer"), session),
                set(),
            )


class ToolScopeTests(unittest.TestCase):
    """工具层：权限过滤落到 SQL，越权显式拒绝。"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "five-kit-tools.sqlite"
        self.engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            for store_id, name, owner in (
                ("sea01a", "新加坡店", "April"),
                ("me01a", "迪拜店", "Bob"),
            ):
                session.add(DealerStore(store_id=store_id, name=name, region="东南亚",
                                        sales_owner=owner, is_active=True))
            for store_id, name in (("sea01a", "新加坡店"), ("me01a", "迪拜店")):
                session.add(WalkinDailyReport(report_date="2026-09-16", dealer_id=store_id,
                                              dealer_name=name, walkin_visits=3, deal_count=1))
            session.commit()
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    @contextmanager
    def _auth(self, role: str, store_ids: tuple[str, ...]):
        mode = "all" if role == "admin" else "bound"
        scope = DataScope(mode=mode, store_ids=store_ids, dealer_names=(), owner_keys=())
        with patch("app.mcp_five_kit.resolve_data_scope", return_value=scope):
            yield _identity(role), self.session

    def test_dealer_only_sees_own_store(self):
        from app.mcp_five_kit import five_kit_reports
        with patch("app.mcp_five_kit._authorized_user", lambda: self._auth("dealer", ("sea01a",))):
            result = five_kit_reports("2026-09-16")
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["dealer_id"], "sea01a")

    def test_admin_sees_all_stores(self):
        from app.mcp_five_kit import five_kit_reports
        with patch("app.mcp_five_kit._authorized_user", lambda: self._auth("admin", ())):
            result = five_kit_reports("2026-09-16")
        self.assertEqual({i["dealer_id"] for i in result["items"]}, {"sea01a", "me01a"})

    def test_dealer_cross_store_query_denied(self):
        from app.mcp_five_kit import five_kit_reports
        with patch("app.mcp_five_kit._authorized_user", lambda: self._auth("dealer", ("sea01a",))):
            with self.assertRaises(PermissionError):
                five_kit_reports("2026-09-16", dealer_id="me01a")

    def test_missing_report_requires_admin(self):
        from app.mcp_five_kit import five_kit_missing
        with patch("app.mcp_five_kit._authorized_user", lambda: self._auth("dealer", ("sea01a",))):
            with self.assertRaises(PermissionError):
                five_kit_missing("2026-09-16")
        with patch("app.mcp_five_kit._authorized_user", lambda: self._auth("admin", ())):
            result = five_kit_missing("2026-09-16")
        self.assertEqual(result["reported"], 2)
        self.assertEqual(result["missing_count"], 0)


if __name__ == "__main__":
    unittest.main()
