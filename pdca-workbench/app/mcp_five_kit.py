# -*- coding: utf-8 -*-
"""门店五件套只读 MCP（挂载在 /mcp-five-kit）。

鉴权：PDCA 用户 JWT（与工作台同一套账号），scope 为 ``pdca:read``。
权限：完全复用工作台的 DataScope —— admin 全量；sales/dealer 仅本人名下
      门店；显式请求范围外门店直接拒绝（fail-closed，不静默返回空）。
只读：全部 SELECT，无任何写操作。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

import os

from fastapi import HTTPException
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from sqlmodel import Session, select

from app.auth.deps import ensure_portal_access
from app.auth.models import User
from app.auth.scope import resolve_data_scope
from app.auth.security import decode_access_token, is_token_revoked
from app.config import get_settings
from app.database import get_engine
from app.models.dealer_store import DealerStore
from app.models.walkin_daily_report import (
    WalkinDailyReport,
    latest_walkin_reports,
    revenue_requires_review,
)

_READ_SCOPE = "pdca:read"
VISIT_FIELDS = (
    "walkin_visits", "cross_visits", "online_visits", "recruit_visits", "existing_visits",
)
FUNNEL_FIELDS = ("touch_count", "use_count", "wechat_add_count", "deal_count")


def _service_keys() -> dict[str, dict]:
    """服务密钥：PDCA_MCP_API_KEYS=key:role:owner_key,key2:role2:owner2。

    role ∈ admin/manager（全量）/ sales/dealer（仅 owner_key 名下门店）。
    给机器/Agent 用的长期凭证，与用户 JWT 并存。
    """
    keys: dict[str, dict] = {}
    for item in os.environ.get("PDCA_MCP_API_KEYS", "").split(","):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(":")]
        if not parts[0]:
            continue
        keys[parts[0]] = {
            "role": parts[1] if len(parts) > 1 and parts[1] else "admin",
            "owner_key": parts[2] if len(parts) > 2 else "",
        }
    return keys


@dataclass
class _Identity:
    """调用方身份：user（PDCA 账号）或 service（服务密钥）。"""

    kind: str
    role: str
    owner_key: str = ""
    username: str = ""
    user: User | None = None


class FiveKitTokenVerifier:
    """接受 PDCA 用户 JWT 或服务密钥；吊销/停用/需改密的账号一律拒绝。"""

    async def verify_token(self, token: str) -> AccessToken | None:
        service = _service_keys().get(token)
        if service:
            return AccessToken(
                token=token,
                client_id="pdca-service",
                scopes=[_READ_SCOPE],
                subject=f"service:{service['role']}:{service['owner_key']}",
            )
        payload = decode_access_token(token)
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


def _build_server() -> FastMCP:
    parsed = urlsplit(get_settings().workbench_base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return FastMCP(
        "PDCA 门店五件套",
        instructions=(
            "只读查询门店五件套日报（客流来源 + 成交漏斗）。"
            "权限与工作台一致：管理员看全部，销售/经销商只看本人名下门店；"
            "越权查询会被拒绝。"
        ),
        token_verifier=FiveKitTokenVerifier(),
        auth=AuthSettings(
            issuer_url=origin,
            resource_server_url=f"{origin}/mcp-five-kit/",
            required_scopes=[_READ_SCOPE],
        ),
        transport_security=TransportSecuritySettings(
            allowed_hosts=[parsed.netloc, "127.0.0.1:*", "localhost:*", "testserver"],
            allowed_origins=[origin],
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
    )


five_kit_mcp = _build_server()
five_kit_mcp_app = five_kit_mcp.streamable_http_app()

_original_run = five_kit_mcp.session_manager.run


@asynccontextmanager
async def _guarded_run() -> AsyncIterator[None]:
    """同一进程内可多次启动应用（测试场景）的幂等守卫。"""
    manager = five_kit_mcp.session_manager
    if getattr(manager, "_has_started", False):
        if getattr(manager, "_task_group", None) is not None:
            yield
            return
        manager._has_started = False
    async with _original_run():
        yield


five_kit_mcp.session_manager.run = _guarded_run  # type: ignore[method-assign]


@contextmanager
def _authorized_user():
    """当前 MCP 调用的身份与数据库会话（service 密钥 / 用户 JWT / 本地 stdio）。"""
    access = get_access_token()
    subject = access.subject if access else None
    if not subject:
        # 本地 stdio（可信进程）：用 PDCA_MCP_STDIO_ROLE 显式开启，默认关闭。
        local_role = os.environ.get("PDCA_MCP_STDIO_ROLE", "").strip()
        if local_role:
            with Session(get_engine()) as session:
                yield _Identity(
                    kind="service",
                    role=local_role,
                    owner_key=os.environ.get("PDCA_MCP_STDIO_OWNER", "").strip(),
                ), session
            return
        raise PermissionError("需要 PDCA 身份认证")
    with Session(get_engine()) as session:
        if access.client_id == "pdca-service":
            if not subject.startswith("service:"):
                raise PermissionError("服务身份格式无效")
            _, role, owner_key = subject.split(":", 2)
            yield _Identity(kind="service", role=role, owner_key=owner_key), session
            return
        if access.client_id != "pdca-user":
            raise PermissionError("未知的 MCP 身份类型")
        user = session.exec(select(User).where(User.username == subject)).first()
        if not user or not user.is_active or getattr(user, "must_change_password", False):
            raise PermissionError("PDCA 账号不可用")
        ensure_portal_access(user)
        yield _Identity(kind="user", role=user.role, username=subject, user=user), session


def _allowed_store_ids(identity: _Identity, session: Session) -> set[str] | None:
    """None 表示不限（管理员）；否则为可见门店集合（可能为空 = 看不到任何门店）。"""
    if identity.kind == "user" and identity.user is not None:
        scope = resolve_data_scope(identity.user, session)
        return None if scope.unrestricted else set(scope.store_ids)
    if identity.role in ("admin", "manager"):
        return None
    owner = (identity.owner_key or "").strip()
    if not owner:
        return set()  # fail-closed：服务密钥未绑定门店则看不到任何数据
    rows = session.exec(
        select(DealerStore).where(DealerStore.sales_owner == owner)
    ).all()
    return {row.store_id for row in rows}


def _require_scope(dealer_id: str, allowed: set[str] | None) -> None:
    if dealer_id and allowed is not None and dealer_id not in allowed:
        raise PermissionError(f"无权访问门店「{dealer_id}」")


def _iso(value: str, field: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field} 需为 YYYY-MM-DD") from exc


def _row(row: WalkinDailyReport) -> dict:
    payload = {
        "report_date": row.report_date,
        "dealer_id": row.dealer_id,
        "dealer_name": row.dealer_name,
    }
    for field in VISIT_FIELDS:
        payload[field] = int(getattr(row, field, 0) or 0)
    payload["visits_total"] = sum(payload[f] for f in VISIT_FIELDS)
    for field in FUNNEL_FIELDS:
        payload[field] = int(getattr(row, field, 0) or 0)
    payload["deal_amount_usd"] = float(getattr(row, "deal_amount_yuan", 0) or 0)
    payload["amount_requires_review"] = revenue_requires_review(row.deal_amount_yuan)
    return payload


def _reports(
    session: Session, start: str, end: str, dealer_id: str, allowed: set[str] | None
) -> list[WalkinDailyReport]:
    _require_scope(dealer_id, allowed)
    stmt = select(WalkinDailyReport).where(
        WalkinDailyReport.report_date >= start,
        WalkinDailyReport.report_date <= end,
    )
    if dealer_id:
        stmt = stmt.where(WalkinDailyReport.dealer_id == dealer_id)
    elif allowed is not None:
        stmt = stmt.where(WalkinDailyReport.dealer_id.in_(sorted(allowed)))
    return latest_walkin_reports(session.exec(stmt).all())


@five_kit_mcp.tool(
    name="list_stores",
    description="列出当前账号可见的门店（管理员为全部，销售/经销商为本店）。",
)
def list_stores(region: str = "") -> dict:
    with _authorized_user() as (user, session):
        allowed = _allowed_store_ids(user, session)
        stmt = select(DealerStore).where(DealerStore.is_active == True)  # noqa: E712
        if allowed is not None:
            stmt = stmt.where(DealerStore.store_id.in_(sorted(allowed)))
        if region.strip():
            stmt = stmt.where(DealerStore.region == region.strip())
        rows = list(session.exec(stmt).all())
        return {
            "count": len(rows),
            "unrestricted": allowed is None,
            "stores": [
                {
                    "store_id": r.store_id,
                    "name": r.name,
                    "region": r.region,
                    "country": r.country,
                    "sales_owner": r.sales_owner,
                }
                for r in rows
            ],
        }


@five_kit_mcp.tool(
    name="five_kit_reports",
    description="查询某日期区间的五件套日报明细（客流来源 + 成交漏斗）。",
)
def five_kit_reports(start_date: str, end_date: str = "", dealer_id: str = "") -> dict:
    start = _iso(start_date, "start_date")
    end = _iso(end_date, "end_date") if end_date.strip() else start
    with _authorized_user() as (user, session):
        allowed = _allowed_store_ids(user, session)
        rows = _reports(session, start, end, dealer_id.strip(), allowed)
        return {"count": len(rows), "items": [_row(r) for r in rows]}


@five_kit_mcp.tool(
    name="five_kit_summary",
    description="按门店汇总某区间的五件套合计（进店来源、漏斗、成交金额 USD）。",
)
def five_kit_summary(start_date: str, end_date: str = "", dealer_id: str = "") -> dict:
    start = _iso(start_date, "start_date")
    end = _iso(end_date, "end_date") if end_date.strip() else start
    with _authorized_user() as (user, session):
        allowed = _allowed_store_ids(user, session)
        rows = _reports(session, start, end, dealer_id.strip(), allowed)
        buckets: dict[str, dict] = {}
        for row in rows:
            item = buckets.setdefault(
                row.dealer_id,
                {"dealer_id": row.dealer_id, "dealer_name": row.dealer_name, "days": 0,
                 **{f: 0 for f in VISIT_FIELDS}, **{f: 0 for f in FUNNEL_FIELDS},
                 "deal_amount_usd": 0.0, "excluded_amount_count": 0},
            )
            item["days"] += 1
            for field in VISIT_FIELDS + FUNNEL_FIELDS:
                item[field] += int(getattr(row, field, 0) or 0)
            if revenue_requires_review(row.deal_amount_yuan):
                item["excluded_amount_count"] += 1
            else:
                item["deal_amount_usd"] += float(getattr(row, "deal_amount_yuan", 0) or 0)
        for item in buckets.values():
            item["visits_total"] = sum(item[f] for f in VISIT_FIELDS)
            if item["excluded_amount_count"] == item["days"]:
                item["deal_amount_usd"] = None
        return {
            "start_date": start,
            "end_date": end,
            "stores": sorted(buckets.values(), key=lambda i: i["dealer_id"]),
        }


@five_kit_mcp.tool(
    name="five_kit_missing",
    description="某日应报未报的门店清单（仅管理员可见）。",
)
def five_kit_missing(report_date: str) -> dict:
    day = _iso(report_date, "report_date")
    with _authorized_user() as (user, session):
        allowed = _allowed_store_ids(user, session)
        if allowed is not None:
            raise PermissionError("应报未报名单仅管理员可见")
        stores = list(
            session.exec(select(DealerStore).where(DealerStore.is_active == True)).all()  # noqa: E712
        )
        reported = {
            r.dealer_id
            for r in session.exec(
                select(WalkinDailyReport).where(WalkinDailyReport.report_date == day)
            ).all()
        }
        missing = [
            {"store_id": s.store_id, "name": s.name, "region": s.region,
             "sales_owner": s.sales_owner}
            for s in stores
            if s.store_id not in reported
        ]
        return {
            "report_date": day,
            "active_stores": len(stores),
            "reported": len(reported),
            "missing_count": len(missing),
            "missing": missing,
        }


@five_kit_mcp.tool(
    name="five_kit_trend",
    description="近 N 个月五件套上报趋势（上报天数、进店合计、成交台数、成交金额 USD）。",
)
def five_kit_trend(months: int = 3, dealer_id: str = "") -> dict:
    if not 1 <= months <= 24:
        raise ValueError("months 需在 1~24 之间")
    today = datetime.now().date()
    start = (today - timedelta(days=months * 31)).replace(day=1).isoformat()
    with _authorized_user() as (user, session):
        allowed = _allowed_store_ids(user, session)
        rows = _reports(session, start, today.isoformat(), dealer_id.strip(), allowed)
        buckets: dict[str, dict] = {}
        for row in rows:
            month = row.report_date[:7]
            item = buckets.setdefault(
                month, {"month": month, "days": 0, "visits": 0, "deals": 0,
                        "deal_amount_usd": 0.0, "excluded_amount_count": 0}
            )
            item["days"] += 1
            item["visits"] += sum(int(getattr(row, f, 0) or 0) for f in VISIT_FIELDS)
            item["deals"] += int(getattr(row, "deal_count", 0) or 0)
            if revenue_requires_review(row.deal_amount_yuan):
                item["excluded_amount_count"] += 1
            else:
                item["deal_amount_usd"] += float(getattr(row, "deal_amount_yuan", 0) or 0)
        for item in buckets.values():
            if item["excluded_amount_count"] == item["days"]:
                item["deal_amount_usd"] = None
        return {"months": sorted(buckets.values(), key=lambda i: i["month"])}


def main() -> None:
    """stdio 方式运行（本地 Cursor/Claude 客户端直接拉起）。

    需显式设置 PDCA_MCP_STDIO_ROLE=admin（或 sales/dealer + PDCA_MCP_STDIO_OWNER）
    与 PDCA_DATABASE_URL，进程可信、无 HTTP 鉴权。
    """
    five_kit_mcp.run("stdio")


if __name__ == "__main__":
    main()
