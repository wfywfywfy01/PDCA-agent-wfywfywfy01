# -*- coding: utf-8 -*-
"""单条业务数据写入 PostgreSQL。"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlmodel import Session, select

from app.database import get_engine
from app.models.daily_report import DailyReport
from app.models.logistics import LogisticsShipment
from app.models.pdca_task import PdcaTask


def upsert_daily_report(
    report_date: str,
    report_type: str,
    title: str,
    content: str,
    file_path: str = "",
) -> None:
    """写入或更新日报/问卷 Markdown。"""
    try:
        with Session(get_engine()) as session:
            row = session.exec(
                select(DailyReport).where(
                    DailyReport.report_date == report_date,
                    DailyReport.report_type == report_type,
                ),
            ).first()
            if row:
                row.title = title
                row.content = content
                row.file_path = file_path
                session.add(row)
            else:
                session.add(
                    DailyReport(
                        report_date=report_date,
                        report_type=report_type,
                        title=title,
                        content=content,
                        file_path=file_path,
                    ),
                )
            session.commit()
    except Exception as exc:
        logger.warning("写入 daily_reports 失败: {}", exc)


def update_pdca_task_from_form(
    task_date: str,
    title: str,
    status: str,
    vps_todo_id: str = "",
) -> None:
    """根据 PDCA 任务表单更新库内记录。"""
    if not title.strip():
        return
    try:
        with Session(get_engine()) as session:
            row = session.exec(
                select(PdcaTask).where(
                    PdcaTask.task_date == task_date,
                    PdcaTask.title == title.strip(),
                ),
            ).first()
            if row:
                row.status = status or row.status
                if vps_todo_id:
                    row.vps_todo_id = vps_todo_id
                row.updated_at = datetime.utcnow()
                session.add(row)
            else:
                session.add(
                    PdcaTask(
                        task_date=task_date,
                        title=title.strip(),
                        status=status or "pending",
                        source="pdca-vps",
                        vps_todo_id=vps_todo_id,
                    ),
                )
            session.commit()
    except Exception as exc:
        logger.warning("更新 pdca_tasks 失败: {}", exc)


def upsert_logistics_shipment(
    record_date: str,
    form: dict,
    salesperson: str = "",
) -> None:
    """录入物流单号时写入 PostgreSQL。"""
    tracking = (form.get("tracking_number", [""])[0] or "").strip()
    if not tracking:
        return
    try:
        with Session(get_engine()) as session:
            row = session.exec(
                select(LogisticsShipment).where(
                    LogisticsShipment.tracking_number == tracking,
                ),
            ).first()
            payload = {
                "record_date": record_date,
                "carrier": (form.get("carrier", [""])[0] or "").strip(),
                "customer": (form.get("customer", [""])[0] or "").strip(),
                "salesperson": salesperson or (form.get("salesperson", [""])[0] or "").strip(),
                "ship_date": (form.get("ship_date", [record_date])[0] or record_date).strip(),
                "expected_status": (form.get("expected_status", [""])[0] or "").strip(),
                "current_status": (form.get("current_status", [""])[0] or "").strip(),
                "note": (form.get("note", [""])[0] or "").strip(),
                "synced_at": datetime.utcnow(),
            }
            if row:
                for key, val in payload.items():
                    setattr(row, key, val)
                session.add(row)
            else:
                session.add(LogisticsShipment(tracking_number=tracking, **payload))
            session.commit()
    except Exception as exc:
        logger.warning("写入 logistics_shipments 失败: {}", exc)
