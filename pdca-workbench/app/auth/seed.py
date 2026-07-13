# -*- coding: utf-8 -*-
"""初始化默认用户。"""
from __future__ import annotations

from sqlmodel import Session, select

from app.auth.models import User
from app.auth.security import hash_password
from app.config import get_settings
from app.database import get_engine, init_db
from loguru import logger


def seed_users() -> None:
    """按显式环境变量初始化一次性管理员；不再创建固定密码账号。"""
    init_db()
    settings = get_settings()
    username = settings.bootstrap_admin_username
    password = settings.bootstrap_admin_password
    if not username and not password:
        return
    if not username or not password:
        raise RuntimeError("初始化管理员必须同时设置用户名和密码")
    if len(password) < 12:
        raise RuntimeError("初始化管理员密码至少 12 位")
    with Session(get_engine()) as session:
        exists = session.exec(select(User).where(User.username == username)).first()
        if exists:
            return
        session.add(
            User(
                username=username,
                hashed_password=hash_password(password),
                role="admin",
                display_name=settings.bootstrap_admin_display_name or username,
                must_change_password=True,
                pwd_version=0,
            )
        )
        session.commit()
        logger.info("已创建一次性初始化管理员: {}", username)
