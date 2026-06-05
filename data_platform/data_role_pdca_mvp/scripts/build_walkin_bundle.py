# -*- coding: utf-8 -*-
"""
生成 Walk-in/客流分析台 JSON（不读取 Excel）。

- 越南区：vietnam_store_metrics.json（越南 walk-in 真实参考）
- 其他：dealer_distribution_reference.json（代理商终销表经销商）
"""
import argparse
import json
import random
import re
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
OUT_DIR = WORKSPACE / "modules" / "walkin_cockpit" / "data"
VIETNAM_METRICS = OUT_DIR / "vietnam_store_metrics.json"
DEALER_REF = OUT_DIR / "dealer_distribution_reference.json"

StoreClass = {"CLASS_1": "Class 1", "CLASS_2": "Class 2", "A": "Class 1", "B": "Class 2", "S": "Class 2"}

SEA_COUNTRIES = frozenset(
    {
        "越南",
        "柬埔寨",
        "泰国",
        "新加坡",
        "马来西亚",
        "印尼",
        "印度尼西亚",
        "菲律宾",
        "缅甸",
        "老挝",
        "文莱",
        "印度",
    }
)


def macro_region(country):
    if (country or "").strip() in SEA_COUNTRIES:
        return "东南亚"
    return "欧洲"


def load_vietnam_reference():
    if not VIETNAM_METRICS.exists():
        return None
    return json.loads(VIETNAM_METRICS.read_text(encoding="utf-8"))


def load_dealer_reference():
    if not DEALER_REF.exists():
        raise SystemExit(
            f"缺少经销商参考数据: {DEALER_REF}\n"
            "请先运行: python scripts/import_dealer_distribution_once.py"
        )
    return json.loads(DEALER_REF.read_text(encoding="utf-8"))


def vietnam_store_for_month(ref, ym):
    if not ref:
        return None
    months = ref.get("months") or {}
    payload = months.get(ym)
    if not payload:
        return None
    store = {"id": ref.get("storeId", "vn1"), "dataSource": "vietnam_reference", **payload}
    store["name"] = payload.get("name") or "胡志明旗舰店"
    store["class"] = StoreClass.get(payload.get("class", "CLASS_1"), payload.get("class", "Class 1"))
    return store


def _rng_for(seed_text):
    seed = int(re.sub(r"\D", "", str(hash(seed_text)))[:9] or "42") % (2**31)
    return random.Random(seed)


def _tier_rates(ctype, rng):
    base = {"A": 0.46, "B": 0.38, "S": 0.33}.get(ctype, 0.35)
    touch = {"A": 0.62, "B": 0.54, "S": 0.48}.get(ctype, 0.5)
    use = {"A": 0.5, "B": 0.42, "S": 0.38}.get(ctype, 0.4)
    return (
        max(0.22, min(0.58, base + rng.uniform(-0.05, 0.05))),
        max(0.35, min(0.72, touch + rng.uniform(-0.04, 0.04))),
        max(0.28, min(0.6, use + rng.uniform(-0.04, 0.04))),
    )


def dealer_to_store(dealer, month):
    """将代理商终销行转为驾驶舱 store 结构。"""
    rng = _rng_for(f"{dealer['id']}-{month}")
    amount = float(dealer.get("sellOutAmount") or 0)
    qty = float(dealer.get("sellOutQty") or 0)
    ctype = (dealer.get("customerType") or "S").upper()[:1]
    if amount <= 0:
        tier = {"A": 1200000, "B": 650000, "S": 380000}.get(ctype, 420000)
        amount = tier * rng.uniform(0.85, 1.15)
    sales = int(amount)
    if sales < 80000:
        sales = int(80000 * rng.uniform(1.0, 1.8))
    visits = max(40, int(sales / rng.uniform(38000, 52000)))
    if qty > 0:
        visits = max(visits, int(qty * rng.uniform(8, 15)))
    add_rate, touch_rate, use_rate = _tier_rates(ctype, rng)
    anomalies = []
    if add_rate < 0.35:
        anomalies.append("留资率偏低")
    if sales < 200000 and ctype == "A":
        anomalies.append("A类产出偏弱")
    label = dealer["dealerName"]
    if dealer.get("storeName"):
        label = f"{label}（{dealer['storeName']}）"
    return {
        "id": dealer["id"],
        "name": label,
        "city": dealer.get("country") or "海外",
        "region": macro_region(dealer.get("country") or ""),
        "class": StoreClass.get(ctype, StoreClass["CLASS_2"]),
        "totalVisitGroups": visits,
        "avgAddRate": round(add_rate, 3),
        "totalSalesAmount": sales,
        "anomalies": anomalies,
        "avgTouchRate": round(touch_rate, 3),
        "avgUseRate": round(use_rate, 3),
        "dealerTeam": dealer.get("team") or "",
        "customerType": ctype,
        "dataSource": "dealer_distribution",
    }


