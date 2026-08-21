"""状态变更通知。优先 VPS 物流小帮手 IM，其次 NOTIFY_WEBHOOK。"""

from __future__ import annotations

import os

import requests

CHANNELS_URL = "https://vps-service.vertu.cn/v1/im/user-robots/channels"
PUSH_URL = "https://vps-service.vertu.cn/v1/im/user-robots/push"


def _bot_headers() -> dict:
    app_id = os.environ.get("VPS_IM_APP_ID") or os.environ.get("PDCA_VPS_BOT_APP_ID")
    secret = os.environ.get("VPS_IM_APP_SECRET") or os.environ.get("PDCA_VPS_BOT_APP_SECRET")
    if not app_id or not secret:
        return {}
    return {
        "x-vertu-bot-app-id": app_id,
        "x-vertu-bot-app-secret": secret,
    }


def list_channels() -> list[dict]:
    """查机器人已加入的群。
    @returns {list}
    """
    headers = _bot_headers()
    if not headers:
        raise RuntimeError("缺少 VPS_IM_APP_ID / VPS_IM_APP_SECRET")
    r = requests.get(CHANNELS_URL, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data.get("channels") or []


def _summarize(ch: dict) -> dict:
    return {
        "channel_id": ch.get("channel_id") or ch.get("id"),
        "name": ch.get("name") or ch.get("title") or ch.get("channel_name"),
        "type": ch.get("type") or ch.get("channel_type"),
    }


def push(body: str, channel_id: str | None = None, attachments: list | None = None) -> dict:
    """推到指定群。
    @param {str} body
    @param {str|None} channel_id
    @param {list|None} attachments
    @returns {dict}
    """
    headers = _bot_headers()
    if not headers:
        raise RuntimeError("缺少 VPS_IM_APP_ID / VPS_IM_APP_SECRET")
    cid = channel_id or os.environ.get("VPS_IM_CHANNEL_ID") or os.environ.get("PDCA_VPS_BOT_CHANNEL_ID")
    if not cid:
        raise RuntimeError("缺少 VPS_IM_CHANNEL_ID，先 python bot.py channels")
    payload = {"channel_id": cid, "body": body}
    if attachments:
        payload["attachments"] = attachments
    r = requests.post(
        PUSH_URL,
        headers={**headers, "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    r.raise_for_status()
    try:
        return r.json()
    except Exception:
        return {"ok": True, "http": r.status_code}


def notify(text: str, attachments: list | None = None) -> None:
    """状态变更推送。未配 IM 则 webhook，再不行 stdout。
    @param {str} text
    @param {list|None} attachments
    """
    if _bot_headers() and (os.environ.get("VPS_IM_CHANNEL_ID") or os.environ.get("PDCA_VPS_BOT_CHANNEL_ID")):
        push(text, attachments=attachments)
        return
    url = os.environ.get("NOTIFY_WEBHOOK")
    if url:
        payload = {"msg_type": "text", "content": {"text": text}}
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return
    print(text)


def notify_user(user_id: str, text: str) -> dict:
    """私聊录单人。走当前登录的 vertu-cli，不走群机器人。
    @param {str} user_id
    @param {str} text
    @returns {dict}
    """
    from cli import vertu_cli

    return vertu_cli(
        "im",
        "+send-user",
        "--user-id",
        str(user_id),
        "--body",
        text,
        "--no-json",
    )
