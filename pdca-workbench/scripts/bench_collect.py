# -*- coding: utf-8 -*-
"""采集耗时对照：并发版 collect_ledger vs 同样调用串行跑的墙钟时间。

用法::  python scripts/bench_collect.py 2026-09-19
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app import duzhan_ledger as dl  # noqa: E402


def timed(label, fn):
    start = time.perf_counter()
    value = fn()
    cost = time.perf_counter() - start
    print(f"  {label}: {cost:6.1f}s", flush=True)
    return value, cost


def main() -> int:
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-09-19"
    settings = get_settings()
    print(f"数据日 {day}；OCR 并发={settings.mto_ocr_workers}", flush=True)

    print("\n[1] 并发版 collect_ledger 总耗时", flush=True)
    ledger, parallel_cost = timed("collect_ledger(并发)", lambda: dl.collect_ledger(day))

    print("\n[2] 同样数据源串行跑一遍（模拟改造前）", flush=True)
    period = {"start_date": day, "end_date": day}
    report_channel = settings.todo_group_channel_id
    serial = 0.0
    _, cost = timed("personal-okr", dl.fetch_personal_okr)
    serial += cost
    _, cost = timed("Agent/IM 报告", dl.load_vps_activity)
    serial += cost
    _, cost = timed("Vemory", lambda: dl.fetch_vemory_day(day))
    serial += cost
    report_messages, cost = timed("日报群", lambda: dl.fetch_channel_history(report_channel, day, "300"))
    serial += cost
    channel_ids = sorted({cid for item in dl.OWNERS for cid in dl._history_ids(item) if cid})
    histories = {}
    for channel_id in channel_ids:
        rows, cost = timed(f"群历史 {channel_id[:8]}", lambda cid=channel_id: dl.fetch_channel_history(cid, day, "200"))
        histories[channel_id] = rows
        serial += cost
    print("  小计（顶源+群历史）: %.1fs" % serial, flush=True)

    mcp_serial = 0.0
    for owner in dl.OWNERS:
        subject = dl._subject(owner)
        if not subject:
            continue
        _, cost = timed(f"MCP {owner.display}", lambda sub=subject: dl._mcp_bundle(sub, period))
        mcp_serial += cost
    serial += mcp_serial
    print("  小计（MCP）: %.1fs" % mcp_serial, flush=True)

    ocr_serial = 0.0
    for owner in dl.OWNERS:
        if not owner.im_user_id:
            continue
        msgs: list = []
        for cid in dl._history_ids(owner):
            msgs.extend(histories.get(cid) or [])
        msgs = dl.messages_on_day(msgs, day, dl._group_timezone(owner))
        from app.mto_ocr import review_mto_images

        _, cost = timed(f"OCR {owner.display}", lambda m=msgs, u=owner.im_user_id: review_mto_images(m, u))
        ocr_serial += cost
    serial += ocr_serial
    print("  小计（OCR）: %.1fs" % ocr_serial, flush=True)

    people = ledger.get("people") or []
    print("\n结论：并发 %.1fs ｜ 串行约 %.1fs ｜ 节省 %.1fs（%.0f%%）" % (
        parallel_cost, serial, serial - parallel_cost,
        (serial - parallel_cost) / serial * 100 if serial else 0,
    ), flush=True)
    print("台账人数=%d 红榜=%d 黑榜=%d" % (len(people), len(ledger.get("red") or []), len(ledger.get("black") or [])), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())