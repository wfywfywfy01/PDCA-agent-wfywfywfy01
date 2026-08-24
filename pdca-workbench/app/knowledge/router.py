"""Authenticated same-origin API for human and AI knowledge queries."""
from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
import httpx
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.auth.deps import get_current_user
from app.auth.models import User
from app.auth.router import _check_rate_limit, _clear_fail, _rate_limit_key, _record_fail
from app.auth.security import create_access_token, decode_token, verify_password
from app.auth.scope import resolve_data_scope
from app.audit import log_action
from app.config import get_settings
from app.database import get_session
from app.knowledge.client import (
    request_content,
    request_json,
    require_knowledge_access,
    scoped_dealers,
)


router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class QueryBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    dealer_id: UUID | None = None
    category: str | None = Field(default=None, max_length=40)
    top_k: int = Field(default=8, ge=1, le=20)


class ExportBody(BaseModel):
    asset_id: UUID
    reason: str = Field(min_length=10, max_length=500)
    confirmation: Literal["export-original"]


class ExportDownloadBody(BaseModel):
    export_token: str = Field(min_length=32, max_length=200)


class UploadPresignBody(BaseModel):
    dealer_id: UUID
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=160)
    byte_size: int = Field(gt=0)
    content_hash: str = Field(min_length=64, max_length=64)


class UploadCompleteBody(UploadPresignBody):
    logical_key: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=40)
    sensitivity: Literal["internal", "confidential", "restricted"] = "internal"
    object_key: str = Field(min_length=1, max_length=900)
    original_name: str = Field(min_length=1, max_length=500)


class ReauthBody(BaseModel):
    password: str = Field(min_length=1, max_length=256)


class ReviewDecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=3, max_length=500)


_REAUTH_COOKIE = "pdca_knowledge_reauth"
_REAUTH_PURPOSE = "knowledge-original-export"
_REAUTH_SECONDS = 300
_UPLOAD_CHUNK_SIZE = 1024 * 1024


def _require_original_export_admin(user: User, session: Session) -> None:
    if user.role != "admin" or not resolve_data_scope(user, session).unrestricted:
        raise HTTPException(status_code=403, detail="仅管理员可导出原件")


def _require_upload_access(user: User, session: Session, dealer_id: UUID) -> None:
    if user.role not in {"sales", "manager", "admin"}:
        raise HTTPException(status_code=403, detail="当前账号没有资料上传权限")
    require_knowledge_access(user, session, dealer_id)


