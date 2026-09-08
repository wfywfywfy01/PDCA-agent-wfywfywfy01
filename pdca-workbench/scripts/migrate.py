# -*- coding: utf-8 -*-
"""显式、可重复的部署前数据库迁移入口。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.database import get_engine, init_db


def main() -> int:
    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    config = Config(str(ROOT / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))

    if "alembic_version" not in tables and tables:
        # 历史生产库先用当前幂等补丁补齐，再建立正式迁移基线。
        init_db()
        command.stamp(config, "head")
        print("历史数据库已补齐并标记到 Alembic head")
        return 0

    command.upgrade(config, "head")
    # 过渡期补齐尚未被早期迁移覆盖的模型表；后续迁移只走 Alembic。
    init_db(apply_patches=False)
    print("数据库迁移完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
