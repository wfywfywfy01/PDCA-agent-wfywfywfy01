# Dar Al Sabaek / Safiranhamrah 近30天激活明细（对齐 CLICK TECH SERVICES 激活情况.xlsx）
DEALER_DEPT_ID = 1569
start_date = params.get("start_date") or "2026-06-24"
end_date = params.get("end_date") or "2026-07-23"

records = env["mobile.activation.report"].search_read(
    [
        ("department_id", "child_of", [DEALER_DEPT_ID]),
        ("activation_state", "=", "activated"),
        ("activation_time", ">=", start_date),
        ("activation_time", "<=", end_date + " 23:59:59"),
        "|", "|",
        ("partner_name", "ilike", "Sabaek"),
        ("partner_name", "ilike", "Safiranhamrah"),
        ("partner_name", "ilike", "Safiran"),
    ],
    [
        "partner_name", "activation_state", "sale_date", "activation_time",
        "vsn", "product_name", "activation_country", "activation_city",
        "salesperson", "sale_order_number", "department_id", "private_country_id",
    ],
    order="activation_time desc",
)

def _d(v, n=19):
    if not v:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:n]
    return str(v)[:n]

def _m2o_name(v):
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return v[1] or ""
    return v or ""

def _match(name):
    low = (name or "").lower()
    if "sabaek" in low:
        return "Dar Al Sabaek"
    if "safiran" in low:
        return "Safiranhamrah"
    return None

STATE_LABEL = {
    "activated": "已激活",
    "not_activated": "未激活",
}

rows = []
for r in records:
    dealer = _match(r.get("partner_name"))
    if not dealer:
        continue
    rows.append({
        "国家": _m2o_name(r.get("private_country_id")),
        "销售单号": r.get("sale_order_number") or "",
        "销售日期": _d(r.get("sale_date"), 10),
        "销售员": _m2o_name(r.get("salesperson")),
        "销售部门": _m2o_name(r.get("department_id")),
        "客户名称": (r.get("partner_name") or "").strip(),
        "货品名称": r.get("product_name") or "",
        "VSN": r.get("vsn") or "",
        "激活状态": STATE_LABEL.get(r.get("activation_state") or "", r.get("activation_state") or ""),
        "激活时间": _d(r.get("activation_time"), 19).replace("T", " "),
        "激活国家": r.get("activation_country") or "",
        "激活城市": r.get("activation_city") or "",
        "_dealer_key": dealer,
    })

ai["result"] = {
    "period": {"start": start_date, "end": end_date},
    "count": len(rows),
    "rows": rows,
}
