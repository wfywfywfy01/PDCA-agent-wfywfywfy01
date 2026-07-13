# -*- coding: utf-8 -*-
"""APScheduler 定时任务与 PostgreSQL 备份。"""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from app.config import get_settings
from app.legacy import bridge
from app.models.sync import run_full_sync, sync_dealer_sales_from_vps

_scheduler: BackgroundScheduler | None = None


_BACKUP_KEEP = 14  # 保留最近 N 份备份


def _prune_backups(backup_dir: Path, pattern: str, keep: int) -> None:
    """删除旧备份，只保留最近 keep 份。"""
    files = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
            logger.info("清理旧备份: {}", old.name)
        except Exception as exc:
            logger.warning("清理备份失败 {}: {}", old.name, exc)


def backup_database() -> str | None:
    """备份数据库：PostgreSQL 用 pg_dump，SQLite 用文件复制。"""
    settings = get_settings()
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if settings.is_postgresql:
        info = settings.pg_connection_info
        dest = backup_dir / f"pdca_{stamp}.sql"
        env = os.environ.copy()
        if info.get("password"):
            env["PGPASSWORD"] = info["password"]
        cmd = [
            "pg_dump",
            "-h", info["host"],
            "-p", info["port"],
            "-U", info["user"],
            "-d", info["database"],
            "-f", str(dest),
            "--no-owner",
            "--no-acl",
        ]
        try:
            subprocess.run(cmd, env=env, check=True, capture_output=True, text=True)
            logger.info("PostgreSQL 已备份: {}", dest)
            _prune_backups(backup_dir, "pdca_*.sql", _BACKUP_KEEP)
            return str(dest)
        except FileNotFoundError:
            logger.warning("未找到 pg_dump，跳过 PostgreSQL 备份")
            return None
        except subprocess.CalledProcessError as exc:
            logger.error("pg_dump 失败: {}", exc.stderr or exc)
            return None

    db_path = settings.data_dir / "pdca.db"
    if not db_path.is_file():
        return None
    dest = backup_dir / f"pdca_{stamp}.db"
    shutil.copy2(db_path, dest)
    logger.info("SQLite 已备份: {}", dest)
    _prune_backups(backup_dir, "pdca_*.db", _BACKUP_KEEP)
    return str(dest)


def daily_sync_job() -> None:
    """每日 VPS/文件同步任务（06:00）。"""
    date_text = bridge.today_text()
    logger.info("开始每日同步: {}", date_text)
    try:
        result = run_full_sync(date_text)
        logger.info("每日同步完成: {}", result)
    except Exception as exc:
        logger.exception("每日同步失败: {}", exc)
    backup_database()


def logistics_tracking_refresh_job() -> None:
    """物流状态自动刷新（07:30）：抓取 UPS/FedEx/DHL 在途运单官网状态。"""
    import asyncio
    from app.logistics.service import refresh_tracking_statuses

    logger.info("物流状态自动刷新开始")
    try:
        result = asyncio.run(refresh_tracking_statuses())
        logger.info("物流状态自动刷新完成: {}", result)
    except Exception as exc:
        logger.exception("物流状态自动刷新异常: {}", exc)


def kpi_refresh_job() -> None:
    """KPI 数据刷新（09:00 / 12:00 / 21:00）：重新生成 chart_data.json + dashboard.html。"""
    date_text = bridge.today_text()
    logger.info("KPI 刷新开始 {}", date_text)
    try:
        code, _stdout, stderr = bridge.run_pdca(date_text, push=False)
        if code == 0:
            logger.info("KPI 刷新完成 {}", date_text)
        else:
            logger.warning("KPI 刷新失败 code={} stderr={}", code, (stderr or "")[:300])
    except Exception as exc:
        logger.exception("KPI 刷新异常: {}", exc)


def start_scheduler() -> BackgroundScheduler | None:
    """启动后台调度器。"""
    global _scheduler
    settings = get_settings()
    if not settings.scheduler_enabled:
        logger.info("调度器已禁用 (PDCA_SCHEDULER_ENABLED=0)")
        return None
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler()

    # 06:00 — 文件同步 + 备份
    parts = settings.sync_cron.split()
    if len(parts) == 5:
        minute, hour, day, month, dow = parts
        _scheduler.add_job(
            daily_sync_job,
            trigger="cron",
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=dow,
            id="daily_sync",
            max_instances=1,
            coalesce=True,
        )
    else:
        _scheduler.add_job(
            daily_sync_job,
            trigger="interval",
            hours=24,
            id="daily_sync",
            max_instances=1,
        )

    # 20:00 — VPS Sell-out 日内补充同步（当日 MTD 最新数据）
    _scheduler.add_job(
        lambda: sync_dealer_sales_from_vps(bridge.today_text()),
        trigger="cron",
        hour=20,
        minute=0,
        id="vps_dealer_sync_20",
        max_instances=1,
        coalesce=True,
    )

    # 07:30 — 物流状态自动刷新（UPS/FedEx/DHL 官网）
    _scheduler.add_job(
        logistics_tracking_refresh_job,
        trigger="cron",
        hour=7,
        minute=30,
        id="logistics_tracking_refresh",
        max_instances=1,
        coalesce=True,
    )

    # 09:00 / 12:00 / 21:00 — KPI 数据刷新
    for hour in (9, 12, 21):
        _scheduler.add_job(
            kpi_refresh_job,
            trigger="cron",
            hour=hour,
            minute=0,
            id=f"kpi_refresh_{hour:02d}",
            max_instances=1,
            coalesce=True,
        )

    _scheduler.start()
    logger.info(
        "调度器已启动 cron={} logistics_tracking=07:30 kpi_refresh=09:00/12:00/21:00",
        settings.sync_cron,
    )
    return _scheduler


def stop_scheduler() -> None:
    """停止调度器。"""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
