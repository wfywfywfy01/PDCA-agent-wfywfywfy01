import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class HeiwuTaskScheduleTests(unittest.TestCase):
    def test_exclusion_configuration_is_explicit_and_empty_by_default(self):
        from app.config import Settings

        with patch.dict(os.environ, {
            "PDCA_HEIWU_TASK_EXCLUDED_NAMES": " 成员甲,成员乙 ,,",
            "PDCA_HEIWU_TASK_EXCLUDED_USER_IDS": "101, 102,invalid,0,-1",
        }):
            settings = Settings()
        self.assertEqual(settings.heiwu_task_excluded_names, ("成员甲", "成员乙"))
        self.assertEqual(settings.heiwu_task_excluded_user_ids, (101, 102))
        with patch.dict(os.environ, {
            "PDCA_HEIWU_TASK_EXCLUDED_NAMES": "",
            "PDCA_HEIWU_TASK_EXCLUDED_USER_IDS": "",
        }):
            settings = Settings()
        self.assertEqual(settings.heiwu_task_excluded_names, ())
        self.assertEqual(settings.heiwu_task_excluded_user_ids, ())

    def test_defaults_are_separate_from_congratulations(self):
        from app.config import Settings

        with patch.dict(os.environ, {}):
            for key in ("PDCA_HEIWU_TASKS_ENABLED", "PDCA_HEIWU_TASK_PUBLISHER_USER_IDS",
                        "PDCA_HEIWU_TASK_MORNING_TIME", "PDCA_HEIWU_TASK_EVENING_TIME"):
                os.environ.pop(key, None)
            settings = Settings()
        self.assertFalse(settings.heiwu_tasks_enabled)
        self.assertEqual(settings.heiwu_task_publisher_user_ids, ())
        self.assertEqual(settings.heiwu_task_morning_time, "10:00")
        self.assertEqual(settings.heiwu_task_evening_time, "20:00")

    def test_task_schedule_registers_only_when_explicitly_enabled(self):
        from app.scheduler import jobs

        class RecordingScheduler:
            def __init__(self, **_kwargs):
                self.jobs = []

            def add_job(self, func, *args, **kwargs):
                self.jobs.append((func, args, kwargs))

            def start(self):
                pass

        settings = SimpleNamespace(
            scheduler_enabled=True, sync_cron="0 6 * * *", daily_report_enabled=False,
            todo_remind_enabled=False, todo_remind_times=[], todo_group_notice_enabled=False,
            todo_group_channel_id="", todo_scoring_enabled=False, todo_ledger_sync_enabled=False,
            todo_brief_enabled=False, todo_okr_link_enabled=False, heiwu_enabled=False,
            heiwu_tasks_enabled=True, heiwu_task_publisher_user_ids=(123,),
            heiwu_task_morning_time="09:35", heiwu_task_evening_time="20:05",
        )
        with patch.object(jobs, "_scheduler", None), patch.object(jobs, "get_settings", return_value=settings), \
             patch.object(jobs, "BackgroundScheduler", RecordingScheduler):
            scheduler = jobs.start_scheduler()
        task_jobs = {item[2]["id"]: item for item in scheduler.jobs if item[2]["id"].startswith("heiwu_tasks_")}
        self.assertEqual(set(task_jobs), {"heiwu_tasks_morning", "heiwu_tasks_evening"})
        self.assertEqual(task_jobs["heiwu_tasks_morning"][2]["hour"], 9)
        self.assertEqual(task_jobs["heiwu_tasks_morning"][2]["minute"], 35)
        self.assertEqual(task_jobs["heiwu_tasks_evening"][2]["minute"], 5)
        self.assertEqual(str(task_jobs["heiwu_tasks_evening"][2]["timezone"]), "Asia/Shanghai")
        self.assertFalse(any(item[2]["id"] == "heiwu_poll" for item in scheduler.jobs))
        settings.heiwu_tasks_enabled = False
        with patch.object(jobs, "_scheduler", None), patch.object(jobs, "get_settings", return_value=settings), \
             patch.object(jobs, "BackgroundScheduler", RecordingScheduler):
            disabled = jobs.start_scheduler()
        self.assertFalse(any(item[2]["id"].startswith("heiwu_tasks_") for item in disabled.jobs))


if __name__ == "__main__":
    unittest.main()
