# Runbook

## Routine checks

- PDCA `/health` and data-hub `/health/ready` return `200`.
- `/metrics` is scraped from the private network.
- Sales users see only assigned dealers; out-of-scope requests fail closed.
- Search results include source file, version, and page or media timestamp.
- Sales original export returns `403`; admin export requires a reason and creates an audit event.
- PostgreSQL backups run daily and a disposable restore drill runs monthly.

## Incident

1. Stop the failing import, worker, or release.
2. Record commit, request ID, actor, time window, affected dealer, and row/asset counts.
3. Preserve failed inputs and logs outside Git.
4. Roll back the app or restore/rerun the idempotent data pipeline.
5. Add a regression test and update `PROGRESS.md`.
## 数据库可用性（2026-09-20 起）

生产库在远端 10.100.0.176（PostgreSQL 18 + Caddy/Docker 宿主），出现过“TCP 可连但服务冻结”的整机不可用。当前防护：

- PDCA-DBGuard（每 5 分钟，scripts/db_guard.ps1）：协议层探测数据库与 /health；故障与恢复仅在状态变化时推送 IM 告警；数据库恢复而工作台未起来时自动拉起并复验。日志 pdca-workbench/data/logs/db_guard.log，状态 pdca-workbench/data/runtime/db_guard_state.json。
- PDCA-LogicalBackup（每日 06:30，scripts/pg_logical_backup.py）：用 psycopg2 逐表导出 gzip JSONL 到 pdca-workbench/data/backups/，保留 14 份，不依赖 pg_dump 版本（本机 pg_dump 16.9 与服务端 18.4 不匹配，应用内置 pg_dump 备份因此长期失败）。
- 手工核验：powershell -NoProfile -ExecutionPolicy Bypass -File scripts\db_guard.ps1；python scripts\pg_logical_backup.py --workbench-root <workbench 目录>（需数据库在线）。

注意：生产环境数据库不可用时不要重启工作台——bootstrap_database() 会因“生产环境 PostgreSQL 不可用”直接中止启动；正确顺序是等数据库恢复后再拉起（守护脚本已自动处理）。详见 docs/INCIDENT_2026-09-20-db-outage.md。
