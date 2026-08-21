from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from app.auth.odoo_sso import issue_odoo_ticket, parse_odoo_ticket


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
