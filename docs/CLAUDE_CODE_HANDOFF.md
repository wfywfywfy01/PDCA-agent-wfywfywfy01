# 经销商 PDCA 项目 · Claude Code 交接文档

> 用途：交给 Claude Code 做二次开发前的项目地图。  
> 仓库根目录：`D:\经销商PDCA`  
> 文档更新：2026-06-08

---

## 1. 项目是什么

面向海外经销商团队的 **PDCA 经营管理工作台**：销售日报、业绩看板、物流核查、每日待办、会议中心、客流/线上 OKR、Agent/Hermes 调度、Check/Act 报告。

**当前主服务**（请优先改这里）：

| 项 | 值 |
|---|---|
| 目录 | `D:\经销商PDCA\pdca-workbench` |
| 技术栈 | FastAPI + Uvicorn + SQLModel + PostgreSQL（可回退 SQLite）+ JWT Cookie 多角色 |
| 默认端口 | **8767** |
| 登录 | http://127.0.0.1:8767/login |
| 启动 | `cd pdca-workbench && python scripts/init_db.py && python run.py` |

**遗留单体**（逻辑仍被桥接调用，勿随意删）：

| 项 | 值 |
|---|---|
| 脚本 | `D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\pdca_workbench.py` |
| 原端口 | 8765（已由 `pdca-workbench` 替代对外服务） |
| 日结流水线 | `data_platform\data_role_pdca_mvp\scripts\data_role_pdca_daily.py` |

**业务数据根（MVP）**：

`D:\经销商PDCA\data_platform\data_role_pdca_mvp`

---

## 2. 仓库目录地图

```text
D:\经销商PDCA\
├── AGENTS.md                          # Agent 分工与 MVP 业务规则（必读）
├── docs\
│   └── CLAUDE_CODE_HANDOFF.md         # 本文档
├── pdca-workbench\                    # ★ 生产 FastAPI 服务（主改代码区）
│   ├── app\
│   │   ├── main.py                    # 应用入口、路由注册、健康检查
│   │   ├── config.py                  # 环境变量与路径
│   │   ├── database.py                # PG/SQLite 引擎、bootstrap 回退
│   │   ├── logging_setup.py
│   │   ├── auth\                      # 用户、JWT、角色 seed
│   │   ├── legacy\bridge.py           # 桥接 pdca_workbench.py
│   │   ├── pages\router.py            # HTML 页面 GET + Vue 顶栏注入
│   │   ├── pdca\post_router.py        # 表单 POST（问卷/待办/物流/run…）
│   │   ├── logistics\                 # 物流 API + service
│   │   ├── dashboard\                 # 经营首页 API
│   │   ├── walkin\                    # 客流/线上 OKR API
│   │   ├── meeting\                   # 会议中心 API
│   │   ├── files\                     # 受控文件下载
│   │   ├── admin\                     # 管理/同步
│   │   ├── models\                    # SQLModel 表 + writes.py 写库
│   │   ├── scheduler\                 # 定时同步
│   │   └── vertu\                     # vertu CLI 客户端
│   ├── frontend\
│   │   ├── login.html
│   │   └── shared\shell.js            # Vue 顶栏导航
│   ├── data\pdca_local.sqlite         # PG 不可用时的本地回退库
│   ├── scripts\init_db.py
│   ├── run.py
│   ├── .env / .env.example
│   └── README.md
│
├── data_platform\data_role_pdca_mvp\   # ★ 业务数据 + 前端模块 + 脚本
│   ├── inputs\
│   │   ├── logistics\{date}_tracking.csv    # 物流单号录入
│   │   ├── todos\{date}_todos.csv
│   │   └── questionnaires\{date}_questionnaire.md
│   ├── outputs\{date}\                    # 日结输出
│   │   ├── logistics_check_report.md
│   │   ├── {date}_logistics_results.csv
│   │   ├── pdca_daily_check.md
│   │   ├── data_summary_report.md
│   │   ├── dashboard.html
│   │   └── chart_data.json
│   ├── modules\                           # 静态前端模块（由 pages 路由托管）
│   │   ├── logistics_center\index.html    # 物流进展看板
│   │   ├── walkin_cockpit\                 # 客流/线上 OKR
│   │   ├── meeting_center\
│   │   └── home_dashboard\
│   ├── config\
│   │   ├── carriers.json                  # 承运商查询 URL 模板
│   │   ├── settings.json                  # logistics 异常/正常关键词
│   │   └── sales_aliases.csv              # 销售姓名别名
│   ├── scripts\
│   │   ├── pdca_workbench.py              # 遗留工作台（3962 行）
│   │   └── data_role_pdca_daily.py        # 日结流水线
│   └── docs\
│       └── PROJECT_DESIGN_AND_FEATURES.md # 更完整的产品设计（旧端口 8765 描述）
│
├── teams\yang-jingjing\                   # 小组 PDCA 文件（日报/检查/行动）
├── dealer_pdca\                           # 另一套经销商驾驶舱（独立子项目）
├── dist\                                  # 静态演示 zip
└── data_raw\ / data_requests\             # 拉数 DSL/脚本（非工作台核心）
```

