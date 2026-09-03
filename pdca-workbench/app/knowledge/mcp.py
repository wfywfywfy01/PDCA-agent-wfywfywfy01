"""Authenticated MCP tools for dealer knowledge retrieval."""
from __future__ import annotations

from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlmodel import Session, select

from app.auth.deps import ensure_portal_access
from app.auth.models import User
from app.auth.security import decode_token, is_token_revoked
from app.config import get_settings
from app.database import get_engine
from app.knowledge.client import request_json, require_knowledge_access, scoped_dealers


_READ_SCOPE = "knowledge:read"


class PDCATokenVerifier:
    """Accept active PDCA user JWTs; reject revoked or stale credentials."""

    async def verify_token(self, token: str) -> AccessToken | None:
        payload = decode_token(token)
        if not payload or is_token_revoked(payload):
            return None
        username = str(payload.get("sub") or "")
        if not username:
            return None
        with Session(get_engine()) as session:
            user = session.exec(select(User).where(User.username == username)).first()
            if (
                not user
                or not user.is_active
                or getattr(user, "must_change_password", False)
                or int(payload.get("pwd_v", 0)) != int(getattr(user, "pwd_version", 0) or 0)
            ):
                return None
            try:
                ensure_portal_access(user)
            except HTTPException:
                return None
        return AccessToken(
            token=token,
            client_id="pdca-user",
            scopes=[_READ_SCOPE],
            expires_at=int(payload["exp"]) if payload.get("exp") else None,
            subject=username,
        )


def _public_origin() -> str:
    parsed = urlsplit(get_settings().workbench_base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _build_server() -> FastMCP:
    origin = _public_origin()
    host = urlsplit(origin).netloc
    return FastMCP(
        "Vertu Dealer Knowledge",
        instructions=(
            "Search only the caller's authorized dealer knowledge. "
            "Use list_dealers before searching and preserve citations in answers."
        ),
        token_verifier=PDCATokenVerifier(),
        auth=AuthSettings(
            issuer_url=origin,
            resource_server_url=f"{origin}/mcp/",
            required_scopes=[_READ_SCOPE],
        ),
        transport_security=TransportSecuritySettings(
            allowed_hosts=[host, "127.0.0.1:*", "localhost:*", "testserver"],
            allowed_origins=[origin],
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )


knowledge_mcp = _build_server()
knowledge_mcp_app = knowledge_mcp.streamable_http_app()


@contextmanager
def _authorized_user():
    access = get_access_token()
    username = access.subject if access else None
    if not username:
        raise PermissionError("PDCA authentication is required")
    with Session(get_engine()) as session:
        user = session.exec(select(User).where(User.username == username)).first()
        if not user or not user.is_active or getattr(user, "must_change_password", False):
            raise PermissionError("PDCA account is unavailable")
        ensure_portal_access(user)
        yield user, session


def _dealer_id(value: str) -> UUID | None:
    return UUID(value.strip()) if value.strip() else None


def _query(value: str) -> str:
    query = " ".join(value.strip().split())
    if not query or len(query) > 500:
        raise ValueError("query must contain 1 to 500 characters")
    return query


def _top_k(value: int) -> int:
    if not 1 <= value <= 20:
        raise ValueError("top_k must be between 1 and 20")
    return value


@knowledge_mcp.tool(
    name="list_dealers",
    description="List dealer names and IDs visible to the authenticated PDCA user.",
)
async def list_dealers() -> dict:
    with _authorized_user() as (user, session):
        require_knowledge_access(user, session)
        return {"dealers": scoped_dealers(user, session)}


@knowledge_mcp.tool(
    name="search_dealer_knowledge",
    description=(
        "Search authorized dealer documents, images, and media. Returns redacted "
        "evidence snippets with source citations. Call list_dealers first."
    ),
)
async def search_dealer_knowledge(
    query: str,
    dealer_id: str = "",
    category: str = "",
    top_k: int = 8,
) -> dict:
    dealer_uuid = _dealer_id(dealer_id)
    payload = {
        "query": _query(query),
        "top_k": _top_k(top_k),
    }
    if dealer_uuid:
        payload["dealer_id"] = str(dealer_uuid)
    if category.strip():
        payload["category"] = category.strip()[:40]
    with _authorized_user() as (user, session):
        require_knowledge_access(user, session, dealer_uuid)
        return await request_json(
            "POST",
            "/v1/search",
            user=user,
            session=session,
            request_id=f"mcp-{uuid4().hex}",
            body=payload,
        )


@knowledge_mcp.tool(
    name="answer_dealer_question",
    description=(
        "Answer a dealer question from authorized evidence only. Returns citations "
        "and states when evidence is insufficient. Call list_dealers first."
    ),
)
async def answer_dealer_question(
    question: str,
    dealer_id: str = "",
    category: str = "",
    top_k: int = 8,
) -> dict:
    dealer_uuid = _dealer_id(dealer_id)
    payload = {
        "query": _query(question),
        "top_k": min(_top_k(top_k), 10),
    }
    if dealer_uuid:
        payload["dealer_id"] = str(dealer_uuid)
    if category.strip():
        payload["category"] = category.strip()[:40]
    with _authorized_user() as (user, session):
        require_knowledge_access(user, session, dealer_uuid)
        return await request_json(
            "POST",
            "/v1/answers",
            user=user,
            session=session,
            request_id=f"mcp-{uuid4().hex}",
            body=payload,
        )
