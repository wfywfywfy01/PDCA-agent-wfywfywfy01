"""运单生命周期与异常。异常可盖展示层，不回退主状态。"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta

# 主状态只允许向前。待人工权重低于已出国际单，方便面单匹配后继续走。
WEIGHTS = {
    "PENDING": 10,
    "LABELED": 20,
    "IN_TRANSIT": 30,
    "CUSTOMS": 40,
    "DELIVERED": 100,
    "RETURNED": 110,
}

DISPLAY = {
    "PENDING": "已预报",
    "LABELED": "已出国际单",
    "IN_TRANSIT": "运输中",
    "CUSTOMS": "清关中",
    "DELIVERED": "签收已确认",
    "RETURNED": "已退回至香港货代仓",
}

EXCEPTION_DISPLAY = {
    "CUSTOMS_HOLD": "海关扣关",
    "ADDRESS_ERROR": "地址错误",
    "DELIVERY_FAILED": "投递失败",
    "NO_EVENT_TIMEOUT": "超时无轨迹",
    "REVIEW": "待人工",
}

_DISPLAY_TO_LIFE = {v: k for k, v in DISPLAY.items()}
_DISPLAY_TO_LIFE["待人工"] = "PENDING"
_DISPLAY_TO_LIFE["海关扣关"] = "CUSTOMS"
_DISPLAY_TO_LIFE["地址错误"] = "IN_TRANSIT"
_DISPLAY_TO_LIFE["投递失败"] = "IN_TRANSIT"
_DISPLAY_TO_LIFE["超时无轨迹"] = "IN_TRANSIT"

DELIVERED_KEYS = ("delivered", "已签收", "投递完成", "shipment delivered")
RETURN_KEYS = ("returned", "return to sender", "退回", "return to")
HOLD_KEYS = ("customs hold", "held by customs", "扣关", "扣留", "documentation required")
ADDRESS_KEYS = ("address incorrect", "address error", "地址错误", "undeliverable")
FAIL_KEYS = ("delivery failed", "投递失败", "unsuccessful delivery")
CUSTOMS_KEYS = ("customs cleared", "released by customs", "清关完成", "customs")
TRANSIT_KEYS = ("in transit", "on the way", "departed", "arrived", "运输中")


def lifecycle_of(row: dict | None) -> str:
    """从台账行读生命周期，缺列则从签收状态反推。
    @param {dict|None} row
    @returns {str}
    """
    if not row:
        return "PENDING"
    raw = (row.get("生命周期") or "").strip()
    if raw in WEIGHTS:
        return raw
    return _DISPLAY_TO_LIFE.get((row.get("签收状态") or "").strip(), "PENDING")


def advance(old: str | None, new: str) -> str:
    """只向前推进。权重相同或更低则保持旧值。
    @param {str|None} old
    @param {str} new
    @returns {str}
    """
    prev = old if old in WEIGHTS else "PENDING"
    nxt = new if new in WEIGHTS else prev
    if WEIGHTS[nxt] > WEIGHTS[prev]:
        return nxt
    return prev


def display_status(lifecycle: str, exception: str = "") -> str:
    """展示用签收状态。异常覆盖文案，不改生命周期。
    @param {str} lifecycle
    @param {str} exception
    @returns {str}
    """
    if exception:
        return EXCEPTION_DISPLAY.get(exception, exception)
    return DISPLAY.get(lifecycle, DISPLAY["PENDING"])


def detect_exception(text: str) -> str:
    """从官网正文抽异常码，没有则空串。
    @param {str} text
    @returns {str}
    """
    low = text.lower()
    if any(k in low for k in HOLD_KEYS):
        return "CUSTOMS_HOLD"
    if any(k in low for k in ADDRESS_KEYS):
        return "ADDRESS_ERROR"
    if any(k in low for k in FAIL_KEYS):
        return "DELIVERY_FAILED"
    return ""


def lifecycle_from_text(text: str) -> str:
    """从官网正文映射生命周期。查不到当运输中。
    @param {str} text
    @returns {str}
    """
    low = text.lower()
    if any(k in low for k in DELIVERED_KEYS):
        return "DELIVERED"
    if any(k in low for k in RETURN_KEYS):
        return "RETURNED"
    if any(k in low for k in HOLD_KEYS) or any(k in low for k in CUSTOMS_KEYS):
        return "CUSTOMS"
    if "not found" in low or "no information" in low:
        return "LABELED"
    if any(k in low for k in TRANSIT_KEYS):
        return "IN_TRANSIT"
    return "IN_TRANSIT"


def event_hash(text: str) -> str:
    """轨迹摘录指纹，空白变化不重复通知。
    @param {str} text
    @returns {str}
    """
    norm = " ".join(text.lower().split())[:240]
    return hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest()[:16]


def warn_date(now: datetime | None = None) -> str:
    """首次可追踪时写入的 5 天预警日。
    @param {datetime|None} now
    @returns {str}
    """
    day = (now or datetime.now()) + timedelta(days=5)
    return f"{day.year}/{day.month}/{day.day}"


def past_warn(value: str | None, now: datetime | None = None) -> bool:
    """预警日是否已过。
    @param {str|None} value
    @param {datetime|None} now
    @returns {bool}
    """
    if not value:
        return False
    m = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", value) or re.search(
        r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})", value
    )
    if not m:
        return False
    a, b, c = m.group(1), m.group(2), m.group(3)
    try:
        if len(a) == 4:
            parsed = datetime(int(a), int(b), int(c))
        else:
            year = int(c) if len(c) == 4 else 2000 + int(c)
            parsed = datetime(year, int(a), int(b))
    except ValueError:
        return False
    stamp = now or datetime.now()
    return stamp.date() > parsed.date()


def needs_review(row: dict) -> bool:
    """C 级、待人工、未关闭异常。
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
