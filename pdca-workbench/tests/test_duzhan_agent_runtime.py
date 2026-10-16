# -*- coding: utf-8 -*-
"""配置 → 运行时（db 源）：翻译、过滤、台账分档、调度注册。"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.ctob import OWNERS
from app.duzhan import GROUPS, DuzhanGroup, groups_for_tz
from app.duzhan_admin import runtime
from app.duzhan_admin.service import dump_blocks, parse_blocks
from app.models.duzhan_agent import DuzhanAgent

NEW_GROUP = GROUPS[0]
FOLLOW_GROUP = "776e2a94-884a-45dd-aab5-566e15e6b521"  # app.ctob.OWNERS[0]


def _blocks(**over):
    return {
        "blocks": [
            {"type": "group", "channel_id": over.get("channel_id", NEW_GROUP.channel_id),
             "label": over.get("label", NEW_GROUP.name)},
            {"type": "times", "slots": over.get("slots", ["10:00", "15:00", "20:00"])},
            {"type": "style", "lang": over.get("lang", NEW_GROUP.lang)},
        ]
    }


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, **kwargs):
        self.jobs.append({"func": func.__name__, **kwargs})

    def ids(self):
        return [job["id"] for job in self.jobs]


class RuntimeTranslationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.patch_engine = patch("app.database.get_engine", return_value=self.engine)
        self.patch_engine.start()
        self.addCleanup(self.patch_engine.stop)

    def add(self, name, blocks, *, enabled=True, timezone="Asia/Shanghai"):
        with Session(self.engine) as session:
            row = DuzhanAgent(name=name, enabled=enabled, timezone=timezone,
                              blocks_json=dump_blocks(parse_blocks(blocks)))
            session.add(row)
            session.commit()
            session.refresh(row)
            return row

    def test_group_of_matches_hardcoded_group(self):
        agent = self.add("新人组官", _blocks())
        group = runtime.group_of(agent)
        self.assertEqual(group.name, NEW_GROUP.name)
        self.assertEqual(group.channel_id, NEW_GROUP.channel_id)
        self.assertEqual(group.lang, NEW_GROUP.lang)
        self.assertEqual(group.tz, NEW_GROUP.tz)

    def test_group_of_binds_business_group_by_channel_id(self):
        other = GROUPS[1]
        agent = self.add("错配群名", _blocks(label=other.name))
        group = runtime.group_of(agent)
        self.assertEqual(group.channel_id, NEW_GROUP.channel_id)
        self.assertEqual(group.name, NEW_GROUP.name)

    def test_group_of_uses_agent_name_and_default_tz(self):
        agent = self.add("没名字的群", {"blocks": [
            {"type": "group", "channel_id": NEW_GROUP.channel_id},
            {"type": "times", "slots": ["10:00"]},
        ]}, timezone="")
        group = runtime.group_of(agent)
        self.assertEqual(group.name, NEW_GROUP.name)
        self.assertEqual(group.tz, "Asia/Shanghai")
        self.assertEqual(group.lang, "zh")

    def test_slots_accept_custom_clock_times(self):
        agent = self.add("档位官", {"blocks": [
            {"type": "group", "channel_id": NEW_GROUP.channel_id},
            {"type": "times", "slots": ["09:35", "14:05", "20:00"]},
        ]})
        self.assertEqual(runtime.slot_times_of(agent), ["09:35", "14:05", "20:00"])
        self.assertEqual(runtime.slots_of(agent), [9, 14, 20])
        self.assertEqual(runtime.previous_slot_of(agent, "14:05"), (0, "09:35"))
        self.assertEqual(runtime.previous_slot_of(agent, "09:35"), (-1, "20:00"))
        self.assertIsNone(runtime.previous_slot_of(agent, "10:00"))

        single = self.add("单档官", {"blocks": [
            {"type": "group", "channel_id": NEW_GROUP.channel_id},
            {"type": "times", "slots": ["14:10"]},
        ]})
        self.assertIsNone(runtime.previous_slot_of(single, "14:10"))

    def test_duzhan_agents_skips_follow_and_invalid(self):
        self.add("跟进群官", _blocks(channel_id=FOLLOW_GROUP, label="跟进群"))
        self.add("坏配置官", {"blocks": [{"type": "times", "slots": ["10:00"]}]})
        self.add("停用官", _blocks(), enabled=False)
        good = self.add("好配置官", _blocks())
        picked = runtime.duzhan_agents()
        self.assertEqual([agent.id for agent, _group in picked], [good.id])

    def test_group_of_returns_none_without_group_block(self):
        agent = self.add("无群官", {"blocks": [{"type": "times", "slots": ["10:00"]}]})
        self.assertIsNone(runtime.group_of(agent))

    def test_config_source_falls_back_to_code(self):
        with patch("app.config.get_settings", return_value=SimpleNamespace(duzhan_config_source="weird")):
            self.assertEqual(runtime.config_source(), "code")
            self.assertFalse(runtime.using_db())
        with patch("app.config.get_settings", return_value=SimpleNamespace(duzhan_config_source="DB")):
            self.assertTrue(runtime.using_db())

    def test_send_conditions_use_calendar_and_observed_data(self):
        agent = self.add("条件官", {
            "blocks": [
                *_blocks()["blocks"],
                {"type": "condition", "key": "holiday", "value": False},
                {"type": "condition", "key": "has_data", "value": True},
            ]
        })
        self.assertFalse(runtime.conditions_allow(agent, "2026-10-01", {"people": []}))
        self.assertFalse(runtime.conditions_allow(agent, "2026-10-13", {"people": []}))
        ledger = {"people": [{"group": NEW_GROUP.name, "mtd_wan": 0}]}
        self.assertTrue(runtime.conditions_allow(agent, "2026-10-13", ledger))
        self.assertFalse(runtime.conditions_allow(agent, "2026-10-01", ledger))

    def test_ctob_has_data_requires_observed_value(self):
        agent = self.add("跟进数据条件", {"blocks": [
            *_blocks(channel_id=FOLLOW_GROUP, label="跟进群")["blocks"],
            {"type": "condition", "key": "has_data", "value": True},
        ]})
        self.assertFalse(runtime.conditions_allow(agent, "2026-10-13", {
            "summary": {"reached": None, "car": 0}, "chats": [], "cohort": {"focus_new": 0},
        }))
        self.assertTrue(runtime.conditions_allow(agent, "2026-10-13", {
            "summary": {"reached": 0}, "chats": [], "cohort": {},
        }))
        self.assertTrue(runtime.conditions_allow(agent, "2026-10-13", {
            "summary": {}, "chats": [], "cohort": {"rows": [{"name": "某客户"}]},
        }))

    def test_ctob_timezone_is_fixed_to_shanghai(self):
        from app.duzhan_admin import service

        agent = self.add(
            "巴黎跟进群官",
            _blocks(channel_id=FOLLOW_GROUP, label="跟进群"),
            timezone="Europe/Paris",
        )

        self.assertEqual(runtime.group_of(agent).tz, "Asia/Shanghai")
        self.assertIn("C转B 跟进群仅支持 Asia/Shanghai 时区", service.validate_agent(agent))


class DbGroupsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.stack = [
            patch("app.database.get_engine", return_value=self.engine),
            patch("app.config.get_settings", return_value=SimpleNamespace(
                duzhan_config_source="db", duzhan_times=["10:00", "15:00", "20:00"], duzhan_lead_minutes=15)),
        ]
        for item in self.stack:
            item.start()
            self.addCleanup(item.stop)
        with Session(self.engine) as session:
            session.add(DuzhanAgent(name="巴黎官", enabled=True, timezone="Europe/Paris",
                                    blocks_json=dump_blocks(parse_blocks(_blocks(lang="en", label="巴黎群")))))
            session.add(DuzhanAgent(name="上海官", enabled=True, timezone="Asia/Shanghai",
                                    blocks_json=dump_blocks(parse_blocks(_blocks(label="上海群")))))
            session.commit()

    def test_groups_for_tz_uses_config_when_db(self):
        # 取数归属只认 channel_id；可编辑展示名不能切换到另一组业务数据。
        paris = groups_for_tz("Europe/Paris")
        self.assertEqual([group.name for group in paris], [NEW_GROUP.name])
        self.assertEqual(paris[0].lang, "en")
        shanghai = groups_for_tz("Asia/Shanghai")
        self.assertEqual([group.name for group in shanghai], [NEW_GROUP.name])

    def test_channel_filter(self):
        self.assertEqual(len(groups_for_tz("Asia/Shanghai", [NEW_GROUP.channel_id])), 1)
        self.assertEqual(groups_for_tz("Asia/Shanghai", ["11111111-1111-4111-8111-111111111111"]), [])

    def test_cron_timezones_from_config(self):
        self.assertEqual(runtime.cron_timezones(), ["Europe/Paris", "Asia/Shanghai"])

    def test_register_agent_jobs(self):
        from app.duzhan import cron_timezones as code_timezones

        self.assertEqual(code_timezones(), ["Europe/Paris", "Asia/Shanghai"])
        scheduler = FakeScheduler()
        registered = runtime.register_agent_jobs(scheduler)
        self.assertEqual(len(registered), 2)
        ids = scheduler.ids()
        self.assertIn("duzhan_europe_paris_10", ids)
        self.assertIn("duzhan_collect_europe_paris_20", ids)
        self.assertIn("duzhan_backup_europe_paris_15", ids)
        push = next(job for job in scheduler.jobs if job["id"] == "duzhan_europe_paris_10")
        self.assertEqual(push["kwargs"]["channel_ids"], [NEW_GROUP.channel_id])
        self.assertEqual(push["kwargs"]["ledger_job"], "duzhan_push:db:Europe/Paris")

    def test_register_agent_jobs_uses_custom_minutes(self):
        with Session(self.engine) as session:
            custom = DuzhanAgent(
                name="自定义时间官",
                enabled=True,
                timezone="Asia/Shanghai",
                blocks_json=dump_blocks(parse_blocks(_blocks(
                    channel_id="11111111-1111-4111-8111-111111111111",
                    label="自定义时间群",
                    slots=["09:35"],
                ))),
            )
            session.add(custom)
            session.commit()
            session.refresh(custom)
            custom_id = custom.id
        scheduler = FakeScheduler()
        registered = runtime.register_agent_jobs(scheduler)

        row = next(item for item in registered if item["agent_id"] == custom_id)
        self.assertEqual(row["slots"], ["09:35"])
        push = next(job for job in scheduler.jobs if job["id"] == "duzhan_asia_shanghai_0935")
        collect = next(job for job in scheduler.jobs if job["id"] == "duzhan_collect_asia_shanghai_0935")
        backup = next(job for job in scheduler.jobs if job["id"] == "duzhan_backup_asia_shanghai_0935")
        self.assertEqual((push["hour"], push["minute"]), (9, 35))
        self.assertEqual((collect["hour"], collect["minute"]), (9, 20))
        self.assertEqual((backup["hour"], backup["minute"]), (10, 5))

    def test_register_agent_jobs_keeps_target_day_across_midnight(self):
        with Session(self.engine) as session:
            session.add(DuzhanAgent(
                name="跨天时间官",
                enabled=True,
                timezone="Asia/Shanghai",
                blocks_json=dump_blocks(parse_blocks(_blocks(
                    channel_id="22222222-2222-4222-8222-222222222222",
                    label="跨天时间群",
                    slots=["00:05", "23:50"],
                ))),
            ))
            session.commit()
        scheduler = FakeScheduler()
        runtime.register_agent_jobs(scheduler)

        collect = next(job for job in scheduler.jobs if job["id"] == "duzhan_collect_asia_shanghai_0005")
        early_backup = next(job for job in scheduler.jobs if job["id"] == "duzhan_backup_asia_shanghai_0005")
        late_backup = next(job for job in scheduler.jobs if job["id"] == "duzhan_backup_asia_shanghai_2350")
        self.assertEqual((collect["hour"], collect["minute"]), (23, 50))
        self.assertEqual(collect["kwargs"]["trigger_offset_minutes"], -15)
        self.assertEqual(early_backup["kwargs"]["trigger_offset_minutes"], 30)
        self.assertEqual((late_backup["hour"], late_backup["minute"]), (0, 20))
        self.assertEqual(late_backup["kwargs"]["trigger_offset_minutes"], 30)

    def test_same_slot_batches_groups_and_follow_owners(self):
        other_channel = "11111111-1111-4111-8111-111111111111"
        with Session(self.engine) as session:
            for name, channel in (("上海二官", other_channel),
                                  ("跟进一官", OWNERS[0].channel_id),
                                  ("跟进二官", OWNERS[1].channel_id)):
                session.add(DuzhanAgent(name=name, enabled=True, timezone="Asia/Shanghai",
                                        blocks_json=dump_blocks(parse_blocks(
                                            _blocks(channel_id=channel, label=name)))))
            session.commit()
        scheduler = FakeScheduler()
        self.assertEqual(len(runtime.register_agent_jobs(scheduler)), 5)
        self.assertEqual(len(scheduler.ids()), len(set(scheduler.ids())))
        collect = next(job for job in scheduler.jobs if job["id"] == "duzhan_collect_asia_shanghai_15")
        self.assertCountEqual(collect["kwargs"]["channel_ids"], [NEW_GROUP.channel_id, other_channel])
        self.assertEqual(sum(job["id"].startswith("duzhan_collect_asia_shanghai_15") for job in scheduler.jobs), 1)
        duzhan_backup = next(job for job in scheduler.jobs if job["id"] == "duzhan_backup_asia_shanghai_15")
        self.assertEqual((duzhan_backup["hour"], duzhan_backup["minute"]), (15, 30))
        follow = next(job for job in scheduler.jobs if job["id"] == "ctob_db_15")
        self.assertEqual({owner.channel_id for owner in follow["kwargs"]["owners"]},
                         {OWNERS[0].channel_id, OWNERS[1].channel_id})
        self.assertEqual(follow["kwargs"]["ledger_job"], "ctob:db")
        backup = next(job for job in scheduler.jobs if job["id"] == "ctob_db_backup_15")
        self.assertEqual((backup["hour"], backup["minute"]), (15, 30))

    def test_register_agent_jobs_respects_independent_feature_switches(self):
        with Session(self.engine) as session:
            session.add(DuzhanAgent(
                name="跟进开关官",
                enabled=True,
                timezone="Asia/Shanghai",
                blocks_json=dump_blocks(parse_blocks(_blocks(
                    channel_id=OWNERS[0].channel_id,
                    label="跟进开关群",
                    slots=["09:35"],
                ))),
            ))
            session.commit()

        follow_only = FakeScheduler()
        registered = runtime.register_agent_jobs(
            follow_only, duzhan_enabled=False, ctob_enabled=True,
        )
        self.assertTrue(registered)
        self.assertTrue(all(row["kind"] == "follow" for row in registered))
        self.assertTrue(all(job_id.startswith("ctob_db_") for job_id in follow_only.ids()))

        duzhan_only = FakeScheduler()
        registered = runtime.register_agent_jobs(
            duzhan_only, duzhan_enabled=True, ctob_enabled=False,
        )
        self.assertTrue(registered)
        self.assertTrue(all(row["kind"] == "duzhan" for row in registered))
        self.assertFalse(any(job_id.startswith("ctob_db_") for job_id in duzhan_only.ids()))

    def test_register_agent_jobs_warns_when_nothing_enabled(self):
        with Session(self.engine) as session:
            for row in session.exec(__import__("sqlmodel").select(DuzhanAgent)).all():
                session.delete(row)
            session.commit()
        scheduler = FakeScheduler()
        self.assertEqual(runtime.register_agent_jobs(scheduler), [])
        self.assertEqual(scheduler.jobs, [])


class DbSchedulerSwitchTests(unittest.TestCase):
    class RecordingScheduler:
        def __init__(self, **_kwargs):
            self.jobs = []

        def add_job(self, func, *args, **kwargs):
            self.jobs.append((func, args, kwargs))

        def start(self):
            return None

    @staticmethod
    def settings(
        *,
        duzhan_enabled: bool,
        ctob_enabled: bool,
        reply_enabled: bool = False,
        healthcheck_enabled: bool = False,
    ):
        return SimpleNamespace(
            scheduler_enabled=True,
            sync_cron="0 6 * * *",
            daily_report_enabled=False,
            todo_remind_enabled=False,
            todo_remind_times=[],
            todo_group_notice_enabled=False,
            todo_group_channel_id="",
            todo_scoring_enabled=False,
            todo_ledger_sync_enabled=False,
            todo_brief_enabled=False,
            todo_okr_link_enabled=False,
            duzhan_enabled=duzhan_enabled,
            duzhan_times=["10:00", "15:00", "20:00"],
            duzhan_lead_minutes=15,
            duzhan_reply_enabled=reply_enabled,
            ctob_enabled=ctob_enabled,
            agent_healthcheck_enabled=healthcheck_enabled,
        )

    def start(self, settings, *, using_db: bool = True):
        from app.scheduler import jobs as scheduler_jobs

        original = scheduler_jobs._scheduler
        scheduler_jobs._scheduler = None
        register = MagicMock(return_value=[])
        try:
            with patch.object(scheduler_jobs, "get_settings", return_value=settings), patch.object(
                scheduler_jobs, "BackgroundScheduler", self.RecordingScheduler,
            ), patch("app.duzhan_admin.runtime.using_db", return_value=using_db), patch(
                "app.duzhan_admin.runtime.register_agent_jobs", register,
            ):
                scheduler = scheduler_jobs.start_scheduler()
        finally:
            scheduler_jobs._scheduler = original
        return scheduler, register

    def test_db_registration_passes_independent_switches(self):
        for duzhan_enabled, ctob_enabled in ((True, False), (False, True)):
            with self.subTest(duzhan_enabled=duzhan_enabled, ctob_enabled=ctob_enabled):
                scheduler, register = self.start(self.settings(
                    duzhan_enabled=duzhan_enabled,
                    ctob_enabled=ctob_enabled,
                ))
                register.assert_called_once_with(
                    scheduler,
                    duzhan_enabled=duzhan_enabled,
                    ctob_enabled=ctob_enabled,
                )

    def test_db_mode_registers_duzhan_at_poll(self):
        scheduler, _register = self.start(self.settings(
            duzhan_enabled=True,
            ctob_enabled=False,
            reply_enabled=True,
        ))
        self.assertIn("duzhan_at_poll", [kwargs["id"] for _, _, kwargs in scheduler.jobs])

    def test_ctob_only_mode_registers_and_runs_slot_health(self):
        settings = self.settings(
            duzhan_enabled=False,
            ctob_enabled=True,
            healthcheck_enabled=True,
        )
        scheduler, _register = self.start(settings)
        self.assertIn("agent_slot_health", [kwargs["id"] for _, _, kwargs in scheduler.jobs])

        from app.scheduler import jobs as scheduler_jobs

        with patch.object(scheduler_jobs, "get_settings", return_value=settings), patch(
            "app.duzhan_admin.runtime.using_db", return_value=True,
        ), patch(
            "app.agents.flow_controller.run_health_checks_for", return_value=[],
        ) as run_health:
            scheduler_jobs.agent_slot_health_job()
        run_health.assert_called_once_with()

    def test_code_ctob_only_mode_does_not_start_db_health_scan(self):
        settings = self.settings(
            duzhan_enabled=False,
            ctob_enabled=True,
            healthcheck_enabled=True,
        )
        scheduler, _register = self.start(settings, using_db=False)
        self.assertNotIn("agent_slot_health", [kwargs["id"] for _, _, kwargs in scheduler.jobs])

        from app.scheduler import jobs as scheduler_jobs

        with patch.object(scheduler_jobs, "get_settings", return_value=settings), patch(
            "app.duzhan_admin.runtime.using_db", return_value=False,
        ), patch(
            "app.agents.flow_controller.run_health_checks_for", return_value=[],
        ) as run_health:
            scheduler_jobs.agent_slot_health_job()
        run_health.assert_not_called()


if __name__ == "__main__":
    unittest.main()
