# -*- coding: utf-8 -*-
"""督战证据日报（app 模块 + CLI）：把每人当天被系统读到的全部证据导成单文件 HTML。

固定测试流程（老板 2026-09-18 定）：
  1) 跑本脚本 → 生成 HTML 到桌面；
  2) 人工逐人核对「系统读到的 = 群里真实发生的」；
  3) 读错的进问题清单，改完再跑一遍，直到无误。

只读，不发任何消息。用法（在 pdca-workbench 目录下）：
  python scripts/evidence_report.py --day 2026-09-18 --out "C:/Users/frank/Desktop/督战证据_2026-09-18.html"
"""
from __future__ import annotations

import base64
import html
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from loguru import logger

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def load_env_file() -> None:
    """把 pdca-workbench/.env 灌进环境（与部署同源），已存在的变量不覆盖。"""
    path = APP_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def clip(text: object, limit: int = 200) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def wan(value: object) -> str:
    if value is None:
        return "待确认"
    try:
        return f"{round(float(value), 2):g} 万"
    except (TypeError, ValueError):
        return "待确认"


def hours(minutes: object) -> str:
    if minutes is None:
        return "待确认"
    try:
        return f"{float(minutes) / 60:.2f} h"
    except (TypeError, ValueError):
        return "待确认"


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


def thumb_b64(path: Path, max_width: int = 760, quality: int = 72) -> str | None:
    """缩略图转 base64，控制 HTML 体积；没有 Pillow 就原样嵌（过大则跳过）。"""
    try:
        from PIL import Image
    except Exception:  # noqa: BLE001 — 没有 Pillow 时退回原图
        raw = path.read_bytes()
        if len(raw) > 1_500_000:
            return None
        return "data:image/" + ("png" if path.suffix.lower() == ".png" else "jpeg") + ";base64," + base64.b64encode(raw).decode("ascii")
    try:
        with Image.open(path) as image:
            image = image.convert("RGB")
            if image.width > max_width:
                ratio = max_width / float(image.width)
                image = image.resize((max_width, int(image.height * ratio)))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001 — 单张图坏了不影响整份报告
        return None
def download_images(owner_rows: list[dict], raw_by_owner: dict[str, list[dict]], limit: int) -> dict[str, list[dict]]:
    """下载 MTO 图片并生成缩略图，返回 {display: [{name, b64, note}]}。"""
    out: dict[str, list[dict]] = {}
    workdir = Path(tempfile.mkdtemp(prefix="pdca-evidence-"))
    used = 0
    for row in owner_rows:
        display = str(row.get("display") or "")
        items: list[dict] = []
        for msg in raw_by_owner.get(display) or []:
            if used >= limit:
                break
            for att in msg.get("attachments") or []:
                if str(att.get("attachment_type") or "") != "image":
                    continue
                if used >= limit:
                    break
                name = str(att.get("name") or "image")
                url = str(att.get("url") or "")
                key = str(att.get("storage_key") or "")
                if not (url or key):
                    continue
                target = workdir / (str(used) + "-" + name.replace("/", "_"))
                args = ["im", "+attachment-download", "--output", str(target)]
                args += (["--url", url] if url else ["--storage-key", key])
                # 用 app.vertu.client 解析 CLI 路径：容器里 vertu-cli 不在 PATH 上，
                # 直接 subprocess("vertu-cli") 会静默失败（本地 951 KB、容器 53 KB 就是这个原因）。
                from app.vertu.client import run_vertu_sync

                code, _out, err = run_vertu_sync(args, timeout=90.0)
                if code != 0 or not target.exists():
                    logger.warning("证据日报图片下载失败 {}: {}", name, (err or "")[:120])
                    items.append({"name": name, "b64": None, "note": "下载失败"})
                    used += 1
                    continue
                b64 = thumb_b64(target)
                items.append({"name": name, "b64": b64, "note": "" if b64 else "图片过大未内嵌"})
                used += 1
        if items:
            out[display] = items
    return out


