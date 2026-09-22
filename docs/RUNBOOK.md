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

注意：生产环境数据库不可用时不要重启工作台——bootstrap_database() 会因“生产环境 PostgreSQL 不可用”直接中止启动；正确顺序是等数据库恢复后再拉起（守护脚本已自动处理）。详见 docs/INCIDENT_2026-09-20-db-outage.md。- PDCA-NativeBackup（每日 06:15，scripts/pg_native_backup.py）：通过 Docker Engine API 让数据库容器自己执行 pg_dump（版本天然匹配，无需本机安装客户端），再把 dump 取回本机 data/backups/native_*.dump（custom 格式，pg_restore 可直接恢复），保留 14 份。
- 手工核验：python scripts\pg_native_backup.py --workbench-root <workbench 目录>；恢复示例：pg_restore -h <host> -U postgres -d pdca --clean <native_*.dump>。
## GitHub 推送不通时（DNS 解析到不可达 IP）

现象：`git push` 报 `Failed to connect to github.com port 443`，但其它公网站点正常。
原因：网络会把 github.com 解析到一个**不可达**的 IP（2026-09-20 实测：解析结果 20.205.243.166 超时，
而 140.82.112.x~116.x 与 20.27.177.113 均可达），hosts 文件一般没有管理员权限修改。

处理步骤：

1. 起本地隧道代理（自动探测并选中可达 IP，保持 TLS SNI 为 github.com，证书校验正常）：
   ```powershell
   node scripts/gh_tunnel_proxy.cjs            # 默认监听 127.0.0.1:8899
   ```
2. 另开一个终端让 git 走代理（仅在需要时用，不要固化进全局 config）：
   ```powershell
   git -c http.proxy=http://127.0.0.1:8899 push origin <branch>
   git -c http.proxy=http://127.0.0.1:8899 ls-remote origin
   ```
3. `gh`（GitHub CLI）走 api.github.com，通常**可直连**，一般不需要代理；需要时可临时设 `HTTPS_PROXY`。

注意事项：代理是临时工具，用完即停；固化到 `git config --global http.https://github.com/.proxy` 会导致代理未启动时 git 全部失败。
