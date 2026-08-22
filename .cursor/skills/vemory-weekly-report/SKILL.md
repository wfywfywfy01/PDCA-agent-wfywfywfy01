---
name: vemory-weekly-report
description: >-
  用 vertu-cli 拉取刘春梅权限范围内的 Vemory 会议，生成本周/本月汇总 JSON 与 HTML 词云周报。
  Use when the user asks for Vemory weekly report, 会议词云, 按周汇总, 刘春梅 Vemory,
  海外经销商会议统计, or to refresh the vemory_weekly HTML dashboard.
---

# Vemory 按周汇总周报

## 目标

在 **刘春梅账号**（或同等 VPS 权限）下，拉取本人 + HR 下属 + 海外销售团队的 Vemory 会议，输出：

1. 周 JSON：`data_raw/liu_vemory_week_YYYY-MM-DD.json`（周一日期）
2. HTML 周报：`data_platform/data_role_pdca_mvp/outputs/vemory_weekly/vemory_weekly_YYYY-MM-DD.html`

页面含 KPI、按人/类型汇总、**会议主题词云**（可筛人员/类型）。

## 前置条件

1. 已安装 `@vertu-tech/vps-cli`，Windows 路径通常为 `%APPDATA%\npm\vertu.cmd`
2. 已登录且 **IM 端点 ok**（Vemory 走 IM）：

```powershell
vertu reauth
vertu whoami
# default 与 im 两行 STATUS 均应为 ok
```

3. 读 vps-cli 技能：`~/.codex/skills/vps-cli/SKILL.md`（或项目内等价文档）

## 权限边界

- **可拉**：本人、HR 下属、已验证的销售（杨晶晶/何海文/王宇彤/于冰/尤文静等）
- **不可拉**：非下属同部门人员（如丁菘）→「你没有权限查询该用户的数据」
- **吴黎**：刘春梅账号曾返回无权限，需管理员开 CLI 策略或本人账号
- **经销商客户**无 Vemory 账号；数据是内部员工的会议录音

## 标准流程（本周）

```
Task Progress:
- [ ] Step 1: vertu reauth
- [ ] Step 2: 拉取本周 JSON
- [ ] Step 3: 补拉/刷新指定销售（若缺失或 0 场）
- [ ] Step 4: 生成 HTML 周报
- [ ] Step 5: 打开 HTML 给用户确认
```

### Step 1: 刷新会话

```powershell
vertu reauth
```

### Step 2: 拉取本周全员

```powershell
python data_raw/pull_liu_vemory_week.py
```

- 输出：`data_raw/liu_vemory_week_<本周一>.json`
- 内置 `SLEEP_SEC=6` 防 API 限流（`odoo_vemory_list_meetings` 约 15/min）
- 人员清单见 `pull_liu_vemory_week.py` 的 `TARGETS`

### Step 3: 补拉销售（于冰/尤文静等）

若某人缺失、或 raw 里 **0 场但应有多场**，用强制刷新：

```powershell
python data_raw/refresh_sales_week.py
```

修改脚本顶部 `WEEK_START` / `WEEK_END` / `JSON_PATH` / `REFRESH` 可指定周与人员。

单人探测：

```powershell
vertu odoo vemory meetings --user-id 13551 --start-date 2026-06-08 --end-date 2026-06-14 --max-meetings 100
```

查 IM uid：

```powershell
# domain 写文件避免 PowerShell 引号问题
vertu odoo data search --endpoint im --model-name res.users --domain "@data_raw/_domain_name.json" --fields id,name,login,mobile --limit 5
```

### Step 4: 生成 HTML

```powershell
python data_platform/data_role_pdca_mvp/scripts/build_vemory_weekly_html.py
```

指定输入：

```powershell
python data_platform/data_role_pdca_mvp/scripts/build_vemory_weekly_html.py --input data_raw/liu_vemory_week_2026-06-08.json
```

一步拉取+生成：

```powershell
python data_platform/data_role_pdca_mvp/scripts/build_vemory_weekly_html.py --pull
```

### Step 5: 打开报告

```powershell
Start-Process "data_platform/data_role_pdca_mvp/outputs/vemory_weekly/vemory_weekly_<周一>.html"
```

## 本月累计（MTD）

```powershell
python data_raw/pull_liu_vemory_mtd.py
```

## 脚本索引

| 脚本 | 用途 |
|------|------|
| `data_raw/pull_liu_vemory_week.py` | 本周全员 Vemory → JSON |
| `data_raw/refresh_sales_week.py` | 强制刷新指定销售并重算 summary |
| `data_raw/pull_liu_vemory_mtd.py` | 本月累计拉取 |
| `data_platform/.../build_vemory_weekly_html.py` | JSON → HTML 词云周报 |
| `data_platform/.../vemory_bridge.py` | 单日会议拉取（工作台复用） |

## HTML 页面结构

- 顶部 KPI：会议总数、时长、有效时长（剔除 >2h 误录）、待办
- 按人汇总表
- 会议类型分布
- **会议主题词云**（wordcloud2.js CDN；筛人员/类型/关键词）

**不包含**：按日汇总表、会议明细表（已按产品要求移除）。

## 常见问题

| 现象 | 处理 |
|------|------|
| `RATE_LIMITED` | 间隔 8–10s 再拉；不要一次 burst |
| 某人 0 场但应有数据 | 跑 `refresh_sales_week.py` 覆盖空记录 |
| IM 401 | `vertu reauth --endpoint im` |
| 词云空白 | 检查 CDN；或本地引 wordcloud2 |
| 今天周一却找不到 JSON | 文件名用**该周周一**日期，不是今天 |

## 维护 TARGETS

新增销售时，在 `pull_liu_vemory_week.py` 的 `TARGETS` 追加 `(im_uid, "姓名")`：

```python
(13063, "于冰"),
(13551, "尤文静"),
(13122, "杨晶晶"),
# ...
```

先用 `vertu odoo data search --endpoint im` 查 uid，再 `--user-id` 试拉确认权限。

## 相关技能

- **vps-cli**：登录、IM 端点、引号约定
- **cursor-daily-report**：Cursor 团队日报（transcripts，与 Vemory 不同数据源）
