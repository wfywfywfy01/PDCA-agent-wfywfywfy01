# 近30天：Dar Al Sabaek / Safiranhamrah 手机激活
# 数据源：mobile.activation.report
# params: {"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}

DEALER_DEPT_ID = 1569
start_date = params.get("start_date") or "2026-06-24"
end_date = params.get("end_date") or fields.Date.today().strftime("%Y-%m-%d")

records = env["mobile.activation.report"].search_read(
    [
        ("department_id", "child_of", [DEALER_DEPT_ID]),
        "|", "|", "|",
        ("partner_name", "ilike", "Dar Al Sabaek"),
        ("partner_name", "ilike", "Sabaek"),
        ("partner_name", "ilike", "Safiranhamrah"),
        ("partner_name", "ilike", "Safiran"),
    ],
    [
        "partner_name", "activation_state", "sale_date", "vsn", "product_name",
        "activation_country", "private_country_id",
    ],
)

def _d(v):
    if not v:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()[:10]
    return str(v)[:10]

def _match_dealer(name):
    n = (name or "").strip()
    low = n.lower()
    if "sabaek" in low or "dar al" in low:
        return "Dar Al Sabaek"
    if "safiran" in low:
        return "Safiranhamrah"
    return n

window_rows = []
all_count = {"Dar Al Sabaek": 0, "Safiranhamrah": 0}
for r in records:
    dealer = _match_dealer(r.get("partner_name"))
    if dealer not in ("Dar Al Sabaek", "Safiranhamrah"):
        continue
    all_count[dealer] = all_count.get(dealer, 0) + 1
    sale_d = _d(r.get("sale_date"))
    row = {
        "dealer": dealer,
        "partner_name": (r.get("partner_name") or "").strip(),
        "vsn": r.get("vsn") or "",
        "product_name": r.get("product_name") or "",
        "activation_state": r.get("activation_state") or "",
        "sale_date": sale_d,
        "activation_country": r.get("activation_country") or "",
    }
    if sale_d and start_date <= sale_d <= end_date:
        window_rows.append(row)

by_dealer = {}
for row in window_rows:
    d = by_dealer.setdefault(row["dealer"], {
        "dealer": row["dealer"],
        "shipped": 0,
        "activated": 0,
        "not_activated": 0,
        "products": {},
    })
    d["shipped"] += 1
    if row["activation_state"] == "activated":
        d["activated"] += 1
    else:
        d["not_activated"] += 1
    pname = row["product_name"] or "(未知)"
    p = d["products"].setdefault(pname, {"product": pname, "shipped": 0, "activated": 0})
    p["shipped"] += 1
    if row["activation_state"] == "activated":
        p["activated"] += 1

summaries = []
for name in ("Dar Al Sabaek", "Safiranhamrah"):
    d = by_dealer.get(name)
    if not d:
        summaries.append({
            "dealer": name,
            "shipped": 0,
            "activated": 0,
            "not_activated": 0,
            "activation_rate": 0,
            "products": [],
            "all_time_matched": all_count.get(name, 0),
        })
        continue
    products = sorted(d["products"].values(), key=lambda x: -x["activated"])
    summaries.append({
        "dealer": d["dealer"],
        "shipped": d["shipped"],
        "activated": d["activated"],
        "not_activated": d["not_activated"],
        "activation_rate": round(d["activated"] / d["shipped"] * 100, 1) if d["shipped"] else 0,
        "products": products[:20],
        "all_time_matched": all_count.get(name, 0),
    })

activated_detail = [r for r in window_rows if r["activation_state"] == "activated"]
activated_detail.sort(key=lambda x: (x["dealer"], x["sale_date"] or "", x["product_name"]))

# 按日汇总激活数
by_day = {}
for r in activated_detail:
    key = (r["dealer"], r["sale_date"])
    by_day[key] = by_day.get(key, 0) + 1
daily = [
    {"dealer": k[0], "sale_date": k[1], "activated": v}
    for k, v in sorted(by_day.items())
]

ai["result"] = {
    "period": {
        "start": start_date,
        "end": end_date,
        "note": "口径：sale_date 落入近30天的出货记录中，activation_state=activated 计为已激活",
    },
    "summary": summaries,
    "daily_activated": daily,
    "activated_detail": activated_detail,
}
