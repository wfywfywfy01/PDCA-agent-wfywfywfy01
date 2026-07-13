from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, SQLModel, create_engine

from app.auth.models import User
from app.auth.scope import visible_dealer_names, visible_store_ids
from app.config import Settings
from app.models.dealer_store import DealerStore
from app.pages.router import _serve_module, view_path, walkin_assets
from app.pdca.post_router import post_questionnaire
from app.validation import require_iso_date, resolve_file_under


class InputValidationTests(unittest.TestCase):
    def test_require_iso_date_accepts_real_date(self):
        self.assertEqual(require_iso_date("2026-07-13"), "2026-07-13")

    def test_require_iso_date_rejects_traversal_and_impossible_date(self):
        for value in ("../../tmp", "2026-02-31", "2026-7-1"):
            with self.subTest(value=value), self.assertRaises(HTTPException):
                require_iso_date(value)

    def test_resolve_file_under_rejects_sibling_and_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "assets"
            sibling = Path(tmp) / "assets_backup"
            base.mkdir()
            sibling.mkdir()
            inside = base / "ok.html"
            outside = sibling / "secret.html"
            inside.write_text("ok", encoding="utf-8")
            outside.write_text("secret", encoding="utf-8")
            self.assertEqual(resolve_file_under(base, "ok.html"), inside.resolve())
            with self.assertRaises(HTTPException):
                resolve_file_under(base, "../assets_backup/secret.html")

    def test_view_path_rejects_file_outside_allowlist(self):
        outside = Path(__file__).resolve().parents[1] / "README.md"
        with self.assertRaises(HTTPException):
            asyncio.run(view_path(path=str(outside), date="2026-07-13", from_url="", user=User()))

    def test_walkin_html_rejects_encoded_traversal(self):
        with self.assertRaises(HTTPException):
            asyncio.run(
                walkin_assets(
                    rel_path="..%2F..%2F..%2F..%2Fpdca-workbench%2Ffrontend%2Flogin.html",
                    date="2026-07-13",
                    user=User(),
                )
            )

    def test_write_route_rejects_invalid_date_before_reading_form(self):
        with self.assertRaises(HTTPException):
            asyncio.run(post_questionnaire(request=None, date="../../outside", _user=User()))

    def test_module_page_falls_back_when_skinning_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            index = Path(tmp) / "index.html"
            index.write_text("<!doctype html><html><body>raw module</body></html>", encoding="utf-8")
            with patch("app.pages.router.bridge.skin_cockpit_html", side_effect=RuntimeError("boom")):
                response = _serve_module(index, "2026-07-13", "模块", "模块")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"raw module", response.body)

    def test_module_dir_falls_back_to_repository_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            expected = root / "data_platform" / "data_role_pdca_mvp" / "modules" / "walkin_cockpit"
            expected.mkdir(parents=True)
            (expected / "index.html").write_text("ok", encoding="utf-8")
            env = {
                "PDCA_REPO_ROOT": str(root),
                "PDCA_MVP_ROOT": str(root / "wrong-mvp-root"),
            }
            with patch.dict(os.environ, env, clear=False):
                settings = Settings()
            self.assertEqual(settings.walkin_cockpit_dir, expected.resolve())


class DataScopeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all([
            DealerStore(store_id="store-a", name="Dealer A", sales_owner="alice"),
            DealerStore(store_id="store-b", name="Dealer B", sales_owner="bob"),
        ])
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_dealer_scope_is_single_store(self):
        user = User(role="dealer", dealer_id="store-a")
        self.assertEqual(visible_store_ids(user, self.session), ["store-a"])
        self.assertEqual(visible_dealer_names(user, self.session), ["Dealer A"])

    def test_sales_scope_uses_store_owner(self):
        user = User(role="sales", username="alice")
        self.assertEqual(visible_store_ids(user, self.session), ["store-a"])

    def test_manager_scope_is_unrestricted(self):
        self.assertIsNone(visible_store_ids(User(role="manager"), self.session))


if __name__ == "__main__":
    unittest.main()
