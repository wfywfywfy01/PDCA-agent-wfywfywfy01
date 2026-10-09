# -*- coding: utf-8 -*-
"""《海外渠道每日销售汇报模板》合规检查。

老板 2026-09-30 定版模板（15:00 快报 / 20:00 汇总通用），团队按这份模板发日报，
督战官不再只看「交没交」，还要按模板核对必填项：

    基础信息（日期 / 时段 / 负责人 / 负责市场客户）
    分市场进度（每个客户：订单% + 回款% + USD 金额）
    卡点（客户 + 卡点 + 需要谁支持 + 期望完成时间）
    明日重点（20:00 档必填，且不能写「继续跟进」这类空话）

三条原则：
1. 全部确定性判断（正则 + 计数），不调大模型，不猜；
2. 只报「缺什么」，不替人下结论说没干活；
3. 「读不到」与「没交」在调用侧区分，本模块只判断拿到的文本。
"""
from __future__ import annotations

import re
import unicodedata

#: 判定为「空话」的明日重点写法（模板填写要求第 3 条）
EMPTY_TALK = (
    "继续跟进",
    "持续跟进",
    "继续推进",
    "正常推进",
    "保持跟进",
    "跟进中",
    "继续努力",
    "加强沟通",
    "持续推进",
    "待定",
    "tbd",
)

#: 15:00 档只要分市场进度 + 卡点；20:00 档要完整版
_SLOT_15 = "15:00"
_SLOT_20 = "20:00"

_DATE_RE = re.compile(r"(20\d{2}\s*[-/年.]\s*\d{1,2}\s*[-/月.]\s*\d{1,2})|(\d{1,2}\s*月\s*\d{1,2}\s*日)")
_USD_RE = re.compile(r"(?:USD|US\$|\$|美元)\s*[:：]?\s*[\d,，]+(?:\.\d+)?", re.I)
_ORDER_PCT_RE = re.compile(r"订单[^%\n]{0,16}(\d{1,3})\s*%")
_CASH_PCT_RE = re.compile(r"回款[^%\n]{0,16}(\d{1,3})\s*%")
_OWNER_RE = re.compile(r"负责人\s*[:：]?\s*([^\n|]{1,40})")
_MARKET_RE = re.compile(r"(负责市场|负责客户|所辖市场|负责区域)\s*[:：/]?\s*([^\n|]{0,60})")
_CUSTOMER_RE = re.compile(r"(▍|【[^】]{1,30}】|^\s*客户\s*[:：]|^\s*\d+[、.．]\s*\S)", re.M)
_BLOCKER_HEAD_RE = re.compile(r"卡点|blocker", re.I)
_NO_BLOCKER_RE = re.compile(r"(无卡点|暂无卡点|没有卡点|无\s*blockers?|no\s*blockers?)", re.I)
_TOMORROW_HEAD_RE = re.compile(r"(明日重点|明日工作|明日计划|明天重点|下一步工作)")
_SLOT_15_RE = re.compile(r"15\s*[:：]\s*00|15\s*点|下午\s*3\s*点")
_SLOT_20_RE = re.compile(r"20\s*[:：]\s*00|20\s*点|晚上\s*8\s*点|晚\s*8\s*点")
_DEADLINE_RE = re.compile(r"(\d{1,2}\s*月\s*\d{1,2}\s*日|\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2}|本周|下周|明天|today|tomorrow|this\s*week|next\s*week)", re.I)
_PLACEHOLDER_RE = re.compile(r"^[_\-—…\s]*$")


def normalize(text: str) -> str:
    """全角转半角 + 统一换行；模板会被人手改写，先归一化再判断。"""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for ch in raw:
        if ch == "\n":
            out.append(ch)
            continue
        code = ord(ch)
        if code == 0x3000:
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return unicodedata.normalize("NFKC", "".join(out))


def _clean(value: str) -> str:
    """去掉下划线占位、模板里的方括号说明。"""
    text = str(value or "").strip().strip("|").strip()
    text = re.sub(r"[（(][^）)]{0,20}(可选|示例|勾选)[^）)]{0,20}[）)]", "", text)
    return text.strip()


def _is_blank(value: str) -> bool:
    text = _clean(value)
    return not text or bool(_PLACEHOLDER_RE.match(text))


def detect_slot(text: str) -> str:
    """识别这份日报标的是哪个时段；都没标返回空串。"""
    body = normalize(text)
    has20 = bool(_SLOT_20_RE.search(body))
    has15 = bool(_SLOT_15_RE.search(body))
    if has20:
        return _SLOT_20
    if has15:
        return _SLOT_15
    return ""


def _section(text: str, head: re.Pattern[str]) -> str:
    """截出某个标题到下一个同级标题之间的正文。"""
    lines = text.split("\n")
    start = None
    for index, line in enumerate(lines):
        if head.search(line):
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if re.match(r"^\s*#{1,4}\s*\S", line) and not head.search(line):
            break
        collected.append(line)
    return "\n".join(collected)


