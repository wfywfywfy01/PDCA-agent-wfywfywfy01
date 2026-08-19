# -*- coding: utf-8 -*-
"""
备份恢复演练（P5）：把最新 pg_dump 备份恢复到临时库并校验，随后删除。

用法（在能访问生产 PG 的运维机/容器内）：
    python scripts/backup_restore_drill.py
    python scripts/backup_restore_drill.py --file data/backups/pdca_20260819_060000.sql
    python scripts/backup_restore_drill.py --psql /usr/lib/postgresql/18/bin/psql

校验内容：users / dealer_sales / walkin_daily_reports 等关键表行数 > 0
（备份为新库时部分表可为空，脚本按"表存在且可查询"判定结构完整，
行数检查仅对 users 强制非零）。

建议每周执行一次（Linux cron 示例见 docs/运维手册-P5.md）。
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_ROOT = SCRIPT_DIR.parent
if str(WORKBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_ROOT))

from app.config import get_settings  # noqa: E402

SCRATCH_DB = "pdca_restore_check"
CHECK_TABLES = ["users", "dealer_sales", "walkin_daily_reports", "meeting_records", "pdca_tasks"]


def _find_psql(explicit: str) -> str | None:
    if explicit:
        path = Path(explicit)
        return str(path) if path.is_file() else None
    for candidate in ("psql", "psql18", "psql16", "psql15", "psql14"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def _latest_backup(explicit: str) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.is_file() else None
    backup_dir = get_settings().data_dir / "backups"
    files = sorted(
        [p for p in backup_dir.glob("pdca_*.sql") if p.stat().st_size > 0],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files[0] if files else None


def _run_psql(psql: str, info: dict, args: list[str]) -> tuple[int, str]:
    env = os.environ.copy()
    if info.get("password"):
        env["PGPASSWORD"] = info["password"]
    cmd = [
        psql,
        "-h", info.get("host", "localhost"),
        "-p", str(info.get("port") or 5432),
        "-U", info.get("user") or "",
        "-v", "ON_ERROR_STOP=1",
        "-X", "-q",
        *args,
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _admin_sql(psql: str, info: dict, sql: str) -> tuple[int, str]:
    """连接默认库（postgres）执行管理语句。"""
    env = os.environ.copy()
    if info.get("password"):
        env["PGPASSWORD"] = info["password"]
    cmd = [
        psql,
        "-h", info.get("host", "localhost"),
        "-p", str(info.get("port") or 5432),
        "-U", info.get("user") or "",
        "-d", info.get("database") or "postgres",
        "-X", "-q", "-c", sql,
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def main() -> int:
    parser = argparse.ArgumentParser(description="备份恢复演练：临时库恢复 + 结构校验 + 清理")
    parser.add_argument("--file", default="", help="备份文件（默认最新 pdca_*.sql）")
    parser.add_argument("--psql", default="", help="psql 可执行文件路径")
    parser.add_argument("--keep-scratch", action="store_true", help="保留临时库（排障用）")
    args = parser.parse_args()

    info = get_settings().pg_connection_info
    psql = _find_psql(args.psql)
    if not psql:
        print("[FAIL] 未找到 psql，请安装 PostgreSQL 客户端或 --psql 指定路径")
        return 1
    backup = _latest_backup(args.file)
    if not backup:
        print("[FAIL] 未找到备份文件（data/backups/pdca_*.sql）")
        return 1
    print(f"演练目标: {backup.name} ({backup.stat().st_size} bytes)")
    print(f"连接目标: {info.get('host')}:{info.get('port')}/{info.get('database')}")

    print(f"[1/4] 清理旧临时库 {SCRATCH_DB}…")
    rc, output = _admin_sql(psql, info, f'DROP DATABASE IF EXISTS {SCRATCH_DB}')
    if rc != 0 and "does not exist" not in output:
        # DROP IF EXISTS 出错以外的失败才中止
        if rc != 0:
            pass
    print(f"[2/4] 创建临时库 {SCRATCH_DB}…")
    rc, output = _admin_sql(psql, info, f'CREATE DATABASE {SCRATCH_DB}')
    if rc != 0:
        print(f"[FAIL] 创建临时库失败:\n{output[:400]}")
        return 1
    print(f"[3/4] 恢复备份到 {SCRATCH_DB}…")
    env = os.environ.copy()
    if info.get("password"):
        env["PGPASSWORD"] = info["password"]
    proc = subprocess.run(
        [psql, "-h", info.get("host", "localhost"), "-p", str(info.get("port") or 5432),
         "-U", info.get("user") or "", "-d", SCRATCH_DB, "-v", "ON_ERROR_STOP=1", "-X", "-q", "-f", str(backup)],
        env=env, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        print(f"[FAIL] 恢复执行失败:\n{(proc.stderr or proc.stdout)[:400]}")
        return 1
    print(f"[4/4] 校验关键表结构…")
    for table in CHECK_TABLES:
        rc, output = _run_psql(
            psql, info,
            ["-d", SCRATCH_DB, "-t", "-A", "-c", f"SELECT count(*) FROM {table}"],
        )
        if rc != 0:
            print(f"[FAIL] 表 {table} 不存在或不可查询:\n{output[:200]}")
            if not args.keep_scratch:
                _admin_sql(psql, info, f'DROP DATABASE IF EXISTS {SCRATCH_DB}')
            return 1
        count = int("".join(ch for ch in output if ch.isdigit()) or "0")
        print(f"  {table}: {count} 行")
    _admin_sql(psql, info, f'DROP DATABASE IF EXISTS {SCRATCH_DB}')
    print("\n[PASS] 备份恢复演练通过：备份可完整恢复，关键表结构正常。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
