# -*- coding: utf-8 -*-
"""数据导出 API（Excel / CSV）。"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Annotated
from urllib.parse import quote

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.auth.deps import require_role
from app.auth.models import User
from app.auth.scope import normalize_scope_key, resolve_data_scope, scoped_active_dealer_names
from app.config import get_settings
from app.database import get_session
from app.models.dealer_sales import DealerSales, snapshot_amount_state
from app.models.walkin_daily_report import WalkinDailyReport, latest_walkin_reports
from app.validation import require_iso_date, require_iso_month

router = APIRouter(prefix="/api/export", tags=["export"])

_ROLE_LABEL = {"viewer": "只读", "sales": "销售", "manager": "主管", "admin": "管理员"}


def _wb_response(wb: openpyxl.Workbook, filename: str) -> StreamingResponse:
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    safe_name = filename.replace(" ", "_")
    encoded = quote(safe_name, encoding="utf-8")
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


def _header_style(ws, row: int, cols: int) -> None:
    """给表头行添加样式。"""
    from openpyxl.styles import Font, PatternFill, Alignment
    fill = PatternFill("solid", fgColor="1E3A5F")
    font = Font(bold=True, color="FFFFFF", size=11)
    align = Alignment(horizontal="center", vertical="center")
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = fill
        cell.font = font
        cell.alignment = align


def _append_data_row(ws, values: list) -> None:
    """Keep upstream/user text as XLSX text, never an executable formula."""
    ws.append(values)
    for cell in ws[ws.max_row]:
        if isinstance(cell.value, str):
            cell.data_type = "s"


# ── 五件套明细导出 ─────────────────────────────────────────────────────────────

@router.get("/walkin-metrics")
async def export_walkin_metrics(
    user: Annotated[User, Depends(require_role("dealer"))],
    session: Annotated[Session, Depends(get_session)],
    month: str = Query(""),
    dealer_id: str = Query(""),
):
    """导出当前账号可见范围内的门店五件套日报 Excel。"""
    stmt = select(WalkinDailyReport).order_by(
        WalkinDailyReport.report_date, WalkinDailyReport.dealer_id
    )
    if month:
        require_iso_month(month)
        stmt = stmt.where(WalkinDailyReport.report_date.startswith(month))
    from app.walkin.router import _dealer_ids_for_user
    allowed = _dealer_ids_for_user(user, session)
    if dealer_id and dealer_id not in allowed:
        raise HTTPException(status_code=403, detail="该门店不在当前账号的数据权限范围内")
    if not allowed:
        raise HTTPException(status_code=403, detail="账号未绑定可导出的门店")
    stmt = stmt.where(WalkinDailyReport.dealer_id.in_(allowed))
    if dealer_id:
        stmt = stmt.where(WalkinDailyReport.dealer_id == dealer_id)
    rows = latest_walkin_reports(session.exec(stmt).all())

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"五件套_{month or '全部'}"

    headers = [
        "日期", "门店ID", "门店名称",
        "walkin直接进店", "异业介绍", "线上", "招聘自带", "存量老客户", "合计进店",
        "触摸产品", "试用体验", "微信添加", "成交组数",
        "成交金额(USD)", "金额需核查",
        "提交人", "提交时间",
    ]
    ws.append(headers)
    _header_style(ws, 1, len(headers))

    settings = get_settings()
    revenue_review_threshold = min(
        settings.max_reported_revenue_usd,
        getattr(settings, "revenue_review_threshold_usd", settings.max_reported_revenue_usd),
    )

    for r in rows:
        total = r.total_visits
        _append_data_row(ws, [
            r.report_date, r.dealer_id, r.dealer_name,
            r.walkin_visits, r.cross_visits, r.online_visits,
            r.recruit_visits, r.existing_visits, total,
            r.touch_count, r.use_count, r.wechat_add_count, r.deal_count,
            r.deal_amount_yuan,
            "是" if r.deal_amount_yuan > revenue_review_threshold else "否",
            r.submitted_by,
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
        ])

    # 自动列宽
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 32)

    fname = f"五件套_{month or '全部'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return _wb_response(wb, fname)


# ── 经销商业绩导出 ─────────────────────────────────────────────────────────────

@router.get("/dealer-sales")
async def export_dealer_sales(
    user: Annotated[User, Depends(require_role("viewer"))],
    session: Annotated[Session, Depends(get_session)],
    month: str = Query(""),
    batch_date: str = "",
):
    """导出经销商业绩快照；可显式选择批次，默认保留历史全量。"""
    stmt = select(DealerSales).order_by(DealerSales.check_date, DealerSales.dealer_name)
    if month:
        require_iso_month(month)
        stmt = stmt.where(DealerSales.check_date.startswith(month))
    if batch_date:
        require_iso_date(batch_date)
        if month and not batch_date.startswith(month):
            raise HTTPException(status_code=422, detail="批次日期不在所选月份")
        stmt = stmt.where(DealerSales.check_date == batch_date)
    scope = resolve_data_scope(user, session)
    markers = session.exec(stmt.where(DealerSales.source_file.in_([
        "vertu-cli:sales-orders:failed", "vertu-cli:sales-orders:confirmed-empty",
    ]))).all() if scope.unrestricted else []
    names = scoped_active_dealer_names(user, session)
    if scope.unrestricted:
        rows = session.exec(stmt).all()
    elif names:
        rows = session.exec(stmt.where(DealerSales.dealer_name.in_(names))).all()
    else:
        rows = []
    rows = [row for row in rows if row.dealer_name and row.source_file not in {
        "vertu-cli:sales-orders:failed", "vertu-cli:sales-orders:confirmed-empty",
    }]
    if batch_date and not rows and not any(
        marker.source_file == "vertu-cli:sales-orders:confirmed-empty" for marker in markers
    ):
        raise HTTPException(
            status_code=409,
            detail="所选批次没有当前账号可见的业绩明细；可能尚未同步或客户尚未映射，不代表零业绩",
        )
    active_names = {normalize_scope_key(name) for name in names}
    batches: dict[str, list[DealerSales]] = {}
    for row in rows:
        batches.setdefault(row.check_date, []).append(row)
    amount_states = {day: snapshot_amount_state(batch) for day, batch in batches.items()}
    failed_stmt = select(DealerSales.check_date).where(
        DealerSales.source_file == "vertu-cli:sales-orders:failed"
    )
    if month:
        failed_stmt = failed_stmt.where(DealerSales.check_date.startswith(month))
    latest_failed_by_month: dict[str, str] = {}
    for failed_day in session.exec(failed_stmt).all():
        key = failed_day[:7]
        latest_failed_by_month[key] = max(latest_failed_by_month.get(key, ""), failed_day)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"业绩_{month or '全部'}"

    headers = ["日期", "经销商", "区域", "国家",
                "Sell-in(万)", "Sell-out(万)", "台量", "同步时间", "门店映射状态", "Sell-in金额状态"]
    ws.append(headers)
    _header_style(ws, 1, len(headers))

    for r in rows:
        _append_data_row(ws, [
            r.check_date, r.dealer_name, r.region, r.country,
            r.sell_in_wan if amount_states[r.check_date] == "available" else None, r.sell_out_wan, r.units,
            r.synced_at.strftime("%Y-%m-%d %H:%M") if r.synced_at else "",
            "已匹配在用门店" if normalize_scope_key(r.dealer_name) in active_names else "未映射门店",
            "金额待复核（旧快照有销量但金额全部为零）" if amount_states[r.check_date] == "suspect" else
            "旧快照（较新同步失败）" if latest_failed_by_month.get(r.check_date[:7], "") >= r.check_date else "可用",
        ])

    notes = wb.create_sheet("口径与限制")
    _append_data_row(notes, ["口径", "每个日期是当月累计快照，不是日增量；不同日期快照不可相加。"])
    _append_data_row(notes, ["权限", "未能以门店名称精确匹配的上游客户只向管理员显示，不自动归属销售。"])
    _append_data_row(notes, ["待办", "上游须提供稳定客户 ID 或经审核的客户—门店映射，才能准确分配脱敏客户业绩。"])
    _append_data_row(notes, ["选中批次", batch_date or "全部历史批次（不可直接汇总）"])
    _append_data_row(notes, ["可见批次日期", ", ".join(sorted(batches))])
    if batch_date:
        amount_state = amount_states.get(batch_date, "missing")
        stale_batch = latest_failed_by_month.get(batch_date[:7], "") >= batch_date
        _append_data_row(notes, ["所选批次 Sell-in 合计(万)",
                                 round(sum(row.sell_in_wan for row in rows), 4)
                                 if amount_state == "available" and not stale_batch else
                                 "旧快照，较新同步失败，不可作当前对账" if stale_batch else "金额待核查"])
        _append_data_row(notes, ["所选批次台量合计", sum(row.units for row in rows)])
        _append_data_row(notes, ["所选批次未映射行数", sum(
            normalize_scope_key(row.dealer_name) not in active_names for row in rows
        ) if scope.unrestricted else "仅管理员可查看"])
    _append_data_row(notes, ["同步状态", ", ".join(
        f"{row.check_date}: {'同步失败，不代表零业绩' if row.source_file.endswith(':failed') else '已确认空批次'}"
        for row in markers
    ) or ("未发现失败或空批次标记" if scope.unrestricted else "仅管理员可查看")])

    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=8)
        ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 36)

    fname = f"业绩_{month or '全部'}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return _wb_response(wb, fname)
