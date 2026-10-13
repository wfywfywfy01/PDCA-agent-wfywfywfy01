# Omega 独立 Web 进程实现计划

> **面向 AI 代理的工作者：** 在当前 worktree 内按复选框执行并记录验证结果。当前会话由同一代理内联执行。

**目标：** VPS 集成 Key 失效时，销售仍能在原网址登录、语音/文字陪练和复盘；真实 Vemory 导入独立报错。

**架构：** 复用生产 PDCA 镜像，在同一 PostgreSQL 和签名密钥上启动 `pdca-omega-web`，监听宿主机 `127.0.0.1:8771`。关闭该进程的 VPS 启动检查、调度和备份；现有 `pdca-omega-worker` 继续处理文本与复盘任务。Caddy 只将 SPA、账号、Omega API、代理范围查询和 Vemory 预览转发给独立进程；PDCA 其余 API 仍走 8768。

**技术栈：** FastAPI、PostgreSQL、Docker over SSH、Caddy、PowerShell、Python unittest。

---

## 文件与职责

- `pdca-workbench/app/main.py`：关闭调度的独立进程不执行生产启动备份。
- `pdca-workbench/tests/test_omega_standalone.py`：VPS 故障隔离和健康状态回归。
- `pdca-workbench/scripts/deploy_omega_web.py`：从已运行的 PDCA 容器复制必要环境、共享账号数据，安全启动和回滚独立进程。
- `pdca-workbench/tests/test_deploy_omega_web.py`：部署参数、密钥不落日志、版本和挂载校验。
- `pdca-workbench/deploy/omega-caddy.caddy`：同站路由片段，供服务器配置和审查。
- `pdca-workbench/docs/OMEGA_INDEPENDENT_WEB.md`：部署、回滚、故障演练和验收。

### 任务 1：关闭重复备份

- [x] 测试 `PDCA_SCHEDULER_ENABLED=0`、`PDCA_REQUIRE_VERTU=0` 时启动不调用 `backup_database` 或 `vertu_health`，`/health` 在 DB 可用时仍为 200。
- [x] 运行 `python -m unittest tests.test_omega_standalone -v` 确认旧代码失败。
- [x] 让生产启动备份只在 `settings.scheduler_enabled` 时执行，重跑测试。

### 任务 2：独立容器部署

- [x] 测试独立容器必须使用与 PDCA 一致的镜像 revision、PostgreSQL、签名密钥、账号环境和 `/app/data`；必须设置 `PDCA_REQUIRE_VERTU=0`、`PDCA_SCHEDULER_ENABLED=0`、`PDCA_OMEGA_ENABLED=1`，且不能使用明文 Docker TCP。
- [x] 运行 `python -m unittest tests.test_deploy_omega_web -v` 确认失败。
- [x] 实现 Docker over SSH 启动、健康等待、失败回滚；临时环境文件在 `finally` 删除；不输出环境变量值。重跑测试。

### 任务 3：同站路由和线上演练

- [x] 核对 `OmegaPage.vue` 请求路径，将 `/app`、`/app/*`、`/api/auth/*`、`/api/omega/*`、`/api/knowledge/scope`、`/api/meeting-center/vemory/detail` 路由至 8771；单列 `/omega-health`。
- [x] 使用 `caddy validate` 验证配置；保留旧 Caddyfile 备份，再 reload。
- [x] 从同站网址验证登录、场景卡、创建会话、文字回合、报告和语音 WebSocket 握手；隔离探针模拟无效 VPS Key，核对 Omega 200 和 VPS 检查失败。
- [ ] 将真实会议服务故障的 503 提示部署并通过公网验证。
- [x] 运行后端 Omega/认证回归、前端 typecheck/build、部署脚本测试，记录证据和未通过的生产门槛。

## 验收

1. `/omega-health` 返回 200 且 `vertu_cli.not_required=true`；`/health` 继续表示主工作台真实 VPS 状态。
2. 同一 `test` 账号在原 `/app/omega` 可登录并读取原有会话；其它销售仅看到自己/组内授权数据。
3. VPS Key 无效时，场景创建、文本/语音对话、结束、评分和历史报告不受影响；只有真实 Vemory 导入返回清晰的服务不可用错误。
4. 容器重启后路由与健康保持；失败部署保留上一可用版本；已在进行的语音会话不被更新过程强制中断。