---

## 3. 环境与配置

复制 `pdca-workbench\.env.example` → `.env`，关键变量：

| 变量 | 说明 |
|------|------|
| `PDCA_WORKBENCH_PORT` | 默认 `8767` |
| `PDCA_DATABASE_URL` | PostgreSQL 连接串（用户自建库） |
| `PDCA_MVP_ROOT` | 指向 `data_platform/data_role_pdca_mvp` |
| `PDCA_REPO_ROOT` | 仓库根 `D:\经销商PDCA` |
| `PDCA_SECRET_KEY` | JWT 密钥 |
| `VERTU_COMMAND` | 默认 `vertu` |

**数据库策略**（`app/database.py`）：

1. 启动时 `bootstrap_database()` 优先连 PostgreSQL。
2. 连不上则自动回退 `pdca-workbench/data/pdca_local.sqlite`（模式 `sqlite-fallback`）。
3. 健康检查：`GET /health` 返回 `database` 字段。

**默认账号**（`app/auth/models.py` → `DEFAULT_USERS`）：

| 用户名 | 密码 | 角色 | 说明 |
|--------|------|------|------|
| admin | admin123 | admin | 管理员 |
| manager | manager123 | manager | 主管 |
| sales | sales123 | sales | 销售，`sales_name=何海文` |
| viewer | viewer123 | viewer | 只读 |

销售账号的 `sales_name` 用于物流 CSV 字段 `salesperson` 过滤。

---

## 4. 角色与权限

角色等级（`app/auth/models.py`）：`viewer(0) < sales(1) < manager(2) < admin(3)`。

| 能力 | viewer | sales | manager | admin |
|------|--------|-------|---------|-------|
| 看页面/API | ✓ | ✓ | ✓ | ✓ |
| 录入问卷/待办/物流 | | ✓ | ✓ | ✓ |
| 运行 PDCA `POST /run` | | | ✓ | ✓ |
| Hermes 对话 | | | ✓ | ✓ |
| Agent 文件编辑 | | | | ✓ |
| 物流按销售筛选 | | 仅本人 | 全部+筛选 | 全部+筛选 |

认证：`pdca_token` httpOnly Cookie 或 Bearer JWT。依赖见 `app/auth/deps.py`。

---

## 5. 路由速查

### 5.1 页面（GET）

| 路径 | 说明 | 实现 |
|------|------|------|
| `/` | 经营驾驶舱 | `dashboard` + legacy |
| `/home-classic` | 经典工作台 | bridge |
| `/logistics-center/` | **物流进展看板** | `modules/logistics_center/index.html` |
| `/logistics` | 物流单号录入 | bridge `render_logistics` |
| `/questionnaire` | 每日问卷 | bridge |
| `/todos` | 待办录入 | bridge |
| `/pdca-vps` | PDCA 日结 | bridge |
| `/walkin-cockpit/` | 客流/线上 OKR | 静态模块 |
| `/meeting-center/` | 会议中心 | 静态模块 |
| `/view-path` | Hermes 结果预览 | bridge |
| `/open-path` | 打开本地输出文件 | `pages/router.py` |

HTML 页面通过 `pages/helpers.py` 注入 Vue 顶栏（`frontend/shared/shell.js`）。

### 5.2 表单 POST

