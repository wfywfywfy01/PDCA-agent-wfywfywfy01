# 代码审查报告 · PDCA 督战系统（2026-09-20）

## 一、结论
1. **没有发现 P0（会立刻造成错误数据/丢消息/泄露密钥）的问题**：密钥扫描（`vbs_`/`sk-`/JWT/私钥）在 git 跟踪文件中零命中，`.env` 已被忽略，运行时产物有清理任务。
2. **P1 集中在三处**：claim 台账的 at-most-once 语义会让“当天失败=当天不再重试”；仓库缺 `.gitignore` 保护（`data/`、`node_modules/`、`dist/` 未忽略，生成物大量入库）；异常吞噬 9 处（含 token 撤销入库失败被静默）。
3. **P2 集中在可维护性与运行编排**：三个核心模块超 1300 行；早 8 点任务扎堆；图片认图串行且时长不可控；前端内联 JS 无 CI 语法校验。

## 二、审查范围与方法
- 范围：`pdca-workbench/` 下 **267 个 Python 文件**、**66 个测试文件**（658 例）、前端 `apps/web` 与 `pdca-workbench/frontend`、调度与发布脚本、CI 工作流。
- 方法：五路并行人工审查 + 本地静态证据采集（密钥扫描、异常吞噬统计、大文件统计、真实 TODO 统计、跟踪文件体积、env 文件敏感项、git tree 对比远端）。
- 本报告所有发现均带 文件:行 与代码证据；未验证的一律不写。

## 三、发现（按严重度）

### P1-1 claim 台账 at-most-once：当天失败即当天不再重试
- 证据：`pdca-workbench/app/scheduler/run_ledger.py:18-50`
```python
existing = session.exec(select(ScheduledJobRun).where(ScheduledJobRun.run_key == run_key)).first()
if existing is not None:
    if existing.status == "sending" and ...:   # 只回收“卡住 30 分钟”的发送中
        ...
    return False                                # 含 status=failed：一律不再认领
```
- 影响：`duzhan/ctob/daily_digest/evidence_report/campaign_wa_check` 全部共用这套语义。当天首次失败（网络/上游抖动）后，8:30 的兜底触发也会被跳过；实证：2026-09-18 19:45 采集被容器重启打断，20:00 档只能按空表推送。
- 建议：区分“可重试失败”和“已成功”，例如 `status == "failed" and (now - finished_at) < 30min → 允许再认领一次`；或给兜底任务用独立 bucket。

### P1-2 .gitignore 缺关键项，运行期产物已入库
- 证据：`.gitignore` 关键项检查 —— `.env` 已忽略，但 `data/`、`node_modules/`、`dist/`、`*.key` **未见**；`git ls-files` 里已有 66 个“数据/生成物类”文件，最大 897 KB：
```
897 KB overseas_weekly/outputs/_w3_zhoubao1_media/image1.png
735 KB overseas_weekly/outputs/2026-W30_海外经销商周报_static.html
283 KB overseas_weekly/outputs/_cursor_ivan_pull.json
```
- 影响：`pdca-workbench/data/` 下有运行库、导出报告、含客户号的证据 HTML；一旦误 `git add .` 就会把业务数据与个人信息带进仓库；大文件也让 clone/CI 变慢。
- 建议：补 `.gitignore`（`pdca-workbench/data/`、`**/node_modules/`、`**/dist/`、`*.key`、`*.dump`、`overseas_weekly/outputs/`），并用 `git rm --cached` 摘掉已入库的生成物。

