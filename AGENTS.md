# 经销商 PDCA Agent 规则

## 工程与发布规则
- `main` 是唯一生产基线；需求在 `codex/<task>` 工作树完成，Review 后合并。
- 生产只部署明确 Git commit；禁止部署未提交目录或个人工作树。
- 开始修改前阅读 `README.md`、相关测试、迁移和接口契约；只改需求涉及文件。
- 合并前运行后端测试、前端类型检查与构建、Compose 校验、`git diff --check`。
- `.env`、密钥、客户原件、导出文件和浏览器验收产物不得进入 Git。
- PDCA 与 `vertu-data-hub` 独立仓库、独立发布；只通过私有 API 通信，不跨库直连。

## 工作台与数据中台
- Cursor 作为日常工作台，用于编辑模板、日报、检查报告和行动建议。
- Hermes 作为调度中枢，负责按日触发检查脚本、汇总结果、分派 Agent。
- Git 暂作为临时销售数据中台，所有 Plan / Do / Check / Act 文件均纳入版本管理。

## 小组目录
- 小组资料集中放在 `teams/yang-jingjing/`。
- 月度目标放在 `monthly_targets/`。
- 销售日报放在 `daily_logs/<sales>/YYYY-MM-DD.md`。
- 检查报告放在 `check_reports/`。
- 明日行动建议放在 `pdca_actions/`。
- 组长辅导建议放在 `coaching/`。

## Agent 分工
- `team-pdca-planner`：维护小组目标、默认过程指标和月度指标模板。
- `daily-sales-log-checker`：检查销售日报是否提交、字段是否完整。
- `team-kpi-checker`：检查团队和个人业绩、回款、过程指标完成情况。
- `customer-coverage-checker`：检查客户负责人分布、重点客户跟进日期和资源失衡。
- `pdca-action-agent`：根据 Check 结果生成个人明日行动建议。
- `coaching-agent`：生成组长辅导动作和成员培养建议。
- `quota-allocation-agent`：后续根据销售画像、客户池和区域机会分配目标。

## 第一阶段 MVP 规则
1. 每天每个销售提交一份日报。
2. 日报缺失时，个人 Check 标记为高风险，并生成补交与组长跟进动作。
3. 默认每日过程指标来自月度目标文件：
   - 新增客户：3
   - 有效触达：15
   - 客户跟进：8
   - 报价：2
   - 重点客户维护：2
   - 日报提交：1
4. A 类客户若 `last_followup_date` 距检查日超过 7 天，标记为超期风险。
5. B/C 类客户若 `last_followup_date` 距检查日超过 14 天，标记为超期风险。
6. 若组长负责客户数超过团队客户总数 60%，且任一组员负责客户为 0，标记客户资源失衡。
7. 每日脚本至少输出：
   - 团队 Check 报告
   - 每个成员个人 Check 报告
   - 每个成员明日行动建议
   - 组长管理动作

## 人工录入约定
- 空字段保留为空，不用写 `无`。
- 日期统一使用 `YYYY-MM-DD`。
- 客户名必须尽量与 `customers.csv` 保持一致。
- 具体金额后续可补，第一版允许目标为空，但过程指标必须可检查。
