# PDCA 生产加固实现计划

> **面向 AI 代理的工作者：** 按任务顺序执行；每个任务先增加可复现失败的测试，再做最小修复并提交。步骤使用复选框跟踪。

**目标：** 修复审查发现的数据、权限、自动任务和发布缺口，使当前 `main` 达到可测试、可恢复、可审计的生产发布门槛。

**架构：** 业务数据继续以 PostgreSQL 为事实源；所有待办查询通过统一 scope service；所有消息通过带业务幂等键的 outbox 记录状态。部署仍使用不可变 Git SHA 镜像，并在切换前执行备份、迁移和只读验收。

**技术栈：** FastAPI、SQLModel/SQLAlchemy、PostgreSQL、Vue 3、Docker、GitHub Actions、VPS IM。

---

### 任务 1：修复日报、目标、项目列表和回复判断

**文件：**
- 修改：`pdca-workbench/app/daily_report.py`
- 修改：`pdca-workbench/app/vertu/sales.py`
- 修改：`pdca-workbench/app/scheduler/jobs.py`
- 修改：`pdca-workbench/app/todos/router.py`
- 创建：`pdca-workbench/app/todos/reply_signals.py`
- 修改：`pdca-workbench/app/todos/scoring.py`
- 修改：`pdca-workbench/scripts/sync_todo_ledger.py`
- 测试：`pdca-workbench/tests/test_daily_report.py`
- 测试：`pdca-workbench/tests/test_todo_projects.py`
- 测试：`pdca-workbench/tests/test_todo_claims_scoring.py`

- [ ] 增加失败测试：清单外门店不计入必报已报数；任一部门目标缺失时目标状态不可用；日报生成失败只调用告警通道；项目列表有数据时返回 200；“未完成/not done”不是完成信号。
- [ ] 运行：`python -m unittest tests.test_daily_report tests.test_todo_projects tests.test_todo_claims_scoring -v`，确认新测试按预期失败。
- [ ] 实现统一 `classify_reply(text) -> Literal["done", "blocked", "progress", "reply"] | None`，否定规则先于正向关键词；评分和台账复用。
- [ ] 使用 `required_reported_ids = reported_ids & set(REQUIRED_FIVE_KIT_STORES)`；目标接口遇到空值、非数、非有限值或缺部门时抛出数据不可用；修复项目排序变量；日报异常走 `push_vps_alert()`。
- [ ] 重跑测试并执行 `git diff --check`。
- [ ] 提交：`fix: make report and todo results fail closed`。

### 任务 2：修复认领游标和台账零副作用

**文件：**
- 修改：`pdca-workbench/app/todos/claims.py`
- 修改：`pdca-workbench/scripts/sync_todo_ledger.py`
- 修改：`pdca-workbench/app/config.py`
- 修改：`pdca-workbench/app/scheduler/jobs.py`
- 测试：`pdca-workbench/tests/test_todo_claims_scoring.py`
- 创建：`pdca-workbench/tests/test_todo_ledger.py`

- [ ] 增加失败测试：已有游标后处理新消息会推进游标；再次执行不会重认领；`--dry-run` 不创建文档、不写数据库、不调用 sheet API；数据缩减会清除旧尾行；超过容量整批失败。
- [ ] 运行上述测试并记录失败。
- [ ] 将消息按稳定时间和 ID 排序，在事务中更新最新已处理游标；给状态 key 增加唯一冲突重试。
- [ ] dry-run 在 `get_or_create_doc()` 前返回预览；台账写入生成完整矩形范围并清理旧范围，容量校验发生在外部写调用前。
- [ ] 增加 `PDCA_TODO_SCORING_ENABLED`、`PDCA_TODO_LEDGER_ENABLED`；未启用或未配置文档时调度器明确跳过。
- [ ] 重跑测试并提交：`fix: make todo automation idempotent and side-effect safe`。

### 任务 3：完成待办团队权限隔离

**文件：**
- 修改：`pdca-workbench/app/models/todo_project.py`
- 修改：`pdca-workbench/app/models/pdca_task.py`
- 创建：`pdca-workbench/app/todos/scope.py`
- 修改：`pdca-workbench/app/todos/router.py`
- 修改：`pdca-workbench/app/todos/service.py`
- 创建：`pdca-workbench/migrations/versions/20260908_todo_team_scope.py`
- 创建：`pdca-workbench/tests/test_todo_scope_matrix.py`