### P1-3 异常吞噬 9 处（含安全相关）
- 证据：静态统计 `except` 后直接 `pass/continue/return` 共 9 处，零裸 `except`。示例 `pdca-workbench/app/auth/security.py:60`：
```python
try:
    ... session.add(TokenRevocation(jti=jti, expires_at=expires_at)); session.commit()
except Exception:
    pass            # token 撤销入库失败被吞掉
```
其余：`auth/security.py:97`（过期撤销记录清理）、`auth/router.py:71/91/104`、`dashboard/router.py:301`、`logibot/label.py:67`、`logibot/track.py:78`、`signalseller/outreach.py:160`。
- 影响：撤销写入失败 → 已登出的 token 仍可能有效；清理失败 → 表膨胀且无告警。属于“静默降级”，与项目“失败不静默”的原则相冲突。
- 建议：至少 `logger.warning`，安全路径改为“写失败即拒绝请求”。

### P1-4 本地与远端仓库长期漂移，且 git 直推不通
- 证据：`git remote -v` 有三个远端；`git log --oneline origin/main..HEAD` 显示本机两个提交（agent-admin，1055 行）从未上远端；`git push --dry-run` 实测 `Failed to connect to github.com port 443`。
- 影响：本机成果（含另一会话的三策略 WIP）只存在于工作区，误删即丢；发布流程只能通过 GitHub API 补推，缺少固化脚本。
- 处置：本次已用 API 补推三个分支（见第六节）；建议把补推脚本固化到 `scripts/`。

### P2-1 单文件职责过重
- 证据：`duzhan_ledger.py` 1803 行、`scheduler/jobs.py` 1460 行、`duzhan.py` 1391 行、`todos/service.py` 1096 行、`todos/router.py` 867 行。
- 影响：改动面大、回归风险高（本次就出现“CLI 与定时任务两条路径行为不一致”导致漏检）。
- 建议：按“采集 / 渲染 / 发送 / 调度”拆包，渲染纯函数化（已有雏形：`render_brief`）。

### P2-2 早上 8 点任务扎堆
- 证据：注册表 `evidence=07:00`、`digest=08:00`、`campaign_wa_check=08:00(+08:30)`、`strategy_wa_brief=08:00`（另一会话）、本机 `PDCA Evidence Daily 08:00`。
- 影响：同一分钟对 MCP / VPS / Qwen / IM 发起多个重任务，互相抢外部配额与带宽；任一个慢会拖到 09:00 后。
- 建议：错峰为 07:00 证据 → 07:20 腕表核查 → 08:00 汇总与发送。

### P2-3 图片认图串行、时长不可控
- 证据：`scripts/wa_campaign_check.py:fetch_media` 逐张下载 + 调本地 Qwen（单张实测 20–40 秒），每人默认 8 张 × 5 人 = 最多 40 次串行调用。
- 影响：任务可能跑 20 分钟以上；Qwen 抖动会拖长整条链路。
- 建议：并发（4–6）+ 整体时限（超时即降级为“未认图”）+ 当日结果缓存。

### P2-4 前端内联 JS 无 CI 校验
- 证据：`.github/workflows/pdca-ci-cd.yml` 只构建 `apps/web`；`frontend/agent_admin.html` 是手写内联 JS。本次它曾因 `act(id,"approve")` 的引号问题导致整页 JS 失效，只能靠人工发现。
- 建议：CI 里加一步 `node --check`（抽出 `<script>` 或直接用 `html-validate`），并对关键元素 id 做静态比对。

### P2-5 每日 1 MB HTML × 3 人私聊
- 证据：证据日报 951 KB–1 MB（内嵌 24 张缩略图），收件人 3 人（`PDCA_MGMT_HTML_USER_IDS`）。
- 影响：IM 附件体积/配额、移动端打开慢。
- 建议：超过阈值（如 800 KB）自动降级为“只发摘要 + 链接”，或把原图缩到 320px。

### P2-6 外部契约只能靠线上验证
- 证据：`tests/` 66 个文件 658 例，但 MCP / VPS / Qwen / IM 全部 mock；真实契约（字段改名、限流、抽样上限）无双跑校验。
- 实证：本次 MCP `messages` 证据的 `scan_limit`、`page_size` 上限、`media_url` 字段都是线上试出来的。
- 建议：加一个只读“契约探针”（每日 07:30 干跑一次，断言关键字段存在），失败即告警。

