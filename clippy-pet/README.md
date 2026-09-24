# 独立版 Clippy 桌宠

一只微软经典曲别针（Clippy），**独立进程、独立窗口、独立数据目录**。

## 最重要的设计约束

**它一个字节都不写 VPS。** 之前那套"重打包 `app.asar`"的方案把你的客户端弄崩过一次，
所以这个版本从设计上就杜绝了那种后果：

- 不读、不写 `C:\Program Files\VPS` 下的任何文件；
- 自带便携 Electron 内核（本目录 `host\electron.exe`，Electron 33.2.0），不装任何东西、不动注册表；
- 自己的数据全在本目录 `data\` 里（日志、位置、图标、Chromium 缓存）；
- 崩溃只会崩它自己，**VPS 不受影响**；不想要了就把这个文件夹删掉。

代价说清楚：它和"贴顶待命"里的小 V 是**两个独立的东西**，小 V 保持原样不动。

## 已经实测过的部分（全链路跑通）

在写这份文档的机器上逐条跑过，真实日志如下：

| 项 | 结果 |
| --- | --- |
| 引擎 6 个文件（含 1.78 MB 精灵图）拷入 `engine\` | 6/6 SHA256 与源一致 |
| 便携 Electron 启动 + `require('electron')` | ✅ `electron=33.2.0`、`electronModule=object app=yes` |
| 桌宠主进程 | ✅ `start; electron 33.2.0` → `tray icon generated` → `tray created` → `state {...}` |
| 托盘图标（代码生成 PNG） | ✅ `data\tray.png` 751 字节，`new Tray()` 成功 |
| 渲染进程 | ✅ `renderer loaded` → `window ready` → `ready {"w":124,"h":93,"animations":43,"display":"block"}` |
| 截图验证 | ✅ `data\smoke-shot.png` 里能看到完整的曲别针 |
| 点击穿透 | ✅ 鼠标移上去 `interactive = true`，移开 `interactive = false` |
| 常驻性 | ✅ 启动后独立于调用方进程，5 个 electron 进程稳定存活 |

动画总数 **43** 个（不是 41）。

两个踩到并已修掉的真坑：

1. **环境中被注入 `ELECTRON_RUN_AS_NODE=1`** → Electron 退化成纯 Node，症状是
   "进程秒退 + `Cannot find module 'electron'` + 零日志"。两个启动器里都已加
   `set ELECTRON_RUN_AS_NODE=` 清掉它。
2. **`renderer` 读尺寸过早** → 引擎在下一帧才画出元素，首次上报会是 `w:0,h:0`；
   改成延迟 300 ms 再上报，现在稳定是 `124×93`。

还有一个**设计错误**（用户实测反馈"拖不动、点不了"后修掉的）：

3. 最初用"渲染页上报悬停"来切换点击穿透 —— 但窗口一旦处于穿透状态，
   Chromium **不会转发鼠标事件**，渲染页永远收不到 `mousemove`，于是卡死在
   "不接收鼠标"：拖不动、点不了、双击无效。
   改成**主进程 60 ms 轮询光标位置**判定命中区（`screen.getCursorScreenPoint()`），
   并加了 `pet:drag-start` 让拖拽期间始终保持可交互。实测日志：
   `interactive = true → drag start → renderer: drag begin rect → drag end`。

第 4 个问题（用户反馈"卡卡的、不能随意拖动"后修掉的）：

4. **拖动方式换了两次才对**。
   - 第一版用 JS 算 `mousemove` → IPC → `setBounds`，每次移动还带一次
     "主进程 → 渲染页 → 回主进程"往返，天生顿。
   - 第二版想交给系统原生 `win.startDrag()`，结果 **Electron 33 的 BrowserWindow
     上根本没有这个方法**（日志：`native drag failed TypeError: win.startDrag is not a function`），
     交接失败又没有兜底，于是完全拖不动。
   - 现在：渲染页把光标的 **screenX/screenY** 交给主进程，主进程按**增量**移动窗口
     （`win.setPosition`，16 ms 节流）。实测把宠物从 `2436,1299` 拖到 `2236,1174`，
     位移与模拟拖动完全一致。

第 5 个问题（用户反馈"闪退"、且"只能右下角一小块拖动"后定位到的**真正根因**）：

5. **两个控制器在抢点击穿透开关**。主进程 60 ms 命中轮询和渲染页的悬停上报
   同时在调 `setIgnoreMouseEvents`，日志里 `interactive` 在 true/false 之间高频抖动；
   你点击的瞬间窗口恰好是穿透态，点击就穿到桌面（`WindowFromPoint` 返回 `FolderView`
   就是那一刻的证据），所以表现为"点不到、只有偶尔对上的一小块能拖"。
   修法：**只保留主进程命中轮询一个权威控制源**（渲染页的上报直接忽略），
   并加**滞回**：进入用大矩形（±26/22），离开用小矩形（±14/12），边界不再抖动。
   实测抖动从几十次降到 1 次。

第 6 个问题（用户要求"双击触发随机动作 + 随机台词"时补的）：

6. 双击要同时满足三件事：随机动画、随机台词、且不能被拖动逻辑吃掉。顺带发现两个真 bug：
   - **引擎自己绑了 dblclick**（播 `ClickedOn`），和我新加的处理器抢动画，看起来像"随机失效"。
     现在启动时用 `removeEventListener` 把引擎那个摘掉，只由我们播**一个**随机动画。
   - **引擎的气泡没有 class**（全靠内联样式创建），所以 `index.html` 里写的
     `.clippy-balloon` 样式一直是死代码；而且 `speak()` 是**逐字显示**（每字 200 ms），
     采样太早会看到空内容。现在给气泡补上 class，`--test-dblclick` 也改为 2.6 s 后采样。
   - 另外：普通单击现在**不再误报** `drag end`（只有真的移动过才报），日志干净很多。

第 7 个问题（"双击有没有真的说话"验证时发现的**气泡被裁**）：

7. 屏幕上看不到台词，但 DOM 里气泡是 `display:block` —— 因为它**跑到窗口外面被裁掉了**。
   实测数据：气泡 `218×59`（`test-balloon` 探针），而当时窗口只有 `380×200`，
   宠物又贴在窗口**右下角**，四周只剩约 124×58 的空间，引擎把四个方位都试了一遍都放不下，
   最后把气泡摆到了 `y=215`（窗口高 200）。
   修法两处：
   - 窗口放大到 **420×280**（能容纳精灵 + 气泡 + 15px 边距）；
   - **宠物改为贴窗口左上角**（原来贴右下），把右侧和下方的空间全留给气泡。
   修完探针输出 `fits:true`，截图里能看到完整气泡：
   `data\smoke-shot.png`（气泡内容"测试气泡：会议纪要记得同步给我。"）。

顺带记两个引擎行为，省得以后又踩：
- **气泡约 2.2～3 秒后自动收起**（`CLOSE_BALLOON_DELAY = 2000` 加上逐字说完的时间），
  所以验证截图必须**在说话后 2 秒内**抓，晚了就是 `display:none`。
- **引擎原生的 `speak()` 要排队**：它把说话放进动画队列，前面有动画在播时会等它播完。
  双击那条路已经不走队列了（见第 9 轮），但 `--test-balloon` 用的还是原生排队版本。

第 8 轮（用户反馈"又卡了"）做的性能收敛：

8. 先量化再改，结论是**桌宠不是系统卡顿的主因**：
   - 桌宠 5 个进程空闲时合计约 **2.8% CPU**（逐进程实测：0.94% / 0.94% / 0.62% / 0.39% / 0%）；
   - 系统里真正吃 CPU 的是 ToDesk（9532s）、VPS 自身（5017s）、Weixin（4926s）、xray（4730s）。
   但仍然修掉了三个会造成**卡顿感**的写法：
   - `setIgnoreMouseEvents` **抖动**：日志里出现过 60ms 内 true→false→true。
     这个调用会重建窗口命中测试并切换 `WS_EX_TRANSPARENT`，频繁切换就是顿感来源。
     现在加防抖：进入等 40ms、离开等 260ms，命中轮询从 60ms 放宽到 80ms。
   - 渲染页**每次 `mousemove` 都发一次 IPC**（`pet:hover`）—— 而主进程早已忽略它。已删除。
   - 每个鼠标事件都写一行日志（`evt mousedown …`）→ 改为只在 `--diag` 时记录。
   顺手删掉 `hitTest` / `reportHover` / `hoverState` / `lastMove` 四处死代码。

第 9 轮（用户反馈"双击之后动作有点慢呢"）：**先量素材，再量开销**。

9. 把 `agent.mjs` 里 43 个动画的帧时长全算了一遍：**每个动画的第 0→1 帧位移
   都发生在 100 ms**（即素材本身没有慢启动），总时长中位数 3.7 s、最长 13.6 s
   （`IdleSnooze`）。所以"慢"跟动画本身无关，是三处引擎开销叠加：
   - **`play()` 要先等 idle 播完**：`_onQueueEmpty()` 建了 `_idlePromise`，
     而 `_playInternal()` 里写着"当前是 idle 就先 await 它"；`agent.stop()` 只发
     `exitAnimation()`，idle 得走完 exit 分支才算 EXITED —— 双击后的动画因此要
     **先空等几百毫秒**。现在动手前把 `_idlePromise` 置空。
   - **新动画只在下一个帧定时器上才画出来**：`showAnimation()` 只重置帧索引，
     真正 `_draw()` 发生在 `_step()` 里，而 `_step()` 要等上一次
     `setTimeout(…, _currentFrame.duration)` 到点，也就是还得再等
     "0 ～ 上一帧时长"。现在 `clearTimeout(_animator._loop)` 后**同步补一次
     `_step()`**，第 0 帧当帧上屏。
   - **台词排在动画后面**：原来 `agent.play(name, 2600)` 占住队列 2.6 s 才轮到
     `speak()`，等于**点完 2.6 秒才出气泡**。现在气泡**跟动画同时**出现（直接让
     气泡对象说话，不再排队），动画上限也从 2600 ms 调到 2800 ms。
   `--test-dblclick` 加了时间线采样，`pet.log` 实测：
   ```
   double click -> action=GetArtsy say=日报交了吗？我先记小本本上。 dispatch=5ms
   timeline: [{"t":128,"anim":"GetArtsy","frame":1,"balloon":"日报交了吗？我先记小"},
              {"t":314,"anim":"GetArtsy","frame":2,"balloon":"日报交了吗？我先记小"},
              {"t":901,"anim":"GetArtsy","frame":8,"balloon":"-"},
              {"t":3004,"anim":"GetArtsy","frame":17,"balloon":"-"}]
   ```
   → **128 ms 时动画已在跑、气泡已显示**；3004 ms 时气泡按设计已收起。

第 10 轮（用户要求"点他就让他背诗"）：**接了 385 首诗词，顺带修掉一个气泡被裁的几何 bug**。

10. 双击从"随机说一句工作台词"改成**随机背一首诗词**（80% 背诗 / 20% 老台词穿插），
    诗库放在独立的 `poems.mjs`（386 条，格式 `"诗句|出处"`，用户自己加行即可）。
    诗句和出处分两行显示 —— 原来气泡的 `white-space` 是默认值，`\n` 会被折成空格，
    所以启动时把 `_balloon._content` 设成 `pre-line`。气泡停留时长也从固定 2 秒改成
    **按字数给**（`1200 + 110×字数`，2400～7000 ms），45 字的句子留 6 秒才收。
    接完必须验最长的一条放不放得下，于是加了 `--test-poem`（挑诗库最长的一条，
    走真实背诗路径，500ms/1600ms 两次采样气泡 rect）。**结果第一次就 `fits:false`**：
    ```
    test-poem longest(45 chars): 多少事，从来急；天地转，光阴迫。一万年太久，只争朝夕。
    test-poem at 500ms: {"rect":{"x":0,"y":252,"w":218,"h":101},"win":{"w":420,"h":280},"fits":false}
    ```
    根因不在气泡大小，而在**精灵贴着窗口左边**：引擎的 `_isOut()` 要求气泡四周各留
    5px 边距，精灵在 `x=0` 时"右上/右下"两个本来放得下的位置全被判为越界，
    四个方向试完都不行，就退回到最后试的"右下" → 气泡沉到 `y=252` 被窗口裁掉。
    修法：`windowOriginFor()` 里让精灵**内缩 8px**（`PET_PAD_X/Y = 8`，窗口允许
    最多探出屏幕左上 8px，那条是透明的）。修完同样的探针：
    ```
    test-poem at 500ms: {"rect":{"x":8,"y":28,"w":218,"h":101},"win":{"w":420,"h":280},"fits":true}
    ```
    截图 `data\smoke-shot.png` 里能看到完整诗句 + 出处两行。
    另外这个 bug 只在**宠物贴近屏幕下边缘**时发作（窗口被上推，气球只能往上放），
    也就是宠物默认待的右下角 —— 所以它是必然会踩到的。
    最后把 385 条诗逐条校对了一遍（原文 + 作者篇名，其中约 99 条联网核对权威站点），
    只查出 **1 条真错**：「天下兴亡，匹夫有责」**不在**《日知录》原文里 —— 原文是
    「保天下者，匹夫之贱，与有责焉耳矣」，那八个字是后人概括、梁启超《痛定罪言》
    引作此语才传开的。已拆成两条：原文归 `顾炎武《日知录·正始》`，八字署
    `顾炎武（梁启超引）`，现在 386 条。另有 14 处属**版本异文**（唯见/惟见、
    粉骨碎身/粉身碎骨、白云生处/深处、红装/红妆…），两种都通行，保持原样。

## 目录结构

```
clippy-pet\
  启动桌宠.cmd          双击启动（GBK + CRLF 编码，中文提示不乱码）
  自检.cmd              启动约 12 秒 → 自动截图 → 退出
  host\electron.exe     便携 Electron 33.2.0 内核（188 MB，来自官方 release zip）
  setup_engine.ps1      把引擎与素材铺到 engine\（幂等）
  fix_launchers.py      把 _launcher_src\*.cmd 转成 GBK+CRLF
  main.js               主进程：透明置顶窗 / 托盘 / 点击穿透 / 拖拽 / 位置持久化
  preload.js            contextBridge 暴露的 IPC
  renderer.js           渲染页：驱动 clippyjs 引擎、41 个动画、音效、说话气泡
  poems.mjs             诗库：386 条 "诗句|出处"，双击背诗用，随便加
  penguin.html          第二个角色的页面（透明窗 + 气泡 + 养成面板样式）
  penguin\              企鹅角色：art.mjs 画法 / anim.mjs 23 个动作 / nurture.mjs 养成 / lines.mjs 台词
  index.html            透明页面 + 气泡样式
  engine\               引擎与素材（共约 1.9 MB）
    index.mjs                     clippyjs 引擎（778 行，MIT）
    chunk.mjs                     引擎附带的小工具模块
    agents\clippy\index.mjs       代理加载器
    agents\clippy\agent.mjs       41 个动画定义（原版数据）
    agents\clippy\map.mjs         原版精灵图 3348×3162（base64 内嵌）
    agents\clippy\sounds-mp3.mjs  原版 15 段音效（base64 内嵌）
  data\                 运行时生成：pet.log / state.json / tray.png / smoke-shot.png
  _launcher_src\        cmd 源码（UTF-8），改完跑 fix_launchers.py 重新生成
