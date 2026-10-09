# Omega v2 独立运行说明

Omega 作为 PDCA 的认证页面 `/app/omega`、API `/api/omega/*` 和独立 `omega-worker` 运行。Codex 不参与线上请求、任务领取、语音识别或复盘生成。默认关闭；旧演示服务及其公开 API 需要在正式切流时另行封闭。

2026-10-09 积木式版本的实现、测试结果和未验收范围见 [omega-building-blocks-acceptance.md](omega-building-blocks-acceptance.md)。下述历史本机试用入口不代表该版本已经上线。

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

实时语音默认使用豆包全双工 3.0，协议模型为 `1.2.6.1`；接入协议见[火山引擎全双工 API](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=zh)和[接入必读](https://docs.volcengine.com/docs/DoubaoVoice/access-mustread?lang=zh)。`PDCA_OMEGA_REALTIME_PROVIDER=qwen` 仅用于显式兼容配置。豆包 API Key 不等于资源权限；握手返回 `45000030 requested resource not granted` 时，需在豆包语音控制台开通 `volc.speech.dialog` 并授权该 Key。远程部署有豆包 Key 时必须使用 SSH 或本地 Docker socket，脚本拒绝经 `tcp://` 传输；从 `.env` 删除该变量即可撤销后续部署注入。文字草稿、文字演练和报告由已配置的 DeepSeek flash 处理。

多人模板最多三位人物，使用可打断的受控多人语音：豆包监听连接持续识别销售发言，自动对手音频不会播放；服务器按点名、角色和议题选择人物，DeepSeek 仅接收该人物可知背景及公开逐字稿，再由独立的固定人物豆包连接合成回复。音色默认依次为 VV、Yunzhou、Xiaotian；自选音色仅接受这三种已验证 ID。每次输出先绑定供应商 started 事件的响应标识，后续无标识 delta 沿用该连接绑定，字幕、音频和落库使用同一 speaker_id/turn_id。多人不宣称原生端到端语音；2026-10-09 关闭 DeepSeek thinking 后，三个人物各一次合成探测的首个服务端 PCM 为 1.766–1.984 秒。这是合成输入的服务端观测，不是浏览器首音 P95；实体麦克风、手机及背景噪声尚未验收。单人保留原生全双工。

求助教练时，浏览器立即停止播放和上行，服务器执行取消输出、提交并静音，等待暂停前音频的最终转写保存后再更新会话并确认；coaching 状态丢弃新 PCM。音频代次由服务器分配，控制编号支持幂等重试，迟到的旧响应不能绑定到恢复后的新发言。建议通过独立持久任务生成，只写私密 Hint，报告仅记录辅助发生时间与 Hint ID。恢复前重新校验权限及 active 状态；断线重连仍保持教练暂停。结束后不能恢复。

暂停和挂断累计追踪已发送 PCM，并等待最终 ASR，最多 8 秒；最终转写后还需 1 秒没有新的 ASR 活动。供应商提交确认不含输入 ID 或帧偏移，且可能早于最终转写，因此不能单凭确认宣布排空。完全为零的 PCM 可按数字静音处理；未确定的非零尾部超时会将任务保存为 failed，并记录“语音尾稿未完成，请检查逐字稿后重新演练”，阻止本场结束评分。仅有环境噪声的非零尾部也可能保守触发此保护；1 秒静默窗口以外的迟到 ASR 尚无供应商完成屏障可证明，需在真实设备验收。认证停止接口强制释放仍在运行的连接，也会留下这一未完成标记。

`scripts/omega_voice_capability_probe.py` 支持固定合成话术、30/120 秒静音及原生 ASR 探测；`scripts/omega_voice_controlled_probe.py` 在临时数据库验证实际 DeepSeek/豆包多人合成和中断；`scripts/omega_voice_pause_probe.py` 验证真实原生 ASR、暂停排空、同一场景恢复，`--silence` 仅发送精确零 PCM。探测都不连接生产数据库或实体麦克风，密钥只从进程环境或显式未跟踪的 env 文件加载。

“语音输入”沿用短句录音：浏览器 TTS 使用设备自带语音引擎，最长 30 秒单声道 WAV，用户核对转写后发送。“开始实时对话”使用浏览器同源 WebSocket 发送持续 16 kHz PCM16；服务端连接所选实时模型，返回 24 kHz PCM16 分片并保存双方最终逐字稿。浏览器不接触供应商密钥；音频不保存。实时对话依赖 HTTPS 页面和浏览器麦克风授权；挂断、切换演练或离开页面会停止本地音轨。

断线重连会把最近 12 条已落库逐字稿（每条最多 500 字）作为历史上下文交给模型。报告仍使用完整冻结逐字稿；长时间会话的跨连接记忆需要单独验收。

## 启动与检查

历史本机试用可在 `pdca-workbench` 目录运行 `python scripts/run_omega_local.py PATH_TO_VOICE_ENV`（支持现有 Qwen 文件或单行 `豆包语音key: ...` 文件），打开 `http://127.0.0.1:8769/app/omega`。首次运行会在当前用户的 `%LOCALAPPDATA%/VertuOmega/local/login.json` 生成本机测试账号，数据保存在同目录的独立 SQLite，不连接正式 PDCA 数据库；密钥只从提供的文件读入进程。这个入口只绑定 `127.0.0.1`，适合在当前电脑试语音，不是生产部署。该脚本不会迁移旧表，也不启动报告 worker；已有本机 SQLite 须先用指向该库的配置执行 `python scripts/migrate.py`，文字回合和报告须另配文本模型及独立 worker。完整版本建议使用下述 Compose 配置。

销售可直接选择三个明确标为模拟的常见卡点，系统按默认训练约束创建并确认场景，然后进入演练。带入真实客户时，先输入自然语言描述，点击 `整理练习`，核对对手可见信息、目标和底线，再点击 `确认并开练`；这一步依次创建任务、确认目标版本并开始演练。金额或日期不完整时不生成回款目标，先按推进下一步练习；不补造客户事实。高级字段仍可手工修改，修改既有任务后须重新确认。草稿、文字演练和报告始终使用 `PDCA_SUPERVISOR_*` 配置的文本模型（当前生产为 DeepSeek），不随实时语音供应商切换。分析请求经过登录与同源校验，最多 6000 字；分析本身只返回浏览器，不自动保存。此功能不依赖文字报告 worker，不能代替报告模型配置。

此前本机试用曾注册 Windows 登录任务 `VertuOmegaLocal`；本轮没有启用或更新该任务。可用 PowerShell 的 `Get-ScheduledTask -TaskName VertuOmegaLocal` 核对状态；服务日志在 `%LOCALAPPDATA%/VertuOmega/local/server.out.log` 和 `server.err.log`。本机登录文件与会话签名密钥都在该目录，需按本机账号凭据保护。浏览器挂断语音时先发送 WebSocket `stop`，等待服务端完成尾部逐字稿保存后关闭；超时调用同源认证接口强制释放租约会标记尾稿未完成，并阻止评分。

1. 从受控代码版本构建 PDCA 镜像，在正式连接串上执行既有 `python scripts/migrate.py`，确认 Alembic 版本为 `021`。生产运行前先做备份和预发布迁移。
2. 设置 `PDCA_OMEGA_ENABLED=1`。文字演练/报告配置模型变量并启动 worker；实时语音设置所选供应商及对应密钥，短句录音另设 ASR 变量。用 `docker compose --profile omega up -d --build pdca-app omega-worker` 启动。worker 不开放端口，使用与 Web 相同的 PostgreSQL 和镜像版本。反向代理需把 `/api/omega/sessions/*/realtime` 的 WebSocket Upgrade 转发到 PDCA 应用，并保留 Cookie 与 Origin。
3. 登录销售或主管账号后访问 `/api/omega/status`。`realtime_configured=true` 说明实时语音变量完整；`model_configured=true` 且 `worker_online=true` 说明文字和报告可用。`ready=false` 时检查功能开关及两条链路配置。变量完整只表示已配置，不代表供应商接入验证通过。
4. 在页面选择用途和场景卡，再点「语音开练」或「文字开练」。五组积木默认收起，可按需修改；主管可存团队预设，销售可存个人预设。自定义描述入口仍可整理场景。九维评分沿用默认权重，更多设定中可调整。场景草稿修订后再次确认会产生新版本；旧演练和既有指派保持原版本。有逐字稿的演练结束后自动请求报告；模型漏掉评分项时自动重试一次，伪造引文仍直接拒绝，其他失败可在页面重试。同组主管追加点评，不覆盖原报告。报告之后生成待确认记忆，销售核对并确认后才更新对应档案。
5. 真实会议复盘输入 Vemory ID，检查来源逐字稿并映射所有说话人。无来源权限、无分说话人逐字稿或未映射完整时拒绝导入。会后目标标为 `post`，成果达成评分为未验证。主管可从报告指派该来源授权的销售做同版本练习；指派页显示来源基线、每次练习评分与达标状态。

## 验证与边界

本地执行 `python -m unittest discover -s tests -p 'test_omega*.py' -v`；一次性本机 PostgreSQL `omega_test` 升级到 `021` 后，以 `PDCA_ENV=development` 和 `OMEGA_TEST_DATABASE_URL` 执行 `python -m unittest tests.test_omega_postgres -v`。前端执行 `npm test`、`npm run typecheck`、`npm run build`，并用模拟上游运行 `python scripts/omega_browser_smoke.py`。另启动 `npm run demo` 后运行 `python scripts/omega_demo_smoke.py` 验证联合流程。

预发布验证：能连续对话，销售插话后对手音频立即停止，最终双方逐字稿按顺序出现，挂断后麦克风停止，断线后可重新连接，报告引用原话。记录首音延迟、打断延迟、掉线率和 30 分钟稳定性；检查反向代理 WebSocket 超时。百炼北京地域已通过合成语音的真实双向回合和自动取消插话测试，应用 WebSocket 已验证转发及落库；真实麦克风、耳机回声、真实模型报告质量、Vemory 实际字段、多人负载和延迟仍需端到端验收。
