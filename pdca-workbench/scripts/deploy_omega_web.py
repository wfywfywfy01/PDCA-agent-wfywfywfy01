"""Deploy Omega's independent web process from the running PDCA image over Docker SSH."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


NAME = "pdca-omega-web"
SOURCE = "pdca-workbench"
REGISTRY = "ghcr.io/wfywfywfy01/pdca-workbench"
PORT = 8771
MOUNTS = {"/app/data", "/root/.vertu", "/root/.vertu/vps-service.json"}
ENV_NAMES = {
    "PDCA_SECRET_KEY", "PDCA_DATABASE_URL", "PDCA_CORS_ORIGINS", "PDCA_WORKBENCH_URL",
    "PDCA_TOKEN_EXPIRE_MINUTES", "PDCA_LOG_LEVEL", "PDCA_ASR_ENABLED", "PDCA_ASR_PROVIDER",
    "PDCA_DOUBAO_REALTIME_API_KEY", "PDCA_SUPERVISOR_PROVIDER", "PDCA_SUPERVISOR_MODEL",
    "PDCA_SUPERVISOR_API_KEY", "PDCA_SUPERVISOR_TIMEOUT_SECONDS",
    "PDCA_KNOWLEDGE_HUB_TEAM_MAP", "PDCA_VPS_LOGIN_URL", "VERTU_COMMAND", "VERTU_APP_ID", "VERTU_APP_KEY",
    "VERTU_USER_LOGIN", "VERTU_VPS_SERVICE_URL",
}


def run_docker(host: str, *args: str, timeout: int = 180) -> str:
    if not host.startswith("ssh://"):
        raise ValueError("Omega deployment requires SSH Docker transport")
    result = subprocess.run(
        ["docker", "-H", host, *args], capture_output=True, text=True, encoding="utf-8",
        timeout=timeout, check=False,
    )
    if result.returncode:
        # Docker stderr may contain environment values. Never echo it.
        raise RuntimeError(f"docker {args[0]} exited {result.returncode}")
    return result.stdout.strip()


def inspect(host: str, name: str) -> dict | None:
    try:
        return json.loads(run_docker(host, "inspect", name))[0]
    except RuntimeError:
        return None


def copy_environment(source: dict) -> dict[str, str]:
    all_env = dict(entry.split("=", 1) for entry in source["Config"]["Env"] if "=" in entry)
    env = {name: value for name, value in all_env.items() if name in ENV_NAMES or name.startswith((
        "PDCA_OMEGA_", "PDCA_VEMORY_", "PDCA_DOUBAO_ASR_"))}
    if not env.get("PDCA_DATABASE_URL", "").startswith("postgresql"):
        raise ValueError("Omega web requires the shared PostgreSQL database")
    if len(env.get("PDCA_SECRET_KEY", "")) < 32:
        raise ValueError("Omega web requires the shared strong signing key")
    for name in ("PDCA_DOUBAO_REALTIME_API_KEY", "PDCA_SUPERVISOR_PROVIDER",
                 "PDCA_SUPERVISOR_MODEL", "PDCA_SUPERVISOR_API_KEY"):
        if not env.get(name):
            raise ValueError(f"Omega web is missing {name}")
    if env.get("PDCA_OMEGA_REALTIME_PROVIDER") != "doubao":
        raise ValueError("Omega web requires the configured Doubao realtime provider")
    env.update({
        "PDCA_ENV": "production",
        "PDCA_HOST": "0.0.0.0",
        "PDCA_WORKBENCH_PORT": "8767",
        "PDCA_AUTH_MODE": "hybrid",
        "PDCA_AUTH_HOST_FALLBACK": "0",
        "PDCA_TRUST_PROXY_HEADERS": "0",
        "PDCA_SECURE_COOKIES": "1",
        "PDCA_REQUIRE_VERTU": "0",
        "PDCA_SCHEDULER_ENABLED": "0",
        "PDCA_OMEGA_ENABLED": "1",
        "PDCA_KNOWLEDGE_HUB_ENABLED": "0",
        "PDCA_HOME_REDIRECT": "/app/omega",
        "PDCA_BOOTSTRAP_ADMIN_USERNAME": "",
        "PDCA_BOOTSTRAP_ADMIN_PASSWORD": "",
    })
    if any("\n" in value or "\r" in value for value in env.values()):
        raise ValueError("Docker environment contains a multiline value")
    return env


def require_revision(source: dict, image: dict) -> str:
    revision = (source.get("Config", {}).get("Labels") or {}).get("com.vertu.pdca.revision")
    image_revision = (image.get("Config", {}).get("Labels") or {}).get("com.vertu.pdca.source_revision")
    if not revision or image_revision != revision:
        raise ValueError("Omega image revision mismatch")
    return revision


def same_environment(current: dict, image: dict, desired: dict[str, str]) -> bool:
    image_env = dict(entry.split("=", 1) for entry in image["Config"].get("Env", []) if "=" in entry)
    actual = dict(entry.split("=", 1) for entry in current["Config"].get("Env", []) if "=" in entry)
    return actual == {**image_env, **desired}


def build_run_args(source: dict, env_path: str, name: str = NAME, *,
                   image_name: str | None = None, revision: str | None = None) -> list[str]:
    networks = source.get("NetworkSettings", {}).get("Networks") or {}
    if "dealer-knowledge" not in networks:
        raise ValueError("PDCA source is not attached to dealer-knowledge")
    mounts = {mount["Destination"]: mount for mount in source.get("Mounts", [])}
    if not MOUNTS.issubset(mounts):
        raise ValueError("PDCA source is missing an Omega shared mount")
    revision = revision or (source["Config"].get("Labels") or {}).get("com.vertu.pdca.revision")
    if not revision:
        raise ValueError("PDCA source revision is missing")
    args = ["run", "-d", "--name", name, "--restart", "unless-stopped",
            "--label", "com.vertu.pdca.omega_web=1",
            "--label", f"com.vertu.pdca.revision={revision}",
            "-p", f"127.0.0.1:{PORT}:8767", "--network", "dealer-knowledge"]
    for destination in sorted(MOUNTS):
        mount = mounts[destination]
        kind = mount["Type"]
        if kind not in {"bind", "volume"}:
            raise ValueError(f"Unsupported Omega mount: {destination}")
        source_name = mount["Source"] if kind == "bind" else mount["Name"]
        if not source_name:
            raise ValueError(f"Omega mount source is missing: {destination}")
        specification = f"type={kind},src={source_name},dst={destination}"
        if not mount["RW"]:
            specification += ",readonly"
        args.extend(("--mount", specification))
    args.extend(("--env-file", env_path, image_name or source["Config"]["Image"]))
    return args


def _write_environment(env: dict[str, str]) -> str:
    descriptor, path = tempfile.mkstemp(prefix="pdca-omega-", suffix=".env")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for name, value in sorted(env.items()):
                stream.write(f"{name}={value}\n")
        return path
    except BaseException:
        Path(path).unlink(missing_ok=True)
        raise


def _active_calls(host: str) -> int:
    query = ("from sqlalchemy import text; from app.database import get_engine; "
             "c=get_engine().connect(); "
             "print(c.execute(text(\"SELECT count(*) FROM omega_jobs WHERE kind = 'realtime' "
             "AND status = 'running'\")).scalar_one()); c.close()")
    for name in (NAME, "pdca-omega-worker", SOURCE):
        candidate = inspect(host, name)
        if candidate and candidate["State"]["Running"]:
            raw = run_docker(host, "exec", name, "python", "-c", query)
            try:
                count = int(raw)
            except ValueError as exc:
                raise RuntimeError("Cannot verify active Omega calls") from exc
            if count < 0:
                raise RuntimeError("Cannot verify active Omega calls")
            return count
    raise RuntimeError("No running container can verify active Omega calls")


def _wait_healthy(host: str, name: str, seconds: int = 120) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        candidate = inspect(host, name)
        if candidate is None:
            raise RuntimeError("Omega container disappeared before health check")
        state = candidate["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if state["Status"] in {"exited", "dead", "restarting"}:
            raise RuntimeError(f"Omega container entered {state['Status']}")
        time.sleep(2)
    raise RuntimeError("Omega container did not become healthy")


def _smoke(host: str, name: str) -> None:
    code = """import json, urllib.error, urllib.request