| 路径 | 权限 | 写 PostgreSQL |
|------|------|----------------|
| `POST /questionnaire` | sales+ | `writes.upsert_daily_report` |
| `POST /todos` | sales+ | `writes.insert_pdca_task` |
| `POST /logistics` | sales+ | CSV + `writes.upsert_logistics_shipment` |
| `POST /run` | manager+ | 触发日结 + 同步 |
| `POST /pdca-task` | sales+ | `writes.update_pdca_task_from_form` |
| `POST /hermes-chat` | manager+ | — |
| `POST /agent-soul` 等 | admin | 写 Agent 文件 |

实现：`app/pdca/post_router.py`。

### 5.3 物流 API

前缀：`/api/logistics`

| 端点 | 说明 |
|------|------|
| `GET /dates` | 有录入数据的批次日期列表 |
| `GET /summary` | 汇总（支持筛选） |
| `GET /shipments` | 运单列表 |
| `GET /salespeople` | 销售名单（manager+） |

查询参数：

- `date`：`YYYY-MM-DD` 或 `all`（默认前端用 `all`）
- `salesperson`：主管筛选销售
- `status`：`all` / `attention` / `transit` / `delivered`
- `q`：搜索单号/客户/承运商
- `open_only`：仅看在途

实现：

- API：`pdca-workbench/app/logistics/router.py`
- 业务：`pdca-workbench/app/logistics/service.py`
- 页面：`data_platform/.../modules/logistics_center/index.html`

---

## 6. 物流模块详解（近期重点）

### 6.1 数据流

```text
销售录入 POST /logistics
  → inputs/logistics/{date}_tracking.csv（legacy bridge.append_logistics）
  → PostgreSQL logistics_shipments（writes.upsert_logistics_shipment）

主管 POST /run（日结）
  → data_role_pdca_daily.build_logistics_report()
  → outputs/{date}/{date}_logistics_results.csv
  → outputs/{date}/logistics_check_report.md

看板 GET /api/logistics/*
  → service.load_shipments() 合并 inputs + outputs
  → 按 sales_name / 筛选条件过滤
```

### 6.2 CSV 字段（`templates/logistics_tracking_template.csv`）

`tracking_number`, `carrier`, `customer`, `salesperson`, `ship_date`, `expected_status`, `current_status`, `note`

### 6.3 状态判断逻辑

`service._judge_status()` + `config/settings.json` 内 `logistics.abnormal_keywords` / `normal_keywords`：

- **异常**：状态含异常关键词
- **待关注**：发货超过 7 天未签收
- **运输中** / **待核查** / **正常（已签收）**
- 输出：`judgement`, `reason`, `progress_pct`, `days_in_transit`, `is_delivered`

### 6.4 已知缺口（可交给 Claude Code 继续）

- [ ] 物流录入 CSV 与 `outputs` 多日期分散，inputs 里目前仅 `2026-05-28_tracking.csv` 有演示数据
- [ ] PostgreSQL `logistics_shipments` 与 CSV 未做全量双向同步
- [ ] 承运商 API 自动查单（仅有官网链接 + `logistics-browser-agent` 设计）
- [ ] 经营首页 `/` 尚无物流卡片入口
- [ ] 更多销售账号与 `sales_name` 映射
- [ ] 导出 Excel / 按客户分组视图
- [ ] 远程 PG `10.100.0.176` 间歇超时，需网络或改连本地 Docker PG

---

## 7. 数据库表（SQLModel）

| 表 | 文件 | 用途 |
|----|------|------|
| `users` | `app/auth/models.py` | 登录、`sales_name` |
| `daily_reports` | `app/models/daily_report.py` | 问卷/日报 |
| `pdca_tasks` | `app/models/pdca_task.py` | 待办 |
| `logistics_shipments` | `app/models/logistics.py` | 物流镜像 |
| `meeting_records` | `app/models/meeting.py` | 会议 |
| `dealer_sales` | `app/models/dealer_sales.py` | 经销商销售 |

写库辅助：`app/models/writes.py`。同步：`app/models/sync.py`。

---

## 8. 遗留桥接（改业务时注意）

`app/legacy/bridge.py` 动态 import `pdca_workbench.py`，暴露：

- `render_home`, `render_logistics`, `append_logistics`, `run_pdca`
- `api_dashboard_overview`, `api_todos_today`, …

**原则**：小改可继续桥接；大改应逐步迁到 `pdca-workbench/app/` 下独立模块。

日结核心：`data_role_pdca_daily.py` 的 `build_logistics_report()` 生成物流核查结果。

---