```

素材来自 [clippyjs](https://github.com/pi0/clippyjs)（MIT），精灵图、动画定义、音效都是**原版数据，未做任何改动**，所以动画和原版一致。

## 跑起来

**这个文件夹就是入口**：`D:\经销商PDCA\clippy-pet\`

引擎素材、便携 Electron、两个启动器都已经铺好了，你只要双击：

| 双击这个 | 作用 |
| --- | --- |
| `自检.cmd` | 先跑这个。约 12 秒后自动截图退出，验证引擎/窗口/渲染都正常 |
| `启动桌宠.cmd` | 自检通过后双击它正式用（常驻，托盘里能退出） |

想要桌面入口：右键 `启动桌宠.cmd` → 发送到 → 桌面快捷方式（我的沙箱没有桌面写权限，这一步得你来）。
也可以把整个 `clippy-pet` 文件夹拖到别处，它是自包含的。

```powershell
# 只有换了机器/删了目录才需要重跑这两步：
#   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\经销商PDCA\clippy-pet\setup_engine.ps1"
#   python "D:\经销商PDCA\clippy-pet\fix_launchers.py"
```

自检正常的话，`data\` 里会有：

| 文件 | 期望内容 |
| --- | --- |
| `pet.log` | `start; electron …` → `tray created` → `window ready …` → `renderer loaded` → `ready {"w":124,"h":93,"animations":41}` → `smoke shot written …` |
| `smoke-shot.png` | 一张 124×93 的曲别针截图（气泡里有一句话） |

两样都对，就双击 **`启动桌宠.cmd`** 正式用。

## 交互

| 操作 | 效果 |
| --- | --- |
| **双击** | **随机播一个动画 + 随机背一首诗词**（诗库 386 条，见下）；动画和气泡**当帧就出**（实测 128 ms 时已在动、气泡已显示） |
| 右键 → 角色 | **Clippy 曲别针 / QQ 企鹅** 随时切换（企鹅另有 23 个动作和养成菜单） |
| 按住左键拖动 | 可拖到桌面任意位置（窗口按指针增量移动，16 ms 节流）；松手后位置记进 `data\state.json` |
| 右键 | 原生菜单：12 个常用动作 / 说句话 / 静音音效 / 回右下角 / 动画列表 / 隐藏 / 显示 / 退出 |
| 托盘图标双击 | 打招呼 + 把桌宠显示出来 |
| 鼠标离开命中区 | 窗口点击穿透（不挡桌面点击）；命中区进入 ±26/22、离开 ±14/12（滞回防抖） |

### 双击背的诗库（`poems.mjs`，随便加）

独立的 `poems.mjs`，**386 条**，一格一条写成 `"诗句|出处"`：

```js
export const POEMS = [
  "苟利国家生死以，岂因祸福避趋之。|林则徐《赴戍登程口占示家人》",
  "北国风光，千里冰封，万里雪飘。|毛泽东《沁园春·雪》",
  "天生我材必有用，千金散尽还复来。|李白《将进酒》",
  // …
];
```

- **加一条**：照格式往数组里插一行，重启桌宠即可，不用改代码。
- **比例**：双击时 80% 背诗、20% 说下面那 16 句工作台词（`renderer.js` 里的 `POEM_RATIO`）。
- **显示**：诗句一行、`——出处` 单独一行（气泡设了 `white-space: pre-line`）。
- **停留时长**按字数给：`1200 + 110×字数`，夹在 2.4～7 秒（长的诗句别刚出来就收）。
- **容量**：气泡最宽 200px、最多约 7 行，所以**单条控制在 70 字以内**最稳；
  当前最长一条 45 字（毛泽东《满江红·和郭沫若同志》）。

覆盖面：毛泽东 60 首（含《沁园春·雪》《忆秦娥·娄山关》《七律·长征》等）、李白 46、
杜甫 32、苏轼 29、辛弃疾 21、陆游 18、爱国言志 37（文天祥 / 岳飞 / 于谦 / 林则徐 /
龚自珍 / 谭嗣同 / 秋瑾 / 顾炎武 / 屈原 / 曹操）、边塞王维 44、白居易李商隐杜牧 25、
唐宋名句 42、宋词 16、近现代 14（鲁迅 / 周恩来 / 朱德 / 陈毅 / 艾青 / 臧克家）。

验证方式（不用手点）：
- `electron.exe main.js --test-poem` —— 自动挑诗库**最长的一条**走真实背诗路径，
  在 500ms / 1600ms 采样气泡 rect 并写进 `pet.log`（这条就是抓出第 10 轮那个裁切 bug 的探针）
- `electron.exe main.js --test-poem --smoke` —— 顺带截图到 `data\smoke-shot.png`

### 双击的随机台词库（`renderer.js` 里的 `PHRASES`，随便改）

```
需要我帮你看点什么吗？ / 又见面啦～ / 这份报表我瞅着有点眼熟。 / 别点我啦，快去写日报！
日报交了吗？我先记小本本上。 / 要我给你讲个回形针的冷笑话吗？ / 拖我去哪儿都行，别拖到回收站就好。
你今天的重点客户跟进了吗？ / 我在这儿待命，随叫随到。 / 刚才那个数对上了，放心。
报告老板，我今天一根都没弯。 / 有需要尽管双击我。 / 这个月目标，咱们还差一点点。
我看你眉头一皱，是不是哪个经销商又拖了？ / 摸鱼可以，别忘了我还盯着你。 / 会议纪要记得同步给我。
```

随机动作从 24 个"有台词感"的动画里挑（`Greeting / Congratulate / Wave / Thinking / Explain /
GetAttention / GetArtsy / GetTechy / GetWizardy / GoodBye / Writing / Save / Print / Searching /
Processing / Alert / CheckingSomething / EmptyTrash / Hearing_1 / SendMail / IdleEyeBrowRaise /
IdleFingerTap / IdleHeadScratch / RestPose`），代码会用 `hasAnimation()` 过滤掉当前 agent 里不存在的。

验证方式（不用手点）：
- `electron.exe main.js --test-dblclick` —— 自己触发一次双击，把"选了哪个动作、说了哪句话、
  气泡是否显示/是否被裁"写进 `pet.log`
- `electron.exe main.js --test-balloon --smoke` —— 单独验证气泡渲染，并截一张带气泡的图到
  `data\smoke-shot.png`

实测输出：

```
renderer: double click -> action=Greeting say=我在这儿待命，随叫随到。
renderer: test-balloon at 1400ms: {"display":"block","text":"测试气泡：会议纪要记得同步给我。",
                                   "rect":{"x":162,"y":73,"w":218,"h":59},"win":{"w":420,"h":280},"fits":true}
