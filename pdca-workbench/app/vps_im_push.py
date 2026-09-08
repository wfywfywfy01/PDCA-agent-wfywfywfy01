# -*- coding: utf-8 -*-
"""VPS IM 机器人推送：告警与日报共用通道。

凭据与目标群从环境变量读取（.env 未跟踪）：
  PDCA_VPS_BOT_APP_ID / PDCA_VPS_BOT_APP_SECRET / PDCA_VPS_BOT_CHANNEL_ID
目标群支持持久化覆盖：data/runtime/push_channel.txt 存在且非空时优先于
环境变量——该文件位于挂载数据目录，跨部署存活，不受部署机 .env 回滚影响。
未配置 channel 时返回 False（调用方降级为通用 webhook / 仅日志）。
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx

from app.config import get_settings

VPS_PUSH_URL = "https://vps-service.vertu.cn/v1/im/user-robots/push"

_PUSH_CHANNEL_OVERRIDE = "runtime/push_channel.txt"


def _channel_override() -> str:
    """读取持久化频道覆盖文件；缺失/为空返回空串。"""
    path = get_settings().data_dir / _PUSH_CHANNEL_OVERRIDE
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def push_vps_message(message: str) -> bool:
    """推送一条文本消息到配置的群；成功返回 True，未配置/失败返回 False。"""
    app_id = os.environ.get("PDCA_VPS_BOT_APP_ID", "").strip()
    app_secret = os.environ.get("PDCA_VPS_BOT_APP_SECRET", "").strip()
    channel_id = _channel_override() or os.environ.get("PDCA_VPS_BOT_CHANNEL_ID", "").strip()
    if not (app_id and app_secret and channel_id):
        return False
    try:
        resp = httpx.post(
            VPS_PUSH_URL,
            json={"channel_id": channel_id, "body": message},
            headers={
                "x-vertu-bot-app-id": app_id,
                "x-vertu-bot-app-secret": app_secret,
            },
            timeout=15.0,
        )
        if resp.status_code != 200:
            return False
        payload = resp.json()
        return bool(payload.get("ok"))
    except Exception:  # noqa: BLE001 — 推送失败仅返回 False，由调用方降级
        return False
