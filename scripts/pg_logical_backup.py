# -*- coding: utf-8 -*-
"""版本无关的 PostgreSQL 逻辑备份。

背景：远端生产库是 PostgreSQL 18，本机 pg_dump 只有 16/12，pg_dump 会直接报
"server version mismatch" 而失败（历史上因此长期没有可用备份）。本脚本用 psycopg2
直连逐表导出为 gzip JSONL，不依赖 pg_dump 版本，任何服务端版本都能跑。

用法：
    python scripts/pg_logical_backup.py [--workbench-root D:\\经销商PDCA\\pdca-workbench] [--keep 14]

产物：<workbench>/data/backups/logical_<UTC时间戳>.jsonl.gz（内含 __manifest__ 记录表名/行数/库版本）
退出码：0 成功；1 失败（便于计划任务告警）
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(r"D:\经销商PDCA\pdca-workbench")


def parse_database_url(workbench_root: Path) -> str:
    """优先环境变量，其次 workbench/.env。"""
    url = os.environ.get("PDCA_DATABASE_URL", "").strip()
    if url:
        return url
    env_file = workbench_root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("PDCA_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return ""


def connect_args(url: str) -> dict:
    match = re.match(r"postgresql(?:\+psycopg2)?://(?P<user>[^:]+):(?P<pass>[^@]+)@(?P<host>[^:/]+):?(?P<port>\d*)/(?P<db>[^?]+)", url)
    if not match:
        raise SystemExit("无法解析 PDCA_DATABASE_URL")
    return {
        "host": match.group("host"),
        "port": int(match.group("port") or 5432),
        "user": match.group("user"),
        "password": match.group("pass"),
        "dbname": match.group("db"),
        "connect_timeout": 10,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="PDCA 逻辑备份（版本无关）")
    parser.add_argument("--workbench-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--keep", type=int, default=14, help="保留最近 N 份")
    args = parser.parse_args()

    workbench_root = Path(args.workbench_root)
    url = parse_database_url(workbench_root)
    if not url:
        print("[backup] 未找到 PDCA_DATABASE_URL", file=sys.stderr)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("[backup] 缺少 psycopg2", file=sys.stderr)
        return 1

    backup_dir = workbench_root / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / ("logical_" + stamp + ".jsonl.gz")

    try:
        conn = psycopg2.connect(**connect_args(url))
    except Exception as exc:  # noqa: BLE001
        print("[backup] 数据库连接失败: " + type(exc).__name__ + ": " + str(exc)[:200], file=sys.stderr)
        return 1

    tables: list[str] = []
    total_rows = 0
    try:
        with conn.cursor() as cur:
            cur.execute("select version()")
            server_version = str(cur.fetchone()[0])
            cur.execute(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_type = 'BASE TABLE' order by table_name"
            )
            tables = [row[0] for row in cur.fetchall()]

            with gzip.open(target, "wt", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "__manifest__": {
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "server_version": server_version,
                        "tables": tables,
                    }
                }, ensure_ascii=False) + "\n")

                for table in tables:
                    cur.execute('select * from "' + table + '"')
                    columns = [desc[0] for desc in cur.description]
                    rows = 0
                    while True:
                        batch = cur.fetchmany(500)
                        if not batch:
                            break
                        for record in batch:
                            payload = {}
                            for key, value in zip(columns, record):
                                if isinstance(value, (datetime,)):
                                    value = value.isoformat()
                                elif isinstance(value, (bytes, bytearray)):
                                    value = value.hex()
                                payload[key] = value
                            fh.write(json.dumps({"table": table, "row": payload}, ensure_ascii=False, default=str) + "\n")
                            rows += 1
                    total_rows += rows
                    fh.write(json.dumps({"__table_done__": table, "rows": rows}, ensure_ascii=False) + "\n")
    finally:
        conn.close()

    size_kb = round(target.stat().st_size / 1024, 1)
    print("[backup] 完成 " + target.name + " 表=" + str(len(tables)) + " 行=" + str(total_rows) + " 大小=" + str(size_kb) + "KB")

    # 保留最近 N 份
    backups = sorted(backup_dir.glob("logical_*.jsonl.gz"))
    for stale in backups[: max(0, len(backups) - args.keep)]:
        stale.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
