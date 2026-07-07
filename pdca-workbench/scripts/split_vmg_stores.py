# -*- coding: utf-8 -*-
"""将 sea02 (VMG JSC) 拆分为 4 个门店并创建对应账号。
运行方式（在 pdca-workbench 目录下）：
    python scripts/split_vmg_stores.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.models import User
from app.auth.security import hash_password
from app.config import get_settings
from app.database import bootstrap_database, get_engine
from app.models.dealer_store import DealerStore
from app.models.walkin_daily_report import WalkinDailyReport
from sqlmodel import Session, select

NEW_STORES = [
    ("sea02a", "VMG Communication and Technology JSC · Saigon",    "东南亚", "越南", "L2", "yubing"),
    ("sea02b", "VMG Communication and Technology JSC · Caravelle", "东南亚", "越南", "L2", "yubing"),
    ("sea02c", "VMG Communication and Technology JSC · Majestic",  "东南亚", "越南", "L2", "yubing"),
    ("sea02d", "VMG Communication and Technology JSC · REX",       "东南亚", "越南", "L2", "yubing"),
]


def _password(store_id: str) -> str:
    return f"Vertu{store_id.capitalize()}2024!"


def main(dry_run: bool = False) -> None:
    get_settings()
    bootstrap_database()
    engine = get_engine()

    with Session(engine) as session:
        # 1. 检查 sea02 是否存在
        old = session.exec(select(DealerStore).where(DealerStore.store_id == "sea02")).first()
        if not old:
            print("sea02 不存在，可能已经迁移过了。")
        else:
            print(f"找到旧记录: {old.store_id} - {old.name}")

        # 2. 插入 4 条新门店
        print("\n--- 门店 ---")
        existing_ids = {
            s.store_id for s in session.exec(select(DealerStore)).all()
        }
        for i, (sid, name, region, country, level, owner) in enumerate(NEW_STORES):
            if sid in existing_ids:
                print(f"SKIP  {sid}  {name}")
            else:
                print(f"CREATE {sid}  {name}")
                if not dry_run:
                    session.add(DealerStore(
                        store_id=sid, name=name, region=region,
                        country=country, dealer_level=level,
                        sales_owner=owner, sort_order=100 + i,
                    ))

        if not dry_run:
            session.commit()

        # 3. 删除旧的 sea02 门店（以及对应的 User）
        if old:
            old_user = session.exec(
                select(User).where(User.username == "sea02")
            ).first()
            if old_user:
                print(f"\nDELETE user: sea02 ({old_user.display_name})")
                if not dry_run:
                    session.delete(old_user)
            print(f"DELETE store: sea02")
            if not dry_run:
                session.delete(old)
                session.commit()

        # 4. 为 4 个新门店创建账号
        print("\n--- 账号 ---")
        print(f"{'store_id':<10} {'username':<12} {'password':<28} 状态")
        print("-" * 65)
        for sid, name, *_ in NEW_STORES:
            username = sid
            password = _password(sid)
            existing_user = session.exec(
                select(User).where(User.username == username)
            ).first()
            if existing_user:
                print(f"{sid:<10} {username:<12} {password:<28} SKIP")
            else:
                print(f"{sid:<10} {username:<12} {password:<28} CREATE")
                if not dry_run:
                    session.add(User(
                        username=username,
                        hashed_password=hash_password(password),
                        role="dealer",
                        display_name=name,
                        dealer_id=sid,
                        must_change_password=True,
                        pwd_version=0,
                    ))

        if not dry_run:
            session.commit()
            print("\n完成。")
        else:
            print("\n（--dry-run 模式，未写入数据库）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="拆分 VMG 门店为 4 个独立账号")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
