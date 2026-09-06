# -*- coding: utf-8 -*-
"""Synchronize the approved dealer-to-sales permission matrix.

Dry-run by default. Use ``--apply`` only after reviewing the summary.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth.models import User
from app.auth.scope import sync_user_dealer_assignments
from app.auth.security import hash_password
from app.database import bootstrap_database, get_engine
from app.models.audit_log import AuditLog
from app.models.dealer_store import DealerStore


@dataclass(frozen=True)
class MatrixRow:
    dealer: str
    country: str
    source: str
    status: str
    sales: str


MATRIX = (
    MatrixRow("AI-SARAF CO", "伊拉克", "", "停止", "Lina"),
    MatrixRow("Behzadi Boutique", "伊拉克", "继承丁菘自拓", "停止", "Lina"),
    MatrixRow("Billionaire Collections", "阿联酋", "继承自拓", "存续", "Lina"),
    MatrixRow("CLICK TECH SERVICES", "卡塔尔", "C转B", "未提货", "尤文静"),
    MatrixRow("Dar Al Sabaek", "科威特", "Distributor邮箱", "存续", "尤文静"),
    MatrixRow("HASSIB ABDALLAH AMIR ALLAH", "伊拉克", "", "未提货", "Lina"),
    MatrixRow("Luxem Store", "伊朗", "继承李寅柳客户", "存续", "Lina"),
    MatrixRow("Mkateb for e-commerce", "约旦", "Distributor邮箱", "停止", "Lina"),
    MatrixRow("My Shops Electronics Trading LLC", "阿塞拜疆", "C转B", "存续", "Lina"),
    MatrixRow("Rashid lukman rashid", "伊拉克", "自拓", "停止", "Lina"),
    MatrixRow("Safiranhamrah", "伊朗", "继承王珊自拓", "存续", "尤文静"),
    MatrixRow("TİVALİ Commercial Broker LLC", "伊朗", "C转B", "存续", "Lina"),
    MatrixRow("Veysel Sevis Ltd", "土耳其", "C转B", "停止", "Lina"),
    MatrixRow("Bestcom", "乌克兰", "自拓", "停止", "Lina"),
    MatrixRow("FRONTANA GIDA DIS TICARET LIMITED", "乌克兰", "转介绍", "停止", "Lina"),
    MatrixRow("IQ-QUEST SP. Z O.O.", "波兰", "客户主动咨询", "停止", "Lina"),
    MatrixRow("Optimizers d.o.o.", "斯洛文尼亚", "继承马文娜自拓", "停止", "Lina"),
    MatrixRow("Robo Trading Ltd", "保加利亚", "继承张晏培自拓", "停止", "Lina"),
    MatrixRow("VERTU LONDON LTD", "英国", "投流获客", "存续", "Lina"),
    MatrixRow("vipconnect.de", "德国", "C转B", "停止", "Lina"),
    MatrixRow("Quantum Reserve", "瑞士", "PR转", "未提货", "尤文静"),
    MatrixRow("GURU ELECTRONICS SINGAPORE PTE LTD", "印度", "继承自拓", "存续", "杨晶晶"),
    MatrixRow("LZB INDIA ELECTRIC PRIVATE LIMITED-高山", "印度", "转介绍", "未提货", "杨晶晶"),
    MatrixRow("Sidd Senthil", "印度", "C转B", "存续", "何海文"),
    MatrixRow("Parth Kamlesh Doshi", "印度", "C转B", "存续", "何海文"),
    MatrixRow("Sun International General Trading", "印度", "自拓", "停止", "杨晶晶"),
    MatrixRow("BIN BIN INVESTMENT(CAMBODIA) COLTD", "柬埔寨", "继承刘圣自拓", "存续", "于冰"),
    MatrixRow("VMG Communication and Technology Joint Stock Company", "越南", "询盘", "存续", "于冰"),
    MatrixRow("VST ECS (Thailand) Co., Ltd.", "泰国", "自拓", "存续", "于冰"),
    MatrixRow("Zmc automotive Pte Ltd", "新加坡", "继承Jason自拓", "停止", "于冰"),
    MatrixRow("Altyn Zaman H.J.", "土库曼斯坦", "询盘", "停止", "杨晶晶"),
    MatrixRow("Bizcon Group", "乌兹别克斯坦", "询盘", "存续", "杨晶晶"),
    MatrixRow("CONTINENTAL PLUS LLC.——已拉黑", "俄罗斯", "自拓", "停止", "杨晶晶"),
    MatrixRow("LLC “TC Azimut”", "俄罗斯", "老代理客户转介绍", "存续", "杨晶晶"),
    MatrixRow("LYZHINA OLGA", "哈萨克斯坦", "自拓", "停止", "杨晶晶"),
    MatrixRow("reStore", "俄罗斯", "自拓", "存续", "杨晶晶"),
    MatrixRow('ТОО "VERTU AZIA KZ"', "哈萨克斯坦", "", "停止", "杨晶晶"),
    MatrixRow("ECN GmbH", "瑞典", "", "停止", "Lina"),
    MatrixRow("Yuemmai", "泰国", "老代理二级", "存续", "于冰"),
    MatrixRow("CAT NG", "", "", "", "Lina"),
    MatrixRow("Chandan Jain", "", "", "", "马文娜"),
    MatrixRow("Francesco Fico", "", "", "", "张晏培"),
    MatrixRow("Gavin Foo", "", "", "", "Lina"),
    MatrixRow("Kamal Preet Singh", "", "", "", "吴佳军"),
    MatrixRow("KICKmobiles", "", "", "", "马文娜"),
    MatrixRow("LI MINGBIN 894831", "", "", "", "Lina"),
    MatrixRow("meisam khosravi", "", "", "", "Lina"),
    MatrixRow("Mohammad reza Abrishamchi", "", "", "", "马文娜"),
    MatrixRow("Rani Saidi", "", "", "", "Lina"),
    MatrixRow("Rybakov Denis Valerevich", "", "", "", "Lina"),
    MatrixRow("Sat Singh", "", "", "", "马文娜"),
    MatrixRow("Soknida Them", "", "", "", "马文娜"),
    MatrixRow("XIE FUKANG", "", "", "", "刘圣"),
    MatrixRow("Ivo Krastev", "", "", "", "马文娜"),
    MatrixRow("Keo Chamreun", "", "", "", "于冰"),
    MatrixRow("Ms. Linh", "", "", "", "于冰"),
    MatrixRow("Cuprum Management BV", "", "", "", "Safae"),
    MatrixRow("GUPTA KANISHA", "", "", "", "杨晶晶"),
    MatrixRow("Safin Ahmed lssa", "", "", "", "Safae"),
    MatrixRow("SASCO GLOBAL LOGISTICS FZCO", "", "", "", "何海文"),
    MatrixRow("Taher Jasem", "", "", "", "尤文静"),
    MatrixRow("UNDO WORLD PRIVATE LIMITED", "", "", "", "杨晶晶"),
    MatrixRow("天津市蓟州区拓晖电子产品经营商行", "", "", "", "杨晶晶"),
    MatrixRow("Pier Boakye", "", "", "", ""),
    MatrixRow("Rafal Jedlinski", "", "", "", ""),
)

# Matrix sales label: (username, immutable owner key).
OWNER_ACCOUNTS = {
    "Lina": ("lina", "Lina"),
    "尤文静": ("viki", "Viki"),
    "杨晶晶": ("yangjingjing", "April"),
    "何海文": ("hehaiwen", "Haiwen"),
    "于冰": ("yubing", "Ivan"),
    "Safae": ("safae", "Safae"),
}

# These salespeople have no PDCA login account yet.  Their customers remain
# in the centrally managed pool until an account is explicitly provisioned.
PUBLIC_POOL_SALES = {"马文娜", "张晏培", "吴佳军", "刘圣"}
PUBLIC_POOL_OWNER_KEY = "中台公共池"

# Approved exact aliases and multi-store dealer groups. No fuzzy authorization matching.
STORE_TARGETS = {
    "Rashid lukman rashid": ("me010",),
    "Safiranhamrah": ("me011",),
    "TİVALİ Commercial Broker LLC": ("me012",),
    "LZB INDIA ELECTRIC PRIVATE LIMITED-高山": ("sa002",),
    "BIN BIN INVESTMENT(CAMBODIA) COLTD": ("sea01",),
    "VMG Communication and Technology Joint Stock Company": ("sea02", "sea02a", "sea02b", "sea02c", "sea02d"),
    "VST ECS (Thailand) Co., Ltd.": ("sea03",),
    "CONTINENTAL PLUS LLC.——已拉黑": ("ca003",),
    "LLC “TC Azimut”": ("ca004",),
    "reStore": ("ca006", "ca007", "ca008", "ca009", "ca010", "ca011"),
    "Taher Jasem": ("me017",),
}

KNOWLEDGE_IDS = {
    "me005": "4a4d7fac-4402-44b4-9dfe-704613d4ec5a",
    "me011": "43838f2c-ed24-4da9-9963-a292a89b99e3",
    "sea01": "635576a3-844c-497f-bee9-58995fb7706e",
    "sea02": "02ec6588-a9ad-4d5c-ae94-8ac91ad12c5d",
    "sea02a": "02ec6588-a9ad-4d5c-ae94-8ac91ad12c5d",
    "sea02b": "02ec6588-a9ad-4d5c-ae94-8ac91ad12c5d",
    "sea02c": "02ec6588-a9ad-4d5c-ae94-8ac91ad12c5d",
    "sea02d": "02ec6588-a9ad-4d5c-ae94-8ac91ad12c5d",
    "sea03": "eb001b29-4cf9-4a40-88a3-58e6b4ec9298",
}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for char in text if char.isalnum())


def generated_store_id(name: str) -> str:
    return "master-" + hashlib.sha256(normalize(name).encode("utf-8")).hexdigest()[:12]


def sync_matrix(session: Session, *, actor: str = "frank") -> dict:
    stores = list(session.exec(select(DealerStore)).all())
    by_id = {store.store_id: store for store in stores}
    by_name = {normalize(store.name): store for store in stores}
    summary = {"created_stores": 0, "updated_stores": 0, "created_users": 0, "assignments": 0}

    for row in MATRIX:
        target_ids = STORE_TARGETS.get(row.dealer)
        if target_ids:
            targets = [by_id[store_id] for store_id in target_ids if store_id in by_id]
            if len(targets) != len(target_ids):
                missing = sorted(set(target_ids) - set(by_id))
                raise RuntimeError(f"Missing approved store targets for {row.dealer}: {missing}")
        else:
            existing = by_name.get(normalize(row.dealer))
            if existing:
                targets = [existing]
            else:
                store_id = generated_store_id(row.dealer)
                if store_id in by_id:
                    raise RuntimeError(f"Generated store_id collision: {store_id}")
                existing = DealerStore(
                    store_id=store_id,
                    name=row.dealer,
                    country=row.country,
                    sales_owner="",
                    team_key="overseas",
                    is_active=True,
                    sort_order=900,
                )
                session.add(existing)
                by_id[store_id] = existing
                by_name[normalize(row.dealer)] = existing
                targets = [existing]
                summary["created_stores"] += 1

        owner_key = (
            PUBLIC_POOL_OWNER_KEY if row.sales in PUBLIC_POOL_SALES
            else OWNER_ACCOUNTS[row.sales][1] if row.sales else ""
        )
        for store in targets:
            before = (store.country, store.sales_owner, store.team_key, store.knowledge_dealer_id)
            if row.country:
                store.country = row.country
            store.sales_owner = owner_key
            store.team_key = "overseas"
            if store.store_id in KNOWLEDGE_IDS:
                store.knowledge_dealer_id = KNOWLEDGE_IDS[store.store_id]
            session.add(store)
            after = (store.country, store.sales_owner, store.team_key, store.knowledge_dealer_id)
            summary["updated_stores"] += before != after

    users = {user.username: user for user in session.exec(select(User)).all()}
    managed_users: list[User] = []
    for sales_label, (username, owner_key) in OWNER_ACCOUNTS.items():
        user = users.get(username)
        if user is None:
            user = User(
                username=username,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                role="sales",
                display_name=sales_label,
                sales_name=sales_label,
                owner_key=owner_key,
                team_key="overseas",
                data_scope="self",
                is_active=True,
                must_change_password=True,
            )
            session.add(user)
            summary["created_users"] += 1
        else:
            user.role = "sales"
            user.owner_key = owner_key
            user.team_key = "overseas"
            user.data_scope = "self"
            session.add(user)
        managed_users.append(user)

    session.flush()
    for user in managed_users:
        summary["assignments"] += len(sync_user_dealer_assignments(user, session))

    session.add(AuditLog(
        username=actor,
        action="sync_dealer_permissions",
        resource="approved-sales-matrix-2026-09-03",
        detail=json.dumps(summary, ensure_ascii=False),
    ))
    session.flush()
    return summary


def main(*, apply: bool = False) -> None:
    bootstrap_database()
    with Session(get_engine()) as session:
        summary = sync_matrix(session)
        if apply:
            session.commit()
        else:
            session.rollback()
        print(json.dumps({"mode": "apply" if apply else "dry-run", **summary}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync approved dealer sales permissions")
    parser.add_argument("--apply", action="store_true", help="write changes; default is dry-run")
    args = parser.parse_args()
    main(apply=args.apply)
