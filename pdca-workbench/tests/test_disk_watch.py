# -*- coding: utf-8 -*-
"""磁盘水位监测单测。"""
from __future__ import annotations

import unittest

from app.todos.disk_watch import disk_usage, levels_for


class DiskWatchTests(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(levels_for(0.05), [("critical", 6 * 3600)])
        self.assertEqual(levels_for(0.15), [("warning", 24 * 3600)])
        self.assertEqual(levels_for(0.60), [])
        self.assertEqual(levels_for(1.0), [])

    def test_usage_missing_mount_safe(self):
        total, free, pct = disk_usage("/nonexistent-path-xyz")
        self.assertEqual((total, free, pct), (0, 0, 1.0))


if __name__ == "__main__":
    unittest.main()
