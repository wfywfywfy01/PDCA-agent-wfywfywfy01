# 经销商 PDCA Agent 规则

## 产出物目录（2026-09-23 用户要求，长期有效）
- 督战官/PDCA 的产出物（证据 HTML、策略核查 HTML、说明文档、导出文件）统一放
  `D:\Vertu\data\excel\26年数据\<月>月\部门工作画像\督战官文件`；
  **不准再丢桌面**（可用 `PDCA_DROP_DIR` 覆盖，支持 `{month}` 占位符）。
- 容器/本机运行目录（`pdca-workbench/data/...`）只放运行时中间产物，不作为交付位置。

## 工程与发布规则
- `main` 是唯一生产基线；需求在 `codex/<task>` 工作树完成，Review 后合并。
- 生产只部署明确 Git commit；禁止部署未提交目录或个人工作树。
- 开始修改前阅读 `README.md`、相关测试、迁移和接口契约；只改需求涉及文件。
- 合并前运行后端测试、前端类型检查与构建、Compose 校验、`git diff --check`。
- `.env`、密钥、客户原件、导出文件和浏览器验收产物不得进入 Git。
- PDCA 与 `vertu-data-hub` 独立仓库、独立发布；只通过私有 API 通信，不跨库直连。


## 终端与进程纪律（2026-09-23 用户要求，长期有效）
- **起 PowerShell 一律放后台**（2026-09-23 用户追加要求）：所有 `pwsh` 调用必须
  `run_in_background: true`，拿 job id → `job_output` 收结果 → 用完 `job_kill`/自然退出；
  禁止在前台起命令占住会话。**且"后台"仅指一次性命令后台化**，用户不需要长驻服务；
  确需常驻时必须用户明确说"常驻"，并登记 pid/端口以便收尾全杀。
- 起 PowerShell 一律隐藏窗口：需要交互式/自行 spawn 时用
  `Start-Process -WindowStyle Hidden`，或 `-NoNewWindow`、`process.startInfo.CreateNoWindow = $true`；
  禁止 `Start-Process` 不带窗口参数地拉可见控制台。
- **绝对不许弹窗（2026-09-23 用户强调，最高优先级）**：控制台窗口、GUI 窗体、
  MessageBox/InputBox、UAC 提权提示、凭据弹窗、浏览器或桌面应用弹层，一律禁止出现。
  具体禁令：
  - 禁止一切需要交互输入的命令：`Read-Host`、`Get-Credential`、`pause`、
    `Out-GridView`、`Show-Command`、`-Confirm` 交互提示。
  - 禁止 `Start-Process -Verb RunAs`（必弹 UAC）；需要提权时先报告用户，由用户手动执行。
  - 禁止直接运行 `.bat`：本仓 `.bat` 结尾带 `pause`，会留窗口等按键。
    要跑批处理须先确认无 `pause`，或用 `cmd /c` 且已剥离 `pause`。
  - 已知含 UAC 提权的脚本（**本 Agent 禁止直接运行**）：
    `pdca-workbench/app/vps_pet_pack/apply_patch.ps1`、`install_clippy_fixed.ps1`、
    `restore_pristine_run.ps1`（均 `Start-Process powershell -Verb RunAs`）。
  - 命令一律后台跑（见上条），绝不在前台阻塞等用户交互；结果用文本返回给用户，
    不用弹窗汇报。
- **Win11 弹窗根因与修复（2026-09-23 实测，长期有效）**：本机 Windows 11 初始把
  "默认终端应用"设为 *让 Windows 决定*（`HKCU\Console\%%Startup` 的
  `DelegationConsole`/`DelegationTerminal` 为空），导致 **Windows Terminal 托管控制台程序，
  无视 `-WindowStyle Hidden` 与 `CREATE_NO_WINDOW`**，于是每次 pwsh 调用都会在桌面闪出
  一个可见控制台窗口（实测：宿主 `VPS.exe` 派生的 shell 每次都留可见窗口）。
  已修复：把两个值都改成 conhost GUID `{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}`。
  - **交付给用户的一句话**：设置 → 终端 → 默认终端应用 = "Windows 控制台主机"；
    改注册表等价，无需管理员，新会话生效。
  - **改回原样**：把两个值都写成 `{00000000-0000-0000-0000-000000000000}`（让 Windows 决定）。
  - 修复后**显式隐藏启动的进程不再产生可见窗口**（A/B 实测）；若宿主仍弹窗，
    需重启 VPS 桌面端让新会话继承新委派；再不行则要打 DSH 运行时的进程创建补丁
    （`dsh-win32-process/lib/index.js` 里 `creationFlags=1028` 含 `CREATE_NEW_CONSOLE`）。
  - 排查手法备查：枚举可见顶层窗口看 `class=C`（控制台类）窗口的 PID/标题，
    再回溯父链即可定位是谁在弹窗。
