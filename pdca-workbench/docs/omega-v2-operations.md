# Omega v2 独立运行说明

Omega 作为 PDCA 的认证页面 `/app/omega`、API `/api/omega/*` 和独立 `omega-worker` 运行。Codex 不参与线上请求、任务领取、语音识别或复盘生成。默认关闭；旧演示服务及其公开 API 需要在正式切流时另行封闭。

## 环境变量

在未跟踪的 `.env` 或部署密钥管理器配置，不把密钥放进仓库或聊天记录。

| 变量 | 用途 |
|---|---|
| `PDCA_OMEGA_ENABLED=1` | 开放新入口；文字模型与 worker 同时就绪，或实时语音凭据完整时可进入 |
| `PDCA_DATABASE_URL`、`PDCA_SECRET_KEY` | 沿用 PDCA PostgreSQL 和登录密钥 |
| `PDCA_SUPERVISOR_PROVIDER`、`PDCA_SUPERVISOR_MODEL`、`PDCA_SUPERVISOR_API_KEY` | 对话与报告的 OpenAI 兼容 HTTPS 模型接口；可复用已获准的内部模型凭据，需显式配置到这三个变量 |
| `PDCA_ASR_ENABLED=1`、`PDCA_DOUBAO_ASR_APP_KEY`、`PDCA_DOUBAO_ASR_ACCESS_KEY` | 可选语音转写；关闭时仍可文字演练 |
| `PDCA_OMEGA_REALTIME_PROVIDER=doubao`、`PDCA_DOUBAO_REALTIME_API_KEY` | 豆包实时语音模型 3.0（Seeduplex，API 模型 ID `1.2.6.1`）；仅服务端持有 API Key。须先开通 `volc.speech.dialog` 资源 |
| `PDCA_QWEN_REALTIME_WORKSPACE_ID`、`PDCA_QWEN_REALTIME_API_KEY` | 阿里云百炼北京地域 `qwen-audio-3.1-realtime-plus`；业务空间 ID 来自专属域名最左侧一段，API Key 只放服务端。独立于录音文件 ASR |
| 既有 Vemory/Vertu 凭据 | 仅真实会议来源读取使用，浏览器不接触凭据 |

实时语音默认仍使用 `qwen-audio-3.1-realtime-plus`。设置 `PDCA_OMEGA_REALTIME_PROVIDER=doubao` 后使用豆包 `1.2.6.1`；接入协议见[火山引擎全双工 API](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=zh)和[接入必读](https://docs.volcengine.com/docs/DoubaoVoice/access-mustread?lang=zh)。豆包 API Key 不等于资源权限；握手返回 `45000030 requested resource not granted` 时，需在豆包语音控制台开通 `volc.speech.dialog` 并授权该 Key，再切换生产变量。文字草稿、文字演练和报告仍由已配置的文本模型处理。

“语音输入”沿用短句录音：浏览器 TTS 使用设备自带语音引擎，最长 30 秒单声道 WAV，用户核对转写后发送。“开始实时对话”使用浏览器同源 WebSocket 发送持续 16 kHz PCM16；服务端连接所选实时模型，返回 24 kHz PCM16 分片并保存双方最终逐字稿。浏览器不接触供应商密钥；音频不保存。实时对话依赖 HTTPS 页面和浏览器麦克风授权；挂断、切换演练或离开页面会停止本地音轨。

断线重连会把最近 12 条已落库逐字稿（每条最多 500 字）作为历史上下文交给模型。报告仍使用完整冻结逐字稿；长时间会话的跨连接记忆需要单独验收。

## 启动与检查

本机独立试用可在 `pdca-workbench` 目录运行 `python scripts/run_omega_local.py PATH_TO_VOICE_ENV`（支持现有 Qwen 文件或单行 `豆包语音key: ...` 文件），打开 `http://127.0.0.1:8769/app/omega`。首次运行会在当前用户的 `%LOCALAPPDATA%/VertuOmega/local/login.json` 生成本机测试账号，数据保存在同目录的独立 SQLite，不连接正式 PDCA 数据库；密钥只从提供的文件读入进程。这个入口只绑定 `127.0.0.1`，适合在当前电脑试语音，不是生产部署。文字回合和报告需另配文本模型。

新建谈判任务先输入自然语言描述，点击 `AI 分析`。使用百炼实时模型时，可通过其文本接口生成草稿；切到豆包实时语音后，草稿使用已配置的文本模型。分析请求经过登录与同源校验，最多 6000 字；结果只返回浏览器，不自动创建或确认任务。缺失信息须由销售补充，保存草稿后仍要人工确认目标版本。此功能不依赖文字报告 worker，不能代替报告模型配置。

当前电脑已注册 Windows 登录任务 `VertuOmegaLocal`，无需保持 Codex 会话运行。可用 PowerShell 的 `Get-ScheduledTask -TaskName VertuOmegaLocal` 查看状态，`Start-ScheduledTask -TaskName VertuOmegaLocal` 启动；服务日志在 `%LOCALAPPDATA%/VertuOmega/local/server.out.log` 和 `server.err.log`。本机登录文件与会话签名密钥都在该目录，需按本机账号凭据保护。浏览器挂断语音时先发送 WebSocket `stop`，等待服务端完成尾部逐字稿保存后关闭；超时再调用同源认证接口释放租约。

1. 从受控代码版本构建 PDCA 镜像，在正式连接串上执行既有 `python scripts/migrate.py`，确认 Alembic 版本为 `017`。生产运行前先做备份和预发布迁移。
2. 设置 `PDCA_OMEGA_ENABLED=1`。文字演练/报告配置模型变量并启动 worker；实时语音设置所选供应商及对应密钥，短句录音另设 ASR 变量。用 `docker compose --profile omega up -d --build pdca-app omega-worker` 启动。worker 不开放端口，使用与 Web 相同的 PostgreSQL 和镜像版本。反向代理需把 `/api/omega/sessions/*/realtime` 的 WebSocket Upgrade 转发到 PDCA 应用，并保留 Cookie 与 Origin。
3. 登录销售或主管账号后访问 `/api/omega/status`。`realtime_configured=true` 说明实时语音变量完整；`model_configured=true` 且 `worker_online=true` 说明文字和报告可用。`ready=false` 时检查功能开关及两条链路配置。变量完整只表示已配置，不代表供应商接入验证通过。
4. 在页面创建任务、设置买方信息与九维评分权重（合计 100）、确认目标版本、开始演练。场景草稿修订后再次确认会产生新版本；旧演练和既有指派保持原版本。结束后请求报告；同组主管追加点评，不覆盖原报告。
5. 真实会议复盘输入 Vemory ID，检查来源逐字稿并映射所有说话人。无来源权限、无分说话人逐字稿或未映射完整时拒绝导入。会后目标标为 `post`，成果达成评分为未验证。主管可从报告指派该来源授权的销售做同版本练习；指派页显示来源基线、每次练习评分与达标状态。

## 验证与边界

本地执行 `python -m pytest tests/test_omega_flow.py tests/test_omega_realtime.py -q`；一次性本机 PostgreSQL `omega_test` 升级到 `017` 后，以 `PDCA_ENV=development` 和 `OMEGA_TEST_DATABASE_URL` 执行 `python -m pytest tests/test_omega_postgres.py -q`。前端执行 `npm test`、`npm run typecheck`、`npm run build`，并用模拟上游运行 `python scripts/omega_browser_smoke.py`。另启动 `npm run demo` 后运行 `python scripts/omega_demo_smoke.py` 验证联合流程。

预发布验证：能连续对话，销售插话后对手音频立即停止，最终双方逐字稿按顺序出现，挂断后麦克风停止，断线后可重新连接，报告引用原话。记录首音延迟、打断延迟、掉线率和 30 分钟稳定性；检查反向代理 WebSocket 超时。百炼北京地域已通过合成语音的真实双向回合和自动取消插话测试，应用 WebSocket 已验证转发及落库；真实麦克风、耳机回声、真实模型报告质量、Vemory 实际字段、多人负载和延迟仍需端到端验收。
