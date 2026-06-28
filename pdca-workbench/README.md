# PDCA 工作台 · 生产环境

基于 **FastAPI + PostgreSQL + JWT 多角色认证** 的本地生产部署。

## 快速启动

```bash
cd pdca-workbench
cp .env.example .env   # 填写 PDCA_DATABASE_URL
pip install -r requirements.txt
python scripts/init_db.py
python run.py
```

访问 http://127.0.0.1:8767/login

## 默认账号

| 用户名 | 密码 | 角色 |
|--------|------|------|
| admin | admin123 | 管理员 |
| manager | manager123 | 主管 |
| sales | sales123 | 销售 |
| viewer | viewer123 | 只读 |

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

### 表单 POST

| 路径 | 权限 | 说明 |
|------|------|------|
| `POST /questionnaire` | sales+ | 保存问卷 → PostgreSQL |
| `POST /todos` | sales+ | 追加代办 → PostgreSQL |
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
