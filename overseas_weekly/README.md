# 海外经销商周报（总览 MVP）

对齐《海外经销商2026年7月第二周周报》前半部分：全盘 KPI + 三组达成 + 区域/代理商贡献。

## 三套口径（2026-07-16）

| 口径 | JSON 字段 | 规则 | 用途 |
|------|-----------|------|------|
| **dealer_owner** | `headline` / `groups` | 经销商 → 配置销售 → 汇报组 | OKR 主口径（含跟单记名） |
| **ppt** | `headline_ppt` / `groups_ppt` | owner − `non_team_salespeople` | **对齐 PPT 组数**（剔 郑丽苹/陈晓霜） |
| **salesperson_aligned** | `groups_aligned` / `people` | 按 Odoo「销售人员」映射 | 个人贡献表 |

非团队记名见 `config/dealers.json` → `attribution.non_team_salespeople`。  
W2 校验：`py overseas_weekly/scripts/verify_ppt_align.py`（应对齐通过）。

## 目录

- `config/dealers.json` — 代理商/销售/OKR/归口规则
- `scripts/fetch_overview.py` — 取数
- `scripts/verify_ppt_align.py` — W2 PPT 对齐自检
- `outputs/<week>_overview.json` — 结果
- `outputs/<week>_raw_lines.json` — 行级复盘

## 取数

```powershell
py overseas_weekly/scripts/fetch_overview.py --as-of 2026-07-12
py overseas_weekly/scripts/verify_ppt_align.py
py overseas_weekly/scripts/fetch_overview.py --as-of 2026-07-16   # 本周
```

## 汇报分组

| 组 | 成员 |
|----|------|
| Lina组 | Lina、Viki、尤文静、刘彦麟 |
| 于冰组 | 于冰 |
| 杨晶晶组 | 杨晶晶、何海文、Vivi |

## 仍需人工

- Sell-out / 待收款 / 家具台账（约 19 万未进 odoo_sale）
- 各组叙事、线索盘点、商务跟单
