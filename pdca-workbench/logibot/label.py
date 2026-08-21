"""从国际面单图/PDF 抽 Invoice 和国际单号。"""

from __future__ import annotations

import difflib
import re
from datetime import datetime
from pathlib import Path

from db import find_by_order, list_all, upsert

UPS_RE = re.compile(r"1Z[\sA-Z0-9]{16,24}", re.I)
INVOICE_RE = re.compile(r"X[S58]D[-A-Z0-9]*\d+", re.I)
DHL_RE = re.compile(r"\b(\d{10,11})\b")
LABEL_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf"}
SKIP_RECV = ("SHIPTO", "SHIP TO", "TRACKING", "INVOICE", "DESC", "UPS EXPRESS", "DHL")


def _norm_ups(text: str) -> str:
    compact = re.sub(r"[^A-Z0-9]", "", text.upper())
    m = re.search(r"1Z[A-Z0-9]{16}", compact)
    return m.group(0) if m else compact


def _fix_invoice(raw: str | None, orders: list[str]) -> tuple[str | None, str]:
    """OCR 纠错：X5D→XSD，再和已有订单号模糊对齐。
    @param {str|None} raw
    @param {list} orders
    @returns {tuple} (订单号, exact|fuzzy|raw)
    """
    if not raw:
        return None, "none"
    cand = re.sub(r"^X[S58]D", "XSD", raw.upper())
    known = [o for o in orders if o]
    if cand in known:
        return cand, "exact"
    hit = difflib.get_close_matches(cand, known, n=1, cutoff=0.82)
    if hit:
        return hit[0], "fuzzy"
    return cand, "raw"


def _norm_name(value: str | None) -> str:
    """收件人比对用：小写去空白标点。
    @param {str|None} value
    @returns {str}
    """
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (value or "").lower())


_OCR = None


def ocr_text(path: Path) -> str:
    """OCR 面单。PDF 无字则当图读。
    @param {Path} path
    @returns {str}
    """
    global _OCR
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            text = "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)
            if text.strip():
                return text
        except Exception:
            pass
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError("缺少 rapidocr-onnxruntime，先 pip install -r requirements.txt") from exc
    if _OCR is None:
        _OCR = RapidOCR()
    result, _ = _OCR(str(path))
    if not result:
        return ""
    lines = []
    for item in result:
        if isinstance(item, (list, tuple)) and len(item) > 1:
            lines.append(str(item[1]))
        elif isinstance(item, dict) and "text" in item:
            lines.append(str(item["text"]))
    return "\n".join(lines)


def parse_label_text(text: str, orders: list[str] | None = None) -> dict:
    """从 OCR 文本抽单号。
    @param {str} text
    @param {list|None} orders 已有订单号，用于模糊对齐 Invoice
    @returns {dict}
    """
    blob = text.replace(" ", "")
    invoice = None
    invoice_quality = "none"
    m = INVOICE_RE.search(blob) or INVOICE_RE.search(text)
    if m:
        invoice, invoice_quality = _fix_invoice(m.group(0), orders or [])
    tracking = None
    carrier = None
    ups = UPS_RE.search(text)
    if ups:
        tracking = _norm_ups(ups.group(0))
        carrier = "UPS"
    elif "DHL" in text.upper():
        for hit in DHL_RE.findall(text):
            if hit.startswith("86"):
                continue
            tracking = hit
            carrier = "DHL"
            break
    recipient = None
    for line in text.splitlines():
        u = line.upper().replace(" ", "")
        if any(s.replace(" ", "") in u for s in SKIP_RECV):
            continue
        if re.search(r"[A-Za-z]{3,}", line):
            recipient = line.strip()
            break
    return {
        "invoice": invoice,
        "invoice_quality": invoice_quality,
        "tracking": tracking,
        "carrier": carrier,
        "recipient": recipient,
        "desc": None,
        "raw": text,
    }


def _score_row(parsed: dict, row: dict) -> tuple[int, list[str]]:
    """A/B/C 证据分。Invoice 全等 100，收件人/国家各 +8。
    @param {dict} parsed
    @param {dict} row
    @returns {tuple}
    """
    evidence: list[str] = []
    score = 0
    invoice = (parsed.get("invoice") or "").upper()
    order = (row.get("订单号") or "").upper()
    sysno = (row.get("共建销售单号/系统单号") or "").upper()
    if invoice and invoice in (order, sysno):
        score = 100
        quality = parsed.get("invoice_quality") or "exact"
        evidence.append("invoice_fuzzy" if quality == "fuzzy" else "order_no_exact")
    recv = _norm_name(parsed.get("recipient"))
    have = _norm_name(row.get("境外收货人"))
    if recv and have and (recv in have or have in recv):
        score += 8
        evidence.append("consignee_match")
    country = (row.get("目的地") or "").strip().lower()
    raw = (parsed.get("raw") or "").lower()
    if country and country in raw:
        score += 8
        evidence.append("country_match")
    return score, evidence