## 9. 业务规则（来自 AGENTS.md）

- 每日每销售一份日报；缺失 → 高风险 Check
- 默认日过程指标：新增客户 3、有效触达 15、跟进 8、报价 2、重点客户 2、日报 1
- A 类客户超 7 天未跟进、B/C 超 14 天 → 超期风险
- 空字段留空，不写「无」；日期 `YYYY-MM-DD`；客户名对齐 `customers.csv`

小组资料：`teams/yang-jingjing/`（`daily_logs/`, `check_reports/`, `pdca_actions/` 等）。

---

## 10. 给 Claude Code 的修改指引

### 10.1 改物流看板 UI

→ 编辑 `data_platform/data_role_pdca_mvp/modules/logistics_center/index.html`  
样式可引用 `/workbench-cockpit-shell.css`（由服务静态托管）。

### 10.2 改物流 API / 过滤逻辑

→ `pdca-workbench/app/logistics/service.py` + `router.py`

### 10.3 改录入表单

→ legacy：`pdca_workbench.py` 的 `render_logistics` / `append_logistics`  
→ 生产 POST：`pdca-workbench/app/pdca/post_router.py`

### 10.4 改导航顶栏

→ `pdca-workbench/frontend/shared/shell.js`

### 10.5 改页面路由 / 注入顶栏

→ `pdca-workbench/app/pages/router.py` + `helpers.py`

### 10.6 改日结物流核查规则

→ `data_role_pdca_mvp/scripts/data_role_pdca_daily.py` 的 `judge_logistics` / `build_logistics_report`

### 10.7 新增 API

在 `app/` 下建 `router.py`，在 `app/main.py` 里 `include_router`。

---

## 11. 本地验证清单

```powershell
cd D:\经销商PDCA\pdca-workbench
python scripts/init_db.py
python run.py
```

1. `GET http://127.0.0.1:8767/health` → `status: ok`
2. 登录 `sales` / `sales123`
3. 打开 http://127.0.0.1:8767/logistics-center/ → 默认「全部日期」应有演示运单（何海文 1 条，`2026-05-28` 批次）
4. 主管 `manager` 登录 → 可看 2 条 + 销售筛选
5. `POST /run` 后检查 `outputs/{today}/logistics_check_report.md` 是否更新

---

## 12. 其他子项目（一般不动工作台主链）

| 目录 | 说明 |
|------|------|
| `dealer_pdca/` | 经销商 PDCA 驾驶舱（独立 API + 前端） |
| `team-reports/` | 团队周报相关 |
| `data_raw/` / `data_requests/` | Odoo/VPS 拉数 DSL |

更完整产品设计（含旧 8765 架构）：  
`data_platform/data_role_pdca_mvp/docs/PROJECT_DESIGN_AND_FEATURES.md`

静态演示包：`dist/pdca-demo-static.zip`（仅 HTML + 固化 JSON）。

---

## 13. 注意事项

- **不要**在文档或提交中硬编码生产数据库密码；只用 `.env`。
- **不要**删除 `pdca_workbench.py`，生产环境仍桥接其业务函数。
- Windows 路径含中文「经销商」，脚本里建议用绝对路径或已配置的 `PDCA_MVP_ROOT`。
- 改完 Python 需重启 `python run.py`（`reload=False`）。
- 仅用户明确要求时才 `git commit`；仓库有大量未跟踪的 `outputs/` 与日结产物。

---

## 14. 建议 Claude Code 任务示例

可复制到 Claude Code 作为任务描述：

```text
在 D:\经销商PDCA 仓库中：
1. 阅读 docs/SIGNALSELLER_PDCA_INTEGRATION.md（SignalSeller 融合方案）
2. 阅读 docs/CLAUDE_CODE_HANDOFF.md 与 AGENTS.md
3. 按融合方案改造客户管理 8787 + customers.csv ABCD 字段
4. 完成新人培训打卡持久化与上岗测验
```

按需删减即可。

## 15. SignalSeller 获客方法论

- 融合方案：`docs/SIGNALSELLER_PDCA_INTEGRATION.md`
- 方法配置：`data_platform/data_role_pdca_mvp/config/signalseller_methodology.json`
- 培训课表：`data_platform/data_role_pdca_mvp/config/onboarding_curriculum.json`
- 培训入口：http://127.0.0.1:8767/onboarding-center/
