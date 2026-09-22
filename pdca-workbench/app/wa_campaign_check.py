# -*- coding: utf-8 -*-
"""腕表闪购 WhatsApp 核查（定时任务入口）。

采集与渲染复用 scripts/wa_campaign_check.py（同一份代码，CLI 也在用），
这里只负责「按模板生成到指定目录 + 返回概要」，方便调度线程调用。
只读 MCP，不发任何消息（发送由 app/im_files.py 统一负责）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

_SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _script_module():
    """把 scripts/ 加进 sys.path 后导入（脚本自带 __main__ 保护，导入无副作用）。"""
    path = str(_SCRIPTS_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    import wa_campaign_check as module  # noqa: PLC0415 — 延迟导入，避免启动即加载 httpx 依赖

    return module


def run_check(out_dir: Path, days: int = 2, end: str = "", posters_dir: str = "") -> dict:
    """生成「前 24 小时（按日切分）」核查报告到 out_dir，返回概要。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    module = _script_module()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    end = end or datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    target = out_dir / ("机械腕表闪购_WhatsApp核查_" + end + ".html")
    result = module.run(days=days, end=end, posters_dir=posters_dir, out=str(target))
    logger.info(
        "腕表闪购核查已生成 {}｜{} KB｜{} 人",
        result.get("html"),
        round(int(result.get("bytes") or 0) / 1024),
        len((result.get("summary") or {}).get("people") or []),
    )
    return result
