"""跨境货代运营台：只读/复核 logibot sqlite，不另起库。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from app.config import get_settings

_FIELDS = (
    "顺丰单号",
    "订单号",
    "国际单号",
    "快递公司",
    "销售人员",
    "境外收货人",
    "目的地",
    "签收状态",
    "生命周期",
    "异常",
    "匹配级别",
    "匹配证据",
    "最新轨迹",
    "备注",
)


def db_path() -> Path:
    """台账 sqlite 路径。优先 LOGIBOT_DATA_DIR。
    @returns {Path}
    """
    raw = os.environ.get("LOGIBOT_DATA_DIR", "").strip()
    if raw:
        return Path(raw) / "shipments.db"
    return get_settings().data_dir / "logibot" / "shipments.db"


def needs_review(row: dict) -> bool:
    """C 级、待人工、未关异常。
    @param {dict} row
    @returns {bool}
    """
    if (row.get("匹配级别") or "").upper() == "C":
        return True
    if (row.get("签收状态") or "") == "待人工":
        return True
    if row.get("异常"):
        return True
    return False


def to_item(row: dict) -> dict:
    """中文台账列转运营台 JSON。
    @param {dict} row
    @returns {dict}
    """
    return {
        "order_no": row.get("订单号") or "",
        "sf_tracking_no": row.get("顺丰单号") or "",
        "tracking_no": row.get("国际单号") or "",
        "carrier": row.get("快递公司") or "",
        "salesperson": row.get("销售人员") or "",
        "consignee": row.get("境外收货人") or "",
        "country": row.get("目的地") or "",
        "status": row.get("签收状态") or "",
        "lifecycle": row.get("生命周期") or "",
        "exception": row.get("异常") or "",
        "match_level": row.get("匹配级别") or "",
        "match_evidence": row.get("匹配证据") or "",
        "last_event": (row.get("最新轨迹") or "")[:160],
        "note": row.get("备注") or "",
        "needs_review": needs_review(row),
    }


def _connect(path: Path) -> sqlite3.Connection | None:
    if not path.is_file():
        return None
    conn = sqlite3.connect(str(path), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def load_rows() -> list[dict]:
    """读全部货代台账。库不存在返回空列表。
    @returns {list}
    """
    conn = _connect(db_path())
    if conn is None:
        return []
    try:
        existing = {r[1] for r in conn.execute("PRAGMA table_info(shipments)").fetchall()}
        if "顺丰单号" not in existing:
            return []
        cols = [c for c in _FIELDS if c in existing]
        quoted = ",".join(f'"{c}"' for c in cols)
        rows = conn.execute(f"SELECT {quoted} FROM shipments").fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def summarize(items: list[dict]) -> dict:
    """运营台 KPI。
    @param {list} items
    @returns {dict}
    """
    return {
        "total": len(items),
        "in_transit": sum(1 for i in items if i.get("status") in ("运输中", "清关中", "海关扣关")),
        "exception": sum(1 for i in items if i.get("exception")),
        "review": sum(1 for i in items if i.get("needs_review")),
        "delivered": sum(1 for i in items if i.get("status") == "签收已确认"),
        "labeled": sum(1 for i in items if i.get("status") == "已出国际单"),
    }


def load_desk(view: str = "all", keyword: str = "") -> dict:
    """运营台汇总 + 列表。
    @param {str} view all|review|exception
    @param {str} keyword
    @returns {dict}
    """
    path = db_path()
    rows = load_rows()
    items = [to_item(r) for r in rows]
    summary = summarize(items)
    view = (view or "all").strip().lower()
    if view == "review":
        items = [i for i in items if i["needs_review"]]
    elif view == "exception":
        items = [i for i in items if i["exception"]]
    key = (keyword or "").strip().lower()
    if key:
        items = [
            i
            for i in items
            if key in " ".join(
                [
                    i["order_no"],
                    i["sf_tracking_no"],
                    i["tracking_no"],
                    i["carrier"],
                    i["salesperson"],
                    i["consignee"],
                    i["country"],
                    i["status"],
                ]
            ).lower()
        ]
    return {
        "available": path.is_file(),
        "path": str(path),
        "summary": summary,
        "count": len(items),
        "items": items,
    }


def confirm_row(sf_tracking_no: str, reason: str, operator: str) -> dict:
    """人工确认 C 级关联，写回 sqlite。
    @param {str} sf_tracking_no
    @param {str} reason
    @param {str} operator
    @returns {dict}
    """
    sf = (sf_tracking_no or "").strip()
    note = (reason or "").strip()
    if not sf:
        raise ValueError("缺少顺丰单号")
    if len(note) < 2:
        raise ValueError("确认原因至少 2 个字")
    path = db_path()
    conn = _connect(path)
    if conn is None:
        raise FileNotFoundError("货代台账不存在")
    try:
        row = conn.execute(
            'SELECT * FROM shipments WHERE "顺丰单号"=?', (sf,)
        ).fetchone()
        if row is None:
            raise KeyError("运单不存在")
        data = dict(row)
        status = data.get("签收状态") or ""
        if status == "待人工":
            status = "已出国际单" if data.get("国际单号") else "已预报"
        evidence = data.get("匹配证据") or ""
        extra = f"confirmed:{operator}:{note}"
        evidence = f"{evidence},{extra}".strip(",")
        conn.execute(
            """
            UPDATE shipments
            SET "匹配级别"=?, "匹配证据"=?, "签收状态"=?, "备注"=?
            WHERE "顺丰单号"=?
            """,
            (
                "A",
                evidence,
                status,
                ((data.get("备注") or "") + f";复核确认 {note}").strip(";"),
                sf,
            ),
        )
        conn.commit()
        refreshed = conn.execute(
            'SELECT * FROM shipments WHERE "顺丰单号"=?', (sf,)
        ).fetchone()
        return to_item(dict(refreshed) if refreshed else data)
    finally:
        conn.close()
