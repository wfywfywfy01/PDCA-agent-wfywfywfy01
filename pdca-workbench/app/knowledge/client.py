"""Scoped server-to-server client for the dealer knowledge hub."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import HTTPException
from fastapi.responses import Response, StreamingResponse
from jose import jwt
from sqlmodel import Session, select

from app.auth.models import User
from app.auth.scope import resolve_data_scope
from app.config import get_settings
from app.models.dealer_store import DealerStore


def validate_knowledge_hub_settings() -> None:
    settings = get_settings()
    if not settings.knowledge_hub_enabled:
        return
    if not settings.knowledge_hub_url:
        raise RuntimeError("知识库已启用，但 PDCA_KNOWLEDGE_HUB_URL 无效")
    if settings.knowledge_hub_timeout_seconds <= 0:
        raise RuntimeError("PDCA_KNOWLEDGE_HUB_TIMEOUT_SECONDS 必须大于 0")
    if settings.environment == "production":
        if not settings.knowledge_hub_token_key_file:
            raise RuntimeError("生产环境知识库必须使用 PDCA_KNOWLEDGE_HUB_TOKEN_KEY_FILE")
        if settings.knowledge_hub_token_secret:
            raise RuntimeError("生产环境禁止使用 PDCA_KNOWLEDGE_HUB_TOKEN_SECRET")
    _token_key()


def _token_key() -> str:
    settings = get_settings()
    if settings.knowledge_hub_token_key_file:
        try:
            value = Path(settings.knowledge_hub_token_key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("知识库服务令牌密钥文件不可用") from exc
    else:
        value = settings.knowledge_hub_token_secret
    if len(value.encode("utf-8")) < 32:
        raise RuntimeError("知识库服务令牌密钥至少需要 32 字节")
    return value


def _knowledge_scope(user: User, session: Session) -> tuple[str, list[str], list[str]]:
    scope = resolve_data_scope(user, session)
    if scope.unrestricted:
        return scope.mode, [], []
    if scope.store_ids:
        stores = session.exec(
            select(DealerStore).where(
                DealerStore.is_active == True,  # noqa: E712
                DealerStore.store_id.in_(scope.store_ids),
            )
        ).all()
    else:
        stores = []
    dealer_ids: list[str] = []
    for store in stores:
        value = str(getattr(store, "knowledge_dealer_id", "") or "").strip()
        try:
            dealer_ids.append(str(UUID(value)))
        except ValueError:
            continue
    settings = get_settings()
    team_key = str(scope.team_key or "").strip()
    team_keys = [settings.knowledge_hub_team_map.get(team_key, team_key)] if team_key else []
    return scope.mode, sorted(set(dealer_ids)), team_keys


def scoped_dealers(user: User, session: Session) -> list[dict[str, str]]:
    scope = resolve_data_scope(user, session)
    stmt = select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
    if not scope.unrestricted:
        if not scope.store_ids:
            return []
        stmt = stmt.where(DealerStore.store_id.in_(scope.store_ids))
    rows = session.exec(stmt.order_by(DealerStore.name)).all()
    dealers: dict[str, dict[str, str]] = {}
    for row in rows:
        if not _is_uuid(getattr(row, "knowledge_dealer_id", "")):
            continue
        dealer_id = str(UUID(row.knowledge_dealer_id))
        dealers.setdefault(dealer_id, {
            "store_id": row.store_id,
            "name": row.name.split(" · ", 1)[0],
            "dealer_id": dealer_id,
        })
    return list(dealers.values())


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value or ""))
        return True
    except ValueError:
        return False


def _service_token(user: User, session: Session) -> str:
    scope, dealer_ids, team_keys = _knowledge_scope(user, session)
    now = datetime.now(timezone.utc)
    payload = {
        "iss": "pdca-workbench",
        "aud": "dealer-knowledge-hub",
        "sub": user.username,
        "user_id": user.username,
        "role": user.role,
        "scope": scope,
        "dealer_ids": dealer_ids,
        "team_keys": team_keys,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, _token_key(), algorithm="HS256")


def _headers(user: User, session: Session, request_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_service_token(user, session)}",
        "X-Request-ID": request_id[:200],
    }


def _upstream_error(response: httpx.Response) -> HTTPException:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    detail = payload.get("message") or payload.get("detail") or "知识库服务请求失败"
    status_code = response.status_code if response.status_code in {403, 404, 409, 422} else 503
    return HTTPException(status_code=status_code, detail=detail)


async def request_json(
    method: str, path: str, *, user: User, session: Session, request_id: str, body: dict | None = None
) -> dict | list:
    settings = get_settings()
    if not settings.knowledge_hub_enabled:
        raise HTTPException(status_code=503, detail="知识库服务尚未启用")
    try:
        async with httpx.AsyncClient(timeout=settings.knowledge_hub_timeout_seconds) as client:
            response = await client.request(
                method, f"{settings.knowledge_hub_url}{path}",
                headers=_headers(user, session, request_id), json=body,
            )
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="知识库服务暂不可用") from exc
    if not response.is_success:
        raise _upstream_error(response)
    return response.json()


async def request_content(
    method: str, path: str, *, user: User, session: Session, request_id: str, body: dict | None = None
) -> Response:
    settings = get_settings()
    if not settings.knowledge_hub_enabled:
        raise HTTPException(status_code=503, detail="知识库服务尚未启用")
    client = httpx.AsyncClient(timeout=settings.knowledge_hub_timeout_seconds)
    try:
        request = client.build_request(
            method, f"{settings.knowledge_hub_url}{path}",
            headers=_headers(user, session, request_id), json=body,
        )
        response = await client.send(request, stream=True)
    except (httpx.HTTPError, RuntimeError) as exc:
        await client.aclose()
        raise HTTPException(status_code=503, detail="知识库服务暂不可用") from exc
    if not response.is_success:
        await response.aread()
        error = _upstream_error(response)
        await response.aclose()
        await client.aclose()
        raise error

    async def chunks():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    allowed_headers = {
        key: value for key, value in response.headers.items()
        if key.lower() in {"content-disposition", "cache-control"}
    }
    return StreamingResponse(
        chunks(), media_type=response.headers.get("content-type", "application/octet-stream"),
        headers=allowed_headers,
    )
