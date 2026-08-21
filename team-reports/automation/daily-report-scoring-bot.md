# 日报评分机器人

## HTTP 推送配置

| 项 | 值 |
|---|---|
| App ID | `vbot_Ml7y-RprSOIPHrmn` |
| App Secret | `<APP_SECRET>`（环境变量 `DAILY_REPORT_BOT_SECRET`） |
| Endpoint | `POST https://vps-service.vertu.cn/v1/im/user-robots/push` |

### 请求头

```http
Content-Type: application/json
x-vertu-bot-app-id: vbot_Ml7y-RprSOIPHrmn
x-vertu-bot-app-secret: <APP_SECRET>
```

### JSON Body

```json
{
  "body": "消息内容"
}
```

### 调用示例

```bash
curl -X POST https://vps-service.vertu.cn/v1/im/user-robots/push \
  -H 'Content-Type: application/json' \
  -H 'x-vertu-bot-app-id: vbot_Ml7y-RprSOIPHrmn' \
  -H "x-vertu-bot-app-secret: ${DAILY_REPORT_BOT_SECRET}" \
  -d '{"body":"消息内容"}'
```

---

## 评分规则 v1.0

**满分：20 分 | 评分方式：从 20 分起扣**

### 扣分项

| # | 维度 | 扣分 | 判定标准 |
|:-:|------|:---:|----------|
| ① | 成果形式 | -5 | 日报中无链接/图片/文档 |
| ② | 字数要求 | -5 | 今日工作内容不足 50 字 |
| ③ | 工时要求 | -2 | 记录工时总计 < 7.5h |
| ④ | 明日计划 | -5 | 无明日计划板块 |
| ⑤ | 逻辑清晰度 | -2 | 描述混乱无法判断进展 |
| ⑥ | 结构完整性 | -1 | 缺少必要结构模块 |

### 等级

| 分数 | 等级 |
|:----:|:----:|
| 18-20 | 优秀 |
| 14-17 | 达标 |
| 10-13 | 待改进 |
| <10 | 不合格 |

---

## 推送格式

- 排版：`emoji` + `rich_text`
- 末尾小尾巴：`  -from Frank.jr`（注意前导两个空格）

### 推送消息模板

```text
📊 **日报评分 · {date}**

**{user_name}** · {score}/20 · {grade}

**扣分项**
{deduction_lines}

**今日摘要**
{summary}

  -from Frank.jr
```

`deduction_lines` 示例（无扣分时输出「无扣分项 ✅」）：

```text
• 成果形式 -5：无链接/图片/文档
• 字数要求 -5：今日工作内容不足 50 字
```

### 推送示例 Body

```json
{
  "body": "📊 **日报评分 · 2026-07-09**\n\n**张三** · 15/20 · 达标\n\n**扣分项**\n• 成果形式 -5：无链接/图片/文档\n\n**今日摘要**\n完成客户跟进 3 家，整理报价方案。\n\n  -from Frank.jr"
}
```

---

## 定时任务

| 字段 | 值 |
|---|---|
| 触发时间 | 每天 **00:00**（Asia/Shanghai） |
| Cron | `0 0 * * *` |
| 评分对象 | **前一天**提交的日报 |

---

## 排除人员（不计入统计）

以下人员不参与评分、不推送、不纳入汇总统计：

- 二级复核
- 徐华俊
- 欧阳英平
- 赵琨
- 温若琪
- 张琪
- 张懿
- 鲜娜

---

## 自动化 Prompt（复制到 Automation 指令）

```text
运行日报评分机器人，评前一日 Vertu 日报并推送结果：

1. 确认环境变量 DAILY_REPORT_BOT_SECRET 已配置
2. 取前一天日期（Asia/Shanghai），拉取全员日报（排除名单见本文「排除人员」）
3. 按「评分规则 v1.0」从 20 分起扣分，计算等级
4. 按「推送格式」模板组装 emoji + rich_text 消息，末尾加「  -from Frank.jr」
5. POST https://vps-service.vertu.cn/v1/im/user-robots/push
   - Header: x-vertu-bot-app-id = vbot_Ml7y-RprSOIPHrmn
   - Header: x-vertu-bot-app-secret = ${DAILY_REPORT_BOT_SECRET}
   - Body: {"body": "<消息内容>"}
6. 记录推送结果；失败时写入 outbox 待补推

若当日无待评日报，推送「📊 日报评分 · {date}\n\n昨日无待评日报 ✅\n\n  -from Frank.jr」
```

---

## 环境变量

```bash
# team-reports/.env
DAILY_REPORT_BOT_APP_ID=vbot_Ml7y-RprSOIPHrmn
DAILY_REPORT_BOT_SECRET=<APP_SECRET>
```
