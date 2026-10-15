"""Offline checks for Omega's independent Docker deployment contract."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.deploy_omega_web import build_run_args, copy_environment, deploy, require_revision, run_docker, same_environment


class DeployOmegaWebTests(unittest.TestCase):
    def setUp(self):
        self.source = {
            "Config": {
                "Image": "registry.example/pdca:abcdef0",
                "Labels": {"com.vertu.pdca.revision": "abcdef0"},
                "Env": [
                    "PDCA_SECRET_KEY=test-only-secret-12345678901234567890",
                    "PDCA_DATABASE_URL=postgresql://test:test@db/test",
                    "PDCA_REQUIRE_VERTU=1", "PDCA_SCHEDULER_ENABLED=1",
                    "PDCA_OMEGA_ENABLED=1", "PDCA_OMEGA_REALTIME_PROVIDER=doubao",
                    "PDCA_DOUBAO_REALTIME_API_KEY=voice-test-only",
                    "PDCA_SUPERVISOR_PROVIDER=https://api.deepseek.com",
                    "PDCA_SUPERVISOR_MODEL=deepseek-flash",
                    "PDCA_SUPERVISOR_API_KEY=text-test-only",
                    "PDCA_AUTH_MODE=hybrid", "PDCA_VPS_LOGIN_URL=https://vps.example/login",
                    "VERTU_APP_KEY=expired-test-only",
                    "PDCA_AISALES_MCP_TOKEN=must-not-copy",
                ],
            },
            "NetworkSettings": {"Networks": {"dealer-knowledge": {}}},
            "Mounts": [
                {"Type": "bind", "Source": "/srv/pdca/data", "Destination": "/app/data", "RW": True},
                {"Type": "volume", "Name": "pdca-vertu-session", "Destination": "/root/.vertu", "RW": True},
                {"Type": "bind", "Source": "/srv/pdca/vps-service.json", "Destination": "/root/.vertu/vps-service.json", "RW": False},
            ],
        }

    def test_vps_key_can_be_expired_but_omega_boot_is_independent(self):
        env = copy_environment(self.source)
        self.assertEqual(env["VERTU_APP_KEY"], "expired-test-only")
        self.assertEqual(env["PDCA_REQUIRE_VERTU"], "0")
        self.assertEqual(env["PDCA_SCHEDULER_ENABLED"], "0")
        self.assertEqual(env["PDCA_OMEGA_ENABLED"], "1")
        self.assertEqual(env["PDCA_AUTH_MODE"], "hybrid")
        self.assertEqual(env["PDCA_AUTH_HOST_FALLBACK"], "0")
        self.assertEqual(env["PDCA_VPS_LOGIN_URL"], "https://vps.example/login")
        self.assertEqual(env["PDCA_HOME_REDIRECT"], "/app/omega")
        self.assertEqual(env["PDCA_KNOWLEDGE_HUB_ENABLED"], "0")
        self.assertNotIn("PDCA_AISALES_MCP_TOKEN", env)

    def test_run_args_share_data_without_logging_secrets(self):
        args = build_run_args(self.source, "C:/Temp/omega-secret.env", "pdca-omega-web")
        self.assertIn("127.0.0.1:8771:8767", args)
        self.assertIn("type=bind,src=/srv/pdca/data,dst=/app/data", args)
        self.assertIn("type=volume,src=pdca-vertu-session,dst=/root/.vertu", args)
        self.assertNotIn("expired-test-only", " ".join(args))
        self.assertEqual(args[-1], self.source["Config"]["Image"])

    def test_image_revision_must_match_source(self):
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            require_revision(self.source, {"Config": {"Labels": {"com.vertu.pdca.source_revision": "other"}}})
        require_revision(self.source, {"Config": {"Labels": {"com.vertu.pdca.source_revision": "abcdef0"}}})

    def test_exact_target_image_can_update_only_omega_web(self):
        revision = "b" * 40
        target = f"ghcr.io/wfywfywfy01/pdca-workbench:{revision}"
        image = {"Config": {"Labels": {"com.vertu.pdca.source_revision": revision}, "Env": []}}
        current = {"Config": {"Labels": {"com.vertu.pdca.omega_web": "1",
                                          "com.vertu.pdca.revision": revision},
                              "Env": [*(f"{k}={v}" for k, v in copy_environment(self.source).items())]},
                   "State": {"Health": {"Status": "healthy"}}}

        def fake_inspect(_host, name):
            return {"pdca-workbench": self.source, target: image, "pdca-omega-web": current}.get(name)

        with (patch("scripts.deploy_omega_web.inspect", side_effect=fake_inspect),
              patch("scripts.deploy_omega_web.run_docker") as docker):
            self.assertEqual(deploy("ssh://test", target_revision=revision), revision)
            docker.assert_not_called()
        args = build_run_args(self.source, "C:/Temp/omega-secret.env", image_name=target, revision=revision)
        self.assertEqual(args[-1], target)
        self.assertIn(f"com.vertu.pdca.revision={revision}", args)

        image["Config"]["Labels"]["com.vertu.pdca.source_revision"] = "a" * 40
        with patch("scripts.deploy_omega_web.inspect", side_effect=fake_inspect):
            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                deploy("ssh://test", target_revision=revision)
        with patch("scripts.deploy_omega_web.inspect") as inspect_image:
            with self.assertRaisesRegex(ValueError, "40-character"):
                deploy("ssh://test", target_revision="latest")
            inspect_image.assert_not_called()

    def test_exact_target_image_is_pulled_when_missing(self):
        revision = "b" * 40
        target = f"ghcr.io/wfywfywfy01/pdca-workbench:{revision}"
        image = {"Config": {"Labels": {"com.vertu.pdca.source_revision": revision}, "Env": []}}
        current = {"Config": {"Labels": {"com.vertu.pdca.omega_web": "1",
                                          "com.vertu.pdca.revision": revision},
                              "Env": [*(f"{k}={v}" for k, v in copy_environment(self.source).items())]},
                   "State": {"Health": {"Status": "healthy"}}}
        pulled = False

        def fake_inspect(_host, name):
            if name == target:
                return image if pulled else None
            return {"pdca-workbench": self.source, "pdca-omega-web": current}.get(name)

        def fake_docker(_host, *args, **kwargs):
            nonlocal pulled
            self.assertEqual(args, ("pull", target))
            self.assertEqual(kwargs, {"timeout": 900})
            pulled = True
            return ""

        with (patch("scripts.deploy_omega_web.inspect", side_effect=fake_inspect),
              patch("scripts.deploy_omega_web.run_docker", side_effect=fake_docker)):
            self.assertEqual(deploy("ssh://test", target_revision=revision), revision)
        self.assertTrue(pulled)

    def test_plaintext_docker_transport_is_refused_before_execution(self):
        with patch("scripts.deploy_omega_web.subprocess.run") as call:
            with self.assertRaisesRegex(ValueError, "SSH"):
                run_docker("tcp://10.100.0.176:2375", "ps")
            call.assert_not_called()

    def test_extra_main_service_secret_forces_redeployment(self):
        desired = copy_environment(self.source)
        image = {"Config": {"Env": ["PATH=/usr/local/bin"]}}
        current = {"Config": {"Env": ["PATH=/usr/local/bin", *(f"{k}={v}" for k, v in desired.items()),
                                     "PDCA_AISALES_MCP_TOKEN=must-not-copy"]}}
        self.assertFalse(same_environment(current, image, desired))
        current["Config"]["Env"].pop()
        self.assertTrue(same_environment(current, image, desired))

    def test_failed_rename_restarts_existing_web(self):
        old = {"Config": {"Labels": {"com.vertu.pdca.omega_web": "1"}},
               "State": {"Health": {"Status": "unhealthy"}, "Running": True}}
        image = {"Config": {"Labels": {"com.vertu.pdca.source_revision": "abcdef0"}, "Env": []}}
        commands = []

        def fake_inspect(_host, name):
            if name == "pdca-workbench":
                return self.source
            if name == self.source["Config"]["Image"]:
                return image
            return old if name == "pdca-omega-web" else None

        def fake_docker(_host, *args):
            commands.append(args[0])
            if args[0] == "stop":
                old["State"]["Running"] = False
            if args[0] == "rename":
                raise RuntimeError("test rename failure")
            if args[0] == "start":
                old["State"]["Running"] = True
            return ""

        with (patch("scripts.deploy_omega_web.inspect", side_effect=fake_inspect),
              patch("scripts.deploy_omega_web._active_calls", return_value=0),
              patch("scripts.deploy_omega_web.run_docker", side_effect=fake_docker)):
            with self.assertRaisesRegex(RuntimeError, "rename failure"):
                deploy("ssh://test")
        self.assertEqual(commands, ["stop", "rename", "start"])
        self.assertTrue(old["State"]["Running"])


if __name__ == "__main__":
    unittest.main()
