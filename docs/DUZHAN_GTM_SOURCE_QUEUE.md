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
本变更没有开启新定时推送；自动催办需另行确认具体调度和群消息内容。
