# 经销商 PDCA · 静态演示包

本压缩包为**只读演示**：HTML 页面 + 固化 JSON 数据，无需安装 vertu CLI，无需启动 8767 工作台，也无需访问 VPS。

**数据快照日：2026-06-05**

## 快速开始

1. 解压本文件夹（或 `pdca-demo-static.zip`）
2. 在解压后的目录打开终端（PowerShell / CMD / Terminal）
3. 启动本地静态服务：

```bash
python -m http.server 8080
```

4. 浏览器打开：**http://127.0.0.1:8080/**

> 请勿直接双击 `.html` 文件。浏览器安全策略会阻止页面读取本地 JSON，必须通过 HTTP 服务访问。

## 页面导航

| 入口 | 路径 | 说明 |
|------|------|------|
| 导航首页 | `index.html` | 汇总链接 |
| 经营驾驶舱 | `home/index.html?date=2026-06-05` | Sell in/out、待办、会议摘要等 |
| 数据看板 | `dashboard.html` | 34 家门店 + 大区树 + 业绩 |
| 客流 / 线上 OKR | `walkin-cockpit/index.html?date=2026-06-05#oi-merged` | 海外客流、线上渠道线索 |
| 会议中心 | `meeting-center/index.html?date=2026-06-05` | Vemory 会议列表（快照） |

## 数据说明

- 所有数字、门店、渠道线索均已写入各目录下的 `data/*.json`
- 内容与打包当日工作台/VPS 一致，**不会自动更新**
- 会议中心「分配待办」在演示包中已禁用，仅可浏览

## 常见问题

**页面空白或报错？**  
确认已执行 `python -m http.server`，且访问地址为 `http://127.0.0.1:8080/`，不是 `file:///`。

**想换一天的数据？**  
需由维护方在源码仓库重新执行打包脚本（`build_static_demo_package.py --date YYYY-MM-DD`）后重新分发 zip。

## 目录结构（简要）

```
pdca-demo-static/
├── README.md          ← 本文件
├── index.html         ← 导航入口
├── dashboard.html     ← 数据看板
├── home/              ← 经营首页 + data/
├── walkin-cockpit/    ← 客流分析 + data/
└── meeting-center/    ← 会议中心 + data/
```
