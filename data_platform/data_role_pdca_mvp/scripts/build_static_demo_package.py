# -*- coding: utf-8 -*-
"""
打包静态演示包：HTML 模板 + 当前固化 JSON，无需 vertu / 8767 工作台。

输出：dist/pdca-demo-static/ 与 dist/pdca-demo-static.zip
用法：python scripts/build_static_demo_package.py --date 2026-06-05
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
WORKSPACE = SCRIPTS.parent
REPO_ROOT = WORKSPACE.parents[1]
DIST = REPO_ROOT / "dist" / "pdca-demo-static"
DEMO_DATE = "2026-06-05"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


def _import_workbench():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import pdca_workbench as wb  # noqa: WPS433

    return wb


def collect_home_api_snapshot(date_text: str) -> dict[str, object]:
    """导出首页各 API 的 JSON 快照（与当日工作台一致）。"""
    wb = _import_workbench()
    period = "day"
    return {
        "dashboard-overview.json": wb.api_dashboard_overview(date_text, period),
        "sell-in.json": {
            "amount": wb.api_dashboard_overview(date_text, period)["sellInAmount"],
            "wan": wb.api_dashboard_overview(date_text, period)["sellInWan"],
            "note": wb.api_dashboard_overview(date_text, period)["sellInSub"],
        },
        "sell-out.json": {
            "amount": wb.api_dashboard_overview(date_text, period)["sellOutAmount"],
            "wan": wb.api_dashboard_overview(date_text, period)["sellOutWan"],
            "note": wb.api_dashboard_overview(date_text, period)["sellOutSub"],
        },
        "todos-today.json": wb.api_todos_today(date_text),
        "hermes-agent-tasks.json": wb.api_hermes_agent_tasks(date_text),
        "customer-center-summary.json": wb.api_customer_center_summary(),
        "hr-summary.json": wb.api_hr_summary(),
        "exceptions.json": wb.api_exceptions(date_text),
        "important-matters.json": wb.api_important_matters(date_text),
        "task-center-summary.json": wb.api_task_center_summary(date_text),
        "meeting-center-summary.json": wb.api_meeting_center_summary(date_text),
    }


def patch_home_dashboard(html: str, date_text: str) -> str:
    """API 改读本地 data/*.json，链接改相对路径。"""
    replacements = {
        "dashboard: '/api/dashboard/overview'": "dashboard: 'data/dashboard-overview.json'",
        "sellIn: '/api/dashboard/sell-in'": "sellIn: 'data/sell-in.json'",
        "sellOut: '/api/dashboard/sell-out'": "sellOut: 'data/sell-out.json'",
        "todo: '/api/todos/today'": "todo: 'data/todos-today.json'",
        "agentTasks: '/api/hermes-agent/tasks'": "agentTasks: 'data/hermes-agent-tasks.json'",
        "customerCenter: '/api/customer-center/summary'": "customerCenter: 'data/customer-center-summary.json'",
        "humanCenter: '/api/hr/summary'": "humanCenter: 'data/hr-summary.json'",
        "exceptions: '/api/exceptions'": "exceptions: 'data/exceptions.json'",
        "importantMatters: '/api/important-matters'": "importantMatters: 'data/important-matters.json'",
        "taskCenter: '/api/task-center/summary'": "taskCenter: 'data/task-center-summary.json'",
        "meetingCenter: '/api/meeting-center/summary'": "meetingCenter: 'data/meeting-center-summary.json'",
        "processSuggestion: '/api/agent/process-suggestion'": "processSuggestion: 'data/process-suggestion-stub.json'",
        "['/数据看板', '/dashboard']": "['数据看板', '../dashboard.html']",
        "withDate('/walkin-cockpit/')": (
            "'../walkin-cockpit/index.html?date=' + encodeURIComponent(workDate()) + '#oi-merged'"
        ),
    }
    for old, new in replacements.items():
        html = html.replace(old, new)

    static_go_detail = f"""
    function goDetail(type) {{
      const date = workDate();
      const q = '?date=' + encodeURIComponent(date);
      if (type === 'pdca' || type === 'todo' || type.indexOf('agent-task-') === 0) {{
        location.href = '../walkin-cockpit/index.html' + q + '#oi-merged';
        return;
      }}
      if (type.indexOf('vemory') === 0) {{
        location.href = '../meeting-center/index.html' + q;
        return;
      }}
      if (type.indexOf('customer') === 0 || type === 'customer' || type.indexOf('hr') === 0 || type === 'hr') {{
        alert('演示包未包含客户/人力详情页');
        return;
      }}
      alert('演示包：' + type);
    }}"""
    html = re.sub(
        r"function goDetail\(type\) \{[\s\S]*?\n    \}",
        static_go_detail.strip(),
        html,
        count=1,
    )
    banner = (
        '<div class="card" style="margin-bottom:12px;padding:10px 14px;background:#fff8e6;border:1px solid #f0d78c;font-size:13px;">'
        "📦 <strong>静态演示包</strong>：数据已固化，无需 VPS/工作台。建议在本目录执行 "
        "<code>python -m http.server 8080</code> 后打开 "
        f"<code>http://127.0.0.1:8080/</code>（快照日 {date_text}）。</div>"
    )
    html = html.replace('<div class="container">', '<div class="container">' + banner, 1)
    return html


def patch_walkin_index(html: str, date_text: str) -> str:
    """演示包只读 data/ JSON，不走 /api。"""
    html = html.replace(
        "return 'http://127.0.0.1:3780';",
        "return '';",
    )
    html = html.replace(
        "fetch(walkinApiUrl(ym), { cache: 'no-store' })",
        "Promise.reject(new Error('demo-static'))",
    )
    html = html.replace(
        "WalkinOnlineMerged.init(undefined, 'data/vn_data_collect_reference.json')",
        "WalkinOnlineMerged.init('data/online_channel_reference.json', 'data/vn_data_collect_reference.json')",
    )
    note = (
        f'<p style="font-size:12px;color:#64748b;margin:8px 0 0">静态演示包 · 数据快照 {date_text} · 仅读 data/*.json</p>'
    )
    html = html.replace("<body>", "<body>" + note, 1)
    return html


def patch_meeting_center(html: str) -> str:
    """会议中心改读本地 data/*.json。"""
    html = html.replace(
        "const res = await fetch('/api/meeting-center/people');",
        "const res = await fetch('data/people.json');",
    )
    html = html.replace(
        "const res = await fetch('/api/meeting-center/meetings?' + qs.toString());",
        "const res = await fetch('data/meetings.json');",
    )
    html = html.replace(
        "const res = await fetch('/api/meeting-center/dispatch', {",
        "alert('演示包：分配待办功能已禁用'); return;\n      const res = await fetch('data/dispatch-stub.json', {",
    )
    html = html.replace(
        "location.href = withDate('/pdca-vps');",
        "location.href = '../walkin-cockpit/index.html?date=' + encodeURIComponent(workDate()) + '#oi-merged';",
    )
    note = (
        '<div style="margin:8px 0;padding:8px 12px;background:#fff8e6;border:1px solid #f0d78c;font-size:12px;">'
        "📦 静态演示包 · 会议数据已固化</div>"
    )
    html = html.replace("<body>", "<body>" + note, 1)
    return html


def patch_online_merged_js(js: str) -> str:
    """线上经营块固定读 data/online_channel_reference.json。"""
    js = js.replace(
        "function defaultChannelUrl() {\n    if (typeof location !== 'undefined' && location.protocol.indexOf('http') === 0) {\n      var dateQ = new URLSearchParams(location.search).get('date');\n      return dateQ ? '/api/online-channel?date=' + encodeURIComponent(dateQ) : '/api/online-channel';\n    }\n    return 'data/online_channel_reference.json';\n  }",
        "function defaultChannelUrl() {\n    return 'data/online_channel_reference.json';\n  }",
    )
    return js


def copy_tree(src: Path, dst: Path, ignore=None) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def write_readme(date_text: str) -> None:
    """写入演示包说明 README.md。"""
    _write_text(
        DIST / "README.md",
        f"""# 经销商 PDCA · 静态演示包

本压缩包为**只读演示**：HTML 页面 + 固化 JSON 数据，无需安装 vertu CLI，无需启动 8767 工作台，也无需访问 VPS。

**数据快照日：{date_text}**

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
| 经营驾驶舱 | `home/index.html?date={date_text}` | Sell in/out、待办、会议摘要等 |
| 数据看板 | `dashboard.html` | 34 家门店 + 大区树 + 业绩 |
| 客流 / 线上 OKR | `walkin-cockpit/index.html?date={date_text}#oi-merged` | 海外客流、线上渠道线索 |
| 会议中心 | `meeting-center/index.html?date={date_text}` | Vemory 会议列表（快照） |

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
""",
    )


def build(date_text: str) -> Path:
    global DEMO_DATE
    DEMO_DATE = date_text
    month = date_text[:7]

    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)

    # 入口导航
    _write_text(
        DIST / "index.html",
        f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"/><title>PDCA 静态演示包</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;line-height:1.6}}
a{{display:block;margin:8px 0;color:#2563eb}}</style></head><body>
<h1>经销商 PDCA · 静态演示</h1>
<p>数据快照日：<strong>{date_text}</strong>。请先在本文件夹打开终端执行：</p>
<pre>python -m http.server 8080</pre>
<p>浏览器访问 <a href="http://127.0.0.1:8080/">http://127.0.0.1:8080/</a></p>
<h2>页面</h2>
<a href="home/index.html?date={date_text}">经营首页（驾驶舱）</a>
<a href="dashboard.html">数据看板（门店大区树 + 业绩）</a>
<a href="walkin-cockpit/index.html?date={date_text}#oi-merged">客流分析 / 线上 OKR</a>
<a href="meeting-center/index.html?date={date_text}">会议中心（Vemory 快照）</a>
<h2>说明</h2>
<ul>
<li>无需 vertu CLI、无需 8767 工作台</li>
<li>业绩/门店/渠道/会议数据已写入 JSON，与打包当日一致</li>
<li>解压后在本目录执行 <code>python -m http.server 8080</code>，用浏览器打开（勿直接双击 HTML）</li>
</ul>
</body></html>""",
    )

    # 数据看板（已内嵌 DEALER_REGION）
    dash_src = WORKSPACE / "outputs" / date_text / "dashboard.html"
    if not dash_src.is_file():
        candidates = sorted((WORKSPACE / "outputs").glob("*/dashboard.html"), reverse=True)
        dash_src = candidates[0] if candidates else None
    if dash_src and dash_src.is_file():
        shutil.copy2(dash_src, DIST / "dashboard.html")
    else:
        _write_text(DIST / "dashboard.html", "<p>未找到 dashboard.html，请先运行 PDCA 生成 outputs。</p>")

    # 经营首页
    home_dir = DIST / "home"
    home_dir.mkdir(parents=True)
    for css in ("workbench-unified.css", "workbench-cockpit-shell.css"):
        src = WORKSPACE / "modules" / "home_dashboard" / css
        if src.is_file():
            shutil.copy2(src, home_dir / css)
    snapshot = collect_home_api_snapshot(date_text)
    data_dir = home_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in snapshot.items():
        _write_json(data_dir / name, payload)
    _write_json(data_dir / "process-suggestion-stub.json", {"ok": True, "message": "演示包：建议已记录"})

    home_html = patch_home_dashboard(
        _read_text(WORKSPACE / "modules" / "home_dashboard" / "index.html"),
        date_text,
    )
    home_html = home_html.replace('href="workbench-unified.css"', 'href="workbench-unified.css"')
    _write_text(home_dir / "index.html", home_html)

    # Walk-in + 线上经营
    wi_src = WORKSPACE / "modules" / "walkin_cockpit"
    wi_dst = DIST / "walkin-cockpit"
    ignore = shutil.ignore_patterns("_dealer_*", "*.xlsx")
    copy_tree(wi_src, wi_dst, ignore=ignore)
    _write_text(wi_dst / "index.html", patch_walkin_index(_read_text(wi_dst / "index.html"), date_text))
    om_js = wi_dst / "online-merged-insights.js"
    if om_js.is_file():
        _write_text(om_js, patch_online_merged_js(_read_text(om_js)))

    # 确保当月 walkin 包存在
    if str(REPO_ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from workbench_data import build_walkin_api_payload, write_online_channel_reference  # noqa: WPS433

    write_online_channel_reference(date_text)
    bundle = build_walkin_api_payload(month, date_text)
    _write_json(wi_dst / "data" / f"walkin-{month}.json", bundle)

    # 会议中心（固化 Vemory 快照）
    mc_src = WORKSPACE / "modules" / "meeting_center" / "index.html"
    if mc_src.is_file():
        mc_dst = DIST / "meeting-center"
        mc_dst.mkdir(parents=True, exist_ok=True)
        wb = _import_workbench()
        mc_data = mc_dst / "data"
        mc_data.mkdir(parents=True, exist_ok=True)
        _write_json(mc_data / "people.json", wb.api_meeting_center_people())
        _write_json(mc_data / "meetings.json", wb.api_meeting_center_meetings(date_text))
        _write_json(mc_data / "dispatch-stub.json", {"ok": True, "message": "演示包：分配已记录"})
        _write_text(mc_dst / "index.html", patch_meeting_center(_read_text(mc_src)))
        for css in home_dir.glob("workbench-*.css"):
            shutil.copy2(css, mc_dst / css.name)

    write_readme(date_text)

    # zip
    zip_path = DIST.parent / "pdca-demo-static.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in DIST.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(DIST.parent))
    print("demo_dir", DIST)
    print("zip", zip_path)
    return DIST


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=DEMO_DATE)
    args = parser.parse_args()
    build(args.date)


if __name__ == "__main__":
    main()
