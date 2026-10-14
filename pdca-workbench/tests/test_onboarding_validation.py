"""Only current curriculum modules can advance onboarding progress."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.onboarding_progress import OnboardingProgress
from app.onboarding import service


CURRICULUM = {
    "tracks": [
        {"day": 1, "modules": [{"id": "real-one", "title": "First"}]},
        {"day": 2, "modules": [{"id": "real-two", "title": "Second"}]},
    ],
}


class OnboardingValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{(Path(self.temp.name) / 'progress.db').as_posix()}")
        SQLModel.metadata.create_all(self.engine)
        self.engine_patch = patch.object(service, "get_engine", return_value=self.engine)
        self.curriculum_patch = patch.object(service, "load_curriculum", return_value=CURRICULUM)
        self.engine_patch.start()
        self.curriculum_patch.start()

    def tearDown(self):
        self.curriculum_patch.stop()
        self.engine_patch.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def test_unknown_module_and_wrong_day_do_not_graduate(self):
        self.assertFalse(service.complete_module("sales", "fake-one", 999)["ok"])
        self.assertFalse(service.complete_module("sales", "real-one", 2)["ok"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(OnboardingProgress)).all()), 0)

    def test_stale_rows_do_not_count_and_repeat_is_idempotent(self):
        with Session(self.engine) as session:
            session.add(OnboardingProgress(username="sales", day=999, module_id="fake-one"))
            session.commit()
        self.assertEqual(service.build_progress("sales", "sales")["completed_modules"], 0)
        self.assertFalse(service.build_progress("sales", "sales")["graduated"])
        self.assertTrue(service.complete_module("sales", "real-one", 1, score=30)["ok"])
        with Session(self.engine) as session:
            first = session.exec(select(OnboardingProgress).where(OnboardingProgress.module_id == "real-one")).one()
            original = (first.score, first.completed_at)
        self.assertTrue(service.complete_module("sales", "real-one", 1, score=99)["ok"])
        progress = service.build_progress("sales", "sales")
        self.assertEqual(progress["completed_modules"], 1)
        self.assertEqual(progress["progress_pct"], 50)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(OnboardingProgress)).all()), 2)
            repeated = session.exec(select(OnboardingProgress).where(OnboardingProgress.module_id == "real-one")).one()
            self.assertEqual((repeated.score, repeated.completed_at), original)

    def test_missing_curriculum_never_graduates(self):
        with patch.object(service, "load_curriculum", return_value={"tracks": []}):
            progress = service.build_progress("sales", "sales")
        self.assertEqual(progress["total_modules"], 0)
        self.assertFalse(progress["graduated"])


if __name__ == "__main__":
    unittest.main()
