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

### 2026-09-24 补充：三种"看起来不一样、其实是同一个坑"的表现

同一天实测，push 失败会伪装成下面几种样子，别被带偏：

| 看到的报错 | 其实是什么 |
| --- | --- |
| `fatal: unable to access ...: getaddrinfo() thread failed to start` | 连接阶段就挂了，不是解析器坏了 |
| `TLS connect error: error:00000000:lib(0)::reason(0)` / `SSL_ERROR_SYSCALL`（卡约 20 秒） | 命中不可达 IP，TLS ClientHello 发出去没有回应 |
| **exit 128 且一行日志都没有** | 多半是凭据助手没跑起来（见下节），git 把子进程的失败吞掉了 |

**关键**：读操作（`ls-remote` / `fetch`）可能成功而 push 失败 —— DNS 每次返回的 IP 可能不同，
读到的是可达 IP、写撞上不可达 IP。所以"能 fetch 就说明网络没问题"是错的：**写操作一律先挂代理试**。

**抓不到报错时**：用 `ProcessStartInfo` 把 git 输出接到管道里会丢（实测 stdout/stderr 全空），
改成批处理落盘 + 打开跟踪：

```bat
set GIT_TRACE=1
set GIT_CURL_VERBOSE=1
cd /d <工作树>
git push -u origin HEAD 1> out.txt 2> err.txt
```

`err.txt` 里能看到 `Trying <ip>:443` → `TLS Client hello` → 超时，一眼定位。

### 凭据助手路径写坏会静默失败（2026-09-24 实测并修复）

`gh auth setup-git` 写进 `~/.gitconfig` 的是单引号包路径：

```ini
[credential "https://github.com"]
	helper =
	helper = !'C:\Program Files\GitHub CLI\gh.exe' auth git-credential
```

**坑**：单引号内 git 不做转义，一旦路径被写成 `C:\\Program Files\\...`（双反斜杠），
`\\` 会原样交给 sh，"可执行文件路径"就不存在了 → 助手静默不返回凭据 →
push 直接 exit 128、**没有任何输出**。修法：路径改成正斜杠
（`C:/Program Files/GitHub CLI/gh.exe`），改完用

```powershell
git credential fill    # 依次输入 protocol=https / host=github.com / 空行
```

验证能返回 `username=` 和 `password=`（40 位）即可。改前先备份 `~/.gitconfig`。

**还要确认账号对不对**：`gh` 助手返回的是**当前激活账号**的凭据。若该账号对目标仓库没有写权限，
push 会**又一次静默 128**（没有任何 remote 报错）。用 `gh auth status` 看激活账号，
必要时 `gh auth switch`，或直接用下面的应急推法指定有权限的账号。

### 助手暂时修不了时的应急推法（不改任何配置）

把 token 当成一次性 HTTP 头，绕开凭据助手：

```powershell
$token = gh auth token            # 只进内存，不要打印
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("x-access-token:$token"))
git -c http.proxy=http://127.0.0.1:8899 -c credential.helper= `
    -c "http.https://github.com/.extraHeader=Authorization: Basic $b64" `
    push -u origin HEAD
```

用完自检：代理进程已杀、8899 端口没有监听、临时凭据文件已删、`git` 进程无残留。