def collect(day: str, image_limit: int) -> dict:
    """一次采集：台账（含 MTO OCR）+ 每人当天原话 + MTO 原图。"""
    from app.duzhan_ledger import (  # noqa: PLC0415 — 延迟导入，先加载 .env
        DUZHAN_BOT_ID,
        OWNERS,
        _group_timezone,
        _history_ids,
        collect_ledger,
        fetch_channel_history,
        messages_on_day,
    )

    started = time.time()
    ledger = collect_ledger(day)
    raw_by_owner: dict[str, list[dict]] = {}
    attachments: dict[str, list[dict]] = {}
    for owner in OWNERS:
        merged: list[dict] = []
        for channel_id in _history_ids(owner):
            try:
                merged.extend(fetch_channel_history(channel_id, day, "200") or [])
            except Exception as exc:  # noqa: BLE001 — 单个群拉不到不影响整份报告
                print(f"[warn] 拉群历史失败 {owner.display} {channel_id}: {exc}")
        mine = [
            msg for msg in messages_on_day(merged, day, _group_timezone(owner))
            if msg.get("sender_user_id") == owner.im_user_id and not msg.get("revoked_at")
        ]
        mine.sort(key=lambda item: str(item.get("created_at") or ""))
        raw_by_owner[owner.display] = mine
        images: list[dict] = []
        for msg in mine:
            if str(msg.get("message_type") or "") != "image":
                continue
            for att in msg.get("attachments") or []:
                if str(att.get("attachment_type") or "") == "image":
                    images.append({"name": str(att.get("name") or "image"), "url": att.get("url"), "storage_key": att.get("storage_key")})
        attachments[owner.display] = images
    # 注意：把「每人的消息」传进去（download_images 自己挑图片附件），
    # 传附件字典会取不到图片——2026-09-18 首版就因此一张图都没内嵌。
    images = download_images(
        [{"display": item.display} for item in OWNERS], raw_by_owner, image_limit
    )
    ledger["_raw_by_owner"] = raw_by_owner
    ledger["_images"] = images
    ledger["_elapsed"] = round(time.time() - started, 1)
    ledger["_bot_id"] = DUZHAN_BOT_ID
    return ledger
CSS = """
:root { color-scheme: light; }
body { font-family: "Segoe UI", "Microsoft YaHei", sans-serif; margin: 0; padding: 24px 32px 64px; color: #1f2328; background: #f6f7f9; }
h1 { font-size: 22px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 2px solid #d0d7de; }
h3 { font-size: 15px; margin: 18px 0 8px; }
.meta { color: #57606a; font-size: 13px; line-height: 1.7; }
.card { background: #fff; border: 1px solid #d0d7de; border-radius: 8px; padding: 16px 18px; margin: 14px 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 8px 18px; font-size: 13px; }
.kv { display: flex; gap: 6px; }
.kv b { color: #57606a; font-weight: 600; min-width: 78px; }
table { border-collapse: collapse; width: 100%; font-size: 13px; background: #fff; }
th, td { border: 1px solid #d0d7de; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #eef1f4; font-weight: 600; }
.pending { color: #9a6700; }
.bad { color: #b42318; }
.good { color: #1a7f37; }
ul { margin: 6px 0 6px 18px; padding: 0; }
li { margin: 3px 0; font-size: 13px; }
pre { background: #f6f8fa; border: 1px solid #e3e6ea; border-radius: 6px; padding: 10px; overflow-x: auto; font-size: 12.5px; white-space: pre-wrap; }
details { margin: 6px 0; }
summary { cursor: pointer; font-size: 13px; color: #0969da; }
.imgs { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 8px; }
.imgs figure { margin: 0; width: 250px; }
.imgs img { width: 250px; border: 1px solid #d0d7de; border-radius: 6px; }
.imgs figcaption { font-size: 12px; color: #57606a; word-break: break-all; }
.tag { display: inline-block; font-size: 12px; padding: 1px 6px; border-radius: 10px; background: #eef1f4; color: #57606a; margin-right: 6px; }
"""


def evidence_li(items: list[dict], lang: str = "zh") -> str:
    """三关键词明细：金额 + 原文 + 来源。"""
    if not items:
        return "<li class='pending'>未检索到（没有匹配到原话）</li>"
    out = []
    for item in items[:12]:
        amount = item.get("amount_text") or "<span class='pending'>金额待确认</span>"
        snippet = esc(clip(item.get("snippet"), 160))
        source = esc(item.get("source") or "")
        out.append(f"<li><b>{amount}</b> ｜ 原文：{snippet} ｜ 来源：{source}</li>")
    return "".join(out)


