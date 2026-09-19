# -*- coding: utf-8 -*-
"""管理类 HTML 早报的统一发送器（每天 07:00/08:00 私聊给管理层）。

一份收件人名单（PDCA_MGMT_HTML_USER_IDS）给所有「早上固定输出」的 HTML 用：
证据日报、三策略 WhatsApp 简报等，避免各自配一遍。只发文件，不改任何业务数据。

- 机器人身份（督战官 → 待办催办）优先，未配置机器人时回退登录账号身份；
- 群发送必须显式传 channel_id，默认空 => **绝不发群**；
- 失败返回原因、记日志，不抛异常（调用方的 own 告警逻辑继续生效）。
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger


def resolve_user_ids(settings, primary: str, fallback: str = "mgmt_html_user_ids") -> list[int]:
    """收件人优先级：功能自己的配置 > 共享名单。"""
    ids = [int(item) for item in (getattr(settings, primary, []) or [])]
    if ids:
        return ids
    return [int(item) for item in (getattr(settings, fallback, []) or [])]


def send_files(
    *,
    html_path: Path | str,
    user_ids: list[int] | tuple[int, ...] = (),
    channel_id: str = "",
    extra_paths: list[Path | str] | tuple[Path | str, ...] = (),
    caption: str = "",
    idempotency_key: str = "",
    bot_app_id: str = "",
) -> dict:
    """把 HTML（可带 JSON 等附件）私聊发给 user_ids；channel_id 非空才发群。"""
    from app.config import get_settings
    from app.vertu.client import run_vertu_sync

    html = Path(str(html_path))
    if not html.exists():
        return {"sent": [], "failed": [str(html)], "reason": "文件不存在"}
    settings = get_settings()
    if not bot_app_id:
        bot_app_id = (
            getattr(settings, "duzhan_bot_app_id", "")
            or getattr(settings, "todo_bot_app_id", "")
        ).strip()
    body_file = html.with_suffix(".body.txt")
    body_file.write_text(caption or html.stem, encoding="utf-8")
    attach = [str(html)] + [str(Path(item)) for item in extra_paths if Path(item).exists()]
    sent: list[str] = []
    failed: list[str] = []
    try:
        for user_id in user_ids or ():
            args = (
                ["im", "+bot-send-user", "--app-id", bot_app_id]
                if bot_app_id
                else ["im", "+send-user"]
            )
            args += ["--user-id", str(user_id), "--body-file", str(body_file)]
            for path in attach:
                args += ["--attach", path]
            args += ["--message-type", "file"]
            if idempotency_key:
                args += ["--idempotency-key", f"{idempotency_key}-{user_id}"]
            code, out, err = run_vertu_sync(args, timeout=180.0)
            if code == 0:
                sent.append(f"user:{user_id}")
            else:
                failed.append(f"user:{user_id}")
                logger.warning("早报私聊发送失败 {}: {}", user_id, (err or out or "")[:160])
        if channel_id:
            args = ["im", "+send", "--channel-id", channel_id, "--body-file", str(body_file)]
            for path in attach:
                args += ["--attach", path]
            args += ["--message-type", "file"]
            if idempotency_key:
                args += ["--idempotency-key", f"{idempotency_key}-{channel_id[:8]}"]
            code, out, err = run_vertu_sync(args, timeout=180.0)
            if code == 0:
                sent.append("channel")
            else:
                failed.append("channel")
                logger.warning("早报群发送失败 {}: {}", channel_id[:8], (err or out or "")[:160])
    finally:
        body_file.unlink(missing_ok=True)
    return {"sent": sent, "failed": failed}