base = 'http://127.0.0.1:8767'
with urllib.request.urlopen(base + '/app/omega', timeout=8) as response:
    assert response.status == 200 and b'/app/assets/' in response.read()
with urllib.request.urlopen(base + '/api/auth/config', timeout=8) as response:
    assert json.load(response)['auth_mode'] == 'hybrid'
for path in ('/api/auth/me', '/api/omega/status'):
    try:
        urllib.request.urlopen(base + path, timeout=8)
    except urllib.error.HTTPError as error:
        assert error.code == 401
    else:
        raise AssertionError('Unauthenticated Omega request was accepted')
print('ok')"""
    if run_docker(host, "exec", name, "python", "-c", code) != "ok":
        raise RuntimeError("Omega web smoke check failed")


def deploy(host: str, *, target_revision: str | None = None) -> str:
    if target_revision is not None and not re.fullmatch(r"[0-9a-f]{40}", target_revision):
        raise ValueError("Omega target revision must be an exact 40-character Git SHA")
    source = inspect(host, SOURCE)
    if source is None:
        raise RuntimeError("PDCA source container is missing")
    image_name = f"{REGISTRY}:{target_revision}" if target_revision else source["Config"]["Image"]
    image = inspect(host, image_name)
    if image is None and target_revision:
        run_docker(host, "pull", image_name, timeout=900)
        image = inspect(host, image_name)
    if image is None:
        raise RuntimeError("PDCA source image is missing")
    revision = (image.get("Config", {}).get("Labels") or {}).get("com.vertu.pdca.source_revision")
    if target_revision:
        if revision != target_revision:
            raise ValueError("Omega image revision mismatch")
    else:
        revision = require_revision(source, image)
    env = copy_environment(source)
    current = inspect(host, NAME)
    if current and (current.get("Config", {}).get("Labels") or {}).get("com.vertu.pdca.omega_web") != "1":
        raise RuntimeError("Omega container name is already owned by another service")
    if current and current["State"].get("Health", {}).get("Status") == "healthy" and (
        current["Config"].get("Labels") or {}).get("com.vertu.pdca.revision") == revision:
        if same_environment(current, image, env):
            return revision
    if current and _active_calls(host):
        raise RuntimeError("Active Omega realtime call; deployment deferred")
    env_path = _write_environment(env)
    old_name = f"{NAME}-rollback-{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    renamed = False
    try:
        args = build_run_args(source, env_path, image_name=image_name, revision=revision)
        if current:
            try:
                run_docker(host, "stop", "--time", "30", NAME)
                run_docker(host, "rename", NAME, old_name)
                renamed = True
            except BaseException:
                old = inspect(host, NAME)
                if old and not old["State"]["Running"]:
                    run_docker(host, "start", NAME)
                raise
        try:
            run_docker(host, *args)
            _wait_healthy(host, NAME)
            _smoke(host, NAME)
        except BaseException:
            if inspect(host, NAME):
                run_docker(host, "rm", "-f", NAME)
            if renamed:
                run_docker(host, "rename", old_name, NAME)
                run_docker(host, "start", NAME)
                _wait_healthy(host, NAME)
            raise
        if renamed:
            try:
                run_docker(host, "rm", "-v", old_name)
            except RuntimeError:
                print("Omega web healthy; old rollback container needs manual cleanup")
        return revision
    finally:
        Path(env_path).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-host", default="ssh://pdca-docker-176")
    parser.add_argument("--revision", help="deploy this tested, exact Git SHA to Omega only")
    args = parser.parse_args()
    revision = deploy(args.docker_host, target_revision=args.revision)
    print(f"Omega web healthy: {revision}")


if __name__ == "__main__":
    main()
