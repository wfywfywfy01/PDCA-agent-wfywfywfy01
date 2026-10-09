# 后端切换到 main 的切换手册（2026-10-09 核验版）

> 目标：把生产后端从 `codex/mto-fix @ 11f1e82` 切到 `main @ 1a791fd`，让 `/api/omega/*`、
> `/api/duzhan-agents` 等 main 已具备的能力上线。**前端已在 2026-10-09 用本分支构建并部署。**

## 一、核验结论（已实测，非推断）

| 项 | 结论 | 证据 |
| --- | --- | --- |
| 生产数据库版本 | **已在 `018`（main 的 head）**，无需再跑迁移 | 生产 checkout 只有 001–013，`alembic current` 报 "Can't locate revision '018'" → 库比代码新 |
| main 后端可导入 | ✔ 生产 `.env` + main 代码导入无异常 | 打印到 **27 条** `/api/omega/*`、`/api/duzhan-agents*` 路由 |
| 端到端可用 | ✔ 临时实例（8768，调度器关闭）14 条路由全过 | `/omega` 显示真实任务与卡点；`/admin/duzhan-agents` 返回 403 权限不足（此前为 404）；`/admin/agents` 显示 11 个机器人 |
| 备份 | ✔ 切换前已留最新原生备份 | `pdca-workbench/data/backups/native_20261009_092830.dump`（custom 格式，489 KB） |

## 二、切换前必须先处理的事（**唯一阻塞项**）

生产 checkout `D:\经销商PDCA` 有 **64 个未提交改动**，其中 13 个文件的内容与 main 不一致
（其余 51 个为 apps/web，即本次前端发布内容，已在 main 分支中就绪）：

| 文件 | 生产独有行 | 说明 |
| --- | --- | --- |
| `pdca-workbench/app/duzhan.py` | 24 | 本地热修（`groups_for_tz`/`prepare_duzhan` 等） |
| `pdca-workbench/app/scheduler/jobs.py` | 17 | 本地热修（duzhan/ctob 任务封装） |
| `pdca-workbench/app/wa_strategies.json` | 15 | **运行时数据**（UI 写入的策略） |
| `pdca-workbench/app/strategy_wa_brief.py` | 14 | 本地热修 |
| `pdca-workbench/tests/test_strategy_wa_brief.py` | 12 | 测试 |
| `pdca-workbench/app/config.py` | 3 | 本地开关（`daily_report_enabled` 等） |
| `pdca-workbench/app/ctob.py`、`scripts/deploy_remote_docker.ps1` | 各 3 | 本地热修 |
| `.gitignore`、`AGENTS.md` | — | 仓库配置 |
| `app/monthly_sales_targets.json`、`app/im_files.py`、`Dockerfile`、`tests/test_daily_report.py` 等 | 0 | main 已是超集，可安全取 main |

**处理方式（二选一，由 owner 决定）**：
1. 先把这些热修提交到 `codex/mto-fix`（推荐，之后切换无损失）；
2. 或切换时按上表把 13 个文件原样拷回（脚本见下），运行数据文件（`wa_strategies.json`）必须保留。

## 三、切换步骤（保留热修版）

```powershell
$PROD = "D:\经销商PDCA"; $KEEP = "C:\Windows\Temp\pdca-backend-keep"
New-Item -ItemType Directory -Force $KEEP | Out-Null
# 0) 备份：数据库 + 未提交文件
python "$PROD\scripts\pg_native_backup.py"
git -C $PROD stash push -u -m "pre-main-cutover"   # 或先 commit 到 codex/mto-fix
# 1) 把待保留文件拷出来
$files = @("pdca-workbench/app/duzhan.py","pdca-workbench/app/scheduler/jobs.py",
  "pdca-workbench/app/wa_strategies.json","pdca-workbench/app/strategy_wa_brief.py",
  "pdca-workbench/app/config.py","pdca-workbench/app/ctob.py","pdca-workbench/app/im_files.py",
  "pdca-workbench/app/monthly_sales_targets.json","pdca-workbench/tests/test_strategy_wa_brief.py",
  "pdca-workbench/scripts/deploy_remote_docker.ps1",".gitignore","AGENTS.md")
foreach ($f in $files) { $d = Join-Path $KEEP $f; New-Item -ItemType Directory -Force (Split-Path $d) | Out-Null; Copy-Item (Join-Path $PROD $f) $d -Force }
# 2) 代码切到 main
git -C $PROD fetch origin main; git -C $PROD checkout main; git -C $PROD pull --ff-only
# 3) 回填热修与运行数据
foreach ($f in $files) { Copy-Item (Join-Path $KEEP $f) (Join-Path $PROD $f) -Force }
# 4) 先关调度器启动，观察一轮
$env:PDCA_SCHEDULER_ENABLED = "0"
& "$PROD\pdca-workbench\start.bat"    # 监听 8767
```

## 四、验证清单

```powershell
curl.exe -s http://127.0.0.1:8767/health           # status=ok, database_connected=true
curl.exe -s -o NUL -w "%{http_code}\n" http://127.0.0.1:8767/api/omega/status        # 200（此前 404）
curl.exe -s -o NUL -w "%{http_code}\n" http://127.0.0.1:8767/api/duzhan-agents       # 200/403（此前 404）
```

浏览器再走一遍 14 条路由（`/app/*`）：无溢出、无旧表格类名、无 5xx。

## 五、回滚

```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8767 -State Listen).OwningProcess -Force
git -C D:\经销商PDCA checkout codex/mto-fix
git -C D:\经销商PDCA stash pop            # 若步骤 0 用了 stash
& D:\经销商PDCA\pdca-workbench\start.bat
```
数据库无需回滚（迁移未执行、schema 未变）。

## 六、调度器副作用（务必留意）

`.env` 里 `PDCA_DUZHAN_ENABLED=1`、`PDCA_OMEGA_ENABLED=1`、`PDCA_DUZHAN_TIMES=10:00,15:00,20:00`；
main 的调度器比旧 checkout 多了 omega/督战相关任务。**切换不要在 10:00 / 15:00 / 20:00 前后 15 分钟内做**，
否则可能出现重复推送；首次启动建议保持 `PDCA_SCHEDULER_ENABLED=0` 观察一轮再放开。

## 七、本次核验用的临时实例（可复现）

```powershell
# 在分支工作树里：复制生产 .env（.gitignore 已忽略），起 8768，关调度器，验完即杀
copy D:\经销商PDCA\pdca-workbench\.env D:\经销商PDCA\.worktrees\agent-admin-console\pdca-workbench\.env
cd D:\经销商PDCA\.worktrees\agent-admin-console\pdca-workbench
$env:PDCA_WORKBENCH_PORT="8768"; $env:PDCA_HOST="127.0.0.1"; $env:PDCA_SCHEDULER_ENABLED="0"; python run.py
```
