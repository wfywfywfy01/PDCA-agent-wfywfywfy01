# -*- coding: utf-8 -*-
"""SignalSeller 获客方法论服务（ProfileBuilder + FollowUp + CommandCenter）。"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.legacy import bridge

DEFAULT_TEAM = "yang-jingjing"
CUSTOMER_MGMT_PORT = 8787


def _methodology() -> dict:
    path = get_settings().config_dir / "signalseller_methodology.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def team_customers_path(team: str = DEFAULT_TEAM) -> Path:
    return get_settings().repo_root / "teams" / team / "customers.csv"


def _read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_date(text: str) -> datetime | None:
    try:
        return datetime.strptime((text or "")[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _silent_days(last_followup: str, ref: str | None = None) -> int | None:
    last = _parse_date(last_followup)
    if not last:
        return None
    ref_dt = _parse_date(ref or bridge.today_text()) or datetime.utcnow()
    return max(0, (ref_dt - last).days)


def priority_to_abcd(priority: str) -> str:
    """legacy priority → ABCD。"""
    p = (priority or "").strip().upper()
    if p in ("S", "A"):
        return "A"
    if p == "B":
        return "B"
    if p == "C":
        return "C"
    return "D"


def score_customer(row: dict, ref_date: str | None = None) -> dict:
    """
    ProfileBuilder：计算 ABCD、分数、沉默天数、建议动作。

    @param row customers.csv 行
    @param ref_date 参考日期 YYYY-MM-DD
    """
    cfg = _methodology().get("abcd_grading", {})
    ref = ref_date or bridge.today_text()
    priority = (row.get("priority") or "").strip()
    abcd = (row.get("abcd_grade") or "").strip().upper() or priority_to_abcd(priority)
    silent = _silent_days(row.get("last_followup_date", ""), ref)
    status = (row.get("status") or "").lower()

    value_score = int(row.get("value_score") or 0)
    intent_score = int(row.get("intent_score") or 0)
    if not value_score:
        value_score = 40 if abcd in ("A", "B") else 25
    if not intent_score:
        intent_score = 40 if abcd in ("A", "C") else 28
        if silent is not None and silent > 14:
            intent_score = max(10, intent_score - 15)

    overdue_days = 7 if abcd == "A" else 14 if abcd in ("B", "C") else 30
    is_overdue = silent is not None and silent > overdue_days and status == "active"
    alerts: list[str] = []
    next_action = (row.get("next_action") or "").strip()

    if silent is not None and silent >= 7 and abcd in ("A", "B"):
        alerts.append(f"沉默 {silent} 天，建议价值型触达")
    if is_overdue:
        alerts.append(f"超 PDCA 跟进阈值（{overdue_days} 天）")
    if not next_action:
        alerts.append("缺少 next_action，请补充下一步")

    followup_round = (row.get("followup_round") or "1").strip()
    suggested = _suggest_action(abcd, silent, row)

    grade_cfg = cfg.get("grades", {}).get(abcd, {})
    return {
        **row,
        "abcd_grade": abcd,
        "value_score": value_score,
        "intent_score": intent_score,
        "silent_days": silent,
        "overdue_days_threshold": overdue_days,
        "is_overdue": is_overdue,
        "alerts": alerts,
        "followup_round": followup_round,
        "suggested_action": suggested,
        "followup_frequency": grade_cfg.get("followup_frequency", ""),
        "effort_pct": grade_cfg.get("effort_pct", 0),
    }


def _suggest_action(abcd: str, silent: int | None, row: dict) -> str:
    """FollowUpOrchestrator 建议动作。"""
    if row.get("next_action"):
        return row["next_action"]
    if silent is not None and silent >= 14:
        return "发送重启沟通消息（行业见解/工具，零压力结尾）"
    if silent is not None and silent >= 7:
        return "纯价值触达：案例或报告，不追问下单"
    if abcd == "A":
        return "SPIN 需求确认 + 推进方案/报价"
    if abcd == "B":
        return "分享同行案例，培育意向"
    if abcd == "C":
        return "快速确认需求，推动小单成交"
    return "模板化月度触达，保持存在感"


def resolve_owner_filter(role: str, sales_name: str, display_name: str, username: str, owner_query: str = "") -> str | None:
    if role == "sales":
        return sales_name or display_name or username
    if owner_query.strip():
        return owner_query.strip()
    return None


def load_customers(
    team: str = DEFAULT_TEAM,
    owner: str | None = None,
    abcd: str | None = None,
    overdue_only: bool = False,
    ref_date: str | None = None,
) -> list[dict]:
    rows = [score_customer(r, ref_date) for r in _read_csv(team_customers_path(team))]
    if owner:
        rows = [r for r in rows if (r.get("owner") or "").strip() == owner]
    if abcd and abcd.lower() != "all":
        rows = [r for r in rows if r.get("abcd_grade") == abcd.upper()]
    if overdue_only:
        rows = [r for r in rows if r.get("is_overdue")]
    rows.sort(key=lambda r: (
        0 if r.get("is_overdue") else 1,
        -(r.get("silent_days") or 0),
        r.get("abcd_grade", "Z"),
    ))
    return rows


def build_summary(customers: list[dict]) -> dict:
    total = len(customers)
    by_grade = {"A": 0, "B": 0, "C": 0, "D": 0}
    overdue = 0
    silent_risk = 0
    for c in customers:
        g = c.get("abcd_grade", "D")
        by_grade[g] = by_grade.get(g, 0) + 1
        if c.get("is_overdue"):
            overdue += 1
        if (c.get("silent_days") or 0) >= 7:
            silent_risk += 1
    silent_rate = round(silent_risk / total * 100) if total else 0
    return {
        "total": total,
        "by_abcd": by_grade,
        "overdue_count": overdue,
        "silent_risk_count": silent_risk,
        "silent_rate_pct": silent_rate,
        "attention_items": [
            {
                "dealer_name": c.get("dealer_name"),
                "owner": c.get("owner"),
                "abcd_grade": c.get("abcd_grade"),
                "silent_days": c.get("silent_days"),
                "suggested_action": c.get("suggested_action"),
            }
            for c in customers
            if c.get("is_overdue") or (c.get("silent_days") or 0) >= 7
        ][:8],
    }


def list_owners(team: str = DEFAULT_TEAM) -> list[str]:
    names = {(r.get("owner") or "").strip() for r in _read_csv(team_customers_path(team))}
    return sorted(n for n in names if n)


def followup_tasks(customers: list[dict]) -> list[dict]:
    """今日建议跟进任务。"""
    tasks = []
    for c in customers:
        if not c.get("is_overdue") and (c.get("silent_days") or 0) < 7:
            continue
        tasks.append({
            "dealer_name": c.get("dealer_name"),
            "dealer_nickname": c.get("dealer_nickname"),
            "owner": c.get("owner"),
            "abcd_grade": c.get("abcd_grade"),
            "silent_days": c.get("silent_days"),
            "action": c.get("suggested_action"),
            "priority": "HIGH" if c.get("abcd_grade") == "A" else "MEDIUM",
        })
    return tasks


def try_fetch_8787_customers() -> list[dict]:
    """8787 客户管理运行时合并数据。"""
    import socket
    import urllib.error
    import urllib.request

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    try:
        if sock.connect_ex(("127.0.0.1", CUSTOMER_MGMT_PORT)) != 0:
            return []
    finally:
        sock.close()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{CUSTOMER_MGMT_PORT}/api/state", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("customers") or []
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []
