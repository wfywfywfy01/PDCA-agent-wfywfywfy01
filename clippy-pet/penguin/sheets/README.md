# 企鹅精灵图（**不入库**）

`*.webp` 是从 **QQ 宠物原版 Flash 素材** 导出的帧序列，**版权属于腾讯**，
所以**不放进这个公开仓库**（`.gitignore` 里排除了 `clippy-pet/penguin/sheets/*.webp`）。
`sheets.mjs`（帧数 / 行列 / 循环设置）是我们自己生成的元数据，正常入库。

## 怎么自己重新生成

素材来源：社区的 QQ 宠物怀旧服逆向移植项目
`https://github.com/xuemian168/qqpet_automation`
（对方仓库自己声明：仅供个人学习研究怀旧，**严禁商业用途**，与腾讯无关联亦未获授权。
 本项目同属内部自用，不再对外分发这批美术。）

```powershell
# 前置：JDK 17+（跑 FFDec）、本机 Electron（clippy-pet\host\electron.exe）
cd D:\经销商PDCA\clippy-pet
$dl = "$PWD\assets-qqpet"

# 1) 只拉 app.asar 那一段（整包 267MB 直连 GitHub 会 stall：脚本先取 ZIP 尾部中央目录
#    算出 app.asar 的字节区间，再 8MB 一块 + 断点重试地拉）
. .\tools\qqpet-assets\fetch-chunks.ps1
node .\tools\qqpet-assets\fetch-asar.mjs "$dl\chunks" "$dl\app.asar"

# 2) 解开 asar（4778 个文件，其中 1401 个 SWF 就是原版动作库）
node .\tools\qqpet-assets\unpack-asar.mjs "$dl\app.asar" "$dl\app"

# 3) SWF -> PNG 帧（需要 FFDec = JPEXS Free Flash Decompiler）
. .\tools\qqpet-assets\export-frames.ps1 -Dl $dl

# 4) 拼精灵图 + 抠背景（用 Electron 的 canvas 做图像处理）
.\host\electron.exe .\tools\qqpet-assets\sheet-builder.js --scale 1 --quality 0.92
# 产物：assets-qqpet\sheets\*.webp + sheets.json

# 5) 把 webp 拷进 penguin\sheets\，并据 sheets.json 重新生成 sheets.mjs
```

## 踩过的坑（脚本里都处理了）

- FFDec 的 `<itemtypes>` **不能**写 `frame:png`（会直接吐 usage），要写成
  `-format frame:png -export frame <out> <swf>`。
- `sad|upset|prostrate/Stand.swf` 是 AS3 驱动的，只导得出 1 帧，要改用同目录的 `play/P*.swf`。
- FFDec 导出的帧是**不透明底**，而且**不同动作底色还不一样**（待机是白 255、升级是灰 203）——
  只抠白色会漏一半。所以抠背景取"**四边像素的中位色**"当背景色，四边足够统一才做容差泛洪，
  只吃与边界连通的区域（企鹅自己的白肚皮白脸不受影响）；浴缸、房间这类场景动作保留场景。
- 所有帧共用**同一个全局包围盒**，否则不同动作之间企鹅会跳位置。
- 帧统一 **140×140、12 fps**（SWF 头里的 `frameRate`）。

## 没有这些图会怎样

`FramePlayer.load()` 加载失败不会崩，只是企鹅不放动画、画布空白。
正常使用请直接用 `dist\Clippy桌宠-安装包.exe`（里面带了素材），或按上面重新生成。
