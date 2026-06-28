# -*- coding: utf-8 -*-
"""确保 pdca 数据库存在（从 .env 读取连接信息）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

url = os.environ.get("PDCA_DATABASE_URL", "")
parsed = urlparse(url.replace("+psycopg2", ""))
HOST = parsed.hostname or "localhost"
PORT = parsed.port or 5432
USER = parsed.username or "postgres"
PASSWORD = parsed.password or ""
DBNAME = (parsed.path or "/pdca").lstrip("/") or "pdca"

if not PASSWORD:
    print("请在 .env 中设置 PDCA_DATABASE_URL")
    sys.exit(1)

conn = None
last_err = None
for sslmode in ("prefer", "require", "disable"):
    try:
        conn = psycopg2.connect(
            host=HOST,
            port=PORT,
            user=USER,
            password=PASSWORD,
            dbname="postgres",
            sslmode=sslmode,
            connect_timeout=20,
        )
        print(f"已连接 sslmode={sslmode}")
        break
    except Exception as exc:
        last_err = exc
        print(f"sslmode={sslmode} 失败: {exc}")

if conn is None:
    print("无法连接 PostgreSQL:", last_err)
    sys.exit(1)

conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DBNAME,))
if not cur.fetchone():
    cur.execute(f'CREATE DATABASE "{DBNAME}"')
    print(f"已创建数据库 {DBNAME}")
else:
    print(f"数据库 {DBNAME} 已存在")
cur.close()
conn.close()

verify = psycopg2.connect(
    host=HOST,
    port=PORT,
    user=USER,
    password=PASSWORD,
    dbname=DBNAME,
    connect_timeout=20,
)
verify.close()
print(f"连接 {DBNAME} 成功")
