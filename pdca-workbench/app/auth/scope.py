# -*- coding: utf-8 -*-
"""角色对应的数据可见范围。"""
from __future__ import annotations

from sqlmodel import Session, select

from app.auth.models import User
from app.models.dealer_store import DealerStore


def visible_store_ids(user: User, session: Session) -> list[str] | None:
    """dealer/sales 返回可见门店；None 表示全局只读或管理角色。"""
    if user.role == "dealer":
        return [user.dealer_id] if user.dealer_id else []
    if user.role == "sales":
        return list(
            session.exec(
                select(DealerStore.store_id).where(
                    DealerStore.sales_owner == user.username,
                    DealerStore.is_active == True,  # noqa: E712
                )
            ).all()
        )
    return None


def visible_dealer_names(user: User, session: Session) -> list[str] | None:
    """返回与可见门店对应的经销商名称。"""
    store_ids = visible_store_ids(user, session)
    if store_ids is None:
        return None
    if not store_ids:
        return []
    return list(
        session.exec(
            select(DealerStore.name).where(DealerStore.store_id.in_(store_ids))
        ).all()
    )
