# -*- coding: utf-8 -*-
"""文件数据同步到 SQLite。"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.legacy import bridge
from app.models.daily_report import DailyReport
from app.models.dealer_sales import DealerSales
from app.models.meeting import MeetingRecord
from app.models.pdca_task import PdcaTask


def sync_dealer_sales_from_json(date_text: str) -> int:
    """从 data_raw JSON 同步经销商业绩。"""
    settings = get_settings()
    data_raw = settings.repo_root / "data_raw"
    if not data_raw.is_dir():
        return 0
    candidates = sorted(
        data_raw.glob(f"dealer_sales_month_to_date_*{date_text}*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        candidates = sorted(
            data_raw.glob("dealer_sales_month_to_date_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    if not candidates:
        return 0
    path = candidates[0]
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return 0
    rows = payload if isinstance(payload, list) else payload.get("dealers") or payload.get("rows") or []
    count = 0
    with Session(get_engine()) as session:
        # 一次性拉取本月所有已有记录，避免逐行 SELECT（N+1 → 1）
        existing_rows = session.exec(
            select(DealerSales).where(DealerSales.check_date == date_text)
        ).all()
        existing_map: dict[str, DealerSales] = {r.dealer_name: r for r in existing_rows}

        for item in rows:
            if not isinstance(item, dict):
                continue
            name = (item.get("dealer") or item.get("name") or item.get("dealer_name") or "").strip()
            if not name:
                continue
            sell_in = float(item.get("sell_in_wan") or item.get("sellInWan") or 0)
            sell_out = float(item.get("sell_out_wan") or item.get("sellOutWan") or 0)
            existing = existing_map.get(name)
            if existing:
                existing.sell_in_wan = sell_in
                existing.sell_out_wan = sell_out
                existing.synced_at = datetime.utcnow()
                session.add(existing)
            else:
                new_row = DealerSales(
                    check_date=date_text,
                    dealer_name=name,
                    region=str(item.get("region") or ""),
                    country=str(item.get("country") or ""),
                    sell_in_wan=sell_in,
                    sell_out_wan=sell_out,
                    units=int(item.get("units") or 0),
                    source_file=str(path),
                )
                session.add(new_row)
                existing_map[name] = new_row
            count += 1
        session.commit()
    logger.info("同步经销商业绩 {} 条 ({})", count, path.name)
    return count


def sync_pdca_tasks_from_csv(date_text: str) -> int:
    """从 inputs/todos CSV 同步待办。"""
    settings = get_settings()
    csv_path = settings.mvp_root / "inputs" / "todos" / f"{date_text}_todos.csv"
    if not csv_path.is_file():
        return 0
    count = 0
    with Session(get_engine()) as session, csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            title = (row.get("title") or row.get("任务") or row.get("todo") or "").strip()
            if not title:
                continue
            owner = (row.get("owner") or row.get("负责人") or "").strip()
            status = (row.get("status") or row.get("状态") or "pending").strip()
            existing = session.exec(
                select(PdcaTask).where(
                    PdcaTask.task_date == date_text,
                    PdcaTask.title == title,
                ),
            ).first()
            if existing:
                existing.owner = owner
                existing.status = status
                existing.updated_at = datetime.utcnow()
                session.add(existing)
            else:
                session.add(
                    PdcaTask(
                        task_date=date_text,
                        title=title,
                        owner=owner,
                        status=status,
                        source=str(csv_path),
                    ),
                )
            count += 1
        session.commit()
    logger.info("同步待办 {} 条 ({})", count, csv_path.name)
    return count


def sync_daily_reports(date_text: str) -> int:
    """从 outputs 目录同步 Markdown 报告。"""
    out_dir = bridge.output_dir(date_text)
    if not out_dir.is_dir():
        return 0
    count = 0
    with Session(get_engine()) as session:
        for md in out_dir.glob("*.md"):
            content = md.read_text(encoding="utf-8", errors="replace")
            report_type = md.stem.replace(f"{date_text}_", "")
            existing = session.exec(
                select(DailyReport).where(
                    DailyReport.report_date == date_text,
                    DailyReport.report_type == report_type,
                ),
            ).first()
            if existing:
                existing.content = content
                existing.file_path = str(md)
                session.add(existing)
            else:
                session.add(
                    DailyReport(
                        report_date=date_text,
                        report_type=report_type,
                        title=md.stem,
                        content=content,
                        file_path=str(md),
                    ),
                )
            count += 1
        session.commit()
    logger.info("同步日报 {} 份 ({})", count, date_text)
    return count


def sync_meetings(date_text: str) -> int:
    """从 Vemory API 同步会议到数据库。"""
    payload = bridge.api_meeting_center_meetings(date_text)
    meetings = payload.get("meetings") or []
    count = 0
    with Session(get_engine()) as session:
        for m in meetings:
            ext_id = str(m.get("id") or "")
            if not ext_id:
                continue
            existing = session.exec(
                select(MeetingRecord).where(
                    MeetingRecord.meeting_date == date_text,
                    MeetingRecord.external_id == ext_id,
                ),
            ).first()
            todos_json = json.dumps(m.get("todos") or [], ensure_ascii=False)
            participants_json = json.dumps(m.get("participants") or [], ensure_ascii=False)
            if existing:
                existing.title = str(m.get("title") or "")
                existing.brief = str(m.get("brief") or "")
                existing.todos_json = todos_json
                existing.synced_at = datetime.utcnow()
                session.add(existing)
            else:
                session.add(
                    MeetingRecord(
                        meeting_date=date_text,
                        external_id=ext_id,
                        title=str(m.get("title") or ""),
                        meeting_type=str(m.get("meeting_type") or "internal"),
                        bucket=str(m.get("bucket") or "report"),
                        duration_minutes=int(m.get("duration_minutes") or 0),
                        brief=str(m.get("brief") or ""),
                        todos_json=todos_json,
                        participants_json=participants_json,
                    ),
                )
            count += 1
        session.commit()
    logger.info("同步会议 {} 场 ({})", count, date_text)
    return count


_VPS_DEALER_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "data_platform" / "data_role_pdca_mvp"
    / "system_queries" / "dealer_monthly_overseas.py"
)


def sync_dealer_sales_from_vps(date_text: str) -> int:
    """通过 vertu-cli 拉取 VPS odoo_sale 手机 Sell-out + 激活率，同步到 dealer_sales 表。
    以 (check_date, dealer_name) 做 upsert；当天运行多次会覆盖同日记录。
    """
    import shutil

    if not _VPS_DEALER_SCRIPT.is_file():
        logger.warning("VPS dealer 脚本不存在: {}", _VPS_DEALER_SCRIPT)
        return 0

    start_date = date_text[:8] + "01"
    params_payload = {"run_date": date_text, "start_date": start_date, "end_date": date_text}

    vertu_cmd = (
        bridge.vertu_command() if hasattr(bridge, "vertu_command")
        else shutil.which("vertu.cmd") or shutil.which("vertu") or "vertu"
    )
    use_shell = sys.platform == "win32" and str(vertu_cmd).endswith(".cmd")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as pf:
        json.dump(params_payload, pf)
        params_path = pf.name

    try:
        completed = subprocess.run(
            [vertu_cmd, "odoo", "data", "sandbox",
             "--code-file", str(_VPS_DEALER_SCRIPT),
             "--params-file", params_path],
            capture_output=True, text=True, encoding="utf-8", timeout=60,
            shell=use_shell,
        )
    finally:
        Path(params_path).unlink(missing_ok=True)

    raw = (completed.stdout or "").strip()
    if not raw:
        logger.warning("VPS dealer 同步：vertu 无输出 stderr={}", (completed.stderr or "")[:200])
        return 0

    try:
        outer = json.loads(raw)
        result = (
            outer.get("result", {}).get("execution", {}).get("result")
            or outer.get("execution", {}).get("result")
            or outer
        )
        dealers = result.get("dealers", [])
    except Exception as exc:
        logger.warning("VPS dealer 同步：解析失败 {}", exc)
        return 0

    count = 0
    with Session(get_engine()) as session:
        for item in dealers:
            name = (item.get("dealer_name") or "").strip()
            if not name:
                continue
            sell_out_yuan = float(item.get("sell_out_yuan") or 0)
            phone_qty = int(item.get("qty") or 0)
            activation_rate = float(item.get("activation_rate") or 0)
            sell_out_wan = round(sell_out_yuan / 10000, 4)

            existing = session.exec(
                select(DealerSales).where(
                    DealerSales.check_date == date_text,
                    DealerSales.dealer_name == name,
                )
            ).first()
            if existing:
                existing.sell_out_wan = sell_out_wan
                existing.phone_qty = phone_qty
                existing.activation_rate = activation_rate
                existing.units = phone_qty
                existing.synced_at = datetime.utcnow()
                existing.source_file = "vps:odoo_sale"
                session.add(existing)
            else:
                session.add(DealerSales(
                    check_date=date_text,
                    dealer_name=name,
                    sell_in_wan=0.0,
                    sell_out_wan=sell_out_wan,
                    units=phone_qty,
                    phone_qty=phone_qty,
                    activation_rate=activation_rate,
                    source_file="vps:odoo_sale",
                ))
            count += 1
        session.commit()

    logger.info("VPS dealer sell-out 同步 {} 条 ({})", count, date_text)
    return count


def run_full_sync(date_text: str | None = None) -> dict:
    """执行全量文件→数据库同步，单步失败不影响其他步骤。"""
    date_text = date_text or bridge.today_text()
    result: dict = {"date": date_text}
    for key, fn in (
        ("dealer_sales", lambda: sync_dealer_sales_from_json(date_text)),
        ("vps_dealer_sales", lambda: sync_dealer_sales_from_vps(date_text)),
        ("pdca_tasks", lambda: sync_pdca_tasks_from_csv(date_text)),
        ("daily_reports", lambda: sync_daily_reports(date_text)),
        ("meetings", lambda: sync_meetings(date_text)),
    ):
        try:
            result[key] = fn()
        except Exception as exc:
            logger.warning("同步步骤 {} 失败: {}", key, exc)
            result[key] = f"error: {exc}"
    return result
