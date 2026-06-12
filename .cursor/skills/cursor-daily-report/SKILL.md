---
name: cursor-daily-report
description: >-
  生成 Cursor 团队日报：解析 agent-transcripts、输出结构化 JSON/Markdown、
  写入 PostgreSQL，并可选 git push。Use when the user asks for daily cursor report,
  team activity summary, cursor daily summary, or when a scheduled automation runs
  the daily report workflow.
---

# Cursor 团队日报

## 目标

在每天下班前，自动汇总成员当天在 Cursor 中的工作内容，形成结构化日报，并写入 PostgreSQL 与 Git 备份。

## 前置条件

1. 已安装依赖：
   ```bash
   pip install -r team-reports/requirements.txt
   ```
2. 已配置 `team-reports/.env`（参考 `team-reports/.env.example`）
3. 已配置用户名：
   - 环境变量 `CURSOR_REPORT_USER=张三`
   - 或 `team-reports/config/user.json`
4. 已初始化数据库：
   ```bash
   python team-reports/scripts/db_schema.py --create-db
   ```

## 标准流程

按顺序执行，不要跳步：

```
Task Progress:
- [ ] Step 1: 解析当天 transcripts
- [ ] Step 2: 生成结构化日报 JSON
- [ ] Step 3: 用 AI 精炼 daily_summary（详细版）
- [ ] Step 4: 写入 JSON/Markdown 备份
- [ ] Step 5: 写入 PostgreSQL
- [ ] Step 6: git commit + push（若仓库可用）
```

### Step 1: 解析 transcripts

从仓库根目录运行：

```bash
python team-reports/scripts/parse_transcripts.py --date today --workspace "<当前工作区路径>" --output team-reports/.tmp/parsed.json
```

若 `--workspace` 省略，默认使用当前仓库根目录。

### Step 2: 读取解析结果

读取 `team-reports/.tmp/parsed.json`，确认：
- `total_sessions`
- `sessions[]`
- `_raw_sessions[]`（若存在）

若 `total_sessions = 0`，仍要生成空日报，摘要写：`今日未检测到 Cursor 会话记录。`

### Step 3: AI 精炼 daily_summary（详细版）

基于 `_raw_sessions` 或 `sessions`，重写 `daily_summary`，要求：

1. 用中文，面向主管阅读
2. 3-6 条 bullet，概括当天主要工作
3. 每条包含：任务目标、使用工具、产出/进展、结果状态
4. 不粘贴原始对话，不暴露敏感信息
5. 更新 `key_topics`（3-8 个）

**输出模板：**

```markdown
## 今日工作摘要

- 【Hermes 功能梳理】梳理数据岗位 PDCA 与经销商日报 Agent 清单，使用 Read/Glob 查阅文档，输出功能清单，已完成。
- 【物流核查优化】调整物流 browser agent 查询流程，涉及 scripts 与 agents 文档，进行中。
```

将上述内容写入 JSON 的 `daily_summary` 字段（保留 `\n` 换行）。

生成最终 JSON 时，删除 `_raw_sessions` 字段。

### Step 4: 写入 JSON / Markdown 备份

```bash
python team-reports/scripts/publish_daily.py --date today --workspace "<当前工作区路径>" --skip-db
```

若已在 Step 3 手工改好 JSON，则：

1. 写入 `team-reports/daily/<username>/YYYY-MM-DD.json`
2. 用 `report_io.render_daily_markdown()` 逻辑生成同名 `.md`

### Step 5: 写入 PostgreSQL

```bash
python team-reports/scripts/db_writer.py --file team-reports/daily/<username>/YYYY-MM-DD.json --type daily
```

### Step 6: Git 备份（可选）

```bash
python team-reports/scripts/publish_daily.py --date today --git-push
```

或手动：

```bash
git add team-reports/daily/<username>/YYYY-MM-DD.*
git commit -m "chore(team-reports): add cursor daily report YYYY-MM-DD"
git push
```

## 周报 / 月报（主管或周末定时）

```bash
python team-reports/scripts/aggregate_weekly.py --date today --write-db
python team-reports/scripts/aggregate_monthly.py --write-db
```

## 主管查询

```bash
python team-reports/scripts/query_team.py --today
python team-reports/scripts/query_team.py --user 张三 --week
python team-reports/scripts/query_team.py --ranking --month 2026-06
python team-reports/scripts/query_team.py --topics --week
```

## 注意事项

- agent-transcripts 仅包含 tool 调用，不包含 tool 返回结果；总结应基于“做了什么”而非“返回了什么”
- 子 agent 会话位于 `subagents/`，解析脚本会自动合并
- 同一人同一天重复运行会 upsert，不会重复插入
- 数据库密码只放在 `team-reports/.env`，不要写入 skill 或代码

## 一键模式（Automation 推荐）

若无需手工 AI 精炼，可直接：

```bash
python team-reports/scripts/publish_daily.py --date today --git-push
```

Automation 仍建议在 `--skip-db` 前先让 Agent 执行 Step 3 精炼摘要。
