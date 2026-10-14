"""The Caddy patch must never replace another application's site."""
from __future__ import annotations

import unittest

from scripts.apply_pdca_caddy_site import replace_site


class CaddySiteTests(unittest.TestCase):
    def test_replaces_only_pdca_site_and_routes_scope_to_main(self):
        current = "other.example {\n  respond ok\n}\n" + (
            "pdca-workbench-teams.vertu.cn {\n"
            "  @omega_web path /app /api/knowledge/scope\n"
            "  handle @omega_web { reverse_proxy 127.0.0.1:8771 }\n"
            "  handle { reverse_proxy 127.0.0.1:8768 }\n"
            "}\n"
        ) + "later.example {\n  respond ok\n}\n"
        candidate = (
            "# Replace only the pdca-workbench-teams.vertu.cn site block in /etc/caddy/Caddyfile.\n"
            "pdca-workbench-teams.vertu.cn {\n"
            "  @omega_web path /app\n"
            "  handle @omega_web { reverse_proxy 127.0.0.1:8771 }\n"
            "  handle { reverse_proxy 127.0.0.1:8768 }\n"
            "}\n"
        )
        result = replace_site(current, candidate)
        self.assertNotIn("/api/knowledge/scope", result)
        self.assertTrue(result.startswith("other.example {\n  respond ok\n}\n"))
        self.assertTrue(result.endswith("later.example {\n  respond ok\n}\n"))
        self.assertEqual(replace_site(result, candidate), result)

    def test_rejects_missing_or_duplicated_site(self):
        site = "pdca-workbench-teams.vertu.cn {\n respond ok\n}"
        with self.assertRaises(ValueError):
            replace_site("other.example {\n respond ok\n}", site)
        with self.assertRaises(ValueError):
            replace_site(site + "\n" + site, site)
        with self.assertRaises(ValueError):
            replace_site(site, site + "\nother.example {\n respond ok\n}")


if __name__ == "__main__":
    unittest.main()
