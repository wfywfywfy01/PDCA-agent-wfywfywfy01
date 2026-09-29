"""Authenticated, bounded short-utterance transcription for Omega."""
from __future__ import annotations

import asyncio
import io
import wave
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.agents.asr_doubao import DoubaoFlashAsr
from app.auth.deps import get_current_user
from app.auth.models import User
from app.config import get_settings
from app.omega.policy import require_team_user
from app.omega.router import enabled

router = APIRouter(prefix="/api/omega", tags=["omega"])
_slots = asyncio.Semaphore(3)
_max_bytes = 3 * 1024 * 1024


@router.post("/transcribe", dependencies=[Depends(enabled)])
async def transcribe(request: Request, user: Annotated[User, Depends(get_current_user)]):
    require_team_user(user)
    if not get_settings().asr_enabled:
        raise HTTPException(503, "语音识别尚未启用，可继续文字演练")
    if request.headers.get("content-type", "").split(";", 1)[0] != "audio/wav":
        raise HTTPException(415, "仅接收 WAV 音频")
    try:
        announced_size = int(request.headers.get("content-length") or "0")
    except ValueError:
        raise HTTPException(400, "Content-Length 无效") from None
    if announced_size > _max_bytes:
        raise HTTPException(413, "音频超过 3 MB")
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > _max_bytes:
            raise HTTPException(413, "音频超过 3 MB")
        chunks.append(chunk)
    audio = b"".join(chunks)
    if not audio or len(audio) > _max_bytes:
        raise HTTPException(413, "音频为空或超过 3 MB")
    try:
        with wave.open(io.BytesIO(audio), "rb") as source:
            duration = source.getnframes() / source.getframerate()
            valid = (source.getnchannels() == 1 and source.getsampwidth() == 2
                     and source.getframerate() in {16000, 24000, 32000, 48000}
                     and 0.2 <= duration <= 30)
    except (wave.Error, ZeroDivisionError, EOFError):
        valid = False
    if not valid:
        raise HTTPException(422, "音频需为单声道 16-bit PCM WAV，时长 0.2–30 秒")
    adapter = DoubaoFlashAsr(timeout_seconds=45)
    if not adapter.configured:
        raise HTTPException(503, "语音识别尚未配置，可继续文字演练")
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(429, "语音识别繁忙，请稍后重试") from None
    try:
        result = await run_in_threadpool(adapter.recognize, audio, mime="audio/wav", format_hint="wav")
    except Exception as exc:
        raise HTTPException(502, f"语音识别失败：{str(exc)[:120]}") from exc
    finally:
        _slots.release()
    return {"text": result.text, "confidence": result.confidence,
            "needs_manual_review": result.needs_manual_review, "duration_seconds": duration}
