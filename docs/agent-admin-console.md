# Agent 管理后台（Agent Admin Console）

管理当前账号创建的 IM 机器人与 PDCA 智能体的只读/运维入口。
并入 PDCA 工作台：后端 pdca-workbench/app/agent_admin/，前端页面 apps/web/src/pages/AgentAdminPage.vue（路由 /admin/agents，导航「Agent 管理」，仅 admin 可见）。

## 页面能力

### IM 机器人 Tab（数据实时来自 vertu-cli im 域）

- 列表：名称、app_id、说明、公开范围、智能体开关、最近使用时间。
- 操作：公开 ↔ 仅自己可见（im +bot-update）；查看机器人已加入的群聊（im +bot-channels）。
- 创建：名称 / 唯一 key / 说明 / webhook / 公开范围（im +bot-create）。
- 写操作（创建、改公开范围）记入工作台审计日志（bot_create / bot_visibility）。

### PDCA 智能体 Tab（只读）

- 7 个 PDCA 智能体分工与输出位置（固化在 registry.py，与 AGENTS.md《Agent 分工》一致）。
- 模型路由快照：文本任务（DeepSeek flash，PDCA_SUPERVISOR_*）与视觉任务（本地 Qwen 网关，PDCA_QWEN_*）的当前环境变量配置。
- 本机 Hermes profiles 探测（HERMES_HOME / %LOCALAPPDATA%\hermes / ~/.hermes）。

## API

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | /api/agent-admin/bots | manager+ | 我的机器人列表 |
| GET | /api/agent-admin/bot-channels | manager+ | 机器人已加入的群聊 |
| POST | /api/agent-admin/bots | admin | 创建机器人（校验名称/key/webhook） |
| PATCH | /api/agent-admin/bots/{app_id}/visibility | admin | 调整公开范围 |
| GET | /api/agent-admin/pdca-agents | manager+ | 智能体注册表 + Hermes + 模型路由 |

## 约定

- 机器人凭据（app secret）不出现在任何接口返回中；列表沿用 vertu-cli 的 secret_preview。
- vertu-cli 执行失败时接口返回 502 并附错误摘要，不吞错。
- 单测：pdca-workbench/tests/test_agent_admin.py（服务层参数构造、校验器、注册表）。
