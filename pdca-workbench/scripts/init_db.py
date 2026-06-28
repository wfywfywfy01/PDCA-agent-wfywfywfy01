# -*- coding: utf-8 -*-
"""初始化 PostgreSQL 表结构与默认用户。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.seed import seed_users  # noqa: E402
from app.database import check_db_connection, init_db  # noqa: E402
from loguru import logger  # noqa: E402


def main() -> None:
    if not check_db_connection():
        logger.error("无法连接 PostgreSQL，请设置 PDCA_DATABASE_URL 后重试")
        sys.exit(1)
    init_db()
    seed_users()
    logger.info("数据库初始化完成")


if __name__ == "__main__":
    main()
