# 探测 mobile.activation.report 日期字段 + 两家经销商激活全貌
DEALER_DEPT_ID = 1569
start_date = params.get("start_date") or "2026-06-24"
end_date = params.get("end_date") or "2026-07-23"

fg = env["mobile.activation.report"].fields_get()
date_fields = sorted([
    k for k, v in fg.items()
    if v.get("type") in ("date", "datetime") or "date" in k.lower() or "time" in k.lower()
])

# 抽样一条看字段
sample = env["mobile.activation.report"].search_read(
    [("partner_name", "ilike", "Safiran")],
    list(fg.keys())[:40],
    limit=1,
)

records = env["mobile.activation.report"].search_read(
    [
        ("department_id", "child_of", [DEALER_DEPT_ID]),
        "|", "|",
        ("partner_name", "ilike", "Sabaek"),
        ("partner_name", "ilike", "Safiranhamrah"),
        ("partner_name", "ilike", "Safiran"),
    ],
    ["partner_name", "activation_state", "sale_date", "vsn", "product_name", "activation_country"],
)

def _d(v):
    if not v:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]

def _match(name):
    low = (name or "").lower()
    if "sabaek" in low:
        return "Dar Al Sabaek"
    if "safiran" in low:
        return "Safiranhamrah"
    return None

# 全量累计 + 近30天 sale_date
agg = {}
for r in records:
    dealer = _match(r.get("partner_name"))
    if not dealer:
        continue
    a = agg.setdefault(dealer, {
        "total": 0, "activated": 0, "not_activated": 0,
        "sale_in_30d": 0, "sale_in_30d_activated": 0,
        "activated_sale_dates": [],
        "products_activated": {},
    })
    a["total"] += 1
    sale_d = _d(r.get("sale_date"))
    state = r.get("activation_state") or ""
    if state == "activated":
        a["activated"] += 1
        if sale_d:
            a["activated_sale_dates"].append(sale_d)
        pname = r.get("product_name") or "(未知)"
        a["products_activated"][pname] = a["products_activated"].get(pname, 0) + 1
    else:
        a["not_activated"] += 1
    if sale_d and start_date <= sale_d <= end_date:
        a["sale_in_30d"] += 1
        if state == "activated":
            a["sale_in_30d_activated"] += 1

out = []
for dealer, a in agg.items():
    dates = sorted(a["activated_sale_dates"])
    products = sorted(
        [{"product": k, "activated": v} for k, v in a["products_activated"].items()],
        key=lambda x: -x["activated"],
    )[:15]
    # 近30天内「已激活」且 sale_date 在窗口
    out.append({
        "dealer": dealer,
        "lifetime_total": a["total"],
        "lifetime_activated": a["activated"],
        "lifetime_not_activated": a["not_activated"],
        "lifetime_rate": round(a["activated"] / a["total"] * 100, 1) if a["total"] else 0,
        "sale_in_30d": a["sale_in_30d"],
        "sale_in_30d_activated": a["sale_in_30d_activated"],
        "activated_sale_date_min": dates[0] if dates else None,
        "activated_sale_date_max": dates[-1] if dates else None,
        "activated_with_sale_in_30d_count": sum(1 for d in dates if start_date <= d <= end_date),
        "products_activated_top": products,
    })

ai["result"] = {
    "period": {"start": start_date, "end": end_date},
    "date_fields": date_fields,
    "sample_keys": list(sample[0].keys()) if sample else [],
    "dealers": out,
}
