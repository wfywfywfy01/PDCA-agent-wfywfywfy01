# -*- coding: utf-8 -*-
"""服务器核对 MTO 报价图：读完立刻删磁盘文件，台账只留结构化字段。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path

import httpx
from loguru import logger

from app.config import get_settings

RATE_CNY = 7.1
THRESHOLD_WAN = 30.0
PROMPT = (
    "这是 VERTU MTO 报价截图。只根据图上可见文字填 JSON，不要编造。"
    "字段：model, total_usd, delivery, sku, target_customer。"
    "total_usd 只填数字（ESTIMATED TOTAL / USD / $）。"
    "target_customer 是图上的客户名/经销商/国家；没有就空字符串。"
    "只输出一个 JSON 对象。"
)
_JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_quote_text(raw: str) -> dict:
    """从模型输出抠报价字段。读不到标待确认。"""
    text = (raw or "").strip()
    match = _JSON_RE.search(text)
    payload: dict = {}
    if match:
        try:
            loaded = json.loads(match.group(0))
            if isinstance(loaded, dict):
                payload = loaded
        except json.JSONDecodeError:
            payload = {}
    model = str(payload.get("model") or "").strip()
    sku = str(payload.get("sku") or "").strip()
    delivery = str(payload.get("delivery") or "").strip()
    target = str(payload.get("target_customer") or "").strip()
    usd = _usd(payload.get("total_usd"))
    wan = round(usd * RATE_CNY / 10000, 1) if usd is not None else None
    qualifies = wan is not None and wan >= THRESHOLD_WAN
    return {
        "model": model,
        "sku": sku,
        "delivery": delivery,
        "target_customer": target,
        "usd": usd,
        "wan": wan,
        "qualifies": qualifies,
        "raw_ok": bool(model or usd is not None),
    }


def _usd(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("$", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def summarize_quotes(quotes: list[dict]) -> tuple[int, list[str]]:
    """≥30 万且有报价的张数；文案含金额、是否达标、目标客户。"""
    names: list[str] = []
    qualify_n = 0
    for item in quotes:
        if not item.get("raw_ok"):
            names.append("未读出报价")
            continue
        if item.get("qualifies"):
            qualify_n += 1
        usd = item.get("usd")
        wan = item.get("wan")
        money = f"${usd:g}" if usd is not None else "金额待确认"
        bar = "达标" if item.get("qualifies") else "未满30万"
        if wan is not None and usd is not None:
            money = f"${usd:g}≈{wan}万"
        target = str(item.get("target_customer") or "").strip() or "目标客户待确认"
        model = str(item.get("model") or "机型待确认")
        names.append(f"{model} {money}（{bar}）客户:{target}")
    return qualify_n, names[:6]


def ocr_image_bytes(content: bytes, mime: str = "image/jpeg") -> dict:
    """调本机/内网 Qwen 读图。密钥只从配置读。

    WebP 会先转 PNG：本地 Qwen 网关的视觉编码器对 webp 解码不稳定
    （实测 webp 直传读不出报价，转 PNG 后正常）。
    """
    import base64

    if "webp" in (mime or "").lower():
        try:
            import io

            from PIL import Image

            image = Image.open(io.BytesIO(content)).convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            content = buffer.getvalue()
            mime = "image/png"
        except Exception as exc:  # noqa: BLE001 — 转码失败仍按原格式提交
            logger.warning("webp→png 转换失败，按原格式提交: {}", exc)

    settings = get_settings()
    url = settings.qwen_base_url.rstrip("/") + "/v1/chat/completions"
    key = settings.qwen_api_key
    model = settings.qwen_model
    if not key or not url:
        return parse_quote_text("")
    b64 = base64.b64encode(content).decode()
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ],
        # 本地 Qwen 网关为推理模型：reasoning+正文会吃预算，400 曾导致末尾
        # JSON 被截断（finish_reason=length）而读不出报价，给足预算。
        "max_tokens": 1500,
        "temperature": 0.1,
    }
    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            timeout=120.0,
            verify=False,
        )
        resp.raise_for_status()
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = choice["message"]["content"] or ""
        row = parse_quote_text(text)
        # 截断重试一次：追加“直接输出 JSON”引导，避免 reasoning 吃满预算。
        if not row["raw_ok"] and choice.get("finish_reason") == "length":
            payload["messages"] = payload["messages"] + [{
                "role": "user",
                "content": "请直接输出结果 JSON，不要任何说明。",
            }]
            retry_resp = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
                verify=False,
            )
            retry_resp.raise_for_status()
            text = retry_resp.json()["choices"][0]["message"]["content"]
            return parse_quote_text(text)
        return row
    except Exception as exc:  # noqa: BLE001
        logger.warning("MTO OCR 失败: {}", exc)
        return parse_quote_text("")


def _vps_auth() -> tuple[str, dict]:
    """VPS 附件下载凭据。

    优先容器环境变量（部署时注入的最新 Agent 凭据，与拉群消息同一套身份）；
    缺省回退 ~/.vertu/vps-service.json 会话文件（历史会话可能过期，曾导致附件
    下载 401、MTO 全部读不出报价）。
    """
    import os

    env_key = os.environ.get("VERTU_APP_KEY", "").strip()
    env_id = os.environ.get("VERTU_APP_ID", "").strip()
    env_login = os.environ.get("VERTU_USER_LOGIN", "").strip()
    base = os.environ.get(
        "VERTU_VPS_SERVICE_URL", "https://vps-service.vertu.cn"
    ).strip().rstrip("/")
    if env_key and env_login:
        return base, {
            "x-vertu-auth-channel": "vertu-cli",
            "user-agent": "vertu-cli",
            "Authorization": f"Bearer {env_key}",
            "x-vertu-agent-app-id": env_id,
            "x-vertu-user-login": env_login,
        }
    cfg_path = Path.home() / ".vertu" / "vps-service.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    base = str(cfg.get("baseUrl") or "https://vps-service.vertu.cn").rstrip("/")
    headers = {
        "x-vertu-auth-channel": "vertu-cli",
        "user-agent": "vertu-cli",
        "Authorization": f"Bearer {cfg.get('agentAppKey')}",
        "x-vertu-agent-app-id": str(cfg.get("agentAppId") or ""),
        "x-vertu-user-login": str(cfg.get("login") or ""),
    }
    return base, headers


def download_ocr_delete(url_path: str) -> dict:
    """下载到临时目录、OCR、无论成败都删文件。"""
    tmp_dir = Path(tempfile.mkdtemp(prefix="mto-ocr-"))
    dest = tmp_dir / "shot.bin"
    try:
        base, headers = _vps_auth()
        full = url_path if url_path.startswith("http") else base + url_path
        resp = httpx.get(full, headers=headers, timeout=30.0, follow_redirects=True)
        dest.write_bytes(resp.content)
        mime = resp.headers.get("content-type") or "image/jpeg"
        if "webp" in mime or full.lower().endswith(".webp"):
            mime = "image/webp"
        return ocr_image_bytes(resp.content, mime)
    except Exception as exc:  # noqa: BLE001
        logger.warning("MTO 下载失败: {}", exc)
        return parse_quote_text("")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def review_mto_images(messages: list | None, sender_id: int | None) -> tuple[int, list[str], list[dict]]:
    """本人当日图片：OCR 报价与目标客户；磁盘文件不保留。"""
    settings = get_settings()
    quotes: list[dict] = []
    from app.duzhan_ledger import DUZHAN_BOT_ID

    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("revoked_at"):
            continue
        if str(msg.get("sender_bot_id") or "") == DUZHAN_BOT_ID:
            continue
        if str(msg.get("message_type") or "") != "image":
            continue
        if sender_id is not None and msg.get("sender_user_id") != sender_id:
            continue
        for att in msg.get("attachments") or []:
            if not isinstance(att, dict):
                continue
            if str(att.get("attachment_type") or "") not in ("image", ""):
                continue
            url = str(att.get("url") or "")
            if not url:
                continue
            if settings.qwen_api_key:
                quotes.append(download_ocr_delete(url))
            else:
                name = str(att.get("name") or "image")
                quotes.append(
                    {
                        "model": name,
                        "sku": "",
                        "delivery": "",
                        "target_customer": "",
                        "usd": None,
                        "wan": None,
                        "qualifies": False,
                        "raw_ok": False,
                    }
                )
    if settings.qwen_api_key:
        qualify_n, names = summarize_quotes(quotes)
        return qualify_n, names, quotes
    file_names = [str(item.get("model") or "image") for item in quotes]
    return len(quotes), file_names[:6], []
