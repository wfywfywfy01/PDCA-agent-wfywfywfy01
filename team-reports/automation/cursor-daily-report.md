# Cursor Automation — 团队日报定时任务

## 用途

每位成员在每天 **17:30（Asia/Shanghai）** 自动生成 Cursor 日报，写入 PostgreSQL，并 push 到共享 Git 仓库。

## 在 Cursor Automations 编辑器中配置

| 字段 | 建议值 |
|------|--------|
| 名称 | Cursor 团队日报 |
| 描述 | 每天自动汇总 Cursor 工作并写入 PostgreSQL |
| 触发器 | Schedule / Cron |
| Cron | `30 17 * * 1-5` |
| 时区 | Asia/Shanghai |
| 工具 | Shell、Read、Write |
| Skill | `cursor-daily-report` |

## 自动化 Prompt（复制到 Automation 指令）

```text
运行 cursor-daily-report skill，完成今日团队日报：

1. 确认 team-reports/.env 与 CURSOR_REPORT_USER 已配置
2. 解析今天 agent-transcripts
3. 用详细版格式精炼 daily_summary（任务、工具、产出、状态）
4. 写入 team-reports/daily/<username>/ 下的 JSON 和 Markdown
5. 执行 db_writer.py 写入 PostgreSQL
6. git add/commit/push 日报文件

若今天没有会话，仍写入空日报并说明“今日未检测到 Cursor 会话记录”。
```

## 组织架构与查看权限

配置见 `team-reports/config/org.json`。

| 角色 | 人员 | 可见范围 |
|------|------|----------|
| 总监 | Sam、Gary、May、Frank | 全员 |
| 小组长 | Lina | Lina、Viki |
| 小组长 | April | April、Vivi、Haiwen |
| 小组长 | Ivan | Ivan |
| May 组 | Qiqi、Xianna、Zhangyi | 仅自己（组织上归属 May 组） |
| 成员 | Viki、Vivi、Haiwen、Chris | 仅自己 |

```bash
python team-reports/scripts/query_team.py --scope
python team-reports/scripts/query_team.py --viewer Lina --status
python team-reports/scripts/query_team.py --viewer May --ranking --month 2026-06
```

## 团队成员（14 人）

| username | 角色 | 备注 |
|----------|------|------|
| Sam | 总监 | |
| Gary | 总监 | |
| May | 总监 | May 组组长 |
| Frank | 总监 | |
| Lina | 小组长 | |
| April | 小组长 | |
| Ivan | 小组长 | |
| Qiqi | 成员 | May 组 |
| Xianna | 成员 | May 组 |
| Zhangyi | 成员 | May 组 |
| Viki | 成员 | |
| Vivi | 成员 | |
| Haiwen | 成员 | |
| Chris | 成员 | |

每人本地 `team-reports/config/user.json` 中的 `username` 必须与上表一致。

## 成员部署清单

1. 克隆共享 Git 仓库
2. 安装依赖：`pip install -r team-reports/requirements.txt`
3. 复制配置：
   - `cp team-reports/.env.example team-reports/.env`
   - `cp team-reports/config/user.example.json team-reports/config/user.json`
4. 填写 `.env` 中的数据库密码和 `CURSOR_REPORT_USER`
5. 初始化数据库（仅需一次）：
   ```bash
   python team-reports/scripts/db_schema.py --create-db
   ```
6. 安装 Skill：
   - 项目级：已在 `.cursor/skills/cursor-daily-report/`
   - 或复制到个人目录：`~/.cursor/skills/cursor-daily-report/`
7. 在 Cursor Automations 中创建上述定时任务

## Git 备份同步

日报 / 周报 / 月报 JSON 与 Markdown 会同步到本仓库，便于离线查看与版本追溯。

```bash
# 每日发布后（publish_daily --git-push 会自动同步）
python team-reports/scripts/git_sync.py

# 每周五
powershell -ExecutionPolicy Bypass -File team-reports/scripts/run_weekly.ps1

# 每月 1 号
powershell -ExecutionPolicy Bypass -File team-reports/scripts/run_monthly.ps1
```

Git 只存**报告备份**，不存 `.env` / `user.json`（已在 `.gitignore`）。

## 主管侧重任务（可选）

| 任务 | Cron | 命令 |
|------|------|------|
| 周报聚合 + Git | `0 18 * * 5` | `run_weekly.ps1` |
| 月报聚合 + Git | `0 9 1 * *` | `run_monthly.ps1` |

## 验证

```bash
python team-reports/scripts/publish_daily.py --date today
python team-reports/scripts/query_team.py --today
```