def mto_block(row: dict, images: list[dict]) -> str:
    quotes = [item for item in (row.get("mto_quotes") or []) if isinstance(item, dict)]
    lines = []
    for item in quotes:
        verdict = item.get("verdict") or ("达标" if item.get("qualifies") else "未达标")
        lines.append(
            "<li>"
            + esc(item.get("file") or "?")
            + " ｜ 型号 " + esc(item.get("model") or "读不出")
            + " ｜ USD " + esc(item.get("usd") or "读不出")
            + " ｜ 折 " + esc(wan(item.get("wan")))
            + " ｜ " + esc(verdict)
            + " ｜ 交期 " + esc(item.get("delivery") or "读不出")
            + " ｜ 客户 " + esc(item.get("customer") or "读不出")
            + "</li>"
        )
    if not lines:
        lines.append("<li class='pending'>没有可解析的报价图</li>")
    imgs = ""
    if images:
        blocks = []
        for image in images:
            if image.get("b64"):
                blocks.append(
                    "<figure><img src='" + image["b64"] + "' alt='" + esc(image.get("name")) + "'/>"
                    "<figcaption>" + esc(image.get("name")) + "</figcaption></figure>"
                )
            else:
                blocks.append(
                    "<figure><figcaption>" + esc(image.get("name")) + "（" + esc(image.get("note")) + "）</figcaption></figure>"
                )
        imgs = "<div class='imgs'>" + "".join(blocks) + "</div>"
    return "<ul>" + "".join(lines) + "</ul>" + imgs


def person_card(row: dict, raw: list[dict], images: list[dict]) -> str:
    name = esc(row.get("display"))
    parts = [f"<div class='card'><h3>👤 {name} <span class='tag'>{esc(row.get('group'))}</span></h3>"]
    target = row.get("target_wan")
    target_text = wan(target) if target is not None else (
        "按小组口径 " + esc(row.get("group_target_name") or "小组") + " " + wan(row.get("group_target_wan"))
        if row.get("group_target_wan") else "<span class='pending'>待确认</span>"
    )
    gap = row.get("target_gap_wan")
    gap_text = "—"
    if gap is not None:
        gap_text = ("<span class='good'>领先 " if row.get("target_ahead") else "<span class='bad'>落后 ") + f"{abs(float(gap)):g} 万</span>"
    parts.append(
        "<div class='grid'>"
        f"<div class='kv'><b>月目标</b>{target_text}</div>"
        f"<div class='kv'><b>滚动日目标</b>{esc(row.get('daily_target_wan') if row.get('daily_target_wan') is not None else '待确认')} 万/天</div>"
        f"<div class='kv'><b>累计应达</b>{wan(row.get('rolling_target_wan'))}</div>"
        f"<div class='kv'><b>累计到账</b>{wan(row.get('perf_arrived_wan'))}</div>"
        f"<div class='kv'><b>领先/落后</b>{gap_text}</div>"
        f"<div class='kv'><b>WhatsApp</b>{esc(row.get('wa_reached') if row.get('wa_reached') is not None else '待确认')} 户"
        + ("（已同步下限）" if row.get("wa_lower_bound") else "") + "</div>"
        f"<div class='kv'><b>明确意向</b>{esc(row.get('intent_count') if row.get('intent_count') is not None else '待确认')} 户（MCP）</div>"
        f"<div class='kv'><b>MTO 4 款</b>{esc(row.get('mto_count') if row.get('mto_count') is not None else '待确认')} 张</div>"
        f"<div class='kv'><b>工时</b>{hours(row.get('hours_minutes'))}｜{esc(row.get('hours_band') or '待确认')}</div>"
        f"<div class='kv'><b>日报</b>{'已交 ' + str((row.get('daily_report') or {}).get('item_count') or 0) + ' 项' if row.get('daily_report') else '未见'}</div>"
        f"<div class='kv'><b>评分</b>{esc(round(float(row.get('score') or 0)))} 分</div>"
        "</div>"
    )
    parts.append("<h3>① 业绩三关键词（原文级证据）</h3><ul>")
    parts.append("<li><b>到账（系统已录单）</b>：" + wan(row.get("perf_arrived_wan")) + "（系统口径，不是群原话）</li>")
    parts.append("<li><b>水单</b>（客户已付款未到账）：</li>" + evidence_li(row.get("perf_slip") or []))
    parts.append("<li><b>意向</b>（明确意向金额）：</li>" + evidence_li(row.get("perf_intent") or []))
    parts.append("</ul>")
    parts.append("<h3>② MTO 报价图 + OCR 结果</h3>" + mto_block(row, images))
    coll = row.get("collections") or []
    parts.append("<h3>③ 催款/任务（系统读到的条目）</h3>")
    if coll:
        parts.append("<ul>" + "".join(
            "<li>" + esc(clip(item.get("title"), 120)) + " ｜ 金额 " + esc(item.get("amount") or "待确认")
            + " ｜ 进度 " + esc(item.get("progress") or "待确认")
            + " ｜ 状态 " + esc(item.get("status") or "待确认") + "</li>"
            for item in coll[:12]
        ) + "</ul>")
    else:
        parts.append("<div class='pending'>未读到任务条目</div>")
    blockers = row.get("blockers") or []
    parts.append("<h3>④ 卡点与证据</h3><ul>")
    parts.append("<li>卡点：" + (esc("；".join(clip(item, 120) for item in blockers)) if blockers else "<span class='pending'>未见</span>") + "</li>")
    parts.append("<li>证据：" + (esc(" / ".join(clip(item, 60) for item in (row.get("evidence") or [])[:8])) or "<span class='pending'>无</span>") + "</li>")
    parts.append("</ul>")
    parts.append("<h3>⑤ 工时拆解 / VPS / Vemory</h3><ul>")
    parts.append("<li>工时拆解：" + esc(json.dumps(row.get("hours_parts") or {}, ensure_ascii=False)) + "</li>")
    parts.append("<li>WA 窗口：" + esc(row.get("hours_window") or "待确认") + "</li>")
    parts.append(
        "<li>VPS：IM " + esc(row.get("vps_im_sent") if row.get("vps_im_sent") is not None else "待确认")
        + " 条 / Agent " + esc(row.get("vps_agent_calls") if row.get("vps_agent_calls") is not None else "待确认")
        + " 次 / 轮数 " + esc(row.get("vps_turns") if row.get("vps_turns") is not None else "待确认")
        + "（" + esc(row.get("vps_first") or "") + "-" + esc(row.get("vps_last") or "") + "）</li>"
    )
    meetings = row.get("vemory") or []
    parts.append("<li>Vemory：" + (esc("；".join(clip(item.get("name"), 60) for item in meetings[:5])) if meetings else "无有效录音") + "</li>")
    parts.append("</ul>")
    parts.append(
        "<details><summary>⑥ 当天本人群原话（" + str(len(raw)) + " 条，用于逐条核对系统有没有读错）</summary><pre>"
        + esc("\n".join(
            str(msg.get("created_at") or "")[:19] + "  " + str(msg.get("message_type") or "") + "  " + clip(msg.get("body") or "（无正文）", 400)
            for msg in raw[:60]
        ) or "无")
        + "</pre></details>"
    )
    parts.append("</div>")
    return "".join(parts)
