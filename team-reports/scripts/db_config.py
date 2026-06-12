# -*- coding: utf-8 -*-
"""PostgreSQL 连接与配置。"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import psycopg2
from psycopg2.extensions import connection

from report_io import load_env


def db_settings() -> dict[str, str | int]:
    """读取数据库连接配置。"""
    load_env()
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5432")),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "dbname": os.getenv("DB_NAME", "cursor_team_reports"),
    }


def connect(dbname: str | None = None) -> connection:
    """创建 PostgreSQL 连接。"""
    settings = db_settings()
    if dbname:
        settings = dict(settings)
        settings["dbname"] = dbname
    return psycopg2.connect(**settings)


@contextmanager
def db_cursor(dbname: str | None = None) -> Iterator:
    """提供自动提交/回滚的数据库游标上下文。"""
    conn = connect(dbname=dbname)
    try:
        with conn.cursor() as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
