# 数据岗位 PDCA MVP Agents

实际落地版共 12 个 Agent。所有入口都应由 Hermes 调度；Cursor 只作为工作台。

## 1. todo-planner-agent

职责：

- 从 VPS/Hermes 拉今日代办。
- 合并昨天未完成、今天新规划、上级临时交办。
- 生成早上提醒。

输入：

- `inputs/todos/*.csv`
- 昨日问卷
- 上级交办记录

输出：

- `todo_reminder.md`

## 2. data-summary-router-agent

职责：

- 判断今天要做哪类数据汇总。
- 分派给销售、产品、客户维度汇总 Agent。
- 正式业绩数据必须先由 `vps-sales-data-agent` 从 VPS/Odoo 拉取。

输出：

- 汇总任务清单

## 3. vps-sales-data-agent

职责：

- 使用 `vertu-cli` 2.x 从 Vertu 业务快捷命令拉正式业绩数据。
- 使用命令：
  - `vertu-cli sales +orders`
  - `vertu-cli sales +headline-kpi`
- 不再使用旧 `vps-cli` 或任意 Odoo sandbox。

禁止：

- 不允许把临时 Excel 当作正式业绩数据。
- 不允许编造销售员、产品、客户业绩。

## 4. sales-summary-agent

职责：

- 按销售员汇总业绩、数量、回款、在途。

## 5. product-summary-agent

职责：

- 按产品/品类/系列汇总业绩和数量。

## 6. customer-summary-agent

职责：

- 按客户/经销商汇总业绩、数量、回款、在途。

## 7. chart-packaging-agent

职责：

- 把汇总表生成图表数据和可视化建议。
- 输出 Excel、图表数据 JSON 和 HTML 数据看板。

## 8. logistics-tracking-agent

职责：

- 读取物流单号。
- 查询 UPS/FedEx/DHL/SF 等物流状态。
- 判断正常/异常。

MVP 规则：

- 如果没有官方 API key 或网页权限，先生成待查 URL 和人工核对清单。
- 不伪造物流状态。

## 9. logistics-browser-agent

职责：

- 在没有官方 API key 时，调用浏览器进入 UPS/FedEx/DHL 等官网查询页。
- 把官网页面中的最新状态交给 `logistics-tracking-agent` 判断。
- 查询失败时输出“待人工确认”，不能补假状态。

## 10. pdca-questionnaire-agent

职责：

- 生成每日问卷。
- 读取问卷答案。
- 把答案转为完成事项、遗留事项和明日计划。

## 11. pdca-check-act-agent

职责：

- 汇总今日代办、问卷、数据汇总、物流检查。
- 生成每日 Check 和次日 Act。

## 12. im-notifier-agent

职责：

- 把今日提醒、异常物流、PDCA 日结推送给用户。
- 如果 webhook 不存在，写入 outbox。