def overview_table(people: list[dict], raw_by_owner: dict, images: dict) -> str:
    head = (
        "<tr><th>姓名</th><th>群</th><th>月目标</th><th>日目标</th><th>累计应达</th><th>累计到账</th>"
        "<th>领先/落后</th><th>水单</th><th>意向</th><th>MTO</th><th>WhatsApp</th><th>工时</th>"
        "<th>日报</th><th>原话</th><th>图片</th></tr>"
    )
    rows = []
    for row in people:
        name = str(row.get("display") or "")
        gap = row.get("target_gap_wan")
        if gap is None:
            gap_text = "—"
        else:
            gap_text = ("领先 " if row.get("target_ahead") else "落后 ") + f"{abs(float(gap)):g} 万"
        target = wan(row.get("target_wan")) if row.get("target_wan") is not None else (
            "小组口径 " + wan(row.get("group_target_wan")) if row.get("group_target_wan") else "待确认"
        )
        rows.append(
            "<tr>"
            f"<td><b>{esc(name)}</b></td><td>{esc(row.get('group'))}</td><td>{target}</td>"
            f"<td>{esc(row.get('daily_target_wan') if row.get('daily_target_wan') is not None else '待确认')}</td>"
            f"<td>{wan(row.get('rolling_target_wan'))}</td><td>{wan(row.get('perf_arrived_wan'))}</td>"
            f"<td>{gap_text}</td>"
            f"<td>{len(row.get('perf_slip') or [])} 条</td><td>{len(row.get('perf_intent') or [])} 条</td>"
            f"<td>{esc(row.get('mto_count') if row.get('mto_count') is not None else '待确认')} 张</td>"
            f"<td>{esc(row.get('wa_reached') if row.get('wa_reached') is not None else '待确认')} 户</td>"
            f"<td>{hours(row.get('hours_minutes'))}</td>"
            f"<td>{'已交' if row.get('daily_report') else '未见'}</td>"
            f"<td>{len(raw_by_owner.get(name) or [])}</td>"
            f"<td>{len(images.get(name) or [])}</td>"
            "</tr>"
        )
    return "<table>" + head + "".join(rows) + "</table>"


