# -*- coding: utf-8 -*-
"""
客户台账导入器（P3）：teams/*/customers.csv → customer_profiles 表。

- 按 (team, dealer_name) upsert，幂等可重跑；
- 缺失列安全（老 CSV 只有部分列时保持字段默认值）；
- abcd_grade 优先取 CSV 显式列，否则由 priority 推导（S/A→A）；
- 用法：python scripts/import_customers_csv.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_ROOT = SCRIPT_DIR.parent
REPO_ROOT = WORKBENCH_ROOT.parent

if str(WORKBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_ROOT))

from app.database import bootstrap_database, get_engine  # noqa: E402
from app.models.customer_profile import CustomerProfile  # noqa: E402
from sqlmodel import Session, select  # noqa: E402


def priority_to_abcd(priority: str) -> str:
    p = (priority or "").strip().upper()
    if p in ("S", "A"):
        return "A"
    if p in ("B", "C"):
        return p
    return "D"


def _row_value(row: dict, key: str, default: str = "") -> str:
    return (row.get(key) or default or "").strip()


def parse_row(row: dict, team: str) -> dict:
    abcd = _row_value(row, "abcd_grade").upper()
    if not abcd:
        abcd = priority_to_abcd(_row_value(row, "priority"))
    value_raw = _row_value(row, "value_score")
    intent_raw = _row_value(row, "intent_score")
    value_score = int(value_raw) if value_raw.isdigit() else None
    intent_score = int(intent_raw) if intent_raw.isdigit() else None
    return {
        "team": team,
        "dealer_name": _row_value(row, "dealer_name"),
        "dealer_nickname": _row_value(row, "dealer_nickname"),
        "region": _row_value(row, "region"),
        "country": _row_value(row, "country"),
        "owner": _row_value(row, "owner"),
        "priority": _row_value(row, "priority"),
        "status": _row_value(row, "status", "active"),
        "abcd_grade": abcd or "D",
        "value_score": value_score,
        "intent_score": intent_score,
        "lead_source": _row_value(row, "lead_source"),
        "followup_round": _row_value(row, "followup_round", "1"),
        "referral_from": _row_value(row, "referral_from"),
        "last_followup_date": _row_value(row, "last_followup_date"),
        "next_action": _row_value(row, "next_action"),
    }


def discover_csvs(teams_root: Path) -> list[tuple[str, Path]]:
    found = []
    if not teams_root.is_dir():
        return found
    for path in sorted(teams_root.glob("*/customers.csv")):
        found.append((path.parent.name, path))
    return found


def import_team_csv(team: str, path: Path, session: Session) -> int:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    existing = session.exec(
        select(CustomerProfile).where(CustomerProfile.team == team)
    ).all()
    existing_map = {row.dealer_name: row for row in existing if row.dealer_name}
    count = 0
    for raw in rows:
        parsed = parse_row(raw, team)
        name = parsed["dealer_name"]
        if not name:
            continue
        if name in existing_map:
            item = existing_map[name]
            for key, value in parsed.items():
                if key != "dealer_name":
                    setattr(item, key, value)
            item.updated_at = datetime.utcnow()
            session.add(item)
        else:
            session.add(CustomerProfile(**parsed))
            existing_map[name] = None
        count += 1
    session.commit()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="客户台账导入（customers.csv → customer_profiles）")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--teams", default="", help="teams 目录（默认仓库根 teams）")
    args = parser.parse_args()

    teams_root = Path(args.teams) if args.teams else REPO_ROOT / "teams"
    pairs = discover_csvs(teams_root)
    if not pairs:
        print(f"未发现 customers.csv（teams 目录: {teams_root}）")
        return 1
    for team, path in pairs:
        print(f"  {team}: {path}")
    if args.dry_run:
        print("\n[dry-run] 未写入数据库。")
        return 0

    bootstrap_database()
    total = 0
    with Session(get_engine()) as session:
        for team, path in pairs:
            count = import_team_csv(team, path, session)
            print(f"[import] {team}: {count} 行")
            total += count
    print(f"\n导入完成：共 {total} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
