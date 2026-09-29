"""Run an isolated localhost Omega trial with a user-supplied voice credential file.

Usage: python scripts/run_omega_local.py PATH_TO_VOICE_ENV
The provider key stays in this process; the SQLite database and login file live
under the current user's LocalAppData directory.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def main() -> None:
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VertuOmega" / "local"
    local.mkdir(parents=True, exist_ok=True)
    sys.stdout = (local / "server.out.log").open("a", encoding="utf-8", buffering=1)
    sys.stderr = (local / "server.err.log").open("a", encoding="utf-8", buffering=1)
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/run_omega_local.py PATH_TO_VOICE_ENV")
    lines = Path(sys.argv[1]).read_text(encoding="utf-8-sig").splitlines()
    endpoints = [line.strip() for line in lines if line.strip().startswith("https://")]
    keys = [line.strip() for line in lines if line.strip().startswith("sk-")]
    doubao = [line.split(":", 1)[1].strip() for line in lines
              if line.strip().startswith("豆包语音key:")]
    if len(doubao) == 1 and not endpoints and not keys:
        try:
            uuid.UUID(doubao[0])
        except ValueError:
            raise SystemExit("Doubao API Key format is invalid") from None
        voice_settings = {"PDCA_OMEGA_REALTIME_PROVIDER": "doubao",
                          "PDCA_DOUBAO_REALTIME_API_KEY": doubao[0]}
    elif len(endpoints) == 1 and len(keys) == 1 and not doubao:
        endpoint = urlsplit(endpoints[0])
        match = re.fullmatch(r"([a-z0-9-]+)\.cn-beijing\.maas\.aliyuncs\.com", endpoint.hostname or "")
        if endpoint.scheme != "https" or not match or endpoint.username or endpoint.password:
            raise SystemExit("Credential file must contain a Beijing workspace HTTPS URL")
        voice_settings = {"PDCA_OMEGA_REALTIME_PROVIDER": "qwen",
                          "PDCA_QWEN_REALTIME_WORKSPACE_ID": match.group(1),
                          "PDCA_QWEN_REALTIME_API_KEY": keys[0]}
    else:
        raise SystemExit("Credential file must contain one supported voice API Key")
    login_path = local / "login.json"
    if login_path.exists():
        password = json.loads(login_path.read_text(encoding="utf-8"))["password"]
    else:
        password = secrets.token_urlsafe(20)
        login_path.write_text(json.dumps({"username": "omega-local-manager", "password": password}), encoding="utf-8")

    secret_path = local / "app-secret.txt"
    if secret_path.exists():
        app_secret = secret_path.read_text(encoding="utf-8").strip()
    else:
        app_secret = secrets.token_urlsafe(48)
        secret_path.write_text(app_secret, encoding="utf-8")

    os.environ.update({
        "PDCA_ENV": "development",
        "PDCA_DATABASE_URL": f"sqlite:///{(local / 'omega.sqlite').as_posix()}",
        "PDCA_SECRET_KEY": app_secret,
        "PDCA_AUTH_MODE": "local",
        "PDCA_SECURE_COOKIES": "0",
        "PDCA_OMEGA_ENABLED": "1",
        **voice_settings,
        "PDCA_SCHEDULER_ENABLED": "0",
        "PDCA_ACQUISITION_ENABLED": "0",
        "PDCA_KNOWLEDGE_HUB_ENABLED": "0",
        "PDCA_REQUIRE_VERTU": "0",
        "PDCA_AGENT_ENABLED": "0",
        "PDCA_HOME_REDIRECT": "/app/omega",
    })
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    # Isolated login for the local trial. Never touch the existing PDCA database.
    from sqlmodel import Session, select
    from app.auth.models import User
    from app.auth.security import hash_password
    from app.database import bootstrap_database, get_engine

    bootstrap_database()
    with Session(get_engine()) as db:
        user = db.exec(select(User).where(User.username == "omega-local-manager")).first()
        if user is None:
            db.add(User(username="omega-local-manager", hashed_password=hash_password(password),
                        role="manager", display_name="本机试用主管", team_key="omega-local",
                        must_change_password=False))
            db.commit()

    import uvicorn
    from app.main import app

    print(f"Omega local: http://127.0.0.1:8769/app/omega | login: {login_path}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=8769, log_level="warning")


if __name__ == "__main__":
    main()
