# SignalSeller × 经销商 PDCA 融合方案

> 给 Claude Code / 开发者的实施文档  
> 来源：`SignalSeller_AI获客Agent_产品文档_v1.docx`（《签单手账》方法论）  
> 目标：融入 **客户管理（8787）** + **新人培训** + **现有 PDCA Check/Act**  
> 仓库：`D:\经销商PDCA`  
> 更新：2026-06-08

---

## 0. 一句话目标

把 SignalSeller 的 **「五 Agent + ABCD + 三轮触达 + PDCA 复盘」** 落到现有经销商 PDCA 工作台里，让销售在 **客户管理** 里按方法论干活，新人在 **培训模块** 里 5 天上岗，主管在 **CommandCenter/PDCA Check** 里看指标与异常。

---

## 1. 现有系统盘点（改之前先看）

### 1.1 已有什么

| 模块 | 路径 / 入口 | 现状 |
|------|-------------|------|
| 生产工作台 | `pdca-workbench/` · `:8767` | FastAPI + JWT + 物流/会议/驾驶舱 |
| 客户管理 | `/customer-mgmt` → iframe `8787` | 外部项目 `he-haiwen-dealer-workbench` |
| 客户台账 | `teams/yang-jingjing/customers.csv` | region, owner, priority, last_followup_date… |
| PDCA 规则 | `AGENTS.md` | A 类 7 天、B/C 14 天超期；过程指标 |
| 销售日报 | `teams/.../daily_logs/` | 每日 Do 记录 |
| 新人模式 | 8787 `dealer-adapter.js` | 新人/老人配额（新增、S/A 维护） |
| 日结脚本 | `data_role_pdca_daily.py` | Check 报告、物流、待办 |

### 1.2 客户管理外部项目位置

```text
C:\Users\frank\Documents\Codex\2026-05-27\pdca-codex-1-guru-electronics-singapore\he-haiwen-dealer-workbench\
  server.py          # 8787
  index.html         # Alpine.js 全周期 UI（漏斗/任务/规则）
  dealer-adapter.js  # 新人老人配额、任务生成
```

`pdca_workbench.py` 中 `CUSTOMER_MGMT_ROOT` 指向上述路径；**融合客户管理时主要改这里 + 8767 路由**。

### 1.3 与 SignalSeller 的差距

| SignalSeller | 现有 PDCA | 缺口 |
|--------------|-----------|------|
| ABCD 动态分级 | priority A/B/C + 8787 S/A | 缺 D 类培育流、缺 value/intent 评分 |
| 5 Agent 协同 | 分散脚本 + Hermes 概念 | 未产品化为模块 |
| 三轮触达状态机 | 手动跟进 | 无 FollowUpState |
| FABE/SPIN 内容 | 无 | 需 OutreachCrafter 或模板库 |
| 渠道 ROI 看板 | 驾驶舱偏业绩 | 缺获客漏斗指标 |
| 新人 5 天体系 | 8787 新人配额 | 缺标准课程与测验 |

---

## 2. 方法论映射（书 → Agent → PDCA 模块）

| 花色 | 方法论 | SignalSeller Agent | 融入 PDCA 的位置 |
|------|--------|-------------------|------------------|
| ♥ 红桃 | SPIN / FABE / 卖点 | **OutreachCrafter** | 客户详情「触达文案」Tab；日报模板 |
| ♣ 梅花 | 分类 / 破冰 / 情绪 | **FollowUpOrchestrator** | 客户「跟进状态机」；超期 Check |
| ♦ 方块 | ABCD / SOP / 触发 | **ProfileBuilder** | customers.csv 扩展字段；8787 分级 |
| ♠ 黑桃 | 13 种获客 / 转介绍 | **SignalHunter** | 线索池 Tab；成交后转介绍 SOP |
| 全局 | PDCA / 三大报表 | **CommandCenter** | 8767 驾驶舱 + 日/周/月 Check |

机器可读配置已落盘：

- `data_platform/data_role_pdca_mvp/config/signalseller_methodology.json`
- `data_platform/data_role_pdca_mvp/config/onboarding_curriculum.json`

---

## 3. 客户管理融合设计

### 3.1 统一客户分级（ABCD ↔ 现有 priority）

**建议 customers.csv 扩展字段**（向后兼容，新列可空）：

```csv
region,country,dealer_name,dealer_nickname,owner,priority,status,last_followup_date,next_action,
abcd_grade,value_score,intent_score,lead_source,followup_round,silent_days,referral_from
```

| ABCD | 含义 | 对齐 priority | PDCA 超期（天） | 精力占比 |
|------|------|---------------|-----------------|----------|
| A | 高价值+高意向 | S / A | 7 | 60% |
| B | 高价值+低意向 | B | 14 | 20% |
| C | 低价值+高意向 | C | 14 | 15% |
| D | 低价值+低意向 | D / 线索 | 30 | 5% |

评分逻辑见 `signalseller_methodology.json` → `abcd_grading`（value 0–50 + intent 0–50）。

**ProfileBuilder 职责（8787 或 8767 API）**：