CHECKLIST = """
<h2>复查要点（人工逐条核对，读错就记下来改）</h2>
<ol>
  <li><b>三关键词</b>：每条原话是不是本人说的？金额有没有读错、有没有把“无/无意向/模板回显”当成客户水单或意向？</li>
  <li><b>MTO</b>：图片张数 = 群里实际发的报价图张数？OCR 的型号 / USD / 是否≥30万 / 交期 / 客户名 对不对？</li>
  <li><b>WhatsApp / 意向户数</b>：来自平台统计（MCP），与本人实际聊天量是否同量级？</li>
  <li><b>工时</b>：WA / MTO / 催收 / 会议 / VPS 五块之和是否合理？申报工时与系统证据差多少？</li>
  <li><b>日报</b>：卡片是否已交？条目数与本人自报是否一致？</li>
  <li><b>催款任务 / 卡点</b>：有没有漏读或多读（把计划当卡点）？</li>
  <li><b>红黑榜</b>：综合分 = 过程 50% + 业绩 50%，与事实印象是否一致？</li>
</ol>
<p class="meta">口径：到账=系统已录单；水单=客户已付款未到我们账户；意向=明确意向金额；读不出写「待确认」，一笔都没有写「未检索到」，绝不用 0 冒充。本文件只读生成，未向任何群发送消息。</p>
"""


def build_html(day: str, ledger: dict) -> str:
    people = ledger.get("people") or []
    raw_by_owner = ledger.get("_raw_by_owner") or {}
    images = ledger.get("_images") or {}
    red = ledger.get("red") or []
    black = ledger.get("black") or []
    now = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
    total_images = sum(len(items) for items in images.values())
    embeds = sum(1 for items in images.values() for item in items if item.get("b64"))
    head = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        f"<title>督战证据日报 {esc(day)}</title><style>{CSS}</style></head><body>",
        f"<h1>督战证据日报 · {esc(day)}</h1>",
        "<p class='meta'>"
        f"生成时间：{esc(now)}（北京时间）｜人数：{len(people)}｜MTO 图：{total_images} 张（内嵌 {embeds} 张）"
        f"｜采集耗时：{esc(ledger.get('_elapsed'))} 秒<br/>"
        "数据源：系统已录单（个人 OKR）｜达标群 + 个人跟进群原话（IM）｜AINativeSales MCP（WhatsApp/意向）"
        "｜Vemory 会议｜VPS Agent/IM 活动｜群内报价图（本地 Qwen OCR）"
        "</p>",
        "<h2>总览</h2>",
        overview_table(people, raw_by_owner, images),
        "<h2>红黑榜（综合 = 过程 50% + 业绩 50%）</h2><ul>",
        "<li><b>红榜</b>：" + ("；".join(
            f"{esc(item.get('display'))} 综合{esc(round(float(item.get('combined_score') or 0)))}"
            f"｜过程{esc(round(float(item.get('score') or 0)))}"
            f"｜业绩{esc(item.get('perf_score') if item.get('perf_score') is not None else '按小组口径')}"
            for item in red
        ) or "待确认") + "</li>",
        "<li><b>黑榜</b>：" + ("；".join(
            esc(item.get("display")) + " " + esc(item.get("reason")) for item in black
        ) or "无") + "</li>",
        "</ul>",
        "<h2>逐人证据</h2>",
    ]
    body = [person_card(row, raw_by_owner.get(str(row.get("display"))) or [], images.get(str(row.get("display"))) or []) for row in people]
    return "".join(head) + "".join(body) + CHECKLIST + "</body></html>"

def save_report(day: str, out_dir: Path, image_limit: int = 24) -> dict:
    """采集 + 渲染 + 落盘（HTML 与同名 JSON），返回概要，供定时任务调用。"""
    started = time.time()
    ledger = collect(day, max(image_limit, 0))
    html_text = build_html(day, ledger)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"督战证据_{day}.html"
    html_path.write_text(html_text, encoding="utf-8")
    people = ledger.get("people") or []
    raw = ledger.get("_raw_by_owner") or {}
    images = ledger.get("_images") or {}
    summary = {
        "day": day,
        "html": str(html_path),
        "bytes": html_path.stat().st_size,
        "people": len(people),
        "images": sum(len(items) for items in images.values()),
        "messages": sum(len(items) for items in raw.values()),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (out_dir / f"督战证据_{day}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return summary
