from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from app.auth.odoo_login_map import resolve_pdca_username, should_refuse_odoo_sso_create
from app.auth.odoo_sso import issue_odoo_ticket, parse_odoo_ticket
from app.auth.vps_identity import vps_username


class OdooSsoTicketTests(unittest.TestCase):
    def test_roundtrip(self):
        ticket = issue_odoo_ticket(
            login="fuwangyang",
            uid=2946,
            name="付汪阳",
            job_title="海外渠道中台",
            secret="sso-secret",
        )
        payload = parse_odoo_ticket(ticket, "sso-secret")
        self.assertEqual(payload["login"], "fuwangyang")
        self.assertEqual(payload["uid"], 2946)
        self.assertEqual(payload["job_title"], "海外渠道中台")

    def test_rejects_bad_signature_and_expiry(self):
        ticket = issue_odoo_ticket(login="a", uid=2, name="A", secret="sso-secret")
        self.assertIsNone(parse_odoo_ticket(ticket + "x", "sso-secret"))
        self.assertIsNone(parse_odoo_ticket(ticket, "other"))
        with patch("app.auth.odoo_sso.time.time", return_value=time.time() + 1000):
            self.assertIsNone(parse_odoo_ticket(ticket, "sso-secret"))

    def test_rejects_public_login(self):
        ticket = issue_odoo_ticket(login="public", uid=4, name="Public", secret="sso-secret")
        self.assertIsNone(parse_odoo_ticket(ticket, "sso-secret"))


class OdooDealerLoginMapTests(unittest.TestCase):
    def test_maps_spaced_dealer_login(self):
        self.assertEqual(resolve_pdca_username("Dar Al Sabaek"), "DarAlSabaek")

    def test_maps_restore_email(self):
        self.assertEqual(
            resolve_pdca_username("ac.aviapark.msk@re-store.ru"),
            "RSTR_MSK_АВИАПАРК",
        )

    def test_passthrough_unknown_and_internal(self):
        self.assertEqual(resolve_pdca_username("frank.fu@vertu.cn"), "frank.fu@vertu.cn")
        self.assertEqual(resolve_pdca_username("Yuemmai"), "Yuemmai")

    def test_maps_ankit_jain_to_sidd_senthil(self):
        self.assertEqual(resolve_pdca_username("jainchatters@gmail.com"), "SiddSenthil")

    def test_refuse_unmapped_dealers(self):
        self.assertTrue(should_refuse_odoo_sso_create("VMG Communication"))
        self.assertTrue(should_refuse_odoo_sso_create("Yuemmai"))
        self.assertFalse(should_refuse_odoo_sso_create("Dar Al Sabaek"))
        self.assertFalse(should_refuse_odoo_sso_create("frank.fu@vertu.cn"))

    def test_vps_username_uses_map(self):
        self.assertEqual(vps_username({"login": "Luxem", "name": "Luxem Store"}), "LuxemStore")


class OdooSessionIdentityTests(unittest.TestCase):
    def test_rejects_bad_session_id_shape(self):
        from app.auth.odoo_sso import identity_from_odoo_session

        self.assertIsNone(identity_from_odoo_session("not-a-session"))
        self.assertIsNone(identity_from_odoo_session(""))

    def test_reads_login_from_odoo_session_info(self):
        from app.auth.odoo_sso import identity_from_odoo_session

        class _Resp:
            def json(self):
                return {
                    "jsonrpc": "2.0",
                    "result": {"uid": 13365, "username": "frank.fu@vertu.cn", "name": "付汪阳"},
                }

        with patch("app.auth.odoo_sso.httpx.post", return_value=_Resp()):
            payload = identity_from_odoo_session("a" * 40, claimed_uid="13365")
        self.assertEqual(payload["login"], "frank.fu@vertu.cn")
        self.assertEqual(payload["uid"], 13365)

    def test_rejects_claimed_uid_mismatch(self):
        from app.auth.odoo_sso import identity_from_odoo_session

        class _Resp:
            def json(self):
                return {"result": {"uid": 13365, "username": "frank.fu@vertu.cn", "name": "付汪阳"}}

        with patch("app.auth.odoo_sso.httpx.post", return_value=_Resp()):
            self.assertIsNone(identity_from_odoo_session("b" * 40, claimed_uid="1"))
