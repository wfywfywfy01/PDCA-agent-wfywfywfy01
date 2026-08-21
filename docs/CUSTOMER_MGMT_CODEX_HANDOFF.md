# 客户管理 · Codex 交接地图

> 给 Codex / 外部开发者：PDCA「客户管理」模块代码位置、架构与启动方式。  
> 主仓库：`D:\经销商PDCA`  
> 更新：2026-06-22

---

## 1. 一句话架构

客户管理是 **双服务**：

| 服务 | 端口 | 角色 |
|------|------|------|
| **pdca-workbench** | **8767** | 统一登录、顶栏导航、iframe 壳、SignalSeller API、获客指挥 |
| **he-haiwen-dealer-workbench** | **8787** | 客户管理 **本体**（漏斗、任务、WhatsApp、VPS 客户、触达 Tab） |

8767 的 `/customer-mgmt` 用 iframe 嵌入 8787；8787 可单独打开。

```text
浏览器
  → http://127.0.0.1:8767/customer-mgmt   （需登录）
       → iframe → http://127.0.0.1:8787/
  → http://127.0.0.1:8787/                （直连客户管理后端+前端）
```

---

## 2. 代码根目录（给 Codex 打开的工作区）

### 2.1 主仓库 · 8767 壳 + PDCA 数据

```text
D:\经销商PDCA\
```

| 路径 | 说明 |
|------|------|
| `pdca-workbench/` | FastAPI 生产服务（8767） |
| `pdca-workbench/app/pages/router.py` | `/customer-mgmt` 路由 |
| `pdca-workbench/app/legacy/bridge.py` | 调 legacy `pdca_workbench.py` |
| `pdca-workbench/app/signalseller/` | ABCD、跟进任务、Outreach API（读 CSV） |
| `data_platform/data_role_pdca_mvp/scripts/pdca_workbench.py` | `CUSTOMER_MGMT_ROOT`、`ensure_customer_server()`、iframe HTML |
| `teams/yang-jingjing/customers.csv` | PDCA 客户台账（ABCD 扩展列） |
| `docs/SIGNALSELLER_PDCA_INTEGRATION.md` | SignalSeller × 客户管理融合方案 |
| `docs/CLAUDE_CODE_HANDOFF.md` | 全项目总地图 |

### 2.2 客户管理本体 · 8787（**改 UI/客户 API 主要在这里**）

```text
C:\Users\frank\Documents\Codex\2026-05-27\pdca-codex-1-guru-electronics-singapore\he-haiwen-dealer-workbench\
```

| 文件 | 说明 |
|------|------|
| `server.py` | HTTP 服务 8787；VPS/Odoo、Vemory、WhatsApp、SQLite、`/api/state` |
| `index.html` | Alpine.js 主 UI（任务、漏斗、客户、WhatsApp、应收、管理大盘、**触达文案 Tab**） |
| `dealer-adapter.js` | 真实数据模式：VPS 客户、新人/老人任务配额、Hermes、禁止 Mock |
| `signalseller-bridge.js` | ABCD 徽章、沉默天数（前端桥接） |
| `outreach_engine.py` | 本地 FABE/私信/SPIN；可代理 8767 Hermes |
| `pdca_team_csv.py` | 合并 `teams/.../customers.csv` → VPS 客户 ABCD 字段 |
| `data/dealer_workbench.db` | SQLite（`app_state` + 基础表） |
| `CURSOR_HANDOFF.md` | 8787 项目内交接说明 |
| `run.bat` | 双击启动 8787 |

**注意：** 8787 在 Codex 独立目录，**未纳入** `D:\经销商PDCA` git；8767 通过硬编码路径引用（见下）。

---

## 3. 硬编码路径（改部署时要同步）

```python
# data_platform/data_role_pdca_mvp/scripts/pdca_workbench.py
CUSTOMER_MGMT_ROOT = Path(
    r"C:\Users\frank\Documents\Codex\2026-05-27\pdca-codex-1-guru-electronics-singapore\he-haiwen-dealer-workbench"
)
CUSTOMER_MGMT_PORT = 8787
```

---

## 4. 页面入口（浏览器）

| URL | 说明 |
|-----|------|
| http://127.0.0.1:8767/login | 8767 登录 |
| http://127.0.0.1:8767/customer-mgmt | 客户管理（iframe） |
| http://127.0.0.1:8767/signalseller-center/ | 获客指挥（CSV ABCD，非 8787 UI） |
| http://127.0.0.1:8787/ | 8787 客户管理直连 |

默认账号（8767）：`admin/admin123`、`manager/manager123`、`sales/sales123`（`sales_name=何海文`）

---

## 5. 启动命令

```powershell
# 8767 工作台
cd D:\经销商PDCA\pdca-workbench
python scripts/init_db.py
python run.py

# 8787 客户管理（8767 也会尝试自动拉起，但建议手动先起）
cd C:\Users\frank\Documents\Codex\2026-05-27\pdca-codex-1-guru-electronics-singapore\he-haiwen-dealer-workbench
python server.py
```

