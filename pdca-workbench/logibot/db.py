"""本地 sqlite 台账。主键顺丰单号。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOGIBOT_DATA_DIR") or ROOT / "data")
DB_PATH = DATA_DIR / "shipments.db"

# 金山「跟踪表（4.19后）」原列名，飞书照抄。
PUBLIC_COLS = [
    "序号",
    "操作人员",
    "月份",
    "接单日期",
    "销售人员",
    "销售单录单日期",
    "订单号",
    "共建销售单号/系统单号",
    "产品编码",
    "产品名称",
    "货品总数",
    "手机台数",
    "手表台",
    "目的地",
    "是否发预报（报关资料）",
    "货代",
    "清关方式",
    "快递公司",
    "报关单号",
    "发货日期",
    "顺丰单号",
    "顺丰状态",
    "顺丰签收日期",
    "预计签收时间（3天）",
    "出面单时间",
    "国际单号",
    "签收状态",
    "预计送达时间",
    "预警时间（5天）",
    "签收日期",
    "时效",
    "件数/箱数",
    "发货点",
    "部门",
    "计费重量KG",
    "运费CNY",
    "备注",
    "境内发货人",
    "境外收货人",
    "合同编码",
    "报关日期",
]

INTERNAL_COLS = [
    "预报文件",
    "面单文件",
    "最新轨迹",
    "生命周期",
    "异常",
    "匹配级别",
    "匹配证据",
    "事件哈希",
    "feishu_record_id",
    "im_user_id",
    "updated_at",
]
ALL_COLS = PUBLIC_COLS + INTERNAL_COLS
CLEARABLE = {"异常"}


def connect() -> sqlite3.Connection:
    """打开 sqlite，缺表则建。
    @returns {sqlite3.Connection}
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cols = ", ".join(f'"{c}" TEXT' for c in ALL_COLS)
    conn.execute(
        f'CREATE TABLE IF NOT EXISTS shipments ({cols}, PRIMARY KEY ("顺丰单号"))'
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_messages (message_id TEXT PRIMARY KEY, processed_at TEXT)"
    )
    existing = {r[1] for r in conn.execute("PRAGMA table_info(shipments)").fetchall()}
    for c in ALL_COLS:
        if c not in existing:
            conn.execute(f'ALTER TABLE shipments ADD COLUMN "{c}" TEXT')
    conn.commit()
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert(row: dict, overwrite: bool = False) -> None:
    """按顺丰单号写入。默认不覆盖已有非空字段。
    @param {dict} row
    @param {bool} overwrite 为 True 时用新值覆盖同名字段
    """
    sf = (row.get("顺丰单号") or "").strip()
    if not sf:
        raise ValueError("缺少顺丰单号")
    conn = connect()
    existing = conn.execute(
        'SELECT * FROM shipments WHERE "顺丰单号"=?', (sf,)
    ).fetchone()
    merged = {c: None for c in ALL_COLS}
    if existing:
        merged.update(dict(existing))
    for k, v in row.items():
        if k not in merged:
            continue
        if v is None:
            continue
        if v == "" and not (overwrite and k in CLEARABLE):
            continue
        if overwrite or not merged.get(k):
            merged[k] = str(v)
    merged["顺丰单号"] = sf
    merged["updated_at"] = _now()
    if not merged.get("序号"):
        n = conn.execute("SELECT COUNT(*) FROM shipments").fetchone()[0]
        merged["序号"] = str(n + 1)
    placeholders = ",".join("?" for _ in ALL_COLS)
    colnames = ",".join(f'"{c}"' for c in ALL_COLS)
    conn.execute(
        f"INSERT OR REPLACE INTO shipments ({colnames}) VALUES ({placeholders})",
        [merged.get(c) for c in ALL_COLS],
    )
    conn.commit()
    conn.close()


def get(sf: str) -> dict | None:
    """按顺丰单号取一行。
    @param {str} sf
    @returns {dict|None}
    """
    conn = connect()
    row = conn.execute(
        'SELECT * FROM shipments WHERE "顺丰单号"=?', (sf,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def find_by_order(order: str) -> list[dict]:
    """按订单号取所有票。
    @param {str} order
    @returns {list}
    """
    conn = connect()
    rows = conn.execute(
        'SELECT * FROM shipments WHERE "订单号"=?', (order,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_all() -> list[dict]:
    """全部台账行。
    @returns {list}
    """
    conn = connect()
    rows = conn.execute(
        'SELECT * FROM shipments ORDER BY CAST("序号" AS INTEGER)'
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_trackable() -> list[dict]:
    """有国际单号且渠道可查官网的行。
    @returns {list}
    """
    rows = []
    for r in list_all():
        num = (r.get("国际单号") or "").replace(" ", "")
        carrier = r.get("快递公司") or ""
        if not num:
            continue
        if num.upper().startswith("1Z") or "UPS" in carrier or "DHL" in carrier:
            rows.append(r)
    return rows


def seen_message(message_id: str) -> bool:
    """消息是否已处理。
    @param {str} message_id
    @returns {bool}
    """
    conn = connect()
    row = conn.execute(
        "SELECT 1 FROM seen_messages WHERE message_id=?", (message_id,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_message(message_id: str) -> None:
    """记下已处理消息。
    @param {str} message_id
    """
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO seen_messages(message_id, processed_at) VALUES (?, ?)",
        (message_id, _now()),
    )
    conn.commit()
    conn.close()
