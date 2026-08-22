"""logibot 调度：未启用跳过，缺文件告警。"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.scheduler.jobs import logibot_run_job


class LogibotJobTests(unittest.TestCase):
    def test_disabled_skips_subprocess(self):
        with patch.dict(os.environ, {"LOGIBOT_ENABLED": "0"}, clear=False):
            with patch("subprocess.run") as run:
                logibot_run_job()
                run.assert_not_called()

    def test_missing_bot_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"LOGIBOT_ENABLED": "1", "LOGIBOT_ROOT": tmp},
                clear=False,
            ):
                with patch("app.scheduler.jobs.notify") as alert:
                    logibot_run_job()
                    alert.assert_called()
