# PDCA 经销商经营工作台

海外经销商团队的 **Plan-Do-Check-Act** 数据中台与 Web 工作台。  
基于 **FastAPI + PostgreSQL + vertu CLI（VPS/Odoo）**，由 Cursor 编辑业务数据，Git 做版本管理。

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
- **认证**：`PDCA_AUTH_MODE=vps`（VPS / Odoo 单点登录，依赖 `vertu odoo me`）
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

本地已 `vertu login` 时，可在 `.env` 设 `PDCA_AUTH_MODE=hybrid`（VPS 与本地账号并存）。

---

## 主要页面

| 路径 | 功能 |
|------|------|
| `/` | 经营驾驶舱（Sell In/Out、客户管理中心） |
| `/logistics-center/` | 物流进展 |
| `/signalseller-center/` | 获客指挥 |
| `/walkin-cockpit/` | 客流 / 线上 |
| `/meeting-center/` | 会议中心 |
| `/dashboard` | 数据看板 |
| `/customer-mgmt` | 客户管理（需另部署 8787 服务） |

---

## 技术栈

- **后端**：Python 3.12、FastAPI、SQLModel、PostgreSQL
- **数据**：vertu CLI → Odoo / Vemory；CSV + Git 作业务数据中台
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