旧版一体工作台（数据岗位 bat，非 8767）：

```text
D:\经销商PDCA\data_platform\data_role_pdca_mvp\数据岗位PDCA工作台.bat
```

---

## 6. 数据流

```text
VPS/Odoo res.partner + DEALER_ROSTER
    → 8787 GET /api/vps/dealer-customers
    → dealer-adapter.js loadDealerVpsData()
    → index.html 漏斗 / 客户列表 / 今日任务

teams/yang-jingjing/customers.csv
    → 8787 pdca_team_csv.merge_pdca_csv() enrich ABCD
    → 8767 signalseller/service.load_customers() 获客指挥

8787 前端状态
    → POST /api/state → SQLite app_state
    → 8767 signalseller try_fetch_8787_customers()（可选，8787 在线时）
```

**真实数据模式：** `dealer-adapter.js` 会清空 localStorage Mock，**只展示 VPS 返回 + CSV enrich**；无 VPS 时列表为空。

---

## 7. API 清单

### 7.1 8787（客户管理）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/vps/dealer-customers` | 主数据源：用户 + 客户 + 交互 |
| GET | `/api/pdca/team-customers` | PDCA CSV 只读列表 |
| GET/POST | `/api/state` | 全量前端状态持久化 |
| POST | `/api/outreach/generate` | FABE / 私信 / SPIN |
| GET | `/api/signalseller/abcd-map?level=A` | level → ABCD |
| GET | `/api/vemory/meetings` | 会议 Todo |
| GET | `/api/whatsapp/accounts` | WhatsApp |
| GET | `/api/customers/{id}` | 单客户 + 交互 |

### 7.2 8767（壳 + SignalSeller）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/customer-mgmt` | iframe 壳 |
| GET | `/api/signalseller/summary` | ABCD KPI |
| GET | `/api/signalseller/customers` | CSV 客户 + 评分 |
| GET | `/api/signalseller/followup-tasks` | 今日跟进建议 |
| POST | `/api/signalseller/outreach/generate` | 触达文案（需 sales+ 登录） |

---

## 8. 8787 前端 Tab 结构（index.html）

| Tab id | 名称 | 关键逻辑 |
|--------|------|----------|
| `tasks` | 今日任务 | `dealer-adapter` 配额 + `getTodayTasks()` |
| `funnel` | 漏斗看板 | `getFunnelCustomers()` + ABCD 徽章 |
| `outreach` | 触达文案 | `generateOutreach()` → `/api/outreach/generate` |
| `customers` | 客户管理 | VPS 客户表、`getDealerCustomerRows()` |
| `whatsapp` | WhatsApp | `/api/whatsapp/*` |
| `receivables` | 应收管理 | local + VPS |
| `manager` | 管理大盘 | 组长/总监 |

Alpine 根对象：`appData()` in `index.html`；经销商扩展在 `dealer-adapter.js` 包装 `window.appData`。

---

## 9. 配置与方法论

| 路径 | 用途 |
|------|------|
| `data_platform/data_role_pdca_mvp/config/signalseller_methodology.json` | ABCD、触发器、KPI |
| `data_platform/data_role_pdca_mvp/config/onboarding_curriculum.json` | 新人 5 天课表 |
| `AGENTS.md` | 小组 PDCA 规则（超期天数、过程指标） |

---

## 10. Codex 建议阅读顺序

1. 本文档  
2. `he-haiwen-dealer-workbench/CURSOR_HANDOFF.md`  
3. `he-haiwen-dealer-workbench/dealer-adapter.js`（数据从哪来）  
4. `he-haiwen-dealer-workbench/server.py` → `get_vps_dealer_customers()`  
5. `he-haiwen-dealer-workbench/index.html` → `appData()` / Tab  
6. `docs/SIGNALSELLER_PDCA_INTEGRATION.md` §3 客户管理融合  
7. `pdca-workbench/app/signalseller/service.py`（8767 侧 CSV）

---

## 11. 已知缺口（改代码前知晓）

- 8787 与 `customers.csv` **无双向写回**（仅 enrich 读 CSV）  
- 8787 项目路径在 8767 外，需单独 git / 同步  
- 获客指挥（8767）与客户管理（8787）**两套客户视图**，尚未完全统一  
- 物流单号与客户管理 **未关联**（物流在 `inputs/logistics/` 另一模块）

---

## 12. 给 Codex 的复制用路径块

```text
交接文档:
  D:\经销商PDCA\docs\CUSTOMER_MGMT_CODEX_HANDOFF.md

8767:
  D:\经销商PDCA\pdca-workbench\
  D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\pdca_workbench.py

8787 客户管理:
  C:\Users\frank\Documents\Codex\2026-05-27\pdca-codex-1-guru-electronics-singapore\he-haiwen-dealer-workbench\

客户 CSV:
  D:\经销商PDCA\teams\yang-jingjing\customers.csv
```