def _blocker_rows(section: str) -> list[list[str]]:
    """只认 4 列都填了的表格行；短横线分隔行不算。"""
    rows: list[list[str]] = []
    for line in section.split("\n"):
        if line.count("|") < 4:
            continue
        cells = [_clean(cell) for cell in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        if all(re.fullmatch(r":?-{2,}:?", cell or "-") for cell in cells if cell):
            continue
        if _is_blank("".join(cells)):
            continue
        rows.append(cells)
    return rows


def _tomorrow_items(section: str) -> tuple[int, int]:
    """返回（有效条数, 空话条数）。"""
    good = empty = 0
    for line in section.split("\n"):
        text = _clean(re.sub(r"^\s*\d+[、.．)]?\s*", "", line))
        if _is_blank(text) or re.fullmatch(r"[-*•]?\s*", text):
            continue
        lowered = text.lower()
        if len(text) <= 12 and any(token in lowered for token in EMPTY_TALK):
            empty += 1
            continue
        if any(token in lowered for token in EMPTY_TALK) and len(text) <= 20:
            empty += 1
            continue
        good += 1
    return good, empty


def check_template(text: str, *, submitter: str = "") -> dict:
    """按模板核对一份日报，返回缺项清单与结论（不抛异常）。

    @param text 该人当日日报正文（卡片字段 + 群消息正文合并后的文本）
    @param submitter 已知提交人（卡片里有名字时传进来，避免「负责人未填」误报）
    @returns {"ok", "slot", "missing": [...], "customers", "blockers", "tomorrow", "empty_talk"}
    """
    body = normalize(text)
    missing: list[str] = []

    # 一、基础信息
    if not _DATE_RE.search(body):
        missing.append("日期")
    slot = detect_slot(body)
    if not slot:
        missing.append("时段(15:00/20:00)")
    owner_match = _OWNER_RE.search(body)
    owner_value = owner_match.group(1) if owner_match else ""
    if _is_blank(owner_value) and not str(submitter or "").strip():
        missing.append("负责人")
    market_match = _MARKET_RE.search(body)
    market_value = market_match.group(2) if market_match else ""
    if _is_blank(market_value):
        missing.append("负责市场/客户")

    # 二、分市场进度
    customers = len(_CUSTOMER_RE.findall(body))
    if customers == 0:
        missing.append("分市场客户段落")
    if not _ORDER_PCT_RE.search(body):
        missing.append("订单进度百分比")
    if not _CASH_PCT_RE.search(body):
        missing.append("回款进度百分比")
    if not _USD_RE.search(body):
        missing.append("USD 金额")

    # 三、卡点（15:00 / 20:00 都要）
    blocker_section = _section(body, _BLOCKER_HEAD_RE)
    if not blocker_section and not _BLOCKER_HEAD_RE.search(body):
        missing.append("卡点章节")
        blockers = 0
    elif _NO_BLOCKER_RE.search(body):
        blockers = 0
    else:
        rows = _blocker_rows(blocker_section)
        if not rows:
            missing.append("卡点内容")
            blockers = 0
        else:
            blockers = len(rows)
            if any(_is_blank(row[2]) for row in rows):
                missing.append("卡点需要谁支持")
            if any(_is_blank(row[3]) for row in rows):
                missing.append("卡点期望完成时间")
            elif not any(_DEADLINE_RE.search(row[3]) for row in rows):
                missing.append("卡点期望完成时间")

    # 四、明日重点（20:00 档必填；15:00 快报可以不写）
    tomorrow_section = _section(body, _TOMORROW_HEAD_RE)
    good, empty_talk = _tomorrow_items(tomorrow_section)
    tomorrow = good
    if slot in (_SLOT_20, ""):
        if good == 0:
            missing.append("明日重点")
        elif empty_talk:
            missing.append("明日重点(空话)")

    return {
        "ok": not missing,
        "slot": slot,
        "missing": missing,
        "customers": customers,
        "blockers": blockers,
        "tomorrow": tomorrow,
        "empty_talk": empty_talk,
    }


def looks_like_report(text: str) -> bool:
    """这段文本像不像一份日报正文（避免把群里的闲聊当成日报）。

    判定只要满足一条：
    1. 有日期 + 时段标记（15:00 / 20:00）；
    2. 正文够长，且同时出现订单/回款进度百分比与卡点字样。
    """
    body = normalize(text)
    if not body.strip():
        return False
    if _DATE_RE.search(body) and (_SLOT_15_RE.search(body) or _SLOT_20_RE.search(body)):
        return True
    if len(body) >= 120 and (_ORDER_PCT_RE.search(body) or _CASH_PCT_RE.search(body)) and _BLOCKER_HEAD_RE.search(body):
        return True
    return False


def summarize(verdict: dict, *, lang: str = "zh") -> str:
    """把结论压成一句话，给群文案用。"""
    if not verdict:
        return "pending" if lang == "en" else "待确认"
    missing = list(verdict.get("missing") or [])
    if verdict.get("ok"):
        return "template ok" if lang == "en" else "模板合规"
    if lang == "en":
        return "missing " + ", ".join(missing[:4])
    return "缺 " + "、".join(missing[:4]) + ("…" if len(missing) > 4 else "")
