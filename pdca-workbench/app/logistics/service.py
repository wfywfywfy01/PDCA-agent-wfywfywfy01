# -*- coding: utf-8 -*-
"""物流数据加载、判断与按销售过滤。"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.legacy import bridge

JUDGEMENT_ORDER = {
    "异常": 0,
    "待关注": 1,
    "待核查": 2,
    "运输中": 3,
    "正常": 4,
}

STATUS_GROUPS = {
    "attention": {"异常", "待关注"},
    "transit": {"运输中", "待核查"},
    "delivered": set(),
}


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_carriers() -> dict:
    path = get_settings().config_dir / "carriers.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _tracking_url(carriers: dict, carrier: str, tracking_number: str) -> str:
    info = carriers.get(carrier) or carriers.get((carrier or "").upper()) or {}
    template = info.get("tracking_url", "")
    return template.replace("{tracking_number}", tracking_number) if template else ""


def _load_settings() -> dict:
    path = get_settings().config_dir / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _is_delivered(row: dict) -> bool:
    """是否视为已签收。"""
    status = (row.get("current_status") or row.get("status") or "").lower()
    if row.get("progress_pct", 0) >= 100:
        return True
    if "deliver" in status or "签收" in status or "送达" in status:
        return True
    return (row.get("expected_status") or "").lower() == "delivered" and bool(status)


def _days_since_ship(ship_date: str, ref_date: str) -> int | None:
    """发货至参考日的天数。"""
    try:
        ship_dt = datetime.strptime((ship_date or "")[:10], "%Y-%m-%d")
        ref_dt = datetime.strptime((ref_date or bridge.today_text())[:10], "%Y-%m-%d")
        return max(0, (ref_dt - ship_dt).days)
    except ValueError:
        return None


def _judge_status(row: dict, settings: dict, date_text: str) -> tuple[str, str, int]:
    """返回 judgement, reason, progress_pct。"""
    status = (row.get("current_status") or row.get("status") or "").strip()
    status_lower = status.lower()
    logistics_cfg = settings.get("logistics", {})
    for keyword in logistics_cfg.get("abnormal_keywords", []):
        if keyword.lower() in status_lower:
            return "异常", f"状态包含异常关键词：{keyword}", 20
    for keyword in logistics_cfg.get("normal_keywords", []):
        if keyword.lower() in status_lower:
            if "deliver" in status_lower or "签收" in status:
                return "正常", f"状态包含正常关键词：{keyword}", 100
            return "正常", f"状态包含正常关键词：{keyword}", 70
    expected = (row.get("expected_status") or "").lower()
    if expected == "delivered" or "deliver" in status_lower or "签收" in status:
        return "正常", "已签收或送达", 100
    ship_date = (row.get("ship_date") or date_text or "")[:10]
    try:
        ship_dt = datetime.strptime(ship_date, "%Y-%m-%d")
        run_dt = datetime.strptime(date_text, "%Y-%m-%d")
        if (run_dt - ship_dt).days >= 7 and "deliver" not in status_lower:
            return "待关注", "发货超过 7 天，且未标记签收", 45
    except ValueError:
        pass
    if status:
        return "运输中", "在途更新", 65
    return "待核查", "未填写当前状态", 30


def _sales_aliases() -> dict[str, str]:
    path = get_settings().config_dir / "sales_aliases.csv"
    aliases: dict[str, str] = {}
    if not path.is_file():
        return aliases
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                raw = (row.get("raw_sales") or "").strip()
                canonical = (row.get("canonical_sales") or "").strip()
                if raw and canonical:
                    aliases[raw.lower()] = canonical
                    aliases[canonical.lower()] = canonical
    except OSError:
        pass
    return aliases


def canonical_sales_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    aliases = _sales_aliases()
    return aliases.get(text.lower(), text)


def resolve_sales_filter(
    role: str,
    sales_name: str,
    display_name: str,
    username: str,
    salesperson_query: str = "",
) -> str | None:
    """
    解析销售过滤名。

    sales 角色只能看自己的；manager/admin 可看全部或指定销售。
    """
    if role == "sales":
        return canonical_sales_name(sales_name or display_name or username)
    if salesperson_query.strip():
        return canonical_sales_name(salesperson_query.strip())
    return None


def _match_sales(row_sales: str, filter_sales: str | None) -> bool:
    if not filter_sales:
        return True
    row_canon = canonical_sales_name(row_sales)
    return row_canon == filter_sales or (row_sales or "").strip() == filter_sales


def _match_search(row: dict, query: str) -> bool:
    q = (query or "").strip().lower()
    if not q:
        return True
    haystack = " ".join(
        [
            row.get("tracking_number", ""),
            row.get("carrier", ""),
            row.get("customer", ""),
            row.get("salesperson", ""),
            row.get("note", ""),
            row.get("current_status", ""),
        ],
    ).lower()
    return q in haystack


def _match_status_group(row: dict, status_group: str) -> bool:
    group = (status_group or "all").strip().lower()
    if group in ("", "all"):
        return True
    if group == "delivered":
        return _is_delivered(row)
    if group == "attention":
        return row.get("judgement") in STATUS_GROUPS["attention"]
    if group == "transit":
        return not _is_delivered(row) and row.get("judgement") not in STATUS_GROUPS["attention"]
    return row.get("judgement") == status_group


def _sort_shipments(rows: list[dict]) -> list[dict]:
    """异常优先，其次发货日倒序。"""
    return sorted(
        rows,
        key=lambda r: (
            JUDGEMENT_ORDER.get(r.get("judgement", "待核查"), 9),
            0 if _is_delivered(r) else -1,
            -(r.get("days_in_transit") or 0),
            r.get("ship_date", ""),
            r.get("record_date", ""),
        ),
    )


def _enrich_row(row: dict, carriers: dict, cfg: dict, file_date: str, ref_date: str) -> dict:
    enriched = dict(row)
    tracking = (enriched.get("tracking_number") or "").strip()
    enriched["record_date"] = file_date
    enriched["tracking_url"] = enriched.get("tracking_url") or _tracking_url(
        carriers,
        enriched.get("carrier", ""),
        tracking,
    )
    if not enriched.get("judgement"):
        judgement, reason, progress = _judge_status(enriched, cfg, file_date)
        enriched["judgement"] = judgement
        enriched["reason"] = reason
        enriched["progress_pct"] = progress
    else:
        progress = enriched.get("progress_pct")
        if progress is None:
            _, _, progress = _judge_status(enriched, cfg, file_date)
        enriched["progress_pct"] = int(progress or 30)
    enriched["is_delivered"] = _is_delivered(enriched)
    enriched["days_in_transit"] = _days_since_ship(
        enriched.get("ship_date", ""),
        ref_date or file_date,
    )
    enriched["check_report_path"] = check_report_relative_path(file_date)
    enriched["check_report_exists"] = bool(enriched["check_report_path"])
    return enriched


def list_available_dates() -> list[str]:
    """有物流录入数据的日期列表（新→旧）。"""
    inputs_dir = get_settings().mvp_root / "inputs" / "logistics"
    if not inputs_dir.is_dir():
        return []
    dates = []
    for csv_path in inputs_dir.glob("*_tracking.csv"):
        rows = _read_csv(csv_path)
        if any((r.get("tracking_number") or "").strip() for r in rows):
            dates.append(csv_path.stem.replace("_tracking", ""))
    return sorted(dates, reverse=True)


def check_report_relative_path(date_text: str) -> str:
    """核查报告相对 MVP 根路径。"""
    path = get_settings().mvp_root / "outputs" / date_text / "logistics_check_report.md"
    if path.is_file():
        return f"outputs/{date_text}/logistics_check_report.md"
    return ""


def load_shipments(
    date_text: str | None = None,
    salesperson: str | None = None,
    status_group: str = "all",
    query: str = "",
    open_only: bool = False,
) -> list[dict]:
    """合并 inputs 与 outputs 物流数据。"""
    settings = get_settings()
    inputs_dir = settings.mvp_root / "inputs" / "logistics"
    outputs_dir = settings.mvp_root / "outputs"
    carriers = _load_carriers()
    cfg = _load_settings()
    ref_date = date_text or bridge.today_text()
    merged: dict[str, dict] = {}

    if not inputs_dir.is_dir():
        return []

    for csv_path in sorted(inputs_dir.glob("*_tracking.csv")):
        file_date = csv_path.stem.replace("_tracking", "")
        if date_text and date_text != "all" and file_date != date_text:
            continue
        results_path = outputs_dir / file_date / f"{file_date}_logistics_results.csv"
        results_by_tracking = {
            (r.get("tracking_number") or "").strip(): r
            for r in _read_csv(results_path)
        }
        for row in _read_csv(csv_path):
            tracking = (row.get("tracking_number") or "").strip()
            if not tracking:
                continue
            enriched = dict(row)
            if tracking in results_by_tracking:
                enriched.update(results_by_tracking[tracking])
            merged[tracking] = _enrich_row(enriched, carriers, cfg, file_date, ref_date)

    rows = list(merged.values())
    if salesperson:
        rows = [r for r in rows if _match_sales(r.get("salesperson", ""), salesperson)]
    if open_only:
        rows = [r for r in rows if not r.get("is_delivered")]
    rows = [r for r in rows if _match_status_group(r, status_group)]
    rows = [r for r in rows if _match_search(r, query)]
    return _sort_shipments(rows)


def build_summary(shipments: list[dict]) -> dict:
    """汇总物流进展统计。"""
    total = len(shipments)
    delivered = sum(1 for s in shipments if s.get("is_delivered"))
    attention = [s for s in shipments if s.get("judgement") in STATUS_GROUPS["attention"]]
    in_transit = sum(
        1
        for s in shipments
        if not s.get("is_delivered")
        and s.get("judgement") in ("运输中", "正常", "待核查")
    )
    abnormal = len(attention)
    pending = sum(1 for s in shipments if s.get("judgement") == "待核查" and not s.get("is_delivered"))
    rate = round(delivered / total * 100) if total else 0
    return {
        "total": total,
        "delivered": delivered,
        "in_transit": in_transit,
        "abnormal": abnormal,
        "pending": pending,
        "open": total - delivered,
        "delivery_rate_pct": rate,
        "attention_items": [
            {
                "tracking_number": s.get("tracking_number"),
                "customer": s.get("customer"),
                "judgement": s.get("judgement"),
                "reason": s.get("reason"),
            }
            for s in attention[:5]
        ],
    }


def list_salespeople() -> list[str]:
    """所有出现过的销售姓名。"""
    names = set()
    for row in load_shipments(date_text="all"):
        name = canonical_sales_name(row.get("salesperson", ""))
        if name:
            names.add(name)
    return sorted(names)