def build_staff_for_stores(stores, month):
    staff = []
    idx = 1
    names = ["Alex", "Mina", "Omar", "Sara", "Li", "Chen", "Kim", "Noah"]
    for store in stores:
        rng = _rng_for(f"staff-{store['id']}-{month}")
        headcount = 2 if store["totalSalesAmount"] < 500000 else (3 if store["totalSalesAmount"] < 1200000 else 4)
        per_sales = store["totalSalesAmount"] / headcount
        per_groups = max(6, store["totalVisitGroups"] // headcount)
        for j in range(headcount):
            sid = f"{store['id']}-S{idx}"
            idx += 1
            sales = int(per_sales * rng.uniform(0.75, 1.25))
            add_rate = max(0.2, min(0.55, store["avgAddRate"] + rng.uniform(-0.08, 0.08)))
            anomalies = []
            if sales < 60000:
                anomalies.append("低客单价预警")
            if add_rate < 0.3:
                anomalies.append("低添加率")
            staff.append({
                "id": sid,
                "name": names[(idx + j) % len(names)] + str(j + 1),
                "storeId": store["id"],
                "workingDays": int(rng.randint(18, 23)),
                "monthlySales": sales,
                "threeMonthTrend": [int(sales * 0.9), int(sales * 0.95), sales],
                "addRate": round(add_rate, 3),
                "visitGroups": max(4, int(per_groups * rng.uniform(0.85, 1.15))),
                "avgAov": int(sales / max(1, per_groups // 2)),
                "crmReachRate": round(min(0.99, 0.55 + add_rate), 2),
                "anomalies": anomalies,
            })
    return staff


def build_bundle(vn_ref, dealer_ref, ym):
    stores = []
    vietnam = vietnam_store_for_month(vn_ref, ym)
    if vietnam:
        stores.append(vietnam)
    for dealer in dealer_ref.get("dealers") or []:
        if vietnam and dealer.get("region") == "越南区" and "越南" in (dealer.get("country") or ""):
            continue
        stores.append(dealer_to_store(dealer, ym))
    staff = build_staff_for_stores(stores, ym)
    regions = sorted({s["region"] for s in stores})
    return {
        "meta": {
            "month": ym,
            "periodLabel": ym,
            "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "vietnam_reference+dealer_distribution",
            "vietnamStore": vietnam["name"] if vietnam else None,
            "storeCount": len(stores),
            "dealerCount": len(dealer_ref.get("dealers") or []),
            "regionOrder": regions,
        },
        "stores": stores,
        "staff": staff,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="", help="YYYY-MM，默认生成全部越南参考月份 + 当前月")
    args = parser.parse_args()
    vn_ref = load_vietnam_reference()
    dealer_ref = load_dealer_reference()
    months = sorted(set((vn_ref or {}).get("months", {}).keys()) | {args.month} if args.month else [])
    if not months:
        months = [datetime.now().strftime("%Y-%m")]
    if args.month:
        months = [args.month]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ym in months:
        bundle = build_bundle(vn_ref, dealer_ref, ym)
        out = OUT_DIR / f"walkin-{ym}.json"
        out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print("written", out, "stores", len(bundle["stores"]), "staff", len(bundle["staff"]))


if __name__ == "__main__":
    main()
