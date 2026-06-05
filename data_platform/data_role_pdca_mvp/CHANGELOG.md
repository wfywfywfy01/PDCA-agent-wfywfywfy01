# 更新日志

## 2026-06-05 — 今日 ToDo 与任务中心分工

- **今日 ToDo**（左侧）：保留昨日日报明日计划列表，无 PDCA 按钮。
- **任务中心**（底部原位置）：仅作 PDCA 日结入口（统计 +「PDCA 日结」→ `/pdca-vps`）。
- 首页分块独立请求，单接口失败不再拖垮整页。

---

## 2026-06-05 — Sell Out 卡片接入客流分析台

- 经营首页移除快捷按钮「海外客流」「线上经营」；**Sell Out 卡片**点击进入 `/walkin-cockpit/`（海外客流 + 线上经营同一模块）。

---

## 2026-06-05 — 今日 ToDo 接入 PDCA 日结

- 经营首页「今日 ToDo」改为 **昨日群日报「明日计划」**（`vertu odoo daily-report user-summary`），与 `/pdca-vps` 同源。
- `/api/todos/today?date=` 返回计划项含进度、截止日；点击待办或「PDCA 日结」进入日结页做交付检查。

---

## 2026-06-05 — 会议中心（Vemory 复盘与任务分配）

### 新增

- **会议中心页面**（`/meeting-center`）：从 Vemory 拉取会议列表、AI 摘要、章节纪要；会议 Todo 自动推断负责人并 **写入 VPS 待办**。
- **API**：`/api/meeting-center/summary|meetings|people|dispatch`；数据优先 **8787 客户管理缓存 → vertu odoo vemory meetings → 本地 JSON 缓存**（`scripts/vemory_bridge.py`）。
- 经营首页「会议中心」卡片与「跳转 Vemory」均进入 `/meeting-center`（支持 `#filter=interview` 等筛选）。

---

## 2026-06-05 — 经销商工作台驾驶舱合并与数据链路

### 新增

- **经营驾驶舱首页**（`modules/home_dashboard/`）：浅灰底 KPI 卡片、Sell In 与看板「实际达成」同源（`chart_data.json`）、快捷入口。
- **海外客流分析台**（`modules/walkin_cockpit/`）：代理商终销 + 越南 walk-in 参考数据；总—大区—门店三级展示。
- **线上经营并入客流分析**（`online-merged-insights.js`）：
  - 真实销售 ÷ 经销商 OKR 表（含 VERTU 介绍业绩 mock 列）
  - 各渠道线索、区域线索堆叠、客户来源（自有 vs VERTU 推送）
  - 区域汇总表（越南四店区域/门店数来自 Excel，其余列 mock）
- **工作台 API**：`GET /api/walkin?month=&date=`，数据优先级 **vertu CLI → Excel 固化 JSON → mock**（`scripts/workbench_data.py`）。
- **数据同步脚本**：`scripts/sync_workbench_data.py`（可选拉 VPS + 导入两份桌面 Excel + 生成 `walkin-*.json`）。
- **文档**：`docs/WORKBENCH_FRONTEND_GUIDE.md`（端口、路径、皮肤、数据说明）。

### 变更

- `scripts/pdca_workbench.py`：`/` 默认首页改为经营驾驶舱；`/home-classic` 保留原四卡首页；托管 walkin/online 静态模块并注入统一皮肤与 **「← 返回工作台」**；看板注入 `workbench-unified.css`。
- `templates/dashboard_template.html`：顶栏浅色、OKR 区左对齐（完成率与圆环并排）。
- 文案：**「线下事业部」→「经销商」**（界面与入口说明）。
- `/online-cockpit/` 重定向至 `/walkin-cockpit/#oi-merged`。
- `config/data_sources.json`：指向当前 VPS 经销商业绩 JSON。

### 数据文件（入库，运行时只读 JSON）

| 文件 | 来源 |
|------|------|
| `walkin_cockpit/data/dealer_distribution_reference.json` | 代理商终销表 |
| `walkin_cockpit/data/vietnam_store_metrics.json` | `越南门店数据.xlsx` |
| `walkin_cockpit/data/vn_data_collect_reference.json` | `Data collecet(5).xlsx` |
| `walkin_cockpit/data/online_channel_reference.json` | 渠道/OKR 参考结构 |
| `walkin_cockpit/data/walkin-2026-05.json` / `walkin-2026-06.json` | 构建脚本生成 |

### 运维

```powershell
$env:PDCA_WORKBENCH_PORT='8767'
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\pdca_workbench.py

# 同步参考数据（Excel + 可选 VPS）
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\sync_workbench_data.py --date 2026-06-05
```

### 未纳入本提交

- `outputs/`、`outbox/`、按日问卷/待办输入等业务运行产物（仍保持本地未跟踪或忽略）。
- `dealer_pdca/`、`data_requests/` 等并行实验目录。
