"""Release-layer contract checks; no Docker daemon, database or network required."""
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ReleaseDockerfileTests(unittest.TestCase):
    def setUp(self):
        self.text = (ROOT / "pdca-workbench/Dockerfile.release").read_text(encoding="utf-8")
        self.runtime = self.text.split("FROM ghcr.io/", 1)[1]

    def test_runtime_is_digest_pinned_and_keeps_inherited_service_configuration(self):
        self.assertRegex(self.runtime.splitlines()[0], r"^wfywfywfy01/pdca-workbench@sha256:[a-f0-9]{64}$")
        for command in ("CMD", "ENTRYPOINT", "HEALTHCHECK", "VOLUME", "EXPOSE", "USER"):
            self.assertIsNone(re.search(r"^" + command + r"\s", self.runtime, re.MULTILINE))
        self.assertEqual(re.findall(r"^ENV (.+)$", self.runtime, re.MULTILINE), ["PDCA_RELEASE_SHA=$SOURCE_REVISION"])
        self.assertIn("com.vertu.pdca.source_revision=$SOURCE_REVISION", self.runtime)
        self.assertIn("org.opencontainers.image.revision=$SOURCE_REVISION", self.runtime)

    def test_dependency_gate_is_offline_and_checks_installed_consistency(self):
        self.assertIn("python -m pip install --no-index --no-deps -r requirements.lock", self.runtime)
        self.assertIn("&& python -m pip check", self.runtime)
        self.assertNotRegex(self.runtime, r"(?m)^RUN (?:apt|npm|pip) ")

    def test_only_source_directories_are_removed_before_copy(self):
        removal = re.search(r"^RUN rm -rf (.+)$", self.runtime, re.MULTILINE)
        self.assertIsNotNone(removal)
        expected = {"/app/" + path for path in ("app", "frontend", "migrations", "scripts", "logibot", "spa-dist")}
        self.assertEqual(set(removal.group(1).split()), expected)
        for path in ("app", "frontend", "migrations", "scripts", "logibot"):
            self.assertGreater(self.runtime.index("COPY pdca-workbench/" + path + " "), removal.start())
        self.assertIn("COPY pdca-workbench/run.py .", self.runtime)
        self.assertIn("COPY --from=web-build /web/dist ./spa-dist", self.runtime)

    def test_frontend_uses_lockfile_and_all_three_gates(self):
        self.assertIn("ARG NODE_RUNTIME_IMAGE=node:22-bookworm-slim", self.text)
        self.assertIn("COPY apps/web/package.json apps/web/package-lock.json ./", self.text)
        self.assertIn("RUN npm ci --no-audit --no-fund", self.text)
        self.assertIn("RUN npm test && npm run typecheck && npm run build", self.text)

    def test_frontend_pages_are_available_before_node_tests_in_both_images(self):
        for name in ("Dockerfile", "Dockerfile.release"):
            text = (ROOT / "pdca-workbench" / name).read_text(encoding="utf-8")
            stage = text.split(" AS web-build\n", 1)[1].split("\nFROM ", 1)[0]
            before_tests = stage.split("RUN npm test", 1)[0]
            copied = {}
            for sources, destination in re.findall(r"(?m)^COPY (.+) (/\S+)$", before_tests):
                for source in sources.split():
                    target = destination + Path(source).name if destination.endswith("/") else destination
                    copied[target] = source
            for page in ("admin_panel.html", "growth.html"):
                with self.subTest(dockerfile=name, page=page):
                    source = "pdca-workbench/frontend/" + page
                    self.assertEqual(copied.get("/" + source), source)

    def test_postgres_smoke_explicitly_enables_and_runs_growth_tests(self):
        script = (ROOT / "pdca-workbench/scripts/docker_postgres_smoke_test.sh").read_text(encoding="utf-8")
        isolated_run = script.split('docker run --rm --network "container:$DB"', 1)[1].split("\ndocker run ", 1)[0]
        self.assertRegex(isolated_run, r"-e PDCA_TEST_POSTGRES_URL=postgresql\+psycopg2://[^\s]+@127\.0\.0\.1:5432/omega_test\s")
        self.assertRegex(isolated_run, r"python -m unittest [^\n]*\btests\.test_growth_postgres\b")

    def test_full_rebuild_revision_cannot_invalidate_dependency_installation(self):
        full = (ROOT / "pdca-workbench/Dockerfile").read_text(encoding="utf-8")
        runtime = full.split("FROM python:3.12-slim", 1)[1]
        self.assertGreater(runtime.index("ARG SOURCE_REVISION"), runtime.index("RUN python -m playwright install"))
        self.assertLess(runtime.index("ARG SOURCE_REVISION"), runtime.index("COPY pdca-workbench/app"))


if __name__ == "__main__":
    unittest.main()
