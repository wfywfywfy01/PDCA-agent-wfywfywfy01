# -*- coding: utf-8 -*-
"""
初始化 PostgreSQL 数据库与表结构。

用法:
  python db_schema.py
  python db_schema.py --create-db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

from db_config import db_settings, db_cursor


TABLE_DDL = """
CREATE TABLE IF NOT EXISTS daily_reports (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    username TEXT NOT NULL,
    generated_at TIMESTAMPTZ,
    total_sessions INTEGER NOT NULL DEFAULT 0,
    total_turns INTEGER NOT NULL DEFAULT 0,
    daily_summary TEXT NOT NULL DEFAULT '',
    key_topics TEXT[] NOT NULL DEFAULT '{}',
    files_modified TEXT[] NOT NULL DEFAULT '{}',
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (report_date, username)
);

CREATE TABLE IF NOT EXISTS sessions (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    username TEXT NOT NULL,
    session_id TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    topics TEXT[] NOT NULL DEFAULT '{}',
    turns INTEGER NOT NULL DEFAULT 0,
    tools_used TEXT[] NOT NULL DEFAULT '{}',
    files_touched TEXT[] NOT NULL DEFAULT '{}',
    outcome TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (report_date, username, session_id)
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    id BIGSERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    week_end DATE NOT NULL,
    week_label TEXT NOT NULL,
    username TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    total_sessions INTEGER NOT NULL DEFAULT 0,
    total_turns INTEGER NOT NULL DEFAULT 0,
    top_topics TEXT[] NOT NULL DEFAULT '{}',
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (week_label, username)
);

CREATE TABLE IF NOT EXISTS monthly_reports (
    id BIGSERIAL PRIMARY KEY,
    month_label TEXT NOT NULL,
    username TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    total_sessions INTEGER NOT NULL DEFAULT 0,
    total_turns INTEGER NOT NULL DEFAULT 0,
    top_topics TEXT[] NOT NULL DEFAULT '{}',
    raw_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (month_label, username)
);

CREATE INDEX IF NOT EXISTS idx_daily_reports_date ON daily_reports (report_date);
CREATE INDEX IF NOT EXISTS idx_daily_reports_username ON daily_reports (username);
CREATE INDEX IF NOT EXISTS idx_sessions_report_date ON sessions (report_date);
CREATE INDEX IF NOT EXISTS idx_weekly_reports_week_label ON weekly_reports (week_label);
CREATE INDEX IF NOT EXISTS idx_monthly_reports_month_label ON monthly_reports (month_label);
"""


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="初始化 PostgreSQL 表结构")
    parser.add_argument(
        "--create-db",
        action="store_true",
        help="若数据库不存在则自动创建",
    )
    return parser.parse_args()


def ensure_database() -> None:
    """创建目标数据库（若不存在）。"""
    settings = db_settings()
    dbname = str(settings["dbname"])
    conn = psycopg2.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        dbname="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            exists = cur.fetchone()
            if not exists:
                cur.execute(f'CREATE DATABASE "{dbname}"')
                print(f"已创建数据库: {dbname}")
            else:
                print(f"数据库已存在: {dbname}")
    finally:
        conn.close()


def ensure_tables() -> None:
    """创建业务表。"""
    with db_cursor() as cur:
        cur.execute(TABLE_DDL)
    print("表结构初始化完成。")


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    if args.create_db:
        ensure_database()
    ensure_tables()


if __name__ == "__main__":
    main()
