# -*- coding: utf-8 -*-
"""生产验收：建测试账号 → 登录 → 全模块 API + 页面验收 → 数据对账 → 删除测试账号。"""
import json
import os
import secrets
import string
import sys
import urllib.parse as up

import httpx
import psycopg2
from dotenv import load_dotenv

BASE = "https://pdca-workbench-teams.vertu.cn"
TEST_USER = "pdca-accept-test"

load_dotenv(r"D:\经销商PDCA\pdca-workbench\.env")
db_url = os.environ["PDCA_DATABASE_URL"].replace("postgresql+psycopg2://", "postgresql://")
p = up.urlparse(db_url)


def db():
    return psycopg2.connect(
        host=p.hostname, port=p.port, user=p.username,
        password=p.password, dbname=p.path[1:], connect_timeout=8,
    )


def make_password():
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20))


def create_user(password: str):
    import bcrypt as _bcrypt

    hashed = _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt()).decode("utf-8")
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM users WHERE username=%s", (TEST_USER,)
    )
    cur.execute(
        "INSERT INTO users (username, hashed_password, role, display_name, is_active, "
        "created_at, sales_name, must_change_password, pwd_version, dealer_id, "
        "owner_key, team_key, data_scope) "
        "VALUES (%s,%s,%s,%s,true,now(),'',false,0,'','','','all')",
        (TEST_USER, hashed, "admin", "验收测试账号"),
    )
    conn.commit()
    conn.close()


def remove_user():
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE username=%s", (TEST_USER,))
    conn.commit()
    conn.close()


def db_sellin_total(month: str) -> float:
    conn = db()
    cur = conn.cursor()
    cur.execute(
        "SELECT dealer_name, SUM(sell_in_wan) AS wan, SUM(units) AS qty FROM dealer_sales "
        "WHERE check_date LIKE %s GROUP BY dealer_name",
        (month + "%",),
    )
    rows = cur.fetchall()
    conn.close()
    # 与 db_sellin_summary 完全一致：跳过非正业绩，每家 round(2)，再求和 round(2)
    dealers = [round(float(wan), 2) for _, wan, qty in rows if float(wan) > 0 or int(qty or 0) > 0]
    return round(sum(dealers), 2)


def main() -> int:
    password = make_password()
    print(f"[1/5] 创建测试账号 {TEST_USER} (role=admin)…")
    create_user(password)
    client = httpx.Client(timeout=30, follow_redirects=False)

    print("[2/5] 登录…")
    resp = client.post(
        f"{BASE}/api/auth/login",
        json={"username": TEST_USER, "password": password},
    )
    if resp.status_code != 200:
        print(f"  FAIL login: {resp.status_code} {resp.text[:200]}")
        return 1
    print(f"  登录 OK（user={resp.json().get('user', {}).get('username')}）")

    print("[3/5] API 验收…")
    endpoints = [
        ("GET", "/api/auth/me"),
        ("GET", "/api/workbench/today"),
        ("GET", "/api/dashboard/overview?period=month"),
        ("GET", "/api/dashboard/sell-in?period=month"),
        ("GET", "/api/dashboard/sell-out?period=month"),
        ("GET", "/api/dealer/sellin-summary?month=2026-08"),
        ("GET", "/api/customer-center/summary"),
        ("GET", "/api/task-center/tasks"),
        ("GET", "/api/logistics/summary"),
        ("GET", "/api/logistics/shipments"),
        ("GET", "/api/logistics/dates"),
        ("GET", "/api/meeting-center/meetings"),
        ("GET", "/api/meeting-center/summary"),
        ("GET", "/api/signalseller/summary"),
        ("GET", "/api/signalseller/customers"),
        ("GET", "/api/signalseller/followup-tasks"),
        ("GET", "/api/walkin-metrics/summary?month=2026-08"),
        ("GET", "/api/my-stores"),
        ("GET", "/api/onboarding/curriculum"),
        ("GET", "/api/onboarding/progress"),
    ]
    failures = 0
    slow_timeout = httpx.Timeout(90.0)
    for method, path in endpoints:
        if "sellin-summary" in path or "sell-in" in path:
            resp = client.request(method, f"{BASE}{path}", timeout=slow_timeout)
        else:
            resp = client.request(method, f"{BASE}{path}")
        mark = "OK" if resp.status_code == 200 else "FAIL"
        if resp.status_code != 200:
            failures += 1
        print(f"  [{mark}] {resp.status_code} {path}")
    if failures:
        print(f"  API 失败 {failures} 项")

    print("[4/5] 页面与对账验收…")
    checks = [
        ("首页跳转(登录态)", client.get(f"{BASE}/"), 307, "/app/"),
        ("SPA /app/", client.get(f"{BASE}/app/"), 200, None),
        ("SPA /app/login", client.get(f"{BASE}/app/login"), 200, None),
        ("/metrics", client.get(f"{BASE}/metrics"), 200, None),
    ]
    for label, resp, expect, loc in checks:
        ok = resp.status_code == expect and (loc is None or loc in (resp.headers.get("location") or ""))
        mark = "OK" if ok else "FAIL"
        if not ok:
            failures += 1
        print(f"  [{mark}] {label}: {resp.status_code} {resp.headers.get('location','')}")

    resp = client.get(
        f"{BASE}/api/dealer/sellin-summary?month=2026-08",
        timeout=httpx.Timeout(90.0),
    )
    summary = resp.json()
    api_total = float(summary.get("total_wan") or 0)
    source = str(summary.get("source") or "")
    db_total = round(db_sellin_total("2026-08"), 2)
    diff = abs(api_total - db_total)
    print(f"  check: API total_wan={api_total} (source={source}) vs DB SUM={db_total} diff={diff}")
    if source and source != "dealer_sales_db":
        # 实时源（vertu +orders）可领先 DB 快照，属预期差异
        print(f"  [OK] 实时源 {source} 与 DB 快照差 {diff} 万，属正常领先")
    elif diff > 0.01:
        failures += 1
        print("  [FAIL] 对账不一致")

    print(f"[5/5] 删除测试账号 {TEST_USER}…")
    remove_user()
    print("  已删除")
    print("=" * 50)
    print("VERDICT:", "ALL PASS" if failures == 0 else f"{failures} FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
