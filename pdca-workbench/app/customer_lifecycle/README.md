# 客户生命周期接口

前缀 `/api/customer-lifecycle`，使用现有 PDCA Cookie/Bearer 身份。每次操作重新读取有效用户，按 `resolve_data_scope` 的 self/team/all 范围检查客户；默认无范围不放行。本文描述实现契约，不代表已发布。

页面 `/customer-lifecycle` 可从增长页进入，提供建档、资料维护、外部身份绑定、进展提案及确认、业务凭证登记与主管人工核验。新档案即使主体已核实，业务阶段仍从 `pending` 开始，需另行确认业务事实；档案条数不作线索、成交或业绩指标。

本轮是**单客户的一轮跟进生命周期**，不是多商机 CRM。已回款客户的新合作不能倒退覆盖旧阶段；后续需增加独立商机/合作周期，才能分开管理复购、二次合作及各自订单。主来源与协同路径由授权人员人工归属，未自动鉴别原始来源，也不能声称已有 API 归因；有路径归属时必须填写 `source_note` 说明依据，变更保留操作者与时间。

## 管理

- `GET /meta`：阶段字典；`live_collection=false`、`integration_status=awaiting_upstream_interfaces`。
- `GET /owners`：当前可指派的有效负责人 `{items:[{id,display_name,team_key}]}`。
- `GET /customers?q=&namespace=&external_id=`：`{items:[customer]}`；两个外部标识参数须同时提供，精确查映射，未匹配返回空，不创建客户。
- `POST /customers`：`name, owner_user_id, route?, assisted_routes?, source_note?, country?, entity_verified?, decision_maker?, need?, next_action?, due_at?`。服务端生成 UUID、团队，初始 `stage=pending, version=1`。主体核验默认 false；主来源1–7或null，协同去重且不得含主来源，不额外计客户；任一路径非空时 `source_note` 必填，更新时也不能清空依据。
- `GET /customers/{id}`：`{customer,identities,evidence,proposals,business_links,audit,permissions,live_collection}`。权限含 `can_write,can_verify_finance`。日期输出 UTC；未知保留 null。
- `PATCH /customers/{id}`：上述资料字段加 `expected_version`；不能直接改 stage/team/version。资料修改也增加版本并留审计。
- `POST /customers/{id}/identities`：`{namespace,external_id}`，全局唯一。相同姓名不合并，冲突标识不能抢占或自动改绑。

## 证据与确认

`POST /customers/{id}/proposals`：

```json
{
  "source_system": "manual",
  "event_id": "source-stable-event-id",
  "occurred_at": "2026-10-27T02:00:00Z",
  "summary": "来源原文摘要，保留事实与推断边界",
  "source_channel_id": "",
  "source_message_id": "",
  "external_namespace": "",
  "external_id": "",
  "proposed_stage": "contacted",
  "changes": {"next_action": "安排需求会议", "due_at": "2026-10-28T02:00:00Z"},
  "business_link_id": null
}
```

`ai_sales`、`duzhan_im`（亦接受别名 `duzhan`）必须提供已映射客户的 namespace/external_id 与原消息ID；督战证据还需来源群/范围ID。服务器只接受结构化候选，不认客户端自报的 `confirmed/manual_confirmation/actor` 等字段。提交人及采集时间由服务器记录。外部摘要目前由授权用户提交，**未连接上游接口自动验真或采集**。

同 `(source_system,event_id)` 同内容重试返回原提案，异内容409。非人工来源另按系统、来源范围及原消息ID去重，不能靠随机更换event_id重复导入；AI消息键含外部系统命名空间。

`POST /customers/{id}/proposals/{proposal_id}/confirm` 或 `/reject`：`{expected_version,request_key,reason?}`。当前授权用户确认，CAS版本更新、提案决定及审计同一事务；相同请求幂等，不同内容复用key或过时版本409。原事件时间早于已确认阶段、正常阶段倒退均拒绝。拒绝不改变阶段，也保留决定记录。

阶段：`pending/lead/contacted/intent/qualified/ordered/paid/paused/closed`。线索至回款均须已核主体；合格及以后还须决策人、需求、下一步动作与时间。未取得证据的阶段不自动补齐。暂停、关闭保留历史最高阶段，不能借此倒退或重置阶段。

## 订单与收款门槛

- `POST /customers/{id}/business-links`：`{kind:order|payment,namespace,external_id,amount,currency,document_ref,occurred_at,order_link_id?}`。保存独立待核业务凭证，不改变客户阶段；金额十进制、币种分开，唯一业务ID防重复。HTTP 响应的 `amount` 使用十进制字符串（例如 `"100.10"`），避免 JSON 浮点转换；这不改变 SQLite 自身的大数存储精度限制，生产财务精度仍需 PostgreSQL 验收。
- `POST /customers/{id}/business-links/{link_id}/verify`：`{request_key,note}`；仅范围内 manager/admin 可人工核验，记录核验人、时间及说明。**这不是已连接 ERP 的自动校验**，meta明确 `manual_manager_review`。
- ordered/paid 提案必须引用同客户、同类型且已核验的业务关联；paid还须收款关联同客户已核验订单，币种与时间一致。群内“下单/到账”、意向、任务done、SMTP记录均不能绕过。

`paid` 表示已有收款凭证，允许部分回款，不表示全额到账或订单结清。页面逐条展示原币金额，本轮不计算跨币种总额、收入或七路自动归因业绩。

本轮没有采集任务、群外发、AI自动执行或生产写入。督战官、AI销售是独立系统，接口待上游开放；后续适配器须保留系统域、稳定客户/消息ID、原业务时间，并走上述候选与确认门禁。