1. 新线索入池 → 自动算 ABCD + 建议跟进频率  
2. 每周扫描：B→A 升级、A 沉默 14 天预警、C 拖延 30 天降 D  
3. 写回 `customers.csv` + PostgreSQL `customer_profiles`（待建表）

### 3.2 8787 客户管理 UI 改造建议

在 `he-haiwen-dealer-workbench/index.html` 增加 Tab 或子模块：

| Tab | 内容 | 对应 Agent |
|-----|------|------------|
| 漏斗（已有） | 阶段 + ABCD 徽章 | ProfileBuilder |
| 线索池 **【新】** | raw_leads、渠道、状态 | SignalHunter |
| 触达 **【新】** | FABE 邮件/私信草稿、SPIN 问题卡 | OutreachCrafter |
| 跟进 **【新】** | 三轮状态机、下次动作、deadline | FollowUpOrchestrator |
| 任务（已有） | 今日待办，合并触发器产出 | FollowUpOrchestrator |
| 转介绍 **【新】** | 成交后 24h 脚本、推荐人闭环 | SignalHunter |

**FollowUpOrchestrator 触发规则**（编码为 JSON，见 methodology 配置）：

- 新线索 → 实时破冰  
- 「考虑一下」→ 第 3 天案例  
- 沉默 ≥7 天 → 每日扫描提醒  
- 方案 3 天无回复 → 1 分钟摘要  
- 成交 24h → 交付确认 + 转介绍话术  

### 3.3 与 PDCA Check 联动

扩展 `customer-coverage-checker` / `data_role_pdca_daily.py`：

| Check 项 | 规则来源 |
|----------|----------|
| A 类超 7 天未跟进 | AGENTS.md + ABCD |
| B/C 超 14 天 | 同上 |
| 新线索 24h 未触达 | SignalSeller KPI |
| 沉默率 >5% | CommandCenter 预警 |
| 每周新增线索 < 目标 | SignalHunter P0–P3 |

Check 输出写入现有：

- `outputs/{date}/pdca_daily_check.md`  
- `teams/yang-jingjing/check_reports/`  
- 个人 `pdca_actions/{date}_*.md`

### 3.4 数据模型（PostgreSQL，建议 Claude Code 建表）

```text
leads              # 原始线索 source, raw_data, status
customer_profiles  # 关联 customers.csv dealer_name, abcd_grade, scores, pain_points
outreach_messages  # template_type, fabe_content, spin_questions, status
follow_up_states   # customer_id, current_round, next_action, deadline
interactions       # channel, direction, content, sentiment, ts
campaign_metrics   # channel, leads, conversions, cost, roi
onboarding_progress # user_id, day, module_id, completed_at, score
```

写库入口参考：`pdca-workbench/app/models/writes.py` 模式。

---

## 4. 新人培训融合设计

### 4.1 五天上岗路径

完整课表：`config/onboarding_curriculum.json`

| 天 | 主题 | 花色 | 核心产出 |
|----|------|------|----------|
| D1 | 认知与系统 | 红桃 | 会登录工作台、理解 FABE/SPIN |
| D2 | ABCD 与画像 | 方块 | 给 3 客户打分、会改 customers.csv |
| D3 | 触达与跟进 | 梅花 | 1 封 FABE 邮件、1 次跟进记录 |
| D4 | 成交与转介绍 | 黑桃 | 转介绍脚本、物流客户体验 |
| D5 | PDCA 复盘上岗 | CommandCenter | 首周 Plan、上岗测验 |

### 4.2 培训模块入口（8767）

| 项 | 路径 |
|----|------|
| 页面 | `/onboarding-center/` |
| API | `GET /api/onboarding/curriculum` |
| API | `GET /api/onboarding/progress`（按登录用户） |
| API | `POST /api/onboarding/complete`（模块打卡） |

实现骨架：

- 页面：`modules/onboarding_center/index.html`
- 路由：`pdca-workbench/app/onboarding/`（待 Claude Code 补全）
- 顶栏：`frontend/shared/shell.js` 增加「新人培训」

### 4.3 与 8787 新人模式对齐

8787 已有 `isNewbie(user)`、`newbie_threshold_days`、差异化日配额。

**融合原则**：

- **培训模块**：教方法论 + 系统操作（5 天）  
- **8787 新人模式**：上岗后 90 天内自动降配额/加辅导任务  
- **PDCA Check**：新人日报缺失、过程指标不达标 → 高风险  

`onboarding_curriculum.json` → `ongoing_newbie_rules` 与 `dealer-adapter.js` 规则字段应对齐。

### 4.4 培训内容资产（待补充）

| 资产 | 建议路径 |
|------|----------|
| FABE/SPIN Prompt 模板 | `agents/outreach-crafter.md` |
| 触达话术库 | `templates/outreach/` |
| 上岗测验题 | `templates/onboarding_quiz.json` |
| 品牌故事/demo | 已有 Vemory/会议素材可引用 |

---

## 5. 五 Agent 在仓库中的落地文件（建议）

