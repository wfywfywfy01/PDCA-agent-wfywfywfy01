# PDCA 生产审查问题修复实现计划

> **面向 AI 代理的工作者：** 必需子技能：按任务逐项执行；每项先补失败测试，再完成最小修复。步骤使用复选框跟踪。

**目标：** 修复 2026-09-22 全仓审查确认的权限、数据准确性、待办、副作用、推送、迁移和会议音频问题。

**架构：** 复用现有 `DataScope`、`latest_walkin_reports`、Outbox 状态及 VPS 幂等字段，不增加新依赖。所有修复落在现有共享入口；测试使用隔离 SQLite、FastAPI/函数公共接口和 mock 外部服务，禁止连接生产或真实发群。

**技术栈：** Python 3.12、FastAPI、SQLModel/SQLAlchemy、Alembic、unittest、Vue 3、TypeScript、Node test。

---

### 任务 1：Agent 团队权限与只读执行边界

**文件：**
- 修改：`pdca-workbench/app/agents/router.py`
- 修改：`pdca-workbench/app/agents/supervisor_service.py`
- 修改：相关 Agent 查询服务，仅在共享查询入口需要接收 owner/team 范围时修改
- 测试：`pdca-workbench/tests/test_production_review_fixes_2026_09_22.py`

- [x] 写失败测试：manager 的 stats/runs/outbox 等接口不能返回其他团队 owner；`/api/agents/tasks` 的“部门总结”即使正式模式也不创建 Outbox、不写任务。
- [x] 运行定向测试并确认现状失败。
- [x] 将 `resolve_data_scope()` 结果传入 Agent 查询；查询入口强制调用只读采集，不再调用 `run_group_slot()`。
- [x] 运行定向测试，确认跨团队查询为空且只读请求无副作用。

### 任务 2：MCP 身份类型与五件套最新版本口径

**文件：**
- 修改：`pdca-workbench/app/mcp_five_kit.py`
- 测试：`pdca-workbench/tests/test_mcp_five_kit.py`

- [x] 写失败测试：`client_id=pdca-user` 且用户名以 `service:` 开头时仍按数据库用户授权；同店同日两次填报仅汇总最新记录。
- [x] 运行定向测试并确认身份越权、汇总重复。
- [x] 根据可信 `client_id` 区分服务和用户身份；`_reports()` 复用 `latest_walkin_reports()`。
- [x] 运行定向测试，确认特殊用户名不提权，reports/summary/trend 与网页口径一致。

### 任务 3：待办事务响应与回复关联

**文件：**
- 修改：`pdca-workbench/app/todos/router.py`
- 修改：`pdca-workbench/app/models/im_replies.py`，仅当现有字段不足以稳定关联原提醒时增加关联字段
- 修改：`pdca-workbench/app/todos/im_replies.py`，仅用于写入已有/新增关联字段
- 创建：对应 Alembic 迁移，仅当模型增加字段时创建
- 测试：`pdca-workbench/tests/test_todo_replies.py`
- 测试：`pdca-workbench/tests/test_todo_projects.py`

- [x] 写失败测试：五个写端点提交后返回 2xx 且写审计；旧回复不能完成后来提醒中的任务。
- [x] 运行定向测试并确认 500 与错关任务。
- [x] 在 Session 内提取响应/审计字段；按回复对应提醒或不晚于回复时间的最近提醒选择任务。
- [x] 运行定向测试，确认修改、合并、确认、忽略及多轮提醒行为正确且重复操作安全。

### 任务 4：Outbox 有限重试和日报幂等

**文件：**
- 修改：`pdca-workbench/app/agents/outbox.py`
- 修改：`pdca-workbench/app/vps_im_push.py`
- 修改：`pdca-workbench/app/scheduler/jobs.py`
- 测试：`pdca-workbench/tests/test_agent_outbox.py`
- 测试：`pdca-workbench/tests/test_daily_report.py`

- [x] 写失败测试：失败两次的记录不再自动发送且不阻塞第 41 条；同一日报两次 HTTP 尝试携带相同业务幂等键。
- [x] 运行定向测试并确认无限重试、队列饥饿及无幂等字段。
- [x] 查询仅选择未耗尽预算的记录；人工 retry 显式重置；日报将 `daily_report:<日期>:<群>` 的稳定键传给 `_push()`。
- [x] 运行定向测试，确认失败预算、队列公平性、人工重试和响应丢失场景。

### 任务 5：迁移基线与本地数据库识别

**文件：**
- 修改：`pdca-workbench/scripts/migrate.py`
- 修改：`pdca-workbench/app/config.py`
- 测试：`pdca-workbench/tests/test_migrations.py` 或新建同职责测试文件
- 测试：`pdca-workbench/tests/test_run_ledger.py`

- [x] 写失败测试：无版本历史库不能直接 stamp 到 head；SQLite 内存/文件库不标记为远程，本机及远程 PostgreSQL 判断正确。
- [x] 运行定向测试并确认历史库缺约束、SQLite 被误判。
- [x] 历史库按安全基线执行实际迁移；数据库本地性通过 URL scheme/hostname 判断。
- [x] 运行定向测试。
- [ ] PostgreSQL 测试容器升级与重复升级验证（本机 Docker 守护进程不可用，未执行）。

### 任务 6：会议音频前后端契约

**文件：**
- 修改：`apps/web/src/pages/MeetingPage.vue`
- 测试：`apps/web/tests/meeting-audio.test.mjs`

- [x] 写失败测试：历史会议音频请求携带选定日期，并只显示当前 meeting_id 的 `audio_url`。
- [x] 运行前端测试并确认当前字段为空且未过滤。
- [x] 使用详情中的 `audio_url` 或精确过滤音频列表，传入当前会议日期范围。
- [x] 运行测试、类型检查和生产构建。

### 任务 7：全量回归与交付

**文件：**
- 更新：`docs/superpowers/plans/2026-09-22-production-review-fixes.md` 的完成状态

- [x] 运行 `cd pdca-workbench && python -m unittest discover -s tests -p "test_*.py"`，确认零失败且不连接生产。
- [x] 运行 `cd apps/web && npm test && npm run typecheck && npm run build`。
- [x] 检查 `git diff --check`、`git status`、改动文件和敏感信息，确认仅包含本轮修复。
- [x] 提交到 `codex/fix-review-20260922`；不部署生产，部署需用户另行确认。
