"""Destructive synthetic acceptance ONLY in the disposable pdca_review database.

Run inside a local development app container with scheduler disabled and an
isolated PostgreSQL database named pdca_review. Never run against production.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
import os
import re
from uuid import uuid4

import httpx
from sqlalchemy import text

from app.config import get_settings
from app.database import get_engine


def main():
    settings = get_settings()
    assert settings.environment == "development" and not settings.scheduler_enabled
    assert get_engine().url.database == "pdca_review", "Refusing non-disposable database"
    base = "http://127.0.0.1:8767"
    suffix = uuid4().hex[:8]

    @contextmanager
    def login(username, password, new_password=None):
        with httpx.Client(base_url=base, timeout=20, trust_env=False) as client:
            response = client.post("/api/auth/login", json={"username": username, "password": password})
            response.raise_for_status()
            if response.json().get("must_change_password"):
                response = client.post("/api/auth/change-password", json={"old_password": password, "new_password": new_password})
                response.raise_for_status()
            yield client

    with login("smoke-admin", os.environ.get("PDCA_ACCEPTANCE_ADMIN_PASSWORD", "SmokeAdmin123!"), "SmokeAdmin456!") as admin:
        for owner in ("a", "b"):
            store = {"store_id": f"isolate-{owner}-{suffix}", "name": f"Isolated Store {owner} {suffix}",
                     "region": "其他", "country": "Test", "team_key": "isolated", "sales_owner": f"owner-{owner}-{suffix}"}
            admin.post("/api/admin/stores", json=store).raise_for_status()
            user = {"username": f"scope-{owner}-{suffix}", "password": "ScopeUser123!", "role": "sales",
                    "owner_key": f"owner-{owner}-{suffix}", "team_key": "isolated", "data_scope": "self"}
            admin.post("/api/admin/users", json=user).raise_for_status()
        with login(f"scope-a-{suffix}", "ScopeUser123!", "ScopeUser456!") as sales:
            mine = sales.get("/api/my-stores").json()
            assert [row["store_id"] for row in mine] == [f"isolate-a-{suffix}"], mine
            body = {"report_date": date.today().isoformat(), "dealer_id": f"isolate-a-{suffix}",
                    "dealer_name": f"Isolated Store a {suffix}", "walkin_visits": 3,
                    "touch_count": 2, "deal_count": 1, "deal_amount_yuan": 100}
            with ThreadPoolExecutor(max_workers=6) as pool:
                replies = list(pool.map(lambda _: sales.post("/api/walkin-metrics", json=body), range(6)))
            assert all(reply.status_code == 200 for reply in replies), [r.status_code for r in replies]
            with get_engine().connect() as connection:
                count = connection.execute(text("SELECT count(*) FROM walkin_daily_reports WHERE dealer_id=:store AND report_date=:day"),
                                           {"store": body["dealer_id"], "day": body["report_date"]}).scalar()
            assert count == 1, f"Concurrent upsert produced {count} records"
            body["walkin_visits"] = 0
            body["touch_count"] = 0
            body["deal_count"] = 0
            body["deal_amount_yuan"] = 0
            sales.post("/api/walkin-metrics", json=body).raise_for_status()
            with get_engine().connect() as connection:
                values = connection.execute(text("SELECT walkin_visits,deal_amount_yuan FROM walkin_daily_reports WHERE dealer_id=:store"),
                                            {"store": body["dealer_id"]}).one()
            assert tuple(values) == (0, 0), values
            body["dealer_id"] = f"isolate-b-{suffix}"
            assert sales.post("/api/walkin-metrics", json=body).status_code == 403
            assert sales.get("/api/admin/users").status_code == 403
        health = admin.get("/health").json()
        assert health["database"] == "postgresql" and health["database_connected"]
        html = admin.get("/app/").text
        assets = re.findall(r'(?:src|href)="(/app/assets/[^\"]+)"', html)
        assert any(path.endswith(".js") for path in assets)
        for path in assets:
            response = admin.get(path)
            assert response.status_code == 200 and "text/html" not in response.headers["content-type"]
    print("PASS: PostgreSQL login/change-password, 6-way upsert=1 row, true-zero overwrite, owner isolation, cross-owner/admin denial, SPA assets")


if __name__ == "__main__":
    main()
