# Dar / Safiran 近30天激活明细 + vsn.index 匹配 IMEI
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

STATE_LABEL = {"activated": "已激活", "not_activated": "未激活"}

vsns = sorted({(r.get("vsn") or "").strip() for r in records if (r.get("vsn") or "").strip()})
imei_map = {}
if vsns:
    # Odoo domain OR chain for many VSNs
    domain = [("vsn", "in", vsns)]
    idx_rows = env["vsn.index"].search_read(domain, ["vsn", "imei1", "imei2", "meid"], limit=5000)
    for x in idx_rows:
        v = (x.get("vsn") or "").strip()
        if v and v not in imei_map:
            imei_map[v] = {
                "imei1": x.get("imei1") or "",
                "imei2": x.get("imei2") or "",
                "meid": x.get("meid") or "",
            }

rows = []
matched = 0
for r in records:
    dealer = _match(r.get("partner_name"))
    if not dealer:
        continue
    vsn = (r.get("vsn") or "").strip()
    imei = imei_map.get(vsn) or {}
    if imei.get("imei1") or imei.get("imei2"):
        matched += 1
    rows.append({
        "国家": _m2o_name(r.get("private_country_id")),
        "销售单号": r.get("sale_order_number") or "",
        "销售日期": _d(r.get("sale_date"), 10),
        "销售员": _m2o_name(r.get("salesperson")),
        "销售部门": _m2o_name(r.get("department_id")),
        "客户名称": (r.get("partner_name") or "").strip(),
        "货品名称": r.get("product_name") or "",
        "VSN": vsn,
        "IMEI1": imei.get("imei1") or "",
        "IMEI2": imei.get("imei2") or "",
        "激活状态": STATE_LABEL.get(r.get("activation_state") or "", r.get("activation_state") or ""),
        "激活时间": _d(r.get("activation_time"), 19).replace("T", " "),
        "激活国家": r.get("activation_country") or "",
        "激活城市": r.get("activation_city") or "",
        "_dealer_key": dealer,
    })

ai["result"] = {
    "period": {"start": start_date, "end": end_date},
    "count": len(rows),
    "vsn_count": len(vsns),
    "imei_matched": matched,
    "rows": rows,
}