def _level_of(score: int, quality: str, unique: bool) -> str:
    """A 全等唯一；B 模糊或收件人加持；其余 C。
    @param {int} score
    @param {str} quality
    @param {bool} unique
    @returns {str}
    """
    if not unique:
        return "C"
    if quality == "fuzzy":
        return "B"
    if score >= 100:
        return "A"
    if score >= 8:
        return "B"
    return "C"


def _mark_conflict(pool: list[dict], evidence: list[str]) -> None:
    """一对多写入 C 级待人工。
    @param {list} pool
    @param {list} evidence
    """
    note = "面单一对多未匹配"
    for r in pool:
        remark = r.get("备注") or ""
        if note not in remark:
            remark = (remark + ";" + note).strip(";")
        upsert(
            {
                "顺丰单号": r["顺丰单号"],
                "签收状态": "待人工",
                "匹配级别": "C",
                "匹配证据": ",".join(evidence or ["candidate_conflict"]),
                "备注": remark,
            },
            overwrite=True,
        )


def _pick_row(parsed: dict) -> tuple[dict | None, str, list[str]]:
    """Invoice=订单号 匹配；多票再比收货人/国家。
    @param {dict} parsed
    @returns {tuple} (行, 级别, 证据)
    """
    invoice = parsed.get("invoice")
    if not invoice:
        return None, "C", ["missing_invoice"]
    cands = [r for r in find_by_order(invoice) if r]
    if not cands:
        cands = [
            r
            for r in list_all()
            if (r.get("订单号") or "").upper() == invoice.upper()
            or (r.get("共建销售单号/系统单号") or "").upper() == invoice.upper()
        ]
    unmatched = [r for r in cands if not r.get("国际单号")]
    pool = unmatched or cands
    quality = parsed.get("invoice_quality") or "raw"
    if len(pool) == 1:
        score, evidence = _score_row(parsed, pool[0])
        return pool[0], _level_of(score, quality, True), evidence or ["order_no_exact"]
    if len(pool) > 1:
        scored = []
        for r in pool:
            score, evidence = _score_row(parsed, r)
            scored.append((score, evidence, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[0]
        second = scored[1] if len(scored) > 1 else None
        if top[0] > 0 and (second is None or top[0] > second[0]):
            return top[2], _level_of(top[0], quality, True), top[1] + ["split_tiebreak"]
        _mark_conflict(pool, ["candidate_conflict"])
        return None, "C", ["candidate_conflict"]
    return None, "C", ["order_not_found"]


def ingest_label(path: str | Path) -> dict:
    """解析一张面单并回填国际单号。
    @param {str} path
    @returns {dict}
    """
    path = Path(path)
    text = ocr_text(path)
    orders = [r.get("订单号") or "" for r in list_all()]
    orders += [r.get("共建销售单号/系统单号") or "" for r in list_all()]
    parsed = parse_label_text(text, orders)
    parsed["file"] = str(path)
    row, level, evidence = _pick_row(parsed)
    parsed["匹配级别"] = level
    parsed["匹配证据"] = ",".join(evidence)
    if not parsed.get("tracking"):
        parsed["status"] = "无国际单号"
        return parsed
    if not row:
        parsed["status"] = "未匹配订单"
        return parsed
    from status import advance, display_status, lifecycle_of

    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    life = advance(lifecycle_of(row), "LABELED")
    patch = {
        "顺丰单号": row["顺丰单号"],
        "国际单号": parsed["tracking"],
        "出面单时间": now,
        "面单文件": str(path),
        "生命周期": life,
        "签收状态": display_status(life, row.get("异常") or ""),
        "匹配级别": level,
        "匹配证据": ",".join(evidence),
    }
    if parsed.get("carrier"):
        patch["快递公司"] = parsed["carrier"]
    if parsed.get("recipient") and not row.get("境外收货人"):
        patch["境外收货人"] = parsed["recipient"]
    upsert(patch, overwrite=True)
    parsed["status"] = "已匹配"
    parsed["顺丰单号"] = row["顺丰单号"]
    parsed["订单号"] = row.get("订单号")
    return parsed


def ingest_label_dir(dir_path: str | Path) -> list[dict]:
    """处理目录下全部面单。
    @param {str} dir_path
    @returns {list}
    """
    folder = Path(dir_path)
    results = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() in LABEL_EXTS:
            results.append(ingest_label(p))
    return results