def _reauthenticated_at(token: str | None, user: User) -> int:
    payload = decode_token(token or "")
    if not payload or payload.get("sub") != user.username:
        raise HTTPException(status_code=403, detail="导出原件前请重新验证密码")
    if payload.get("purpose") != _REAUTH_PURPOSE:
        raise HTTPException(status_code=403, detail="重新验证凭据用途无效")
    if payload.get("pwd_v") != (getattr(user, "pwd_version", 0) or 0):
        raise HTTPException(status_code=403, detail="密码已变更，请重新验证")
    try:
        return int(payload["iat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="重新验证凭据无效") from exc


def _hash_upload(file) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    file.seek(0)
    while chunk := file.read(_UPLOAD_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    file.seek(0)
    return digest.hexdigest(), size


@router.get("/scope")
async def knowledge_scope(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    settings = get_settings()
    scope = resolve_data_scope(user, session)
    return {
        "enabled": settings.knowledge_hub_enabled,
        "scope": scope.mode,
        "dealers": scoped_dealers(user, session),
        "can_upload": user.role in {"sales", "manager", "admin"},
        "can_export_original": user.role == "admin" and scope.unrestricted,
        "can_review_sensitive": user.role == "admin" and scope.unrestricted,
    }


@router.post("/reauth")
async def reauthenticate_original_export(
    body: ReauthBody,
    request: Request,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    _require_original_export_admin(user, session)
    key = _rate_limit_key(request, user.username)
    _check_rate_limit(key)
    if not verify_password(body.password, user.hashed_password):
        _record_fail(key)
        raise HTTPException(status_code=401, detail="密码验证失败")
    _clear_fail(key)
    token = create_access_token(
        {
            "sub": user.username,
            "purpose": _REAUTH_PURPOSE,
            "pwd_v": getattr(user, "pwd_version", 0) or 0,
        },
        timedelta(seconds=_REAUTH_SECONDS),
    )
    settings = get_settings()
    response.set_cookie(
        key=_REAUTH_COOKIE,
        value=token,
        max_age=_REAUTH_SECONDS,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
    )
    log_action(user.username, "reauth_knowledge_export", resource="knowledge")
    return {"ok": True, "expires_in": _REAUTH_SECONDS}


@router.post("/search")
async def search_knowledge(
    body: QueryBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    require_knowledge_access(user, session, body.dealer_id)
    return await request_json(
        "POST", "/v1/search", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=body.model_dump(mode="json", exclude_none=True),
    )


@router.post("/answers")
async def answer_knowledge(
    body: QueryBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    require_knowledge_access(user, session, body.dealer_id)
    payload = body.model_dump(mode="json", exclude_none=True)
    payload["top_k"] = min(body.top_k, 10)
    return await request_json(
        "POST", "/v1/answers", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""), body=payload,
    )


@router.post("/uploads/presign")
async def presign_knowledge_upload(
    body: UploadPresignBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    _require_upload_access(user, session, body.dealer_id)
    return await request_json(
        "POST",
        "/v1/uploads/presign",
        user=user,
        session=session,
        request_id=getattr(request.state, "request_id", ""),
        body={"scope_type": "dealer", **body.model_dump(mode="json")},
    )


@router.post("/uploads")
async def upload_knowledge_file(
    request: Request,
    dealer_id: Annotated[UUID, Form()],
    title: Annotated[str, Form(min_length=1, max_length=500)],
    category: Annotated[str, Form(min_length=1, max_length=40)],
    sensitivity: Annotated[
        Literal["internal", "confidential", "restricted"], Form()
    ] = "internal",
    file: UploadFile = File(...),
    user: Annotated[User, Depends(get_current_user)] = None,
    session: Annotated[Session, Depends(get_session)] = None,
):
    _require_upload_access(user, session, dealer_id)
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=422, detail="文件名不能为空")
    content_hash, byte_size = await asyncio.to_thread(_hash_upload, file.file)
    content_type = (file.content_type or "application/octet-stream").lower()
    common = {
        "dealer_id": str(dealer_id),
        "filename": filename,
        "content_type": content_type,
        "byte_size": byte_size,
        "content_hash": content_hash,
    }
    request_id = getattr(request.state, "request_id", "")
    signed = await request_json(
        "POST",
        "/v1/uploads/presign",
        user=user,
        session=session,
        request_id=request_id,
        body={"scope_type": "dealer", **common},
    )

    async def chunks():
        await file.seek(0)
        while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
            yield chunk

    try:
        async with httpx.AsyncClient(timeout=None) as client:
            uploaded = await client.put(
                signed["url"], headers=signed.get("headers", {}), content=chunks()
            )
            uploaded.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="私有对象存储上传失败") from exc

    idempotency_key = f"pdca-upload-{secrets.token_urlsafe(18)}"
    result = await request_json(
        "POST",
        "/v1/assets/complete",
        user=user,
        session=session,
        request_id=request_id,
        idempotency_key=idempotency_key,
        body={
            "dealer_id": str(dealer_id),
            "scope_type": "dealer",
            "logical_key": filename.casefold(),
            "title": title,
            "category": category,
            "sensitivity": sensitivity,
            "object_key": signed["object_key"],
            "content_hash": content_hash,
            "original_name": filename,
            "content_type": content_type,
            "byte_size": byte_size,
        },
    )
    log_action(
        user.username,
        "upload_knowledge_asset",
        resource=str(dealer_id),
        detail={"filename": filename, "content_hash": content_hash},
    )
    return result


@router.post("/assets/complete")
async def complete_knowledge_upload(
    body: UploadCompleteBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
):
    _require_upload_access(user, session, body.dealer_id)
    payload = body.model_dump(mode="json")
    payload.pop("filename", None)
    payload["scope_type"] = "dealer"
    payload["content_hash"] = payload["content_hash"].lower()
    return await request_json(
        "POST",
        "/v1/assets/complete",
        user=user,
        session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=payload,
        idempotency_key=idempotency_key,
    )


@router.get("/reviews")
async def list_sensitive_reviews(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    _require_original_export_admin(user, session)
    return await request_json(
        "GET",
        "/v1/reviews",
        user=user,
        session=session,
        request_id=getattr(request.state, "request_id", ""),
    )


@router.post("/reviews/{review_id}/decision")
async def decide_sensitive_review(
    review_id: UUID,
    body: ReviewDecisionBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    _require_original_export_admin(user, session)
    result = await request_json(
        "POST",
        f"/v1/reviews/{review_id}/decision",
        user=user,
        session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=body.model_dump(mode="json"),
    )
    log_action(
        user.username,
        f"{body.decision}_knowledge_sensitive_review",
        resource=str(review_id),
        detail={"reason": body.reason},
    )
    return result


@router.get("/assets/{asset_id}/content", response_model=None)
async def preview_asset(
    asset_id: UUID,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    require_knowledge_access(user, session)
    return await request_content(
        "GET", f"/v1/assets/{asset_id}/content", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
    )


@router.post("/exports", response_model=None)
async def export_original(
    body: ExportBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=200)
    ],
    pdca_knowledge_reauth: Annotated[str | None, Cookie()] = None,
):
    _require_original_export_admin(user, session)
    reauthenticated_at = _reauthenticated_at(pdca_knowledge_reauth, user)
    grant = await request_json(
        "POST", "/v1/exports", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""),
        body=body.model_dump(mode="json"),
        reauthenticated_at=reauthenticated_at,
        idempotency_key=idempotency_key,
    )
    log_action(
        user.username,
        "export_knowledge_original",
        resource=str(body.asset_id),
        detail={"reason": body.reason},
    )
    return {
        "export_id": grant["export_id"],
        "download_url": f"/api/knowledge/exports/{grant['export_id']}/download",
        "download_token": grant["download_token"],
        "expires_at": grant["expires_at"],
        "expires_in": grant["expires_in"],
    }


@router.post("/exports/{export_id}/download", response_model=None)
async def download_original(
    export_id: UUID,
    body: ExportDownloadBody,
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[Session, Depends(get_session)],
):
    _require_original_export_admin(user, session)
    return await request_content(
        "GET",
        f"/v1/exports/{export_id}/download",
        user=user,
        session=session,
        request_id=getattr(request.state, "request_id", ""),
        export_token=body.export_token,
    )
