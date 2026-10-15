# Omega 独立 Web 进程

`pdca-workbench-teams.vertu.cn` 保留原账号和 `/app/omega` 地址。Caddy 将 `/app`、`/app/*`、`/api/auth/*`、`/api/omega/*`、`/api/knowledge/scope` 和单场 Vemory 预览转发到宿主机 `127.0.0.1:8771` 的 `pdca-omega-web`。其它 PDCA API 仍由 8768 的主进程处理；旧 `/omega/*` 演示页仍在 8770。

独立进程与主进程共用 PostgreSQL、`PDCA_SECRET_KEY` 和用户表。它使用 `PDCA_AUTH_MODE=hybrid`、`PDCA_AUTH_HOST_FALLBACK=0`、`PDCA_REQUIRE_VERTU=0`、`PDCA_SCHEDULER_ENABLED=0`：保留本地账号、原 VPS/Odoo 登录入口及其签发的 Cookie，同时禁止把服务器本机的 VPS 身份当成网页访客。进程只接收陪练、语音、文本模型及真实会议导入所需的配置。`pdca-omega-worker` 继续独立消费文本和报告任务。VPS Key 故障只影响真实 Vemory 会议预览/导入；该进程的 `/health` 不探测 VPS。

## 部署

1. 涉及数据库迁移、主工作台或 Omega worker 的提交，先部署已通过 CI 的明确 commit，并确认迁移、`/health`、worker 就绪。只改独立 Omega Web 的提交，可在 main CI 发布镜像后按第 2 步指定精确提交单独更新。不要用未提交目录构建生产镜像。
2. 在装有 Docker CLI、且 `ssh://pdca-docker-176` 可访问的工作机运行：

   ```powershell
   python pdca-workbench/scripts/deploy_omega_web.py --docker-host ssh://pdca-docker-176
   ```

   只更新 Omega Web 时运行 `python pdca-workbench/scripts/deploy_omega_web.py --docker-host ssh://pdca-docker-176 --revision <40位main提交SHA>`。脚本从主容器读取原有配置和挂载，只拉取该提交镜像并核对镜像内的 revision；主工作台及 worker 不随之重启。

   脚本读取主容器的镜像、非扩权的配置子集和共享挂载；验证镜像 revision；拒绝明文 Docker TCP；检查正在进行的语音通话；等待健康检查并验证页面、账号接口和未登录拒绝。失败时恢复上一容器，临时环境文件会删除。主容器和独立容器升级彼此独立；每次主镜像升级后单独运行此步骤。
3. 首次切流时，将 [`deploy/omega-caddy.caddy`](../deploy/omega-caddy.caddy) 的站点块替换 `/etc/caddy/Caddyfile` 内 `pdca-workbench-teams.vertu.cn` 的原站点块。先备份原文件，运行 `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`，再运行 `caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile`。2026-10-13 的服务器备份名为 `/etc/caddy/Caddyfile.before-omega-independent-20261013`。

## 验收

- `/omega-health`：200，`vertu_cli.not_required=true`，`backup.not_required=true`；`/health` 仍显示主 PDCA 的真实 VPS 状态。
- 未登录 `/api/auth/me` 和 `/api/omega/status`：401。登录页保留本地账号与 VPS/Odoo 入口；销售账号登录后能看到原场景、会话和组内授权数据；同一 Cookie 能访问主 PDCA 的有权 API。
- 新建演练后，公网 WebSocket 返回 `ready`，能主动 `stop` 并结束会话。文字回合由 worker 完成，结束后报告任务成功，九维结果可读取。单轮 QA 的总分允许因证据不足为 `null`，不能据此宣称评分质量通过。
- 在不改公网服务的隔离探针内放入无效 `VERTU_APP_KEY`：VPS 检查失败，但 Omega `/health` 仍为 200；真实会议获取在新版路由返回 503 和明确提示。
- Caddy 路由和容器在服务重启后保持；容器升级遇到活动语音时拒绝中断通话。

## 回滚

如果公网 Omega 路由出错，恢复上述 Caddy 备份，验证并 reload；`/app/omega` 将回到主 PDCA 8768。若仅独立容器升级失败，部署脚本会恢复上一容器。不要用旧 `/omega/*` 演示页代替正式陪练。

公开给公司销售和主管使用仍需按 [`omega-building-blocks-acceptance.md`](omega-building-blocks-acceptance.md) 的未验收项完成评分语义门槛、真人场景和实体手机签收；健康、连通与自动报告成功不等于内容质量验收。
