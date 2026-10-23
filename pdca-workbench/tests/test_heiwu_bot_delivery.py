import json
import os
import unittest
from unittest.mock import patch

from app import heiwu


class HeiwuBotDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PDCA_HEIWU_BOT_APP_ID": "vbot_heiwu",
            "PDCA_HEIWU_BOT_APP_SECRET": "",
            "PDCA_DUZHAN_BOT_APP_ID": "vbot_other",
            "PDCA_DUZHAN_BOT_APP_SECRET": "other-secret",
            "PDCA_HEIWU_NOTIFY_AGENT_SLUG": "heiwu-task-notice",
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_explicit_notification_identity_uses_authenticated_cli(self):
        self.assertEqual(heiwu.bot_credentials_effective(), ("vbot_heiwu", ""))
        self.assertTrue(heiwu.configured())
        with patch("app.todos.service._send_with_body_file", return_value=(0, json.dumps({"ok": True}), "")) as send, \
             patch("app.vps_im_push.push_as_bot") as push:
            self.assertTrue(heiwu._reply("学习任务提醒", "source-message", "task-round-key"))
        push.assert_not_called()
        args, body = send.call_args.args
        self.assertEqual(body, "学习任务提醒")
        for flag, value in {"--bot-key": "heiwu-task-notice", "--agent-slug": "heiwu-task-notice", "--channel-id": heiwu.channel_id(),
                            "--parent-message-id": "source-message", "--event-id": "task-round-key",
                            "--idempotency-key": "task-round-key", "--target": "im"}.items():
            self.assertEqual(args[args.index(flag) + 1], value)

    def test_app_id_alone_does_not_select_a_notification_identity(self):
        with patch.dict(os.environ, {"PDCA_HEIWU_NOTIFY_AGENT_SLUG": ""}), \
             patch("app.todos.service._send_with_body_file") as send:
            self.assertFalse(heiwu.configured())
        send.assert_not_called()

    def test_cli_failure_never_switches_identity(self):
        with patch("app.todos.service._send_with_body_file", return_value=(1, "", "permission denied")) as send, \
             patch("app.vps_im_push.push_as_bot") as push:
            self.assertFalse(heiwu._reply("学习任务提醒", "", "task-round-key"))
        self.assertEqual(send.call_count, 1)
        push.assert_not_called()

    def test_cli_ok_false_is_failure(self):
        with patch("app.todos.service._send_with_body_file", return_value=(0, '{"ok":false}', "")), \
             patch("app.vps_im_push.push_as_bot", return_value=False):
            self.assertFalse(heiwu._reply("学习任务提醒", "", "task-round-key"))

    def test_dedicated_secret_keeps_existing_push(self):
        with patch.dict(os.environ, {"PDCA_HEIWU_BOT_APP_SECRET": "dedicated-secret"}), \
             patch("app.vps_im_push.push_as_bot", return_value=True) as push, \
             patch("app.todos.service._send_with_body_file") as send:
            self.assertTrue(heiwu._reply("学习任务提醒", "source-message", "task-round-key"))
        send.assert_not_called()
        self.assertEqual(push.call_args.kwargs["app_id"], "vbot_heiwu")


if __name__ == "__main__":
    unittest.main()