| Agent | 新增/改动的文件 |
|-------|------------------|
| SignalHunter | `app/agents/signal_hunter.py`；8787 线索池 API |
| ProfileBuilder | `app/agents/profile_builder.py`；扩展 customers.csv 导入 |
| OutreachCrafter | `agents/outreach-crafter.md`；8787 触达 Tab |
| FollowUpOrchestrator | `app/agents/followup_orchestrator.py`；触发器 cron |
| CommandCenter | 扩展 `app/dashboard/`；SignalSeller KPI 卡片 |

Hermes 分派关键词示例：

- 「找线索 / LinkedIn」→ SignalHunter  
- 「给客户分级」→ ProfileBuilder  
- 「写开发信 / FABE」→ OutreachCrafter  
- 「跟进提醒 / 沉默客户」→ FollowUpOrchestrator  
- 「本周获客复盘」→ CommandCenter  

---

## 6. 分阶段实施（对齐 SignalSeller P0–P3）

| 阶段 | 周期 | PDCA 交付物 | 验收 |
|------|------|-------------|------|
| **P0** | W1–4 | ABCD 字段 + 8787 展示 + 培训 D1–D2 页面 + Check 超期规则 | 分级可视；新人能完成 D1–D2 打卡 |
| **P1** | W5–8 | 触达模板 Tab + 三轮状态机 MVP + 日报挂钩 | 24h 跟进提醒；1 封 FABE 可生成 |
| **P2** | W9–12 | 多渠道线索 + 4 项预警 + CommandCenter KPI | 沉默率下降；主管看板有获客漏斗 |
| **P3** | W13–16 | 转介绍闭环 + 周/月自动复盘 + Agent 全自动编排 | 推荐率、单线索成本达标 |

---

## 7. Claude Code 任务清单（可直接复制）

```text
工作目录：D:\经销商PDCA
先读：docs/SIGNALSELLER_PDCA_INTEGRATION.md、AGENTS.md、config/signalseller_methodology.json

【客户管理】
1. 扩展 teams/yang-jingjing/customers.csv  schema（abcd_grade 等列），写迁移脚本
2. 在 he-haiwen-dealer-workbench 增加：线索池、触达、跟进状态机 Tab
3. 实现 ProfileBuilder：读 CSV → 算 ABCD → 写回
4. 实现 FollowUpOrchestrator：按 signalseller_methodology.json 触发器生成今日任务
5. customer-coverage-checker 增加：24h 新线索、沉默率、ABCD 分布

【新人培训】
6. 完成 pdca-workbench/app/onboarding/ router + PostgreSQL onboarding_progress 表
7. 完善 modules/onboarding_center/index.html（5 天课表、打卡、进度条）
8. shell.js 增加「新人培训」；sales 角色默认 D1 未完成时首页提示
9. 8787 dealer-adapter.js：newbie_threshold 与 onboarding 毕业状态打通

【CommandCenter】
10. 驾驶舱增加 SignalSeller KPI 卡片：周线索、回复率、沉默率、ABCD 饼图
11. 周报模板增加：渠道 ROI、文案 A/B、ABCD 迁移

【约束】
- 遵守 methodology.json hard_constraints（不连发、不贬竞品）
- 不破坏现有 /customer-mgmt iframe 启动逻辑
- PostgreSQL 不可用时兼容 sqlite-fallback
```

---

## 8. 关键文件索引

| 文件 | 用途 |
|------|------|
| `docs/SIGNALSELLER_PDCA_INTEGRATION.md` | 本文档 |
| `docs/CLAUDE_CODE_HANDOFF.md` | PDCA 工作台总地图 |
| `docs/_signalseller_extract.txt` | docx 纯文本提取 |
| `config/signalseller_methodology.json` | ABCD/触发/渠道/KPI |
| `config/onboarding_curriculum.json` | 5 天培训课表 |
| `teams/yang-jingjing/customers.csv` | 客户主数据 |
| `AGENTS.md` | PDCA MVP 业务规则 |
| `pdca-workbench/app/pages/router.py` | `/customer-mgmt` |
| `he-haiwen-dealer-workbench/index.html` | 客户管理 UI |

---

## 9. 产品原则（Agent 硬约束）

来自 SignalSeller 文档，**所有自动生成内容必须遵守**：

1. **先听后说** — 客户未回复不连发  
2. **先认后解** — 价值前置，零压力结尾  
3. **不争对错 / 不贬竞品** — 只讲差异化  
4. **不空承诺** — 证据来自真实案例/数据  
5. **频控** — 同一客户每周主动触达 ≤2 次  

---

## 10. 开放问题（实施前与业务确认）

1. 客单价门槛 `value_threshold_usd` 默认 50000 是否适合经销商场景？  
2. 8787 项目是否迁回 `D:\经销商PDCA`  monorepo？  
3. 线索来源是否接 LinkedIn / 企微 API，还是先手工录入？  
4. 新人培训是否需多语言（俄/英）版本？  
5. FABE 内容是否走 vertu Hermes，还是本地 Prompt 模板？  

---

*文档结束 · 配合 `SignalSeller_AI获客Agent_产品文档_v1.docx` 原文使用*
