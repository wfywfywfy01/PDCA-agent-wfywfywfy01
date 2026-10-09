"""Run Omega concurrency tests in a temporary local PostgreSQL cluster, then stop it.

Requires PostgreSQL binaries already installed; never reads the application DB URL.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    executable = shutil.which("initdb")
    if not executable and os.name == "nt":
        candidate = Path("C:/Program Files/PostgreSQL/16/bin/initdb.exe")
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        raise RuntimeError("Install PostgreSQL server binaries to run disposable database acceptance")
    binary = Path(executable).parent
    suffix = ".exe" if os.name == "nt" else ""
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    workspace = Path(tempfile.mkdtemp(prefix="omega-pg-acceptance-")).resolve()
    cluster = workspace / "cluster"
    log = workspace / "postgres.log"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    started = False

    def run(command: list[str], env=None, timeout=180):
        # Windows PostgreSQL background children may retain a captured pipe.
        if Path(command[0]).stem == 'pg_ctl':
            result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=timeout, **flags)
            if result.returncode:
                raise RuntimeError(f"temporary PostgreSQL control failed: {result.returncode}")
            return
        result = subprocess.run(command, cwd=root, env=env, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout, **flags)
        if result.returncode:
            raise RuntimeError(result.stdout[-12000:] + result.stderr[-12000:])
        print(result.stdout[-2000:], end="", flush=True)
        if result.stderr:
            print(result.stderr[-3000:], end="", flush=True)

    try:
        run([str(binary / ("initdb" + suffix)), "-D", str(cluster), "-U", "omega_qa",
             "--auth=trust", "--encoding=UTF8", "--locale=C"])
        started = True
        run([str(binary / ("pg_ctl" + suffix)), "-D", str(cluster), "-l", str(log),
             "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"])
        run([str(binary / ("createdb" + suffix)), "-h", "127.0.0.1", "-p", str(port),
             "-U", "omega_qa", "omega_test"])
        url = f"postgresql+psycopg2://omega_qa@127.0.0.1:{port}/omega_test"
        env = dict(os.environ, PDCA_ENV="development", PDCA_SCHEDULER_ENABLED="0",
                   PDCA_REQUIRE_VERTU="0", PDCA_DATABASE_URL=url,
                   PDCA_SECRET_KEY="isolated-omega-acceptance-key-only-32chars",
                   OMEGA_TEST_DATABASE_URL=url, PYTHONIOENCODING="utf-8")
        run([sys.executable, "scripts/migrate.py"], env)
        run([sys.executable, "scripts/migrate.py"], env)
        for name in ("test_omega_postgres.py", "test_omega_memory_postgres.py", "test_omega_templates_postgres.py", "test_migrate_entrypoint.py"):
            if (root / "tests" / name).is_file():
                run([sys.executable, "-m", "unittest", f"tests.{name[:-3]}", "-v"], env)
        # Check backward migration and a fresh re-upgrade after exercising new records.
        run([sys.executable, "-m", "alembic", "-c", "migrations/alembic.ini", "downgrade", "018"], env)
        run([sys.executable, "scripts/migrate.py"], env)
        print("PASS: disposable PostgreSQL concurrency, repeated migration, downgrade/upgrade")
    finally:
        if started and (cluster / 'postmaster.pid').exists():
            run([str(binary / ("pg_ctl" + suffix)), "-D", str(cluster), "-m", "fast", "-w", "stop"], timeout=60)
        if workspace.parent == Path(tempfile.gettempdir()).resolve() and workspace.name.startswith("omega-pg-acceptance-"):
            shutil.rmtree(workspace)


if __name__ == "__main__":
    main()
