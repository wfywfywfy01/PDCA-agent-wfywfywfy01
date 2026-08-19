# -*- coding: utf-8 -*-
"""
历史经销商业绩导入器（P1③）：data_raw/*.json → dealer_sales 表。

语义约定：
- data_raw/dealer_sales_month_to_date_*.json 是【月累计（MTD）】快照，
  同一月多份文件互相重叠，直接全导会重复计数。因此【每月只取最新一份】，
  以该文件截止日期作为 check_date（与月度聚合 startswith(month) 兼容）。
- 当前月默认跳过：其数据由 06:30/20:00 实时同步（sync_dealer_sales_from_vps）
  持续维护，导入器不与实时链路抢写。
- 幂等：按 (check_date, dealer_name) upsert；重跑安全。

用法（生产库谨慎，先 dry-run）：
    python scripts/import_history_dealer_sales.py --dry-run
    python scripts/import_history_dealer_sales.py
    python scripts/import_history_dealer_sales.py --include-current-month
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_ROOT = SCRIPT_DIR.parent
REPO_ROOT = WORKBENCH_ROOT.parent

if str(WORKBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_ROOT))

from app.database import bootstrap_database, get_engine  # noqa: E402
from app.models.dealer_sales import DealerSales  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

_FILE_RE = re.compile(r"dealer_sales_month_to_date_(?P<start>\d{4}-\d{2}-\d{2})"
                      r"(?:_to_(?P<end>\d{4}-\d{2}-\d{2}))?\.json$")


def _extract_rows(payload) -> list[dict]:
    """兼容三类历史结构：ps1（execution.result）、旧 sandbox 生产者
    （result.execution.result）、以及平铺的 dealers/rows。"""
    if not isinstance(payload, dict):
        return []
    candidates: list = []
    execution = payload.get("execution")
    if isinstance(execution, dict):
        candidates.append(execution.get("result"))
    result = payload.get("result")
    if isinstance(result, dict):
        inner = result.get("execution")
        if isinstance(inner, dict):
            candidates.append(inner.get("result"))
        candidates.append(result)
    candidates.append(payload)
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        rows = cand.get("customer_summary") or cand.get("dealers") or cand.get("rows")
        if rows:
            return [row for row in rows if isinstance(row, dict)]
    return []


def _row_parts(row: dict) -> tuple[str, float, int]:
    name = str(
        row.get("partner_name")
        or row.get("dealer_name")
        or row.get("dealer")
        or row.get("name")
        or ""
    ).strip()
    performance = float(row.get("performance") or row.get("sell_in_yuan") or row.get("amount") or 0)
    quantity = int(row.get("quantity") or row.get("qty") or 0)
    return name, performance, quantity


def _file_month(path: Path) -> tuple[str, str]:
    """返回 (截止日期, 月份)。文件名缺截止日期时退化为起始日期。"""
    match = _FILE_RE.match(path.name)
    if not match:
        return "", ""
    end = match.group("end") or match.group("start")
    return end, end[:7]


def discover_monthly_snapshots(data_raw: Path) -> dict[str, Path]:
    """每月一份快照：{month: path}。

    MTD 文件同月互相重叠，只取一份；**优先选有业绩行的最新文件**——
    空转期（如 2026-07-14 起 455 字节空文件）的空壳不得遮蔽此前有数据的
    快照（如 07-14 的 30KB 旧生产者文件）。
    """
    snapshots: dict[str, tuple[bool, float, Path]] = {}
    for path in data_raw.glob("dealer_sales_month_to_date_*.json"):
        if "params" in path.name or not _FILE_RE.match(path.name):
            continue
        end, month = _file_month(path)
        if not month:
            continue
        has_rows = False
        try:
            has_rows = bool(_extract_rows(json.loads(path.read_text(encoding="utf-8-sig"))))
        except (json.JSONDecodeError, OSError):
            pass
        mtime = path.stat().st_mtime
        current = snapshots.get(month)
        # 排序键：(有数据, mtime)；有数据的文件永远优先于空文件
        if current is None or (has_rows, mtime) > (current[0], current[1]):
            snapshots[month] = (has_rows, mtime, path)
    return {month: value[2] for month, value in snapshots.items()}


def import_snapshot(path: Path, session: Session) -> int:
    """导入单月快照；返回写入/更新行数。"""
    end, _month = _file_month(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        print(f"  [skip] 无法解析: {path.name}")
        return 0
    rows = _extract_rows(payload)
    if not rows:
        print(f"  [skip] 无业绩行（空文件?）: {path.name}")
        return 0

    existing = session.exec(
        select(DealerSales).where(DealerSales.check_date == end)
    ).all()
    existing_map = {row.dealer_name: row for row in existing}
    count = 0
    for row in rows:
        name, performance, quantity = _row_parts(row)
        if not name or (performance <= 0 and quantity <= 0):
            continue
        sell_in_wan = round(performance / 10000, 4)
        item = existing_map.get(name)
        if item:
            item.sell_in_wan = sell_in_wan
            item.units = quantity
            item.source_file = path.name
            item.synced_at = datetime.utcnow()
            session.add(item)
        else:
            session.add(
                DealerSales(
                    check_date=end,
                    dealer_name=name,
                    sell_in_wan=sell_in_wan,
                    sell_out_wan=0.0,
                    units=quantity,
                    phone_qty=quantity,
                    activation_rate=0.0,
                    source_file=path.name,
                )
            )
        count += 1
    session.commit()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="历史经销商业绩导入（data_raw → dealer_sales）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将导入的内容，不写库")
    parser.add_argument("--include-current-month", action="store_true",
                        help="包含当前月（默认跳过，当前月由实时同步维护）")
    parser.add_argument("--data-raw", default="", help="data_raw 目录（默认仓库根 data_raw）")
    args = parser.parse_args()

    data_raw = Path(args.data_raw) if args.data_raw else REPO_ROOT / "data_raw"
    if not data_raw.is_dir():
        print(f"data_raw 目录不存在: {data_raw}")
        return 1

    snapshots = discover_monthly_snapshots(data_raw)
    current_month = date.today().strftime("%Y-%m")
    if not args.include_current_month:
        snapshots = {m: p for m, p in snapshots.items() if m != current_month}

    print(f"发现 {len(snapshots)} 个历史月快照（data_raw={data_raw}）")
    for month in sorted(snapshots):
        print(f"  {month}: {snapshots[month].name}")

    if args.dry_run:
        print("\n[dry-run] 未写入数据库。")
        return 0

    bootstrap_database()
    total = 0
    with Session(get_engine()) as session:
        for month in sorted(snapshots):
            path = snapshots[month]
            print(f"[import] {month} <- {path.name}")
            try:
                count = import_snapshot(path, session)
            except Exception as exc:  # noqa: BLE001 — 单月失败不阻断其余月份
                print(f"  [error] {exc}")
                session.rollback()
                continue
            print(f"  [ok] {count} 行")
            total += count
    print(f"\n导入完成：共 {total} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
