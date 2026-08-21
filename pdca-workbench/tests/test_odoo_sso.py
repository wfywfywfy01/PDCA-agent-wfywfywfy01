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
