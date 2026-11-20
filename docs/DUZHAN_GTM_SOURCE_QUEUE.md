# 督战官读取 GTM 来源跟进

管理员使用 `GET /api/duzhan-agents/acquisition-queue`，由 PDCA 服务端请求 GTM 的
`GET /api/integrations/sales-supervision`。令牌仅配置在服务端；不传给浏览器或群机器人。
此入口只读，不代销售接单、不推进阶段、不改已有督战卡片、提示词或定时群推送。

管理页面 `/app/admin/duzhan-agents` 的“获客线索跟进”展示负责人、接单、真实进展、
线索及客户阶段、下一步与截止时间、逾期和暂停触达状态。页面可见时每分钟刷新，
两种队列独立分页；刷新失败保留并明确标注上次数据，不显示虚假的零条。

部署前配置 `PDCA_ACQUISITION_SUPERVISION_URL` 为已核实的 HTTPS GTM 根地址（包含
实际部署前缀，例如 `/gtm`），配置 `PDCA_ACQUISITION_SUPERVISION_TOKEN` 为 GTM
独立授权令牌。禁止 URL 带账号、查询串或 fragment。GTM 端限定实际有效销售账号；
PDCA 请求参数不能扩大该范围。缺配置返回 503，上游不可用或合同失效返回 502，
不能把失败解释成零线索。响应禁止缓存。

旧的 `items`、`by_owner`、`totals`、`truncated` 是公司交接待办。新字段独立记账：

- `source_tasks`：`unit=source_task`，来源任务数、负责人、接单、最近进展、下一步、
  原截止时间、逾期与待补信号，及真实已有客户阶段。未关联或未判定保留空值。
- `owner_pending_replies`：`unit=vps_message`，按人汇总派单后尚未选定具体线索的
  待补消息。不得把这一条回复应用到该人的所有线索。

`source_limit/source_offset`、`reply_limit/reply_offset` 分别控制两组分页；limit 为
1–100，offset 为 0–1000000。重复分页参数拒绝；每组按 `has_more` 继续读取，来源按
`task_id`、消息按 `id` 去重。不同请求之间可能有新数据，定期重扫并保留各页 `as_of`。
来源数、消息数与公司数不可相加后称为客户数。

`stored_outreach_hold=true` 表示已记录暂停，`outreach_hold_status=not_checked`
只表示尚未检查当前来源限制，绝非允许触达。执行联系前仍以 GTM 当前来源门禁为准。

消费者使用字段白名单。群原文、联系方式、来源原始快照、进展备注与未知上游字段不透传。
消息证据仅保留群 ID、原消息 ID、派单消息 ID、发生时间和结构化待补原因。

部署验收必须从 PDCA 进程发起一次真实只读拉取，验证授权范围、分页汇总、三位负责人
和无原文泄露，再称消费者接通。只验证 GTM 接口或机器人已在群内，不算消费成功。
只读管理页与下列催办开关独立；页面可用不代表已启用群催办。

## 正式线索逾期催办（2026-11-17）

`PDCA_ACQUISITION_CHASE_ENABLED=1` 显式开启。另设
`PDCA_ACQUISITION_CHASE_TARGETS` 为 JSON 数组，每项填写已核实的
`owner_user_id`（GTM 负责人）、`vps_user_id`（同一人的 VPS 账号）、
`channel_id`（其业绩群）、`dispatch_message_id`（原机器人汇总派单消息）。
实际映射保存在服务器环境，不提交仓库。部署脚本会保留现役配置；显式设置 0 可关闭。

- 仅生产调度进程运行，每 15 分钟检查；北京时间 09:00–19:00 内每人每天最多一条。
- GTM 响应必须明确 `environment=real`。旧响应缺字段或为 demo，均拒绝发送。
- 完整读取全部来源页（最多 5000 条），验证时间、总数、重复编号和待补回复汇总。
  读取失败、不完整、超过五分钟的快照、未来时间均失败关闭，不视为无任务。
- 仅处理仍开放且上游与实际期限均确认已逾期的任务。已完成、暂停触达、正在处理、
  回复列表截断的任务跳过。一个负责人存在尚未选定线索的待补消息时，暂缓其整条催办。
- 若销售已经回复原派单，督战官会在同一条每日提醒中单列可补全的回复。每条给出
  线索编号、工作台的补充回写编号和需补正的字段。仅纳入已核对负责人、群、原派单
  且校验原因全部属于进度、沟通结果、下一步或截止时间的消息。销售引用原派单，
  填入这两个编号和完整的实际进展，即可补回原回复。只有待补消息时也使用同一档位。
- 发送前用当前 VPS 目录确认既有 `PDCA_DUZHAN_BOT_APP_ID` 对应机器人在群，且
  指定 VPS 负责人仍为群成员。只用 `PDCA_DUZHAN_BOT_*`，不回退其他机器人。
- 一条消息最多列八项普通跟进或补充回写，并提供工作台入口，不含客户原件
  或联系人清单。引用原派单，并要求销售回复线索分发机器人的原派单，以便既有回写识别。
- 沿用 `scheduled_job_runs` 与 VPS 幂等键，键为 `gtm_chase:<owner>:<北京时间日期>`。
  发送失败或结果不明记 `uncertain`，当天不自动重发；记录需人工核对群内是否送达。
- 催办不接受任务、不改阶段、不改截止时间、不解除触达限制；`not_checked` 不代表
  联系许可。没有真实逾期时零发送，不能提前改截止时间制造业务验收。

回归测试：`python -m unittest tests.test_acquisition_chase tests.test_duzhan_acquisition_queue
tests.test_duzhan_group_tasks tests.test_scheduler_run_ledger`（在 `pdca-workbench` 目录）。
测试只用隔离 SQLite、模拟接口与模拟发送，不能称为真实群验收。
