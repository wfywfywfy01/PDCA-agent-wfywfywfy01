"""Read-only production acceptance using an existing account; never seed/delete users.

Credentials: PDCA_SMOKE_USERNAME / PDCA_SMOKE_PASSWORD (never printed).
For independent reconciliation pass --expected-snapshot-wan from a read-only DB query
selecting the latest check_date in the month, including negative returns.
HTTP success alone is not proof of data correctness.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import math
import os
import re
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx


def snapshot_matches(payload: dict, expected: float) -> bool:
    value = payload.get("total_wan")
    return (
        payload.get("source") == "dealer_sales_db_latest_snapshot"
        and payload.get("has_data") is True
        and value is not None and math.isfinite(float(value))
        and math.isfinite(expected) and abs(float(value) - expected) < 0.011
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://pdca-workbench-teams.vertu.cn")
    parser.add_argument("--month", default=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m"))
    parser.add_argument("--expected-revision", default="")
    parser.add_argument("--expected-snapshot-wan", type=float)
    args = parser.parse_args()
    parsed = urlparse(args.base)
    if parsed.hostname not in {"pdca-workbench-teams.vertu.cn", "pdca-workbench.vertu.cn", "localhost", "127.0.0.1"}:
        parser.error("Target must be a PDCA production domain or loopback")
    if parsed.hostname not in {"localhost", "127.0.0.1"} and parsed.scheme != "https":
        parser.error("Production authentication requires HTTPS")
    datetime.strptime(args.month, "%Y-%m")
    username = os.environ.get("PDCA_SMOKE_USERNAME", "")
    password = os.environ.get("PDCA_SMOKE_PASSWORD", "")
    if not username or not password:
        parser.error("Set PDCA_SMOKE_USERNAME and PDCA_SMOKE_PASSWORD for an existing account")

    failures = 0
    with httpx.Client(base_url=args.base.rstrip("/"), timeout=30, follow_redirects=False) as client:
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        if response.status_code != 200:
            print(f"[FAIL] Existing account login: HTTP {response.status_code}", flush=True)
            return 1
        if response.json().get("must_change_password"):
            print("[FAIL] Account requires password change; acceptance did not change it", flush=True)
            return 1
        paths = [
            "/health", "/api/auth/me", "/api/workbench/today",
            "/api/dashboard/overview?period=month", "/api/dashboard/sell-in?period=month",
            "/api/dashboard/sell-out?period=month", f"/api/dealer/sellin-summary?month={args.month}",
            "/api/customer-center/summary", "/api/task-center/tasks",
            "/api/logistics/summary", "/api/logistics/shipments", "/api/logistics/dates", "/api/logistics/freight",
            "/api/meeting-center/meetings", "/api/meeting-center/summary",
            "/api/signalseller/summary", "/api/signalseller/customers", "/api/signalseller/followup-tasks",
            f"/api/walkin-metrics/summary?month={args.month}", "/api/my-stores",
            "/api/onboarding/curriculum", "/api/onboarding/progress",
        ]
        if parsed.hostname == "pdca-workbench.vertu.cn":
            paths = ["/health", "/api/auth/me", "/api/my-stores", f"/api/walkin-metrics/summary?month={args.month}"]
        for path in paths:
            started = time.perf_counter()
            try:
                response = client.get(path)
                response.raise_for_status()
                payload = response.json()
                if path == "/health":
                    assert payload["status"] == "ok" and payload["database_connected"]
                    if args.expected_revision:
                        assert payload["revision"] == args.expected_revision
                if "sellin-summary" in path:
                    print(f"  snapshot: source={payload.get('source')} as_of={payload.get('as_of')} "
                          f"has_data={payload.get('has_data')} total_wan={payload.get('total_wan')}", flush=True)
                    if args.expected_snapshot_wan is not None:
                        assert snapshot_matches(payload, args.expected_snapshot_wan), "Snapshot reconciliation failed"
                print(f"[OK] {path} ({time.perf_counter() - started:.2f}s)", flush=True)
            except (httpx.HTTPError, ValueError, KeyError, AssertionError) as exc:
                failures += 1
                print(f"[FAIL] {path}: {type(exc).__name__}", flush=True)
        if parsed.hostname != "pdca-workbench.vertu.cn":
            response = client.get("/app/")
            assets = re.findall(r'(?:src|href)="(/app/assets/[^\"]+)"', response.text)
            if response.status_code != 200 or not any(asset.endswith(".js") for asset in assets):
                failures += 1
                print("[FAIL] SPA bundle missing", flush=True)
            for asset in assets:
                result = client.get(asset)
                if result.status_code != 200 or "text/html" in result.headers.get("content-type", ""):
                    failures += 1
                    print(f"[FAIL] SPA asset {asset}", flush=True)
    print(f"Read-only acceptance: {failures} failures; no business records written", flush=True)
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