## 四、已确认没问题的点
1. **密钥不入库**：`vbs_`、`sk-`、`-----BEGIN ... PRIVATE KEY-----`、JWT 在 git 跟踪文件中零命中；`.env` 在 `.gitignore` 内；`vbot_` 只出现在 `.env.example` 与测试夹具。
2. **无裸 `except:`**（0 处），异常都带类型或 `# noqa` 说明。
3. **外发链路有幂等**：三追/C转B/日报群/证据日报/腕表核查都带 `claim_run` + 幂等键；IM 发送统一走 `app/im_files.py`，未配 `channel_id` 时绝不发群。
4. **个人信息处理克制**：MTO 图读完即删（`cleanup_temp_files` 隔日兜底）；客户号在报告里默认脱敏（`668***5954`）。
5. **时区与日期边界有测试**：北京/巴黎分群、`messages_on_day`、滚动日目标第 X/Y 天都有用例。
6. **CI 门禁完整**：单测 + `compileall` + `alembic heads` + compose config + PowerShell 解析 + 镜像构建，发布脚本校验 CI 结论后才部署。

## 五、测试覆盖缺口
1. 外部依赖全 mock，缺“真实契约”与“端到端干跑”（见 P2-6）。
2. 失败注入偏少：claim 冲突、IM 部分失败、Qwen 超时、MCP 分页上限等分支缺用例。
3. 前端（`frontend/agent_admin.html`、`apps/web`）只有构建检查，没有 JS 行为断言。
4. 调度注册有时间点断言，但**没有“同一分钟任务数”上限断言**（P2-2 就是在无约束下累积出来的）。
5. 图片类链路（MTO OCR、腕表认图）本地依赖 Pillow，CI 缺失时会被跳过 → 关键分支在 CI 里等于没跑。
6. 本机脚本（`pull_evidence_to_desktop.ps1` 等）只有解析检查，没有“拉取成功/失败”路径用例。

## 六、远程仓库现状与本次补推
- 既有远端：`origin = github.com/wfywfywfy01/PDCA-agent-wfywfywfy01`（所有已合并工作都在 `main`，HEAD `cc10d9e6`）；另有 `prfork`、`upstream`。
- 本机 git 直推不通（443 连接失败），本次改用 **GitHub API** 补推三个分支：

| 分支 | 内容 | 文件数 |
|---|---|---|
| `codex/agent-admin-local` | Agent 管理后台（Vue 页面 + 后端 `app/agent_admin/*` + 测试 + 文档 + 首页/导航直达） | 12 |
| `codex/strategy-wa-wip` | 三策略 WhatsApp 前 24 小时 HTML（另一会话 WIP，仅备份实现与测试） | 2 |
| `codex/scripts-leads` | 线索清洗三件套（build_clean_leads / filter_no_contact / match_and_clean） | 3 |

> 远端 `main` 文件数 1196；本次补推前，上述 17 个文件在 `main` 上均不存在（`AppNav.vue`/`router/index.ts` 已在远端，其余 12 个缺失）。

## 七、建议的修复顺序（一周内）
1. **P1-1** claim 支持“失败可重试”（改 1 个文件 + 3 个用例，收益覆盖全部定时任务）。
2. **P1-2** 补 `.gitignore` + 摘除已入库生成物（10 分钟，防数据外泄）。
3. **P1-3** 9 处异常吞噬加日志/告警（安全路径改为失败即拒）。
4. **P2-2** 早间任务错峰（纯配置）。
5. **P2-4** CI 加前端内联 JS 语法校验。
6. **P2-6** 契约探针（每日只读干跑 + 告警）。

---
*审查人：DeepSeek Harness Agent｜证据采集脚本：`pdca-workbench/data/_review_evidence*.py`（临时文件，未入库）｜本地 git 直推不通，本报告通过 GitHub API 提交。*