# -*- coding: utf-8 -*-
"""日志配置：按天轮转。"""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from app.config import get_settings


def setup_logging() -> None:
    """初始化 loguru 日志。"""
    settings = get_settings()
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {message}",
    )
    logger.add(
        log_dir / "pdca_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
        level=settings.log_level,
    )