```

**命中区比精灵大一圈**（四周各留 26×22 像素）：曲别针是细手臂 + 透明角，按死尺寸判定会让人觉得"点不到"。命中区由**主进程轮询光标**决定，不依赖鼠标事件转发 —— 这一点很关键，见下方"两个真 bug"。

**43 个动画**全部可用（`Congratulate / LookRight / SendMail / Thinking / Explain / IdleRopePile / IdleAtom / Print / Hide / GetAttention / Save / GetTechy / GestureUp / Idle1_1 / Processing / Alert / LookUpRight / IdleSideToSide / GoodBye / LookLeft / IdleHeadScratch / LookUpLeft / CheckingSomething / Hearing_1 / GetWizardy / IdleFingerTap / GestureLeft / Wave / GestureRight / Writing / IdleSnooze / LookDownRight / GetArtsy / Show / LookDown / Searching / EmptyTrash / Greeting / LookUp / GestureDown / RestPose / IdleEyeBrowRaise / LookDownLeft`），
菜单里"动画列表"会把全部名字写进 `pet.log`。

## 排查表（对着 pet.log 看）

| 日志症状 | 原因 / 处理 |
| --- | --- |
| 完全没有 `pet.log`，进程秒退 | 十成是 `ELECTRON_RUN_AS_NODE` 被注入（Electron 退化成纯 Node，`require('electron')` 直接抛错）。确认启动器里有 `set ELECTRON_RUN_AS_NODE=` 这一行；手动启动时先 `set ELECTRON_RUN_AS_NODE=` 再跑。 |
| `start; electron …` 之后立刻断 | Chromium 起不来（平台通道/命名管道被安全软件或组策略拦）。日志里最后一行就是断点；把 `data\pet.log` 发我。 |
| 有 `window ready` 但没有 `renderer loaded` | 渲染页没起来 → 大概率 `engine\` 素材缺文件，重跑 `setup_engine.ps1` |
| `did-fail-load` | 同上：`engine\` 素材路径不对 |
| `tray failed` / `tray icon unavailable` | 只是没托盘图标，不影响桌宠本身；删掉 `data\tray.png` 让它重新生成 |
| `boot failed:` | 引擎报错，日志里有完整堆栈；把这段发我 |
| 桌宠出现但挡桌面点击 | `pet:hover` 没生效，`pet.log` 里应有成对的 `interactive = true/false`；没有就是渲染页没收到鼠标事件 |
| 位置跑偏 / 到屏幕外 | 删掉 `data\state.json` 重启，会回到右下角 |
| 背的诗显示不全 / 气泡被窗口裁掉 | 单条太长了（气泡最多约 7 行）。跑 `electron.exe main.js --test-poem` 看 `fits` 是不是 `true`；`false` 就把那条拆短 |
| 想要更详细的启动日志 | 启动器里加 `set ELECTRON_ENABLE_LOGGING=1`，Chromium 的日志会进 `data\run.err.txt`（用 `--smoke` 时自动落盘） |

## 第二个角色：QQ 企鹅（第 12 轮）

同一只桌宠，右键 → **角色** → 「QQ 企鹅 / Clippy 曲别针」随时切，尺寸、窗口原点、
右键动作菜单都会跟着换，位置记在 `state.json` 的 `character` 里。

**形象是画出来的，不是素材**。先说版权：查过了，**腾讯没有开源** QQ 宠物 / 企鹅形象；
能搜到的只有素材站（授权不明）和玩家二创（衍生自腾讯素材）。所以企鹅是 `penguin/art.mjs`
里用 canvas 2D 现画的一只：黑身白肚、白脸、橘嘴橘脚、红围巾，全部是矢量路径 + 渐变。

**23 个动作**（`penguin/anim.mjs`）：Idle / IdleLook / Wave / Jump / Spin / Dance / Sing /
Happy / Sad / Angry / Hungry / Sleep / Snooze / Eat / Bath / Work / Study / LevelUp / Shy /
Dizzy / Stretch / Walk / Greet。每个动作就是"给定进度 t 返回姿势增量"的一个函数，
所以改手感（抬手多少、跳多高）只改一个数字，不用碰素材。

自检方式是**动作接触表**：`--sheet` 让渲染页把每个动作的 4 个时间点画进一张大图，
`executeJavaScript` 取回 PNG 存到 `data\penguin-sheet.png`，一次就能看出所有姿势对不对
（`--sheet-only=Wave,Jump --sheet-scale=3` 可以只看几个、放大看细节）。
这张表第一次就抓出两个真 bug：**翅膀画在身体后面**（挥手完全看不见）、
**粒子元组下标读错**（一个爱心糊满四格）。

### 养成系统（`penguin/nurture.mjs`）

| 项 | 说明 |
| --- | --- |
| 数值 | 饱食 / 清洁 / 心情 / 精力（0-100）+ 等级 / 经验 / 金币 |
| 衰减 | 饱食 5 分钟 -1、清洁 8 分钟 -1、心情 6 分钟 -1、精力 7 分钟 -1；饿着或脏着心情额外快掉 |
| 离线 | 关掉桌宠也照算，但**最多按 10 小时**结算（不然第二天回来直接饿没了） |
| 动作 | 喂小鱼干(10币) / 洗个澡(5币) / 逗它玩 / 哄它睡觉 / 去打工(赚 28 币) / 去学习(涨 22 经验) |
| 升级 | 经验满了自动升级、+20 金币、播 LevelUp 动画并说一句 |
| 主动 | 哪项低于 30 就会自己演给你看（摸肚子 / 打哈欠 / 委屈脸）并求投喂，同一项 3 分钟内不重复念 |
| 面板 | 右键「看状态」：等级、金币、五条进度条 |

数值存在 `state.json` 的 `pets.penguin` 里（渲染页没有 fs 权限，通过 `pet:stats` IPC 落盘）。
想调手感（掉得快不快、喂一次加多少）只改 `nurture.mjs` 顶上的常量。

**放置逻辑**：面板贴窗口远离企鹅那一侧的边缘，气泡有 6 个候选位（上/左/右/下 + 面板上下），
按"能放下 + 不压住企鹅 + 不压住面板"依次挑 —— 之前面板和气泡在 420px 的窗口里必然叠在一起。

## 第 15 轮：三追（督战官）

用户要的："加一些经销商 PDCA 的追踪进去，每天三追一下 —— 追追待办、追追业绩。说这种话的，
带个眼镜、拿个教鞭。" 明确说了**不要真数据**，就是提醒/敲打。

### 三追

`penguin/chase.mjs`：**每天 09:30 / 14:00 / 17:30** 各追一次，主题轮着来 ——
早追**待办**、午追**业绩**、晚追**进度 + 收尾**，每类 6 句随机（"今天的任务完成了吗？"
"这个月业绩做了多少了？""卡在哪一步了，说清楚。"…），追完再补一句收尾
（"别嫌我烦，我是为你好。"）。

- **不读任何文件**，纯台词；
- **错过会补一次**：重启后如果已经过了某个时间点而且今天还没追过，就补一追；
  追过的记在 `state.json` 的 `pets.penguin.lastChase`（形如 `2026-09-24:1`），**同一天同一追只追一次**；
- 手动追：右键 →「督战官 → 现在追一下」；
- 右键 →「督战官 → 眼镜教鞭常驻」可以一直戴着。

### 督战官皮肤（`penguin/teacher.mjs`）

原版素材里没有眼镜教鞭，所以是**在企鹅本体上叠画**的，而且位置不是写死的：

1. 每帧先 `getImageData` 量出企鹅的**不透明轮廓**；
2. 再在轮廓**上半部分找成片的亮像素**（企鹅的脸是白的、肚皮在下半部分，能分开）→ 白脸的位置；
3. **眼镜对白脸居中**，宽度取脸宽的 0.74（并限不超过身体宽的一半 —— 第一版取 1.15 倍，
   结果眼镜糊住整张脸还盖住蝴蝶结）；
4. 教鞭从右侧翅膀那一点斜指右上，角度随时间小幅摆动（"点点点"）。

量出来的包围盒按 `动画名:帧号` 缓存，不然 12 fps 每帧都重新扫像素。
`--teacher-strip` 会把 6 个动作各抽 4 帧、放大 2 倍拼成一张对位图（蓝框=轮廓、橙框=白脸），
**这张图是调眼镜位置的关键** —— 第一版教鞭横穿脑袋就是它抓出来的。

## 第 14 轮：换成**真·QQ 企鹅原版素材**（重做形象）

用户看了第 12 轮手画的矢量企鹅："我看了做噩梦啊，你找不找得到正确的素材"。于是去找素材。

**结论：腾讯自己没开源过** QQ 宠物 / 企鹅形象（只有素材站和玩家二创），但有社区做的
**怀旧服逆向移植**：[xuemian168/qqpet_automation](https://github.com/xuemian168/qqpet_automation)
—— 把原版 Flash 游戏用 Ruffle 跑起来，Windows/macOS/Linux 都有包。素材就在里面。

### 怎么把素材扒出来的（全程没装任何东西，用系统自带工具）

1. **只取需要的字节**。267 MB 的 mac 包直连 GitHub 下到 73 MB 就 stall（curl 在重试循环里），
   于是先取 ZIP 尾部 128 KB 的**中央目录**，解析出 `app.asar` 的真实区间
   （`90294404`–`266702998`，deflate），再**分块 + 断点重试**只拉这一段（8 MB/块，168 MB 用了 744 秒）。
   顺带记一条：curl 的**后缀 range（`-r -131072`）在这个 CDN 上会失败，必须写显式区间**。
2. **解开 asar**（`assets-qqpet/unpack-asar.mjs`，自己写的）→ 4778 个文件，其中
   **1401 个 SWF（139 MB）**，目录结构就是原版动作库：
   `Action/{GG,MM}/{Egg,Kid,Adult}/{peaceful,happy,sad,upset,prostrate}/{play,interact,stand}/…`
   （GG=公、MM=母，三个成长阶段，各带心情分支）。
3. **SWF → PNG 帧**：用 [JPEXS FFDec](https://github.com/jindrapetrik/jpexs-decompiler)（免费，Java 就行，
   本机有 JDK 21）。正确姿势是 `-format frame:png -export frame <out> <swf>`：
   - `<itemtypes>` 里**不能**写 `frame:png`（会当成非法参数直接吐 usage）；
   - 每个动作都能出**统一的 140×140 帧序列**，12 fps（SWF 头里的 `frameRate=12`）；
   - 注意 `sad/upset/prostrate/Stand.swf` 这类是 AS3 驱动的，只出 1 帧，要改用同目录的 `play/P*.swf`。
4. **拼精灵图 + 抠背景**（`assets-qqpet/sheet-builder.js` + `sheet.html`，用 Electron 的 canvas 做图像处理）：
   - FFDec 导出的帧是**不透明底**，而且不同动作底色还不一样（Idle 是白 255，LevelUp 是灰 203）
     —— 只抠白色会漏掉一半。最终做法：**取四边像素的中位色当背景色**，四边足够统一（>90% 接近）
     才做容差泛洪（只吃与边界连通的区域，所以企鹅自己的白肚皮白脸不受影响），
     边缘按与背景色的距离给半透明；四边不统一的（浴缸、房间这类**场景动作**）原样保留场景。
   - 全部帧共用**同一个全局包围盒**，否则不同动作之间企鹅会跳位置。
   - 打包成 WebP（canvas 直接 `toDataURL("image/webp")`）：**35 个动作 / 4487 帧 / 11.7 MB**。

### 结果

`penguin/sheets/` 下 35 个动作，`penguin/frames.mjs` 是新的帧播放器（`FramePlayer`）：

- 待机 6 种（Idle1-5 + 公企鹅 GGIdle）、开心 3 种、打招呼 3 种、吃东西 2 种、洗澡 2 种、
  生病/治愈、升级、说话、出场/退场、趴下、难过、闹脾气、睡觉/醒来
- **成长阶段**直接用了原版三套素材：**Lv.1 是蛋 → Lv.2-4 幼年 → Lv.5 起成年**，
  喂食/清洁/生病在幼年期还会换成幼年专属动作（KidEat / KidDirty / KidHungry）
- 面板上会显示当前阶段（蛋/幼年/成年）

### 版权（必须说清楚）

这些美术资源**版权属于腾讯**，来自社区的逆向移植包，对方仓库自己写明
「仅供个人学习研究怀旧，严禁商业用途，与腾讯无关联亦未获授权」。
我们这边是**内部自用、不对外分发、不收费**；如果哪天要对外发布，这部分素材必须换掉。

## 第 13 轮：切角色后"桌宠不见了"

用户反馈：切到企鹅之后，桌面看不到角色了。

查证过程（这轮全是取证，没有猜）：

1. **进程和窗口都活着**。用 `EnumWindows` 找到桌宠窗口：`vis=True cls=C rect=(2140,1112)-(2560,1392) ex=0x80028`
   —— 可见、置顶、尺寸位置都对。
2. **窗口内容也是对的**。用 `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` 抓窗口像素，
   出来的就是那只戴红围巾的企鹅，位置和预期一致。
3. **第一次"截屏看不到"是假线索**：`Graphics.CopyFromScreen` 走的是 BitBlt(SRCCOPY)，
   **抓不到 WS_EX_LAYERED 窗口**（透明窗就是分层的）。换成 `BitBlt(SRCCOPY|CAPTUREBLT)`
   之后，桌面上确实有企鹅 —— 也就是说窗口"活着但屏幕上没重绘"。
4. **真正的触发点**：`switchChar()` 里调了 `win.setBounds()` 换尺寸 + `loadFile()` 重新加载页面。
   透明分层窗口在页面重载后可能停在"内容已更新、DWM 没重绘"的状态，用户看到的就是空的。

修法（三处兜底，`main.js`）：

- `raiseToTop()`：`setAlwaysOnTop(false)` → `setAlwaysOnTop(true,"floating")` → `moveTop()`，
  在**创建窗口后**、**换角色 setBounds 后**都调一次；
- `did-finish-load` 里延迟 120ms 再 `raiseToTop()` + `webContents.invalidate()`，
  保证新页面画完之后强制重绘一次；
- **看门狗**（2 秒一轮）新增：窗口可见但 `isAlwaysOnTop()` 为假 → 重新压一次并写日志
  `watchdog: lost always-on-top -> re-raise`。

顺带记两个以后能省时间的结论：
- 判断"桌宠在不在屏幕上"**只能**用 `BitBlt|CAPTUREBLT` 或 `PrintWindow`，
  普通截屏工具/`CopyFromScreen` 会把透明窗漏掉，得出"没显示"的错误结论。
- 判断 z 序要 `GetTopWindow()` 配 `GW_HWNDNEXT` **从顶往下**走；
  `GetWindow(GW_HWNDPREV)` 的方向容易记反（这轮就差点被带偏）。

## 打包成 exe 发给别人（第 11 轮）

交付物：**`dist\Clippy桌宠-安装包.exe`（82 MB，双击即装）**，无需管理员。

没用 electron-builder / npm，全用系统自带工具（`makecab` / `csc` / `expand` / `iexpress` 里的思路）：

1. **先裁载荷**。`host\` 里那 115 MB 的 `electron-win32-x64.zip` 是当初的解压源，运行时
   根本用不到；`locales\` 55 种语言占 **40 MB**，只留 `zh-CN / en-US / en-GB`。
2. **LZX 压成 CAB**。实测同一个 `electron.exe`：deflate(zip) **78.7 MB** vs
   LZX(cab) **66.3 MB**，所以选 CAB。整包 231 MB → **81.8 MB**（35%）。
   两个坑：DDF 里的中文文件名必须**按 GBK 写**（makecab 按 ANSI 解码，UTF-8 会变成 `????`）；
   并且要把 `.Set InfFileName/RptFileName` 指到源目录**外面** —— 否则 makecab 会把
   `setup.inf` 丢进源目录，下一次打包就把"自己的临时文件"也压进去然后报错。
3. **安装器**：单文件 C#（`dist\_build\src\Setup.cs`，系统自带 csc.exe 编译），把 CAB 作为
   资源内嵌，运行时调系统自带 `expand.exe` 解压到 `%LOCALAPPDATA%\ClippyPet`。
   带进度窗口；另有 `--silent / --target= / --desktop= / --menu= / --no-shortcut /
   --no-launch` 供自动化自测（自测全程不弹窗）。
4. **启动器 + 卸载器**：`ClippyPet.exe`（`dist\_build\src\ClippyPet.cs`，139 KB）——清掉
   `ELECTRON_RUN_AS_NODE`；已经在跑就不再开第二只；`--uninstall` 时先把自己复制到 %TEMP%
   再执行删除（否则删不掉正在运行的自己），删完连临时副本一起清掉。
5. **图标**：用 Electron 离屏窗口从精灵图里裁出 Clippy 本体，导出 16/32/48/64/128/256
   六个尺寸（小尺寸写 BMP、大尺寸写 PNG）拼成 `clippy.ico`；安装包、快捷方式都用它。

实测（全流程 `--silent`）：

```
安装   exit=0  37 个文件 231 MB
启动   ClippyPet.exe -> 5 个 electron 进程, window ready + booted
重复点 5 -> 5（不会开出第二只）
卸载   安装目录 / 桌面快捷方式 / 开始菜单 / 注册表项 全部清掉, %TEMP% 无残留
```

装到哪：`%LOCALAPPDATA%\ClippyPet`；桌面 + 开始菜单建快捷方式；「设置 → 应用」里能卸载。

**给别人时的提醒**：exe 没有代码签名，对方第一次运行可能弹 SmartScreen，
点「更多信息」→「仍要运行」。需要 .NET Framework 4.x（Win10/11 自带）。

重新打包：`dist\_build\` 下有 `app\`（裁剪后的载荷）、`src\`（两个 C# 源）、`icon\`（图标与
生成脚本）、`bin\`（编译产物）。改完 app 里的文件后重新 makecab + csc 即可。

## 卸载 / 清理

```powershell
# 关掉桌宠：托盘右键 → 退出（或任务管理器结束那个 VPS.exe 子进程）
# 彻底删除：
Remove-Item -Recurse -Force "D:\经销商PDCA\clippy-pet"

# 顺手清掉之前"改 VPS 包"那套方案的残留（不碰 VPS 安装目录）：
python "D:\经销商PDCA\pdca-workbench\app\vps_pet_pack\cleanup_old_patch.py"
```

## 已知边界

- **开机自启我没做**。要做的话，在启动文件夹放一个指向 `启动桌宠.cmd` 的快捷方式即可：
  `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`。等自检过了再考虑，别一上来就自启。
- 窗口尺寸 380×300，曲别针 124×93 放在窗口内可拖；`moveTo` 类动画只在窗口范围内走动，不是全屏漫游。
  要全屏漫游得改成全屏透明覆盖窗，那样会挡桌面点击，我没这么做。
- 音效默认开启，菜单里可静音（写进 `state.json`，重启仍生效）。
