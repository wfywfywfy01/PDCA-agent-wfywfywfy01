# 数据岗位 PDCA MVP

这是给经销商数据中台岗位使用的 PDCA 演示版 MVP。它先实现“可演示、可跑通、可接 Hermes”的最小闭环。

## MVP 目标

每天形成一条闭环：

```text
早上拉代办 -> 白天处理数据/物流/临时需求 -> 晚上填问卷 -> 自动生成 Check/Act -> 次日继续滚动
```

## 5 个核心需求

1. 北京时间早上，从 VPS/Hermes 拉今日代办。
2. 数据 Agent 生成销售员、产品、客户维度汇总，输出 Excel/图表。
3. 物流 Agent 读取单号，查询 UPS/FedEx 等状态，判断正常/异常并返回消息。
4. 每日问卷记录今天完成、明天计划、昨天遗留、上级交办交付情况。
5. 生成每日 PDCA 日结报告和次日行动清单。

## 目录

```text
data_role_pdca_mvp/
├── README.md
├── HERMES_FLOW.md
├── AGENTS.md
├── config/
├── templates/
├── scripts/
├── inputs/
├── outputs/
└── outbox/
```

> Vemory 会议人员名单不再写入代码。请把真实名单放在未跟踪的
> `config/vemory_people.local.json`，或设置 `PDCA_VEMORY_PEOPLE_JSON`
> 环境变量；格式见 `config/vemory_people.example.json`。

> 旧版 `scripts/pdca_workbench.py` 独立 HTTP 服务默认关闭；请使用
> `pdca-workbench` FastAPI 服务。仅本地开发需要时设置
> `PDCA_ENABLE_LEGACY_HTTP=1`。



## 快速演示

直接读取 `config\data_sources.json` 运行：

```powershell
powershell -ExecutionPolicy Bypass -File D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\run_data_role_pdca_daily.ps1
```

指定日期：

```powershell
powershell -ExecutionPolicy Bypass -File D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\run_data_role_pdca_daily.ps1 -Date 2026-05-28
```

底层 Python 命令：

```powershell
python D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\data_role_pdca_daily.py `
  --date 2026-05-28 `
  --workspace D:\经销商PDCA\data_platform\data_role_pdca_mvp `
  --sales-xlsx "D:\Vertu\data\excel\26年数据\5月\临时需求\26-杨晶晶.xlsx" `
  --sales-sheet 26
```

运行后生成：

- `outputs/YYYY-MM-DD/todo_reminder.md`
- `outputs/YYYY-MM-DD/data_summary_report.md`
- `outputs/YYYY-MM-DD/YYYY-MM-DD_data_summary.xlsx`
- `outputs/YYYY-MM-DD/dashboard.html`
- `outputs/YYYY-MM-DD/logistics_check_report.md`
- `outputs/YYYY-MM-DD/pdca_daily_check.md`
- `outbox/YYYY-MM-DD_im_message.md`

## 下一步接入点

- VPS/Hermes 代办来源：`scripts/todo_source_vps.py`
- Odoo/VPS 数据来源：`sale_order_line_report`，仅取海外事业部 / 经销商
- 金山文档物流单号：`inputs/logistics_tracking_template.csv` 先演示，后续接金山 API/导出文件
- IM 推送：读取 `DEALER_IM_WEBHOOK_URL`

## 每天早上自动运行

注册 Windows 计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File D:\经销商PDCA\data_platform\data_role_pdca_mvp\scripts\setup_morning_task.ps1 -Time 09:00
```

默认任务名：

```text
DealerDataRolePDCAMorning
```
