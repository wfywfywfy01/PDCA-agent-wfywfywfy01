# PDCA 经销商经营工作台

海外经销商团队的 **Plan-Do-Check-Act** 数据中台与 Web 工作台。  
基于 **FastAPI + PostgreSQL + vertu-cli 2.x**，由 Cursor 编辑业务数据，Git 做版本管理。

---

## 仓库里有什么

本仓库**不是**单纯的销售资料夹，核心是可部署的 Web 应用 + 业务数据流水线。

| 路径 | 说明 |
|------|------|
| **`pdca-workbench/`** | **主服务**（8767）：经营首页、认证、API、Docker/systemd 部署 |
| **`data_platform/data_role_pdca_mvp/`** | 看板模块：首页、物流、获客指挥、会议中心、客流等 |
| **`teams/yang-jingjing/`** | 小组 PDCA 数据：客户 CSV、日报、Check 报告、行动建议 |
| **`AGENTS.md`** | Agent 分工与 PDCA 检查规则 |
| **`docs/`** | 集成说明、客户管理交接文档等 |

---

## 两种部署场景（别搞混）

### 1. 对内完整工作台（海外中台）

- **入口**：`https://域名/`
- **认证**：`PDCA_AUTH_MODE=vps`（Vertu 单点登录，依赖 `vertu-cli hr +me`）
- **必挂**：`PDCA_MVP_ROOT` + `PDCA_REPO_ROOT` + 服务器安装 vertu
- **说明**：桌面/运维文档《PDCA对内工作台-运维部署执行文档.md》

### 2. 对外经销商五件套录入

- **入口**：`https://域名/walkin-submit`
- **认证**：`PDCA_AUTH_MODE=local`（本地经销商账号）
- **说明**：`pdca-workbench/docs/部署手册.md`

---

## 本地开发

```bash
git clone https://github.com/Frankie-Foo/PDCA-agent.git
cd PDCA-agent/pdca-workbench

cp .env.example .env
# 填写 PDCA_DATABASE_URL、PDCA_MVP_ROOT、PDCA_REPO_ROOT

pip install -r requirements.txt
python scripts/init_db.py
python run.py
```

访问 http://127.0.0.1:8767/

本地已完成 `vertu-cli auth login` 时，可在 `.env` 设 `PDCA_AUTH_MODE=hybrid`（VERTU 与本地账号并存）；生产环境应使用 `VERTU_APP_ID` / `VERTU_APP_KEY` 应用凭证。

---

## 主要页面

| 路径 | 功能 |
|------|------|
| `/` | 经营驾驶舱（Sell In/Out、客户管理中心） |
| `/app/` | **Vue3 SPA 工作台**（P1+）：登录、驾驶舱、数据看板、物流中心、会议中心、获客指挥、客流五件套、任务中心、新人培训、数据同步 |
| `/app/dashboard` | 数据看板：Sell-in 排行 + 近 6 月趋势（ECharts） |
| `/app/knowledge` | 经销商资料库：权限范围内的 AI 检索、引用与脱敏预览 |
| `/logistics-center/` → `/app/logistics` | 物流进展（已迁 SPA） |
| `/signalseller-center/` → `/app/signalseller` | 获客指挥（已迁 SPA） |
| `/meeting-center/` → `/app/meetings` | 会议中心（已迁 SPA） |
| `/walkin-submit` | 五件套录入（经销商门户；SPA 版在 `/app/walkin`） |
| `/customer-mgmt` | 客户管理（获客外部服务 iframe 或 `/app/signalseller`） |

**切到新前端**：生产 `.env` 设 `PDCA_HOME_REDIRECT=/app/`（旧页面共存，可随时回退）。
**生产运维**：见 `pdca-workbench/docs/运维手册-P5.md`（切换三步曲、监控告警、备份演练、回滚）。

### 生产镜像交付

CI 使用 `pdca-workbench/Dockerfile.release`：基于固定摘要的现役运行时，
重新执行前端 `npm ci`、测试、类型检查和构建，再替换精确 commit 的源码及
SPA 产物。旧源码目录先清理，避免已删除文件残留；不修改 `/app/data`、
`/repo`、`/mvp` 持久卷。镜像标签、OCI/source revision 标签及
`PDCA_RELEASE_SHA` 使用同一个 commit SHA。

发布层只运行 `pip install --no-index --no-deps -r requirements.lock` 和
`pip check`。固定运行时未满足锁定依赖时构建必须失败，不能联网补包或
静默升级。Python、系统包、Node/CLI、浏览器依赖需要变化时，先用保留的
`pdca-workbench/Dockerfile` 完整重建并验证运行时，再更新 release 文件的
固定摘要；不能把 `latest` 当作运行时基线。原 Dockerfile 也保留给本地完整构建。

新的发布镜像保留原运行时大层，使已持有该运行时的服务器复用这些层；
常规源码更新只增加源码、SPA 等小层。CI 的 SQLite 冒烟、PostgreSQL
并发/权限/故障恢复冒烟、main 分支发布门禁保持不变，测试通过后才推送镜像。

---

## 技术栈

- **后端**：Python 3.12、FastAPI、SQLModel、PostgreSQL
- **数据**：vertu-cli 业务快捷命令 → Sales / Vemory；CSV + Git 作业务数据中台
- **调度**：Hermes（日检脚本、Agent 分派，见 `AGENTS.md`）

---

## 文档索引

| 文档 | 用途 |
|------|------|
| `pdca-workbench/README.md` | 服务路由、默认账号、API 说明 |
| `pdca-workbench/docs/部署手册.md` | 对外经销商五件套部署 |
| `docs/CUSTOMER_MGMT_CODEX_HANDOFF.md` | 客户管理（8787）交接 |
| `docs/SIGNALSELLER_PDCA_INTEGRATION.md` | 获客指挥集成说明 |
| `AGENTS.md` | PDCA Agent 规则与小组目录约定 |

---

## 安全提醒

- 勿将 API Key、数据库密码、客户隐私提交到公开仓库
- 生产环境必须更换 `PDCA_SECRET_KEY`，HTTPS 下设置 `PDCA_SECURE_COOKIES=1`
- 合同相关内容需人工复核，AI 输出不构成法律意见

---

## 链接

- **GitHub**：https://github.com/Frankie-Foo/PDCA-agent.git
- **问题反馈**：联系仓库维护人
