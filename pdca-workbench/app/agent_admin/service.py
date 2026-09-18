# -*- coding: utf-8 -*-
"""Agent 管理后台服务层：vertu-cli im 机器人子进程封装。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from loguru import logger

from app.vertu.client import run_vertu


class BotAdminError(RuntimeError):
    """机器人管理命令执行失败（含 vertu-cli 错误信息）。"""


@dataclass
class BotCreateSpec:
    name: str
    bot_key: str | None = None
    description: str | None = None
    webhook_url: str | None = None
    public: bool = False


def _parse_json_or_raise(stdout: str, stderr: str, action: str) -> dict | list:
    text = stdout.strip()
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
    detail = (stderr or "vertu-cli 无输出").strip()[:400]
    raise BotAdminError(f"{action}失败: {detail or '未知错误'}")


async def list_bots() -> list[dict]:
    """我的机器人列表。"""
    _code, stdout, stderr = await run_vertu(["im", "+bots"], timeout=60.0)
    payload = _parse_json_or_raise(stdout, stderr, "查询机器人列表")
    items = payload.get("items", []) if isinstance(payload, dict) else payload
    return [item for item in items if isinstance(item, dict)]


async def list_bot_channels() -> list[dict]:
    """我的全部机器人已加入的群聊。"""
    _code, stdout, stderr = await run_vertu(["im", "+bot-channels"], timeout=60.0)
    payload = _parse_json_or_raise(stdout, stderr, "查询机器人群聊")
    if isinstance(payload, dict):
        # 真实契约键为 channels（vertu-cli im +bot-channels）
        items = payload.get("channels", payload.get("items", []))
        return [item for item in items if isinstance(item, dict)]
    return [item for item in payload if isinstance(item, dict)]


async def create_bot(spec: BotCreateSpec) -> dict:
    """创建 IM 机器人，返回 vertu-cli 原始结果。"""
    args = ["im", "+bot-create", "--name", spec.name]
    if spec.bot_key:
        args += ["--bot-key", spec.bot_key]
    if spec.description:
        args += ["--description", spec.description]
    if spec.webhook_url:
        args += ["--webhook-url", spec.webhook_url]
    if spec.public:
        args.append("--public")
    _code, stdout, stderr = await run_vertu(args, timeout=60.0)
    payload = _parse_json_or_raise(stdout, stderr, "创建机器人")
    logger.info("bot-create ok name={} public={}", spec.name, spec.public)
    return payload if isinstance(payload, dict) else {"result": payload}


async def set_bot_visibility(app_id: str, public: bool) -> dict:
    """调整机器人公开范围（公开 / 仅自己可见）。"""
    flag = "--public" if public else "--private"
    _code, stdout, stderr = await run_vertu(
        ["im", "+bot-update", "--app-id", app_id, flag], timeout=60.0
    )
    payload = _parse_json_or_raise(stdout, stderr, "调整公开范围")
    logger.info("bot-update ok app_id={} public={}", app_id, public)
    return payload if isinstance(payload, dict) else {"result": payload}


def utc_now_iso() -> str:
    """当前 UTC ISO 时间字符串。"""
    return datetime.now(timezone.utc).isoformat()