- 减少进程数：一次 pwsh 调用里用 `;` 串完多步，不要为一个查询起一个 shell。
- 自己起的后台进程用完即杀（`Stop-Process -Id <pid> -Force`，必要时 taskkill /T /F）；
  收尾时确认 `Get-Process powershell,pwsh,node` 里没有本任务遗留的进程。
- 禁止杀别的 Agent/桌面应用的进程：父进程为 `codex.exe`、`VPS.exe`、`WorkBuddyAI.exe`、`msedge.exe` 的
  `node`/`node_repl`/`cmd` 不属于本任务，只报告不处理；确实碍事要先问用户。
- 一次性脚本（`pdca-workbench/data/_push*.ps1` 等）在 `pdca-workbench/data/` 这类 scratch 目录里用完即归档/删除，不要长期堆积。

## 工作台与数据中台
- Cursor 作为日常工作台，用于编辑模板、日报、检查报告和行动建议。
- Hermes 作为调度中枢，负责按日触发检查脚本、汇总结果、分派 Agent。
- Git 暂作为临时销售数据中台，所有 Plan / Do / Check / Act 文件均纳入版本管理。

## 小组目录
- 小组资料集中放在 `teams/yang-jingjing/`。
- 月度目标放在 `monthly_targets/`。
- 销售日报放在 `daily_logs/<sales>/YYYY-MM-DD.md`。
- 检查报告放在 `check_reports/`。
- 明日行动建议放在 `pdca_actions/`。
- 组长辅导建议放在 `coaching/`。

## Agent 分工
- `team-pdca-planner`：维护小组目标、默认过程指标和月度指标模板。
- `daily-sales-log-checker`：检查销售日报是否提交、字段是否完整。
- `team-kpi-checker`：检查团队和个人业绩、回款、过程指标完成情况。
- `customer-coverage-checker`：检查客户负责人分布、重点客户跟进日期和资源失衡。
- `pdca-action-agent`：根据 Check 结果生成个人明日行动建议。
- `coaching-agent`：生成组长辅导动作和成员培养建议。
- `quota-allocation-agent`：后续根据销售画像、客户池和区域机会分配目标。

## 第一阶段 MVP 规则
1. 每天每个销售提交一份日报。
2. 日报缺失时，个人 Check 标记为高风险，并生成补交与组长跟进动作。
3. 默认每日过程指标来自月度目标文件：
   - 新增客户：3
   - 有效触达：15
   - 客户跟进：8
   - 报价：2
   - 重点客户维护：2
   - 日报提交：1
4. A 类客户若 `last_followup_date` 距检查日超过 7 天，标记为超期风险。
5. B/C 类客户若 `last_followup_date` 距检查日超过 14 天，标记为超期风险。
6. 若组长负责客户数超过团队客户总数 60%，且任一组员负责客户为 0，标记客户资源失衡。
7. 每日脚本至少输出：
   - 团队 Check 报告
   - 每个成员个人 Check 报告
   - 每个成员明日行动建议
   - 组长管理动作

## 人工录入约定
- 空字段保留为空，不用写 `无`。
- 日期统一使用 `YYYY-MM-DD`。
- 客户名必须尽量与 `customers.csv` 保持一致。
- 具体金额后续可补，第一版允许目标为空，但过程指标必须可检查。

## 模型路由约定（2026-09-17 拍板，长期有效）
- 图像 / OCR / 视觉任务（MTO 报价图）：只用本地 Qwen 网关（`PDCA_QWEN_*`，
  `qwen3.8-27b` @ `https://qwen3.vertu.cn:8443`）。
- 其他文本任务（主 Agent 决策、群草稿润色等）：只用 DeepSeek flash
  （`PDCA_SUPERVISOR_PROVIDER=https://api.deepseek.com`、
  `PDCA_SUPERVISOR_MODEL=deepseek-flash`）。
- 禁止使用 OpenRouter；除上述两个供应商外不得擅自接入其他模型服务。
