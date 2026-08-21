# -*- coding: utf-8 -*-
"""
海外经销商周报取数：总览 + 产品明细 + 双重归口。

口径：
  - dealer_owner（主/OKR）：按 dealers.json 经销商归属销售 → 汇报组
  - ppt（对齐 PPT 组数）：dealer_owner − non_team 记名（如郑丽苹）
  - salesperson_aligned（个人贡献）：按 odoo「销售人员」映射到团队成员

用法:
  py fetch_overview.py
  py fetch_overview.py --as-of 2026-07-12
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "dealers.json"
OUTPUT_DIR = ROOT / "outputs"
SANDBOX_PATH = ROOT / "scripts" / "_sandbox_overview.py"
GROUP_ORDER = ["Lina组", "于冰组", "杨晶晶组"]


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="海外经销商周报总览+产品明细取数")
    parser.add_argument("--week-start", default="", help="周起始 YYYY-MM-DD")
    parser.add_argument("--week-end", default="", help="周结束 YYYY-MM-DD")
    parser.add_argument("--as-of", default="", help="截止日期，默认今天")
    return parser.parse_args()


def resolve_window(args: argparse.Namespace) -> dict:
    """解析本周、本月、环比、同比窗口。"""
    if args.as_of:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    else:
        as_of = date.today()

    if args.week_start and args.week_end:
        week_start = datetime.strptime(args.week_start, "%Y-%m-%d").date()
        week_end = datetime.strptime(args.week_end, "%Y-%m-%d").date()
    else:
        week_start = as_of - timedelta(days=as_of.weekday())
        week_end = week_start + timedelta(days=6)

    month_start = date(as_of.year, as_of.month, 1)
    mtd_end = min(as_of, week_end)

    if as_of.month == 1:
        prev_month_start = date(as_of.year - 1, 12, 1)
        try:
            prev_month_end = date(as_of.year - 1, 12, mtd_end.day)
        except ValueError:
            prev_month_end = date(as_of.year, 1, 1) - timedelta(days=1)
    else:
        prev_month_start = date(as_of.year, as_of.month - 1, 1)
        try:
            prev_month_end = date(as_of.year, as_of.month - 1, mtd_end.day)
        except ValueError:
            prev_month_end = month_start - timedelta(days=1)

    yoy_start = date(as_of.year - 1, as_of.month, 1)
    try:
        yoy_end = date(as_of.year - 1, as_of.month, mtd_end.day)
    except ValueError:
        yoy_end = date(as_of.year - 1, as_of.month + 1, 1) - timedelta(days=1)

    iso = week_start.isocalendar()
    return {
        "as_of": as_of.isoformat(),
        "week_label": f"{iso.year}-W{iso.week:02d}",
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "month": f"{as_of.year}-{as_of.month:02d}",
        "mtd_start": month_start.isoformat(),
        "mtd_end": mtd_end.isoformat(),
        "prev_month_start": prev_month_start.isoformat(),
        "prev_month_end": prev_month_end.isoformat(),
        "yoy_start": yoy_start.isoformat(),
        "yoy_end": yoy_end.isoformat(),
    }


def build_case_sql(dealers: list[dict]) -> str:
    """把代理商 match 关键字拼成 SQL CASE。"""
    cases = []
    for d in dealers:
        ors = " OR ".join(
            [f"\"客户名称\" ILIKE '%{m.replace(chr(39), chr(39) + chr(39))}%'" for m in d["match"]]
        )
        label = d["name"].replace("'", "''")
        cases.append(f"WHEN ({ors}) THEN '{label}'")
    return "CASE\n" + "\n".join(cases) + "\nELSE NULL\nEND"


def write_sandbox(dealers: list[dict], window: dict) -> None:
    """生成沙箱脚本：行级（经销商×销售人员×产品）聚合。"""
    case_sql = build_case_sql(dealers)
    template = r'''# 海外经销商周报取数（自动生成，含销售人员）
CASE_SQL = """__CASE_SQL__"""

def attributed_rows(start, end):
    sql = (
        "SELECT (" + CASE_SQL + ") AS dealer_name, "
        "COALESCE(\"销售人员\", '') AS salesperson, "
        "COALESCE(\"商品大类\", '未分类') AS major, "
        "COALESCE(\"商品细类\", '未分类') AS series, "
        "SUM(COALESCE(\"实际金额\", 0)) AS amount, "
        "COUNT(*) AS lines, "
        "COUNT(DISTINCT \"原订单号\") AS orders "
        "FROM odoo_sale "
        "WHERE \"销售日期\" >= '" + start + "' "
        "AND \"销售日期\" <= '" + end + " 23:59:59' "
        "AND (" + CASE_SQL + ") IS NOT NULL "
        "GROUP BY 1, 2, 3, 4 "
        "ORDER BY amount DESC"
    )
    return sql_read(sql)

result = {}
windows = {
  "week": ("__WEEK_START__", "__WEEK_END__"),
  "mtd": ("__MTD_START__", "__MTD_END__"),
  "prev_month": ("__PREV_START__", "__PREV_END__"),
  "yoy_mtd": ("__YOY_START__", "__YOY_END__"),
}
for key, pair in windows.items():
    rows = attributed_rows(pair[0], pair[1])
    result[key] = [{
        "dealer": r.get("dealer_name"),
        "salesperson": r.get("salesperson") or "",
        "major": r.get("major") or "未分类",
        "series": r.get("series") or "未分类",
        "amount": float(r.get("amount") or 0),
        "lines": int(r.get("lines") or 0),
        "orders": int(r.get("orders") or 0),
    } for r in rows]

ai["result"] = result
'''
    code = (
        template.replace("__CASE_SQL__", case_sql)
        .replace("__WEEK_START__", window["week_start"])
        .replace("__WEEK_END__", window["week_end"])
        .replace("__MTD_START__", window["mtd_start"])
        .replace("__MTD_END__", window["mtd_end"])
        .replace("__PREV_START__", window["prev_month_start"])
        .replace("__PREV_END__", window["prev_month_end"])
        .replace("__YOY_START__", window["yoy_start"])
        .replace("__YOY_END__", window["yoy_end"])
    )
    SANDBOX_PATH.write_text(code, encoding="utf-8")


def vertu_cmd() -> list[str]:
    """解析 Windows 下可用的 vertu 启动命令。"""
    npm = Path.home() / "AppData" / "Roaming" / "npm"
    cjs = npm / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
    if cjs.exists():
        return ["node", str(cjs)]
    cmd_bat = npm / "vertu.cmd"
    if cmd_bat.exists():
        return [str(cmd_bat)]
    return ["vertu"]


def run_vertu_sandbox() -> dict:
    """调用 vertu 沙箱并解析结果。"""
    cmd = [*vertu_cmd(), "odoo", "data", "sandbox", "--code", f"@{SANDBOX_PATH}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"vertu failed: {proc.stderr or proc.stdout}")
    data = json.loads(proc.stdout.strip())
    # 兼容两种返回：{ok, result:{execution}} 或直接 {validation, execution}
    if "execution" in data:
        execution = data["execution"]
    elif data.get("ok") and isinstance(data.get("result"), dict):
        execution = data["result"].get("execution") or data["result"]
    else:
        raise RuntimeError(json.dumps(data, ensure_ascii=False, indent=2)[:2000])
    if execution.get("error"):
        raise RuntimeError(json.dumps(execution["error"], ensure_ascii=False, indent=2))
    return execution["result"]


def pct(curr: float, base: float) -> float | None:
    """计算增长率百分比。"""
    if base == 0:
        return None
    return round((curr - base) / abs(base) * 100, 1)


def clean_series_name(name: str) -> str:
    """清理商品细类展示名。"""
    if not name:
        return "未分类"
    return name.replace("<br>", " ").replace("<br/>", " ").strip()


def build_name_index(salespeople: dict) -> dict[str, str]:
    """销售人员系统名 → 配置 key（大小写不敏感）。"""
    idx = {}
    for key, meta in salespeople.items():
        idx[key.casefold()] = key
        for n in meta.get("system_names", []):
            idx[str(n).casefold()] = key
    return idx


def resolve_sales_key(
    salesperson: str,
    dealer_owner: str,
    name_index: dict[str, str],
    non_team: dict,
    empty_fallback: str,
) -> tuple[str | None, str]:
    """
    解析行级销售归属。

    Returns:
        (sales_key or None, tag)
        tag: team | non_team | empty_fallback | unknown
    """
    sp = (salesperson or "").strip()
    if not sp:
        if empty_fallback == "dealer_owner":
            return dealer_owner, "empty_fallback"
        return None, "empty"
    if sp in non_team:
        return None, "non_team"
    key = name_index.get(sp.casefold())
    if key:
        return key, "team"
    return None, "unknown"


def aggregate(config: dict, raw: dict, window: dict) -> dict:
    """按双重口径聚合总览与产品。"""
    sales_map = config["salespeople"]
    dealer_meta = {d["name"]: d for d in config["dealers"]}
    month_okr = config.get("okr_monthly", {}).get(window["month"], {})
    group_targets = month_okr.get("groups", {})
    total_target = float(month_okr.get("total") or 0)
    attr_cfg = config.get("attribution", {})
    non_team = attr_cfg.get("non_team_salespeople", {})
    furniture_majors = set(attr_cfg.get("furniture_majors", ["家具"]))
    virtual_series = set(attr_cfg.get("virtual_series", []))
    empty_fallback = attr_cfg.get("empty_salesperson_fallback", "dealer_owner")
    name_index = build_name_index(sales_map)

    def map_period(rows: list[dict]) -> dict:
        """同时产出 dealer_owner 与 salesperson_aligned 两套聚合。"""
        by_dealer: dict[str, dict] = {}
        owner_group: dict[str, float] = defaultdict(float)
        owner_sales: dict[str, float] = defaultdict(float)
        owner_region: dict[str, float] = defaultdict(float)

        ppt_group: dict[str, float] = defaultdict(float)
        ppt_sales: dict[str, float] = defaultdict(float)

        aligned_group: dict[str, float] = defaultdict(float)
        aligned_sales: dict[str, float] = defaultdict(float)
        cross_person: dict[str, float] = defaultdict(float)
        unknown_sp: dict[str, float] = defaultdict(float)

        goods_amt = 0.0
        furniture_amt = 0.0
        virtual_amt = 0.0

        by_major: dict[str, float] = defaultdict(float)
        series_bucket: dict[tuple[str, str], dict] = {}
        group_series: dict[tuple[str, str, str], dict] = {}

        for r in rows:
            name = r.get("dealer")
            meta = dealer_meta.get(name)
            if not meta:
                continue
            amt = float(r.get("amount") or 0)
            lines = int(r.get("lines") or 0)
            orders = int(r.get("orders") or 0)
            major = r.get("major") or "未分类"
            series = clean_series_name(r.get("series") or "未分类")
            owner = meta["sales"]
            group = sales_map[owner]["report_group"]

            # --- dealer_owner ---
            if name not in by_dealer:
                by_dealer[name] = {
                    "name": name,
                    "amount": 0.0,
                    "lines": 0,
                    "sales": owner,
                    "group": group,
                    "region": meta["region"],
                    "country": meta["country"],
                }
            by_dealer[name]["amount"] += amt
            by_dealer[name]["lines"] += lines
            owner_group[group] += amt
            owner_sales[owner] += amt
            owner_region[meta["region"]] += amt

            # --- salesperson_aligned ---
            sales_key, tag = resolve_sales_key(
                r.get("salesperson") or "",
                owner,
                name_index,
                non_team,
                empty_fallback,
            )
            if tag == "non_team":
                sp = (r.get("salesperson") or "").strip()
                cross_person[sp] += amt
                # ppt：剔除非团队记名，不计入 ppt_group
            else:
                # --- ppt = dealer_owner − non_team ---
                ppt_group[group] += amt
                ppt_sales[owner] += amt
                if tag == "unknown":
                    sp = (r.get("salesperson") or "").strip()
                    unknown_sp[sp] += amt
                elif sales_key:
                    ag = sales_map[sales_key]["report_group"]
                    aligned_group[ag] += amt
                    aligned_sales[sales_key] += amt

            # --- product splits ---
            by_major[major] += amt
            sk = (major, series)
            if sk not in series_bucket:
                series_bucket[sk] = {
                    "major": major,
                    "series": series,
                    "amount": 0.0,
                    "lines": 0,
                    "orders": 0,
                }
            series_bucket[sk]["amount"] += amt
            series_bucket[sk]["lines"] += lines
            series_bucket[sk]["orders"] += orders

            gk = (group, major, series)
            if gk not in group_series:
                group_series[gk] = {
                    "group": group,
                    "major": major,
                    "series": series,
                    "amount": 0.0,
                    "lines": 0,
                }
            group_series[gk]["amount"] += amt
            group_series[gk]["lines"] += lines

            if major in furniture_majors:
                furniture_amt += amt
            else:
                goods_amt += amt
            if series in virtual_series or any(v in series for v in virtual_series):
                virtual_amt += amt

        for d in by_dealer.values():
            d["amount"] = round(d["amount"], 2)

        series_list = sorted(
            (
                {
                    **v,
                    "amount": round(v["amount"], 2),
                }
                for v in series_bucket.values()
            ),
            key=lambda x: x["amount"],
            reverse=True,
        )
        majors = [
            {"major": k, "amount": round(v, 2)}
            for k, v in sorted(by_major.items(), key=lambda x: -x[1])
        ]
        by_group_products = sorted(
            (
                {**v, "amount": round(v["amount"], 2)}
                for v in group_series.values()
            ),
            key=lambda x: x["amount"],
            reverse=True,
        )

        return {
            "dealers": by_dealer,
            "groups": {k: round(v, 2) for k, v in owner_group.items()},
            "sales": {k: round(v, 2) for k, v in owner_sales.items()},
            "regions": {k: round(v, 2) for k, v in owner_region.items()},
            "total": round(sum(owner_group.values()), 2),
            "ppt_groups": {k: round(v, 2) for k, v in ppt_group.items()},
            "ppt_sales": {k: round(v, 2) for k, v in ppt_sales.items()},
            "ppt_total": round(sum(ppt_group.values()), 2),
            "aligned_groups": {k: round(v, 2) for k, v in aligned_group.items()},
            "aligned_sales": {k: round(v, 2) for k, v in aligned_sales.items()},
            "aligned_total": round(sum(aligned_group.values()), 2),
            "cross_person": {k: round(v, 2) for k, v in cross_person.items()},
            "unknown_salesperson": {k: round(v, 2) for k, v in unknown_sp.items()},
            "goods_amount": round(goods_amt, 2),
            "furniture_amount": round(furniture_amt, 2),
            "virtual_amount": round(virtual_amt, 2),
            "products": {"majors": majors, "series": series_list},
            "by_group_products": by_group_products,
        }

    mtd = map_period(raw.get("mtd", []))
    week = map_period(raw.get("week", []))
    prev = map_period(raw.get("prev_month", []))
    yoy = map_period(raw.get("yoy_mtd", []))

    def build_groups(amount_key: str = "groups") -> list[dict]:
        """构建组列表；amount_key: groups | ppt_groups | aligned_groups。"""
        out = []
        for g in GROUP_ORDER:
            mtd_amt = mtd[amount_key].get(g, 0.0)
            prev_amt = prev[amount_key].get(g, 0.0)
            yoy_amt = yoy[amount_key].get(g, 0.0)
            week_amt = week[amount_key].get(g, 0.0)
            target = float(group_targets.get(g) or 0)
            out.append({
                "name": g,
                "week_amount": week_amt,
                "mtd_amount": mtd_amt,
                "prev_month_amount": prev_amt,
                "yoy_mtd_amount": yoy_amt,
                "yoy_base_amount": yoy_amt,
                "mom_pct": pct(mtd_amt, prev_amt),
                "yoy_pct": pct(mtd_amt, yoy_amt),
                "okr_target": target,
                "okr_rate": round(mtd_amt / target * 100, 1) if target else None,
            })
        return out

    groups = build_groups("groups")
    groups_ppt = build_groups("ppt_groups")
    groups_aligned = build_groups("aligned_groups")

    top_dealers = sorted(mtd["dealers"].values(), key=lambda x: x["amount"], reverse=True)[:15]
    total_mtd = mtd["total"]
    total_prev = prev["total"]
    total_yoy = yoy["total"]

    high_ticket = []
    for s in mtd["products"]["series"]:
        if s["amount"] <= 0:
            continue
        orders = max(s.get("orders") or 0, 1)
        avg = s["amount"] / orders
        if avg >= 50000 and s["major"] in ("手机", "腕表", "戒指"):
            high_ticket.append({**s, "avg_per_order": round(avg, 2)})

    # 个人贡献（aligned）
    people = []
    for key, meta in sales_map.items():
        people.append({
            "name": key,
            "group": meta["report_group"],
            "week_amount": week["aligned_sales"].get(key, 0.0),
            "mtd_amount": mtd["aligned_sales"].get(key, 0.0),
            "owner_week_amount": week["sales"].get(key, 0.0),
            "owner_mtd_amount": mtd["sales"].get(key, 0.0),
        })
    people.sort(key=lambda x: x["mtd_amount"], reverse=True)

    cross_week = [
        {"salesperson": k, "amount": v, "period": "week"}
        for k, v in sorted(week["cross_person"].items(), key=lambda x: -x[1])
    ]
    cross_mtd = [
        {"salesperson": k, "amount": v, "period": "mtd"}
        for k, v in sorted(mtd["cross_person"].items(), key=lambda x: -x[1])
    ]

    return {
        "meta": {
            **window,
            "source": "odoo_sale via vertu sandbox",
            "currency": "CNY",
            "unit_note": "金额单位：元；Canvas 展示时换算为万元",
            "okr_note": month_okr.get("note", ""),
            "sellout_note": "Sell-out 数据暂缺，本版留空",
            "attribution": {
                "primary": attr_cfg.get("primary", "dealer_owner"),
                "ppt": attr_cfg.get("ppt", "dealer_minus_non_team"),
                "aligned": attr_cfg.get("aligned", "salesperson_aligned"),
                "note": (
                    "groups/headline=经销商归属(OKR)；"
                    "groups_ppt/headline_ppt=对齐PPT组数(剔除非团队记名)；"
                    "groups_aligned/people=销售人员个人贡献；"
                    "cross_person=非团队记名(如郑丽苹)"
                ),
                "yoy_note": (
                    f"同比基期={window['yoy_start']}~{window['yoy_end']}，"
                    f"基期金额见各组 yoy_base_amount / headline.yoy_mtd_amount"
                ),
                "furniture_note": (
                    "家具大类在 odoo_sale 海外匹配代理商中暂无金额；"
                    "PPT「货款+家具」需商务台账补家具"
                ),
            },
        },
        "headline": {
            "week_amount": week["total"],
            "mtd_amount": total_mtd,
            "prev_month_amount": total_prev,
            "yoy_mtd_amount": total_yoy,
            "mom_pct": pct(total_mtd, total_prev),
            "yoy_pct": pct(total_mtd, total_yoy),
            "okr_target": total_target,
            "okr_rate": round(total_mtd / total_target * 100, 1) if total_target else None,
            "goods_amount": mtd["goods_amount"],
            "furniture_amount": mtd["furniture_amount"],
            "virtual_amount": mtd["virtual_amount"],
        },
        "headline_ppt": {
            "week_amount": week["ppt_total"],
            "mtd_amount": mtd["ppt_total"],
            "prev_month_amount": prev["ppt_total"],
            "yoy_mtd_amount": yoy["ppt_total"],
            "mom_pct": pct(mtd["ppt_total"], prev["ppt_total"]),
            "yoy_pct": pct(mtd["ppt_total"], yoy["ppt_total"]),
            "okr_target": total_target,
            "okr_rate": (
                round(mtd["ppt_total"] / total_target * 100, 1) if total_target else None
            ),
            "cross_person_week": round(sum(week["cross_person"].values()), 2),
            "cross_person_mtd": round(sum(mtd["cross_person"].values()), 2),
        },
        "headline_aligned": {
            "week_amount": week["aligned_total"],
            "mtd_amount": mtd["aligned_total"],
            "prev_month_amount": prev["aligned_total"],
            "yoy_mtd_amount": yoy["aligned_total"],
            "mom_pct": pct(mtd["aligned_total"], prev["aligned_total"]),
            "yoy_pct": pct(mtd["aligned_total"], yoy["aligned_total"]),
            "okr_target": total_target,
            "okr_rate": (
                round(mtd["aligned_total"] / total_target * 100, 1) if total_target else None
            ),
            "cross_person_week": round(sum(week["cross_person"].values()), 2),
            "cross_person_mtd": round(sum(mtd["cross_person"].values()), 2),
        },
        "groups": groups,
        "groups_ppt": groups_ppt,
        "groups_aligned": groups_aligned,
        "people": people,
        "cross_person": {
            "week": cross_week,
            "mtd": cross_mtd,
            "unknown_week": week["unknown_salesperson"],
            "unknown_mtd": mtd["unknown_salesperson"],
        },
        "regions_mtd": [
            {"region": k, "amount": v}
            for k, v in sorted(mtd["regions"].items(), key=lambda x: -x[1])
        ],
        "top_dealers_mtd": top_dealers,
        "matched_dealers_mtd": len(mtd["dealers"]),
        "configured_dealers": len(config["dealers"]),
        "products": {
            "mtd_majors": mtd["products"]["majors"],
            "mtd_series": mtd["products"]["series"][:20],
            "week_series": week["products"]["series"][:15],
            "high_ticket_mtd": high_ticket[:10],
            "by_group_mtd": mtd["by_group_products"][:30],
        },
    }


def main() -> int:
    """主入口。"""
    args = parse_args()
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    window = resolve_window(args)
    write_sandbox(config["dealers"], window)
    print(
        f"window={window['week_label']} {window['week_start']}~{window['week_end']} "
        f"mtd={window['mtd_start']}~{window['mtd_end']}"
    )
    raw = run_vertu_sandbox()
    # 缓存原始行，便于复盘
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = OUTPUT_DIR / f"{window['week_label']}_raw_lines.json"
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    report = aggregate(config, raw, window)
    out_path = OUTPUT_DIR / f"{window['week_label']}_overview.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out_path}")
    print("headline(dealer_owner):", json.dumps(report["headline"], ensure_ascii=False))
    print("headline_ppt:", json.dumps(report["headline_ppt"], ensure_ascii=False))
    for g in report["groups"]:
        gp = next(x for x in report["groups_ppt"] if x["name"] == g["name"])
        print(
            f"  {g['name']}: owner_mtd={g['mtd_amount']:.0f} ppt_mtd={gp['mtd_amount']:.0f} "
            f"| owner_week={g['week_amount']:.0f} ppt_week={gp['week_amount']:.0f} "
            f"| okr={gp['okr_rate']}%"
        )
    if report["cross_person"]["week"]:
        print("cross_person week:", report["cross_person"]["week"])
    print("top products mtd:")
    for s in report["products"]["mtd_series"][:8]:
        print(f"  {s['major']}/{s['series']}: {s['amount']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