- [ ] 建立 admin、两个 team manager、两个 sales、dealer、viewer 测试数据；对列表、详情、更新、删除、合并、回复审批和 CSV 导出增加跨团队失败测试。
- [ ] 运行权限矩阵，确认当前跨团队访问暴露。
- [ ] 为项目和任务增加明确 `team_key`；历史空值保持隔离状态，管理员确认后回填，不按显示名猜归属。
- [ ] 实现 `TodoScope` 查询构造器：admin=all、manager=team、sales=self，其余无管理权限；读写共用同一过滤器，越权资源返回 404。
- [ ] 让自动任务只处理显式配置团队；审计记录操作者、team_key、资源 ID 和结果。
- [ ] 运行权限矩阵、迁移测试并提交：`fix: enforce team scope across todo workflows`。

### 任务 4：消息 outbox、运行台账和频道契约

**文件：**
- 创建：`pdca-workbench/app/models/scheduled_job_run.py`
- 创建：`pdca-workbench/app/models/message_outbox.py`
- 创建：`pdca-workbench/app/messaging/outbox.py`
- 修改：`pdca-workbench/app/vps_im_push.py`
- 修改：`pdca-workbench/app/scheduler/jobs.py`
- 修改：`pdca-workbench/app/config.py`
- 修改：`pdca-workbench/scripts/deploy_remote_docker.ps1`
- 创建：`pdca-workbench/tests/test_message_outbox.py`

- [ ] 增加失败测试：同一业务日重复执行只成功发送一次；超时后重试不重复；失败日报业务群 0 条、告警群 1 条；日报和告警频道相同则启动检查失败。
- [ ] 建立数据库唯一约束 `(message_type, business_date, dedupe_key)`；记录 payload hash、频道、尝试数、VPS message ID 和最终状态。
- [ ] 调度任务先创建运行记录和 outbox，再由发送器发送；未知回执保留 `uncertain`，人工或查询确认后才能重发。
- [ ] 部署脚本透传 `PDCA_ALERT_BOT_CHANNEL_ID`，并验证日报频道与告警频道均存在且不同。
- [ ] 运行测试并提交：`feat: add durable idempotency for scheduled messages`。

### 任务 5：CI、迁移、部署和恢复门禁

**文件：**
- 修改：`.github/workflows/pdca-ci-cd.yml`
- 修改：`pdca-workbench/scripts/postgres_acceptance.py`
- 修改：`pdca-workbench/scripts/deploy_remote_docker.ps1`
- 修改：`pdca-workbench/scripts/acceptance_smoke.py`
- 修改：`docs/RUNBOOK.md`

- [ ] CI 增加项目列表真实 HTTP 请求、团队权限矩阵、dry-run 零写入、消息幂等、频道错配和迁移升级测试。
- [ ] 部署前在恢复出的临时数据库运行 migration；检查备份完整解码和关键表计数。
- [ ] 部署候选容器后验证 `/health.revision`、DB、登录、权限、主看板、五件套、任务和静态资源，再切换流量。
- [ ] 在隔离环境执行启动失败、DB 不可用、上游超时及回滚演练，验证恢复时间小于 10 分钟且业务数据丢失为 0。
- [ ] 运行全量验证：后端测试、前端测试/类型检查/构建、SQLite 与 PostgreSQL 容器冒烟、`git diff --check`。
- [ ] 提交：`ci: gate production on business acceptance and recovery`。

### 任务 6：候选版本验收与发布

**文件：**
- 创建：`docs/production-acceptance-2026-09-08.md`

- [ ] 合并前复核所有提交和变更范围，确认未跟踪 `.env`、密钥、客户数据、导出和浏览器产物。
- [ ] 推送分支并创建 PR；等待当前 SHA 的全部 CI 完成。
- [ ] 构建并拉取该 SHA 镜像，在本地 Docker 与真实 PostgreSQL 隔离环境验收。
- [ ] 生产发布前创建并恢复验证备份；保留旧容器回滚配置。
- [ ] 部署主站和五件套门户，执行 API、权限矩阵及桌面/390px 手机只读浏览器验收。
- [ ] 记录 release SHA、备份、容器、测试结果、数据对账和回滚命令。
- [ ] 连续 7 天检查数据差异、越权、漏跑、重复发送和错群；五项均为 0 后标记生产验收完成。
