# -*- coding: utf-8 -*-
"""Dump every user-fed Malaysia raw source onto Desktop. No summarising."""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(r"d:\经销商PDCA")
OUT = Path(r"C:\Users\frank\Desktop\于冰_马来西亚_投喂原件全刨.md")
SNAP_DIR = ROOT / "overseas_weekly" / "outputs"
SHARES = [
    ("1d939024", "2026-07-14 SWAP 门店布局"),
    ("4c58a03d", "2026-07-14 SWAP 零售/电动车"),
    ("6cc96a48", "2026-07-14 DirectD 选址（标题如此）"),
    ("d8ca9b58", "2026-07-15 Pavilion"),
    ("e547d52e", "2026-07-15 Genting 落位"),
    ("e478833d", "2026-07-15 Genting 参观"),
    ("d11b354d", "2026-07-16 KLCC"),
    ("997cda36", "2026-07-16 SWITCH"),
]


def ms_hms(ms: int | None) -> str:
    if not ms:
        return "00:00:00"
    s = int(ms) // 1000
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def dump_snapshot(sid: str, label: str) -> str:
    p = SNAP_DIR / f"_snap_{sid}.json"
    if not p.exists():
        return f"### {label} `{sid}`\n\n（snapshot 文件不存在）\n\n"
    j = json.loads(p.read_text(encoding="utf-8"))
    c = (j.get("data") or {}).get("content") or {}
    lines = [
        f"### {label}",
        "",
        f"- share: https://vemory-share.vemory.ai/share?id={sid}",
        f"- snapshot: https://vemory-meet.vemory.io/snapshot/{sid}",
        f"- name: {c.get('name')}",
        f"- id: {c.get('id')}",
        f"- audio_duration_ms: {c.get('audio_duration')} (~{(c.get('audio_duration') or 0)/60000:.1f}min)",
        f"- created_at: {c.get('created_at')}",
        f"- start_record_time: {c.get('start_record_time')}",
        f"- end_record_time: {c.get('end_record_time')}",
        f"- user_id: {c.get('user_id')}",
        f"- tags: {c.get('tags')}",
        "",
        "#### summary",
        "",
        c.get("summary") or "（无）",
        "",
        "#### chapters",
        "",
    ]
    for ch in c.get("chapters") or []:
        lines.append(f"- **{ch.get('start_time')} {ch.get('title')}**：{ch.get('content')}")
    lines += ["", "#### todos", ""]
    for t in c.get("todos") or []:
        lines.append(f"- [{t.get('status')}] {t.get('speaker')}: {t.get('content')}")
    sents = ((c.get("transcription") or {}).get("sentences")) or []
    lines += ["", f"#### transcription（{len(sents)} 句，原文不删）", ""]
    for s in sents:
        lines.append(
            f"- [{ms_hms(s.get('begin_time'))}–{ms_hms(s.get('end_time'))}] 说话人{s.get('speaker')}: {s.get('text')}"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def dump_yubing_20() -> str:
    p = ROOT / "data_raw" / "overseas_123_vemory_liu_2026-07-01.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    rec = next(r for r in data["results"] if r.get("name") == "于冰")
    parts = [f"于冰 7 月 Vemory 共 {rec.get('total_meetings')} 场（刘春梅账号拉取）。\n"]
    for i, m in enumerate(rec.get("meetings") or [], 1):
        mins = round((m.get("duration_seconds") or 0) / 60)
        parts.append(f"### 于冰场 {i} · {m.get('name')}")
        parts.append("")
        parts.append(f"- start: {m.get('start_time')}  end: {m.get('end_time')}  duration_seconds: {m.get('duration_seconds')} (~{mins}min)  sentences: {m.get('sentence_count')}")
        parts.append("")
        parts.append(m.get("summary") or "（无纪要）")
        parts.append("")
        if m.get("chapters"):
            parts.append("章节：")
            for ch in m["chapters"]:
                if isinstance(ch, dict):
                    parts.append(f"- {ch.get('title') or ch.get('name') or ch}")
                else:
                    parts.append(f"- {ch}")
            parts.append("")
        if m.get("todos"):
            parts.append("待办：")
            for t in m["todos"]:
                if isinstance(t, dict):
                    parts.append(f"- {t.get('content') or t.get('text') or t}")
                else:
                    parts.append(f"- {t}")
            parts.append("")
    return "\n".join(parts)


def dump_csv_file(path: Path, title: str) -> str:
    if not path.exists():
        return f"## {title}\n\n（文件不存在：{path}）\n\n"
    text = path.read_text(encoding="utf-8")
    return f"## {title}\n\n路径：`{path}`\n\n```csv\n{text.rstrip()}\n```\n\n"


def dump_text(path: Path, title: str) -> str:
    if not path.exists():
        return f"## {title}\n\n（文件不存在：{path}）\n\n"
    return f"## {title}\n\n路径：`{path}`\n\n{path.read_text(encoding='utf-8', errors='replace')}\n\n"


def dump_ivan_cursor() -> str:
    p = ROOT / "overseas_weekly" / "outputs" / "_cursor_ivan_pull.json"
    if not p.exists():
        return "## Ivan Cursor 拉取\n\n（无 `_cursor_ivan_pull.json`）\n\n"
    data = json.loads(p.read_text(encoding="utf-8"))
    lines = ["## Ivan Cursor / 日报 API 原件摘录", "", f"文件：`{p}`", ""]
    # keep it raw but only Ivan-related slices to avoid dumping whole team
    blob = json.dumps(data, ensure_ascii=False)
    ivan_hits = blob.count("Ivan") + blob.count("于冰")
    lines.append(f"JSON 内 Ivan/于冰 字面出现 {ivan_hits} 次。下面按 key 拆。")
    lines.append("")
    if isinstance(data, dict):
        for k, v in data.items():
            lines.append(f"### key `{k}`")
            if isinstance(v, dict) and "members" in v:
                members = v.get("members") or []
                ivans = [m for m in members if str(m.get("username", "")).lower() in {"ivan", "于冰"}]
                lines.append(f"date={v.get('date')} submitted={v.get('submitted_count')} missing={v.get('missing_count')}")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(ivans or [{"note": "该日 members 无 Ivan 对象，见 missing"}], ensure_ascii=False, indent=2))
                lines.append("```")
            else:
                s = json.dumps(v, ensure_ascii=False)
                if "Ivan" in s or "于冰" in s or k.lower().find("ivan") >= 0:
                    lines.append("```json")
                    lines.append(s[:20000])
                    lines.append("```")
                else:
                    lines.append(f"（本 key 无 Ivan，跳过。type={type(v).__name__}）")
            lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parts: list[str] = []
    parts.append(
        """# 于冰马来西亚 · 你投喂过的原件全刨

> 这份不是汇报稿。是把你 8/13–8/14 丢进对话的源，按原件扒出来。  
> 整理日 2026-08-14。合同/LOI 非法务意见。

## 投喂清单（会话里你点名给过的）

| # | 你给的 | 形态 | 这次有没有原文 |
|---|--------|------|----------------|
| 1 | `C:\\Users\\frank\\Desktop\\马来西亚市场拓展_客户池与行动手册.html` | 手册 HTML，截止 8/5 | **桌面现已不在**。32 条从仓库 `马来西亚_线索全生命周期.html` LEADS 回刨 |
| 2 | 老板逻辑线 + 穷举要求（Cursor/五件套/订单/物流/Vemory/获客） | 提示词 | 见本页开头会话 |
| 3 | `global-pdca.vertu.cn` 日报 GET 用法（Frank Token，不写 Token） | 接口说明 | `_cursor_ivan_pull.json` Ivan 切片 |
| 4 | 自动化获客马来线索 | CSV 30 行 | 全文附下 |
| 5 | https://www.kdocs.cn/l/chxzet9BUaXO?R=L1MvMjE= 过往名单总表 /S/21 | 金山 | Malaysia 34 行清洗表全文。总抓取 MY75 **当时只记了 Andy Tan / Janson Kwan / Azmir，75 行原表未落盘** |
| 6 | 8 条 Vemory 分享链接 | snapshot | **8 份 JSON 已重拉，转写全文如下** |
| 7 | Majesty HTML | 视觉参考 | 不是马来数据，不附 |
| 8 | humanize-ppt | skill | 不是马来数据，不附 |

仓库里本来就有、会话里当证据用过、这次一并刨出：

| 源 | 路径 |
|----|------|
| 于冰 7 月 20 场 Vemory | `data_raw/overseas_123_vemory_liu_2026-07-01.json` |
| 7/13–17 PDF 提取 | `overseas_weekly/outputs/_w3_yubing_pdf.md` |
| W3 Vemory brief | `overseas_weekly/outputs/_w3_work_from_vemory.json` |
| 获客 CSV | `overseas_weekly/inputs/malaysia/2026-07-23_马来西亚3C与腕表渠道_批量获客导入.csv` |
| 金山 MY | `overseas_weekly/inputs/malaysia/2026-08-13_kdocs_过往名单总表_Malaysia.csv` |

**没拿到原文、不能装全的：** WhatsApp 群、Amy 邮件除一句外的全文、手册 HTML 原文件、金山总抓取 75 行、6/23 118、6/26 MY48、于冰本机 Cursor 对话。

---

## 8 场分享 · snapshot 转写全文

"""
    )
    for sid, label in SHARES:
        parts.append(dump_snapshot(sid, label))

    parts.append("\n---\n\n## 于冰 7 月 Vemory 20 场纪要全文\n\n")
    parts.append(dump_yubing_20())
    parts.append("\n---\n\n")
    parts.append(dump_csv_file(ROOT / "overseas_weekly" / "inputs" / "malaysia" / "2026-07-23_马来西亚3C与腕表渠道_批量获客导入.csv", "获客 CSV 30 行原文"))
    parts.append(dump_csv_file(ROOT / "overseas_weekly" / "inputs" / "malaysia" / "2026-08-13_kdocs_过往名单总表_Malaysia.csv", "金山过往名单 Malaysia 清洗表原文"))
    parts.append(dump_text(ROOT / "overseas_weekly" / "outputs" / "_w3_yubing_pdf.md", "PDF《26.7.13-26.7.17工作》提取原文"))
    parts.append(dump_ivan_cursor())

    # handbook 32 from lifecycle html
    html = ROOT / "overseas_weekly" / "outputs" / "马来西亚_线索全生命周期.html"
    if html.exists():
        text = html.read_text(encoding="utf-8")
        i = text.find("const LEADS = [")
        j = text.find("];", i)
        parts.append("## 手册 32 条（从仓库生命周期页 LEADS 回刨，原桌面手册 HTML 已不在）\n\n```js\n")
        parts.append(text[i : j + 2])
        parts.append("\n```\n\n")

    parts.append(
        """## VPS / 系统（会话里实拉过的数字，不是马来订单）

| 项 | 值 |
|----|----|
| 于冰工号 | 72 |
| 2026-07 SI | ¥1,265,468.52 越柬 |
| 2026-08-01～13 SI | ¥968,982.06 越柬 |
| DirectD / SWITCH / KLCC 检索 | 0 |
| 马来 SI / L2 / 五件套 | 0 |
| 撞名排除 | 于冰杰-1 工号 2933 |

---

*完。转写按 snapshot `transcription.sentences` 全量。音频 URL 在各场 JSON 的 `audio_url`，未重下载 wav。*
"""
    )
    OUT.write_text("".join(parts), encoding="utf-8")
    print("wrote", OUT, "bytes", OUT.stat().st_size)


if __name__ == "__main__":
    main()
