# 近30天：按 activation_time 统计 Dar Al Sabaek / Safiranhamrah 手机激活
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
        "salesperson", "sale_order_number",
    ],
)

def _d(v, n=10):
    if not v:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:n]
    return str(v)[:n]

def _match(name):
    low = (name or "").lower()
    if "sabaek" in low:
        return "Dar Al Sabaek"
    if "safiran" in low:
        return "Safiranhamrah"
    return None

by = {}
detail = []
for r in records:
    dealer = _match(r.get("partner_name"))
    if not dealer:
        continue
    act_t = _d(r.get("activation_time"), 19)
    act_d = act_t[:10]
    sale_d = _d(r.get("sale_date"))
    product = r.get("product_name") or "(未知)"
    row = {
        "dealer": dealer,
        "partner_name": (r.get("partner_name") or "").strip(),
        "vsn": r.get("vsn") or "",
        "product_name": product,
        "sale_date": sale_d,
        "activation_time": act_t,
        "activation_country": r.get("activation_country") or "",
        "activation_city": r.get("activation_city") or "",
        "salesperson": r.get("salesperson") or "",
        "sale_order_number": r.get("sale_order_number") or "",
    }
    detail.append(row)
    a = by.setdefault(dealer, {"dealer": dealer, "activated": 0, "products": {}, "days": {}})
    a["activated"] += 1
    a["products"][product] = a["products"].get(product, 0) + 1
    a["days"][act_d] = a["days"].get(act_d, 0) + 1

summaries = []
for name in ("Dar Al Sabaek", "Safiranhamrah"):
    a = by.get(name)
    if not a:
        summaries.append({"dealer": name, "activated": 0, "products": [], "daily": []})
        continue
    products = sorted(
        [{"product": k, "activated": v} for k, v in a["products"].items()],
        key=lambda x: -x["activated"],
    )
    daily = [{"date": k, "activated": v} for k, v in sorted(a["days"].items())]
    summaries.append({
        "dealer": name,
        "activated": a["activated"],
        "products": products,
        "daily": daily,
    })

detail.sort(key=lambda x: (x["dealer"], x["activation_time"], x["product_name"]))

ai["result"] = {
    "period": {
        "start": start_date,
        "end": end_date,
        "note": "按 activation_time 落入近30天，且 activation_state=activated",
    },
    "total_activated": len(detail),
    "summary": summaries,
    "detail": detail,
}
