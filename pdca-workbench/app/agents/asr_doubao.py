# -*- coding: utf-8 -*-
"""豆包录音文件极速版 ASR HTTP 适配器（第 10 节）。

只做语音识别；任务提取/客户判断/承诺识别一律留给 Agent 层。
官方接口依据：
- 录音文件极速版识别 HTTP：POST {base}/api/v3/auc/bigmodel/recognize/flash
- 约束：音频 <= 2 小时、100 MB；WAV/MP3/OGG OPUS。
重试策略：429/5xx 指数退避最多 3 次；参数/格式错误不重试进入人工队列。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
from loguru import logger

from app.agents.schemas import AsrResult, AsrSegment

# 单次请求约束（超限转人工处理）。
MAX_AUDIO_SECONDS = 2 * 60 * 60
MAX_AUDIO_BYTES = 100 * 1024 * 1024


class AsrError(RuntimeError):
    """ASR 调用失败（含错误码，供上层写 artifact 状态）。"""

    def __init__(self, message: str, code: str = "asr_error", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class DoubaoFlashAsr:
    """录音文件极速版适配器；地址与凭据全部来自环境变量。"""

    def __init__(
        self,
        *,
        base_url: str = "",
        app_key: str = "",
        access_key: str = "",
        api_key: str = "",
        resource_id: str = "",
        timeout_seconds: float = 180.0,
    ):
        import os

        from app.config import get_settings

        settings = get_settings()
        self.base_url = (base_url or os.environ.get("PDCA_DOUBAO_ASR_URL", "") or
                         "https://openspeech.bytedance.com").rstrip("/")
        self.app_key = app_key or os.environ.get("PDCA_DOUBAO_ASR_APP_KEY", "").strip()
        self.access_key = access_key or os.environ.get("PDCA_DOUBAO_ASR_ACCESS_KEY", "").strip()
        self.api_key = api_key or os.environ.get("PDCA_DOUBAO_ASR_API_KEY", "").strip()
        self.resource_id = (resource_id or
                            os.environ.get("PDCA_DOUBAO_ASR_RESOURCE_ID", "volc.bigasr.auc_turbo").strip())
        self.timeout = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.app_key and self.access_key)

    def _url(self) -> str:
        if self.base_url.rstrip("/").endswith("/api/v3/auc/bigmodel/recognize/flash"):
            return self.base_url.rstrip("/")
        return self.base_url.rstrip("/") + "/api/v3/auc/bigmodel/recognize/flash"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-App-Key": self.app_key,
            "X-Api-Access-Key": self.access_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Request-Id": str(time.time_ns()),
            "Content-Type": "application/json",
        }

    def recognize(
        self,
        audio: bytes,
        *,
        mime: str = "audio/mpeg",
        format_hint: str = "mp3",
    ) -> AsrResult:
        """提交音频（Base64）并解析结果；失败抛 AsrError。"""
        if not self.configured:
            raise AsrError("豆包 ASR 未配置", code="not_configured")
        if len(audio) > MAX_AUDIO_BYTES:
            raise AsrError("音频超过 100 MB，转人工处理", code="audio_too_large")
        import base64

        payload: dict[str, Any] = {
            "app": {"appid": self.app_key, "token": self.access_key, "cluster": self.resource_id},
            "user": {"uid": "pdca-agent"},
            "audio": {
                "format": format_hint,
                "data": base64.b64encode(audio).decode(),
            },
            "request": {
                "model_name": "bigmodel",
                "enable_punctuation": True,
                "enable_itn": True,
            },
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = httpx.post(
                    self._url(),
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    return self._normalize(resp.json(), mime)
                if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    last_error = RuntimeError(f"HTTP {resp.status_code}")
                    continue
                raise AsrError(
                    f"HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                    code=f"http_{resp.status_code}",
                    retryable=False,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                break
        raise AsrError(str(last_error or "未知错误"), code="network_error", retryable=True)

    def _normalize(self, payload: dict, mime: str) -> AsrResult:
        """把豆包响应规范化到 AsrResult 契约；缺失字段写空并标人工复核。"""
        result = payload.get("result") or payload.get("response") or {}
        text = str(result.get("text") or "").strip()
        segments: list[AsrSegment] = []
        for utterance in result.get("utterances") or []:
            if isinstance(utterance, dict):
                words = utterance.get("words") or []
                if not words:
                    continue
                segments.append(
                    AsrSegment(
                        speaker=f"speaker_{utterance.get('speaker') or ''}",
                        start_ms=int((words[0].get("start_time") or 0)),
                        end_ms=int((words[-1].get("end_time") or 0)),
                        text=" ".join(str(w.get("text") or "") for w in words),
                        confidence=float(utterance.get("definite") is True),
                    )
                )
        confidence = None
        try:
            raw_conf = result.get("confidence")
            confidence = float(raw_conf) if raw_conf is not None else None
        except (TypeError, ValueError):
            confidence = None
        needs_review = confidence is None or confidence < 0.85 or not text
        return AsrResult(
            meeting_external_id="",
            provider="doubao",
            status="completed",
            language="zh-en",
            text=text,
            segments=segments[:400],
            confidence=confidence,
            needs_manual_review=needs_review,
        )
