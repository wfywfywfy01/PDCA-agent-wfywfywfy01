# -*- coding: utf-8 -*-
"""Agent 管理后台 API：IM 机器人（列表/创建/公开范围/群聊）与 PDCA 智能体状态。"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.agent_admin import registry, service
from app.audit import log_action
from app.auth.deps import require_role
from app.auth.models import User

router = APIRouter(prefix="/api/agent-admin", tags=["agent-admin"])

_BOT_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


class BotCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="机器人名称")
    bot_key: str | None = Field(default=None, max_length=64, description="唯一 key（可选）")
    description: str | None = Field(default=None, max_length=500, description="说明（可选）")
    webhook_url: str | None = Field(default=None, max_length=300, description="webhook（可选）")
    public: bool = Field(default=False, description="设为公开，允许其他群管理员添加")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("机器人名称不能为空")
        return value.strip()

    @field_validator("bot_key")
    @classmethod
    def _bot_key_shape(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not _BOT_KEY_RE.match(value.strip()):
            raise ValueError("bot_key 需以字母/数字开头，仅含字母、数字、-、_，长度 3-64")
        return value.strip()

    @field_validator("webhook_url")
    @classmethod
    def _webhook_scheme(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        if not value.strip().lower().startswith(("http://", "https://")):
            raise ValueError("webhook_url 必须是 http(s) 地址")
        return value.strip()


class BotVisibilityIn(BaseModel):
    public: bool = Field(description="true=公开；false=仅自己可见")


@router.get("/bots")
async def list_bots(
    _user: Annotated[User, Depends(require_role("manager"))],
):
    """我的 IM 机器人列表（vertu-cli im +bots 实时透传）。"""
    items = await service.list_bots()
    return {"items": items, "fetched_at": service.utc_now_iso()}


@router.get("/bot-channels")
async def list_bot_channels(
    _user: Annotated[User, Depends(require_role("manager"))],
):
    """我的全部机器人已加入的群聊。"""
    items = await service.list_bot_channels()
    return {"items": items, "fetched_at": service.utc_now_iso()}


@router.post("/bots")
async def create_bot(
    body: BotCreateIn,
    request: Request,
    current_user: Annotated[User, Depends(require_role("manager"))],
):
    """创建 IM 机器人（写操作，记审计日志）。"""
    try:
        result = await service.create_bot(
            service.BotCreateSpec(
                name=body.name,
                bot_key=body.bot_key,
                description=body.description,
                webhook_url=body.webhook_url,
                public=body.public,
            )
        )
    except service.BotAdminError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    log_action(
        current_user.username,
        "bot_create",
        resource=body.name,
        detail={"public": body.public, "bot_key": body.bot_key},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "result": result}


@router.patch("/bots/{app_id}/visibility")
async def set_bot_visibility(
    app_id: str,
    body: BotVisibilityIn,
    request: Request,
    current_user: Annotated[User, Depends(require_role("manager"))],
):
    """调整机器人公开范围（写操作，记审计日志）。"""
    try:
        result = await service.set_bot_visibility(app_id, body.public)
    except service.BotAdminError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    log_action(
        current_user.username,
        "bot_visibility",
        resource=app_id,
        detail={"public": body.public},
        ip=request.client.host if request.client else "",
    )
    return {"ok": True, "public": body.public, "result": result}


@router.get("/pdca-agents")
async def list_pdca_agents(
    _user: Annotated[User, Depends(require_role("manager"))],
):
    """PDCA 智能体注册表 + 本机 Hermes 档案 + 模型路由只读快照。"""
    return {
        "agents": registry.pdca_agents_snapshot(),
        "hermes_profiles_root": str(registry.hermes_profiles_root())
        if registry.hermes_profiles_root()
        else None,
        "hermes_profiles": registry.hermes_profiles_snapshot(),
        "model_routing": registry.model_routing_snapshot(),
        "fetched_at": service.utc_now_iso(),
    }
