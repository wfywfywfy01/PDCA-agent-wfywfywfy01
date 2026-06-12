# -*- coding: utf-8 -*-
"""一次性迁移 username 大小写。"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from db_config import db_cursor

with db_cursor() as cur:
    for table in ("daily_reports", "sessions", "weekly_reports", "monthly_reports"):
        cur.execute(
            f"UPDATE {table} SET username = %s WHERE username = %s",
            ("Frank", "frank"),
        )
print("username 迁移完成: frank -> Frank")
