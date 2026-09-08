# -*- coding: utf-8 -*-
"""VPS IM 机器人推送：日报与告警分通道。

凭据从环境变量读取（.env 未跟踪）：
  PDCA_VPS_BOT_APP_ID / PDCA_VPS_BOT_APP_SECRET
日报目标群与告警目标群分别支持持久化覆盖（位于挂载数据目录，跨部署
存活，不受部署机 .env 回滚影响）：
  data/runtime/push_channel.txt  — 日报目标群（经销商群）
  data/runtime/alert_channel.txt — 告警/报错目标群（内部运维群）
文件缺失/为空时回退环境变量 PDCA_VPS_BOT_CHANNEL_ID。
未配置 channel 时返回 False（调用方降级为通用 webhook / 仅日志）。
"""
from __future__ import annotations

import os

import httpx

from app.config import get_settings

VPS_PUSH_URL = "https://vps-service.vertu.cn/v1/im/user-robots/push"

_PUSH_CHANNEL_OVERRIDE = "runtime/push_channel.txt"
_ALERT_CHANNEL_OVERRIDE = "runtime/alert_channel.txt"


def _file_channel(relative_path: str) -> str:
    """读取持久化频道覆盖文件；缺失/为空返回空串。"""
    path = get_settings().data_dir / relative_path
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def push_vps_message(message: str) -> bool:
    """推日报/业务消息到日报目标群。"""
    channel_id = _file_channel(_PUSH_CHANNEL_OVERRIDE) or os.environ.get(
        "PDCA_VPS_BOT_CHANNEL_ID", ""
    ).strip()
    return _push(message, channel_id)


def push_vps_alert(message: str) -> bool:
    """推告警/报错消息到告警目标群（与日报群分离）。"""
    channel_id = (
        _file_channel(_ALERT_CHANNEL_OVERRIDE)
        or os.environ.get("PDCA_ALERT_BOT_CHANNEL_ID", "").strip()
    )
    business_channel = _file_channel(_PUSH_CHANNEL_OVERRIDE) or os.environ.get(
        "PDCA_VPS_BOT_CHANNEL_ID", ""
    ).strip()
    if channel_id and channel_id == business_channel:
        return False
    return _push(message, channel_id)


def _push(message: str, channel_id: str) -> bool:
    """推一条文本消息到指定群；成功返回 True，未配置/失败返回 False。"""
    app_id = os.environ.get("PDCA_VPS_BOT_APP_ID", "").strip()
    app_secret = os.environ.get("PDCA_VPS_BOT_APP_SECRET", "").strip()
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
