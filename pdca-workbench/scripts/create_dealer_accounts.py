# -*- coding: utf-8 -*-
"""批量为所有激活门店创建 dealer 账号。
运行方式：在 pdca-workbench 目录下执行
    python scripts/create_dealer_accounts.py [--dry-run]
每家门店生成一个账号，规则：
  username  = store_id（如 me001、sea02）
  password  = Vertu + store_id 首字母大写 + 2024!（如 VertuMe0012024!）
  role      = dealer
  dealer_id = store_id
  must_change_password = True（首次登录强制改密）
已存在的账号跳过（不覆盖）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 把 pdca-workbench 根目录加入 path，使 app.* 可导入
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.models import User
from app.auth.security import hash_password
from app.config import get_settings
from app.database import bootstrap_database, get_engine
from app.models.dealer_store import DealerStore
from sqlmodel import Session, select


def _default_password(store_id: str) -> str:
    """生成初始密码：Vertu + store_id首字母大写 + 2024!"""
    return f"Vertu{store_id.capitalize()}2024!"


def main(dry_run: bool = False) -> None:
    get_settings()  # 触发 .env 加载
    bootstrap_database()  # 自动选择 PostgreSQL 或 SQLite fallback
    engine = get_engine()

    with Session(engine) as session:
        stores = session.exec(
            select(DealerStore).where(DealerStore.is_active == True)
        ).all()

        if not stores:
            print("未找到任何激活门店，请先运行服务初始化数据库。")
            return

        created, skipped = 0, 0
        print(f"{'DRY-RUN  ' if dry_run else ''}共发现 {len(stores)} 家门店\n")
        print(f"{'store_id':<10} {'name':<45} {'username':<12} {'password':<25} 状态")
        print("-" * 110)

        for store in sorted(stores, key=lambda s: s.store_id):
            username = store.store_id
            password = _default_password(store.store_id)

            existing = session.exec(
                select(User).where(User.username == username)
            ).first()

            if existing:
                skipped += 1
                status = "SKIP (already exists)"
            else:
                status = "CREATE"
                if not dry_run:
                    user = User(
                        username=username,
                        hashed_password=hash_password(password),
                        role="dealer",
                        display_name=store.name,
                        dealer_id=store.store_id,
                        must_change_password=True,
                        pwd_version=0,
                    )
                    session.add(user)
                created += 1

            print(f"{store.store_id:<10} {store.name:<45} {username:<12} {password:<25} {status}")

        if not dry_run and created > 0:
            session.commit()

        print(f"\n{'DRY-RUN  ' if dry_run else ''}结果：新建 {created} 个，跳过 {skipped} 个")
        if dry_run:
            print("（--dry-run 模式，未写入数据库）")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="批量创建经销商账号")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入数据库")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
