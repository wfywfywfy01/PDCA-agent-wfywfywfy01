# PDCA 工作台 · 生产环境

基于 **FastAPI + PostgreSQL + JWT 多角色认证** 的本地生产部署。

## 快速启动

```bash
cd pdca-workbench
cp .env.example .env   # 填写 PDCA_DATABASE_URL、PDCA_SECRET_KEY
pip install -r requirements.txt
python scripts/init_db.py
python run.py
```

访问 http://127.0.0.1:8767/login

## 首次管理员

系统不再创建固定密码账号。首次建库时，在 `.env` 中临时设置：

```dotenv
PDCA_BOOTSTRAP_ADMIN_USERNAME=admin
PDCA_BOOTSTRAP_ADMIN_PASSWORD=至少12位随机密码
```

首次启动并成功创建管理员后，立即删除这两个变量。已有数据库账号不受影响；
hybrid/vps 模式也可先通过 VPS 登录，再由管理员面板维护本地账号。

## 完整路由表

### 页面 GET

| 路径 | 说明 |
|------|------|
| `/` | 经营驾驶舱 |
| `/home-classic` | 经典工作台 |
| `/pdca-vps` | PDCA 日结 |
| `/questionnaire` | 每日问卷 |
| `/todos` | 代办录入 |
| `/logistics` | 物流单号录入 |
| `/logistics-center/` | 物流进展看板（销售仅本人） |
| `/im-unread` | IM 未读 |
| `/customer-mgmt` | 客户管理 iframe |
| `/agent-soul` | Agent SOUL 编辑 |
| `/agent-edit` | Agent 多文件编辑 |
| `/view-path` | Hermes 结果预览 |
| `/dashboard` | 数据看板 |
| `/walkin-cockpit/` | 客流/线上 OKR |
| `/meeting-center/` | 会议中心 |
| `/app/knowledge` | 经销商资料库（证据检索、AI 回答、图片预览） |

### 表单 POST

| 路径 | 权限 | 说明 |
|------|------|------|
| `POST /questionnaire` | admin | 保存问卷 → PostgreSQL |
| `POST /todos` | admin | 追加代办 → PostgreSQL |
| `POST /logistics` | sales+ | 追加物流单号 |
| `POST /run` | manager+ | 运行 PDCA 流水线 |
| `POST /pdca-task` | sales+ | 保存 VPS 待办进度 |
| `POST /hermes-chat` | manager+ | Hermes 对话 |
| `POST /agent-soul` | admin | 保存 SOUL.md |
| `POST /agent-core-file` | admin | 保存 Agent 核心文件 |
| `POST /agent-skill` | admin | 上传 Skill |

### API

- `GET /api/dashboard/*` — 经营首页数据
- `GET /api/walkin` / `/api/online-channel` — 客流与线上 OKR
- `GET /api/meeting-center/*` — 会议中心
- `POST /api/meeting-center/dispatch` — 会议待办分派
- `GET /api/files/download` — 受控文件下载
- `GET /api/logistics/summary` — 物流进展汇总（支持全部日期/状态筛选/搜索）
- `GET /api/logistics/shipments` — 运单列表（含在途天数、核查报告链接）
- `GET /api/logistics/dates` — 有数据的录入批次
- `GET /api/logistics/salespeople` — 销售名单（manager+）
- `GET /api/knowledge/scope` — 当前用户可见资料范围
- `POST /api/knowledge/search` — 人工/Agent 共用的带引用检索
- `POST /api/knowledge/answers` — 基于证据的 AI 回答
- `GET /api/knowledge/assets/{id}/content` — 脱敏文本或带水印图片预览
- `POST /api/knowledge/exports` — 管理员确认并填写用途后导出原件

## 经销商资料库接入

PDCA 只在服务端签发最长 5 分钟的作用域 JWT，浏览器不会获得共享密钥。生产环境：

1. 在 PDCA 与 `vertu-data-hub` 主机放置同一份随机密钥文件，权限设为仅部署用户可读。
2. 配置 `PDCA_KNOWLEDGE_HUB_URL` 和 `PDCA_KNOWLEDGE_HUB_TOKEN_KEY_FILE`。
3. 在管理后台的门店资料中填写 data-hub 经销商 UUID；同一经销商的多门店可填写同一 UUID。
4. 用销售账号检查 `/app/knowledge` 只显示本人负责经销商，再用管理员验证原件导出审计。

部门资料范围通过 `PDCA_KNOWLEDGE_HUB_TEAM_MAP` 显式映射，默认把 PDCA 的 `overseas` 映射为 data-hub 的 `overseas-sales`。

## HTTPS

```powershell
.\scripts\setup_ssl.ps1
```

`.env` 设置 `PDCA_SECURE_COOKIES=1`，Docker 使用 `nginx-ssl.conf`：

```bash
docker compose -f docker-compose.yml up -d
# 将 nginx.conf 换为 nginx-ssl.conf 并挂载 certs/
```

## Docker

```bash
docker compose up -d
```

- 应用：http://localhost:8767
- Nginx：http://localhost:8080
- PostgreSQL：localhost:5432

## 环境变量

见 `.env.example`。必填：`PDCA_DATABASE_URL`、`PDCA_SECRET_KEY`。

安全相关默认值：
- `PDCA_TRUST_PROXY_HEADERS=1` 时还必须配置 `PDCA_TRUSTED_PROXY_IPS`，否则代理身份头不会被采信。
- `X-VPS-User-Role` 默认不信任；确需由 SSO 代理写入角色时再显式设置 `PDCA_TRUST_PROXY_ROLE_HEADER=1`。
- 生产 PostgreSQL 不可用时默认拒绝启动，不会静默回退 SQLite；如需回退必须显式 `PDCA_ALLOW_SQLITE_FALLBACK=1`。

