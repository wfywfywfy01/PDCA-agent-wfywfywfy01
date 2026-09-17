# -*- coding: utf-8 -*-
"""ASR 服务（第 10.4 节）：Vemory 会议 -> 豆包转写 -> meeting_asr_artifacts。

触发流程：
  discover -> 判断是否有音频源 -> 计算 artifact_key / sha256 -> 幂等检查
  -> 写 meeting.asr_requested -> 调豆包 -> 规范化 segments -> 落 artifact
  -> 写 meeting.asr_completed / meeting.asr_failed。
同一 audio_sha256 不重复识别；音频不进 Git、不落库；低置信度不自动
创建确定性承诺（needs_manual_review 由 Agent 层消费）。
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from loguru import logger
from sqlmodel import Session, select

from app.agents.asr_doubao import DoubaoFlashAsr, sha256_of
from app.agents.events import write_event
from app.agents.models import MeetingAsrArtifact
from app.agents.schemas import AsrResult
from app.config import get_settings
from app.database import get_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def artifact_key_for(meeting_external_id: str, audio_sha256: str) -> str:
    """稳定 artifact 幂等键。"""
    return f"asr:{meeting_external_id}:{audio_sha256[:16]}"


def find_artifact(meeting_external_id: str) -> MeetingAsrArtifact | None:
    with Session(get_engine()) as session:
        return session.exec(
            select(MeetingAsrArtifact)
            .where(MeetingAsrArtifact.meeting_external_id == meeting_external_id)
            .order_by(MeetingAsrArtifact.id.desc())
        ).first()


def find_by_sha(audio_sha256: str) -> MeetingAsrArtifact | None:
    with Session(get_engine()) as session:
        return session.exec(
            select(MeetingAsrArtifact)
            .where(MeetingAsrArtifact.audio_sha256 == audio_sha256)
            .order_by(MeetingAsrArtifact.id.desc())
        ).first()


def _save_artifact(
    *,
    artifact_key: str,
    meeting_external_id: str,
    meeting_date: str,
    audio_source_ref: str,
    audio_sha256: str,
    duration_ms: int | None,
    status: str,
    language: str = "",
    transcript: str = "",
    segments: list[dict] | None = None,
    confidence: float | None = None,
    review_status: str = "unreviewed",
    error_code: str = "",
    error_detail: str = "",
) -> MeetingAsrArtifact:
    now = utcnow()
    with Session(get_engine()) as session:
        row = session.exec(
            select(MeetingAsrArtifact).where(MeetingAsrArtifact.artifact_key == artifact_key)
        ).first()
        if row is None:
            row = MeetingAsrArtifact(
                artifact_key=artifact_key,
                meeting_external_id=meeting_external_id[:64],
                meeting_date=meeting_date[:10],
                provider="doubao",
                audio_source_ref=audio_source_ref[:512],
                audio_sha256=audio_sha256[:64],
                duration_ms=duration_ms,
                language=language[:32],
                status=status[:32],
                transcript_text=transcript,
                segments_json=json.dumps(segments or [], ensure_ascii=False)[:65536],
                confidence=confidence,
                review_status=review_status[:32],
                error_code=error_code[:64],
                error_detail=error_detail[:2000],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.status = status[:32]
            if transcript:
                row.transcript_text = transcript
            if segments:
                row.segments_json = json.dumps(segments, ensure_ascii=False)[:65536]
            if confidence is not None:
                row.confidence = confidence
            row.review_status = review_status[:32]
            row.error_code = error_code[:64]
            row.error_detail = error_detail[:2000]
            row.updated_at = now
            session.add(row)
        session.commit()
        session.refresh(row)
        return row


def _download_audio(url: str) -> tuple[bytes, str]:
    """下载音频到内存（<=100MB 由适配器拦截）；临时文件不落盘。"""
    resp = httpx.get(url, timeout=120.0, follow_redirects=True)
    resp.raise_for_status()
    mime = resp.headers.get("content-type") or ""
    return resp.content, mime


def _format_hint(mime: str) -> str:
    lowered = (mime or "").lower()
    if "wav" in lowered:
        return "wav"
    if "ogg" in lowered:
        return "ogg"
    return "mp3"


def transcribe_meeting(
    *,
    meeting_external_id: str,
    meeting_date: str,
    audio_url: str = "",
) -> dict:
    """对一场会议执行豆包转写（幂等：同会议或同音频已有成功 artifact 直接返回）。"""
    settings = get_settings()
    if not settings.asr_enabled:
        return {"ok": False, "status": "disabled", "detail": "PDCA_ASR_ENABLED=0"}
    if not meeting_external_id:
        return {"ok": False, "status": "blocked", "detail": "缺 meeting_external_id"}
    existing = find_artifact(meeting_external_id)
    if existing is not None and existing.status == "completed":
        return {"ok": True, "status": "already_completed", "artifact_id": existing.id}
    if not audio_url:
        write_event("meeting.asr_requested", producer="asr_service",
                    event_key=f"asr:requested:{meeting_external_id}",
                    payload={"blocked": "no_audio_source"})
        _save_artifact(
            artifact_key=artifact_key_for(meeting_external_id, "no-audio"),
            meeting_external_id=meeting_external_id,
            meeting_date=meeting_date,
            audio_source_ref="",
            audio_sha256="",
            duration_ms=None,
            status="blocked",
            error_code="no_audio_source",
            error_detail="无可用音频源（Vemory 未提供 URL）",
        )
        return {"ok": False, "status": "blocked", "detail": "no_audio_source"}
    try:
        audio, mime = _download_audio(audio_url)
    except Exception as exc:  # noqa: BLE001
        write_event("meeting.asr_failed", producer="asr_service",
                    event_key=f"asr:failed:{meeting_external_id}",
                    payload={"error": str(exc)[:200]})
        _save_artifact(
            artifact_key=artifact_key_for(meeting_external_id, "download-failed"),
            meeting_external_id=meeting_external_id,
            meeting_date=meeting_date,
            audio_source_ref=audio_url[:512],
            audio_sha256="",
            duration_ms=None,
            status="failed",
            error_code="audio_download_failed",
            error_detail=str(exc)[:2000],
        )
        return {"ok": False, "status": "failed", "detail": "audio_download_failed"}
    audio_sha = sha256_of(audio)
    prior = find_by_sha(audio_sha)
    if prior is not None and prior.status == "completed":
        return {"ok": True, "status": "already_completed", "artifact_id": prior.id}
    write_event("meeting.asr_requested", producer="asr_service",
                event_key=f"asr:requested:{meeting_external_id}",
                payload={"audio_sha256": audio_sha[:16]})
    adapter = DoubaoFlashAsr(timeout_seconds=float(settings.asr_timeout_seconds))
    try:
        result: AsrResult = adapter.recognize(audio, mime=mime, format_hint=_format_hint(mime))
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", "asr_error")
        write_event("meeting.asr_failed", producer="asr_service",
                    event_key=f"asr:failed:{meeting_external_id}",
                    payload={"error": str(exc)[:200], "code": code})
        _save_artifact(
            artifact_key=artifact_key_for(meeting_external_id, audio_sha),
            meeting_external_id=meeting_external_id,
            meeting_date=meeting_date,
            audio_source_ref=audio_url[:512],
            audio_sha256=audio_sha,
            duration_ms=None,
            status="failed",
            error_code=code,
            error_detail=str(exc)[:2000],
        )
        return {"ok": False, "status": "failed", "detail": str(exc)[:300]}
    review_status = "needs_review" if result.needs_manual_review else "auto_ok"
    row = _save_artifact(
        artifact_key=artifact_key_for(meeting_external_id, audio_sha),
        meeting_external_id=meeting_external_id,
        meeting_date=meeting_date,
        audio_source_ref=audio_url[:512],
        audio_sha256=audio_sha,
        duration_ms=None,
        status="completed",
        language=result.language,
        transcript=result.text,
        segments=[item.model_dump() for item in result.segments],
        confidence=result.confidence,
        review_status=review_status,
    )
    write_event("meeting.asr_completed", producer="asr_service",
                event_key=f"asr:completed:{meeting_external_id}",
                payload={"artifact_id": row.id, "needs_manual_review": result.needs_manual_review,
                         "segments": len(result.segments)})
    return {"ok": True, "status": "completed", "artifact_id": row.id,
            "needs_manual_review": result.needs_manual_review}
