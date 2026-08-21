# -*- coding: utf-8 -*-
"""
海外经销商完整周报 v1：总体 → 四部 → 代理商（区域/客户）→ 会议 → 日报。

业绩口径：ppt（dealer_owner − non_team），与既有周报 PPT 对齐。
组织标签：一部=于冰组、二部=杨晶晶组、三部=Lina组、新部=HR 经销商新部（业绩常无 dealer 映射）。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CONFIG = ROOT / "config" / "dealers.json"
OUT_DIR = ROOT / "outputs"
FETCH = ROOT / "scripts" / "fetch_overview.py"
DEPTH_TPL = ROOT / "scripts" / "_sandbox_product_depth.py"
DEPTH_RUN = ROOT / "scripts" / "_sandbox_product_depth_run.py"
VEMORY = REPO / "data_raw" / "overseas_123_vemory_liu_2026-07-01.json"

GROUP_LABEL = {
    "于冰组": "一部（于冰组）",
    "杨晶晶组": "二部（杨晶晶组）",
    "Lina组": "三部（Lina组）",
}
GROUP_ORDER = ["Lina组", "于冰组", "杨晶晶组"]  # 取数顺序
REPORT_ORDER = ["一部（于冰组）", "二部（杨晶晶组）", "三部（Lina组）", "新部"]

AS_OF = date(2026, 7, 19)
WEEK_START = date(2026, 7, 13)
WEEK_END = date(2026, 7, 19)


def wan(x: float) -> str:
    return f"{x / 10000:.2f}"


def pct(x) -> str:
    if x is None:
        return "—"
    return f"{x:+.1f}%" if isinstance(x, (int, float)) else str(x)


def vertu_cmd() -> list[str]:
    npm = Path.home() / "AppData" / "Roaming" / "npm"
    cjs = npm / "node_modules" / "@vertu-tech" / "vps-cli" / "dist" / "vertu.cjs"
    if cjs.exists():
        return ["node", str(cjs)]
    return [str(npm / "vertu.cmd")]


def vertu_cli() -> str:
    return str(Path.home() / "AppData/Roaming/npm/vertu-cli.cmd")


def build_case_sql(dealers: list[dict]) -> str:
    cases = []
    for d in dealers:
        ors = " OR ".join(
            [f"\"客户名称\" ILIKE '%{m.replace(chr(39), chr(39)+chr(39))}%'" for m in d["match"]]
        )
        label = d["name"].replace("'", "''")
        cases.append(f"WHEN ({ors}) THEN '{label}'")
    return "CASE\n" + "\n".join(cases) + "\nELSE NULL\nEND"


def run_fetch() -> Path:
    target = OUT_DIR / "2026-W29_overview.json"
    if target.exists():
        meta = json.loads(target.read_text(encoding="utf-8")).get("meta", {})
        if meta.get("as_of") == AS_OF.isoformat() and meta.get("mtd_end") == AS_OF.isoformat():
            print(f"reuse overview as_of={meta.get('as_of')}", flush=True)
            return target

    cmd = [
        sys.executable,
        str(FETCH),
        "--as-of",
        AS_OF.isoformat(),
        "--week-start",
        WEEK_START.isoformat(),
        "--week-end",
        WEEK_END.isoformat(),
    ]
    print("fetch:", " ".join(cmd), flush=True)
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if target.exists():
        meta = json.loads(target.read_text(encoding="utf-8")).get("meta", {})
        if meta.get("as_of") == AS_OF.isoformat():
            print(f"fetch ok -> {target.name}", flush=True)
            return target
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "fetch failed")[:1000])
    cands = sorted(OUT_DIR.glob("2026-W*_overview.json"), key=lambda p: p.stat().st_mtime)
    return cands[-1]


def run_product_depth(config: dict) -> dict:
    case = build_case_sql(config["dealers"])
    code = (
        DEPTH_TPL.read_text(encoding="utf-8")
        .replace("__CASE_SQL__", case)
        .replace("__MTD_START__", date(AS_OF.year, AS_OF.month, 1).isoformat())
        .replace("__MTD_END__", AS_OF.isoformat())
        .replace("__WEEK_START__", WEEK_START.isoformat())
        .replace("__WEEK_END__", WEEK_END.isoformat())
    )
    DEPTH_RUN.write_text(code, encoding="utf-8")
    cmd = [*vertu_cmd(), "odoo", "data", "sandbox", "--code", f"@{DEPTH_RUN}"]
    print("product depth sandbox...", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    data = json.loads(proc.stdout.strip())
    if "execution" in data:
        ex = data["execution"]
    elif data.get("ok") and isinstance(data.get("result"), dict):
        ex = data["result"].get("execution") or data["result"]
    else:
        raise RuntimeError(json.dumps(data, ensure_ascii=False)[:500])
    if ex.get("error"):
        raise RuntimeError(json.dumps(ex["error"], ensure_ascii=False)[:500])
    return ex["result"]


def series_bucket(series: str) -> str | None:
    s = (series or "").upper().replace(" ", "")
    raw = series or ""
    if "ALPHAFOLD" in raw.upper():
        return "alphafold"
    if "AGENT Q" in raw.upper() or "AGENTQ" in s:
        return "agentq"
    if "METAVERTU 2" in raw.upper() or "METAVERTU2" in s:
        return "meta2"
    if raw.upper().startswith("IVERTU") or "IVERTU" in raw.upper():
        return "ivertu"
    # Meta1: METAVERTU but not 2
    if "METAVERTU" in raw.upper() and "METAVERTU 2" not in raw.upper() and "METAVERTU2" not in s:
        return "meta1"
    return None


def iot_kind(major: str) -> str | None:
    if major in ("腕表", "钢笔", "耳机", "戒指", "手链"):
        return major
    return None


def enrich_products(rows: list[dict], config: dict) -> dict:
    """按 ppt 口径（剔除 non_team）聚合产品桶。"""
    sales_map = config["salespeople"]
    dealer_meta = {d["name"]: d for d in config["dealers"]}
    non_team = set(config.get("attribution", {}).get("non_team_salespeople", {}).keys())

    total = {"amount": 0.0, "qty": 0.0}
    by_major: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "qty": 0.0})
    buckets = {
        k: {"amount": 0.0, "qty": 0.0}
        for k in ("alphafold", "agentq", "meta2", "meta1", "ivertu")
    }
    iot = {k: {"amount": 0.0, "qty": 0.0} for k in ("腕表", "钢笔", "耳机", "戒指", "手链")}
    by_group: dict[str, dict] = defaultdict(
        lambda: {
            "amount": 0.0,
            "qty": 0.0,
            "buckets": {
                k: {"amount": 0.0, "qty": 0.0}
                for k in ("alphafold", "agentq", "meta2", "meta1", "ivertu")
            },
            "iot": {k: {"amount": 0.0, "qty": 0.0} for k in ("腕表", "钢笔", "耳机", "戒指", "手链")},
            "majors": defaultdict(lambda: {"amount": 0.0, "qty": 0.0}),
            "people": defaultdict(lambda: {"amount": 0.0, "qty": 0.0}),
        }
    )
    by_dealer: dict[str, dict] = defaultdict(
        lambda: {
            "amount": 0.0,
            "qty": 0.0,
            "region": "",
            "country": "",
            "group": "",
            "buckets": {
                k: {"amount": 0.0, "qty": 0.0}
                for k in ("alphafold", "agentq", "meta2", "meta1", "ivertu")
            },
            "iot": {k: {"amount": 0.0, "qty": 0.0} for k in ("腕表", "钢笔", "耳机", "戒指", "手链")},
        }
    )
    by_region: dict[str, dict] = defaultdict(lambda: {"amount": 0.0, "qty": 0.0, "dealers": set()})

    for r in rows:
        sp = (r.get("salesperson") or "").strip()
        if sp in non_team:
            continue
        name = r.get("dealer")
        meta = dealer_meta.get(name)
        if not meta:
            continue
        owner = meta["sales"]
        group = sales_map[owner]["report_group"]
        amt = float(r.get("amount") or 0)
        qty = float(r.get("qty") or 0)
        major = r.get("major") or "未分类"
        series = r.get("series") or ""

        total["amount"] += amt
        total["qty"] += qty
        by_major[major]["amount"] += amt
        by_major[major]["qty"] += qty

        g = by_group[group]
        g["amount"] += amt
        g["qty"] += qty
        g["majors"][major]["amount"] += amt
        g["majors"][major]["qty"] += qty
        # person: prefer salesperson if team else owner
        person = sp if sp else owner
        g["people"][person]["amount"] += amt
        g["people"][person]["qty"] += qty

        d = by_dealer[name]
        d["amount"] += amt
        d["qty"] += qty
        d["region"] = meta.get("region") or ""
        d["country"] = meta.get("country") or ""
        d["group"] = group
        by_region[d["region"]]["amount"] += amt
        by_region[d["region"]]["qty"] += qty
        by_region[d["region"]]["dealers"].add(name)

        b = series_bucket(series)
        if b:
            buckets[b]["amount"] += amt
            buckets[b]["qty"] += qty
            g["buckets"][b]["amount"] += amt
            g["buckets"][b]["qty"] += qty
            d["buckets"][b]["amount"] += amt
            d["buckets"][b]["qty"] += qty

        ik = iot_kind(major)
        if ik:
            iot[ik]["amount"] += amt
            iot[ik]["qty"] += qty
            g["iot"][ik]["amount"] += amt
            g["iot"][ik]["qty"] += qty
            d["iot"][ik]["amount"] += amt
            d["iot"][ik]["qty"] += qty

    return {
        "total": total,
        "by_major": dict(by_major),
        "buckets": buckets,
        "iot": iot,
        "by_group": {k: {**v, "majors": dict(v["majors"]), "people": dict(v["people"])} for k, v in by_group.items()},
        "by_dealer": dict(by_dealer),
        "by_region": {
            k: {"amount": v["amount"], "qty": v["qty"], "dealer_count": len(v["dealers"])}
            for k, v in by_region.items()
        },
    }


def classify_meeting(title: str, summary: str) -> str:
    text = f"{title} {summary}".lower()
    if any(k in text for k in ("面试", "interview", "候选人", "招聘")):
        return "面试"
    if any(
        k in text
        for k in (
            "经销商",
            "代理",
            "客户",
            "门店",
            "商场",
            "云顶",
            "thakral",
            "拜访",
            "合作",
            "dealer",
            "customer",
            "store",
            "pavilion",
            "klcc",
        )
    ):
        return "外部会议"
    if any(k in text for k in ("周会", "晨会", "培训", "内部", "对齐", "复盘", "sop", "vps", "日报")):
        return "内部会议"
    return "内部会议"


def load_meetings() -> dict:
    if not VEMORY.exists():
        return {"by_dept": {}, "totals": {}}
    data = json.loads(VEMORY.read_text(encoding="utf-8"))
    # map vemory dept labels
    by = defaultdict(lambda: {"外部会议": 0, "内部会议": 0, "面试": 0, "items": []})
    for r in data.get("results") or []:
        if not r.get("ok"):
            continue
        dept = r.get("dept") or "?"
        # 一部/二部/新部 from vemory; 三部=Lina 不在该 JSON
        label = {"一部": "一部（于冰组）", "二部": "二部（杨晶晶组）", "新部": "新部"}.get(dept, dept)
        for m in r.get("meetings") or []:
            title = m.get("name") or ""
            summary = m.get("summary") or ""
            if any(k in title for k in ("录音连线", "内容极少", "转录内容不足", "简短开场")):
                continue
            cat = classify_meeting(title, summary)
            by[label][cat] += 1
            by[label]["items"].append(
                {
                    "person": r.get("name"),
                    "day": (m.get("start_time") or "")[:10],
                    "cat": cat,
                    "title": title,
                    "dur": int(m.get("duration_seconds") or 0) // 60,
                }
            )
    totals = {"外部会议": 0, "内部会议": 0, "面试": 0}
    for v in by.values():
        for k in totals:
            totals[k] += v[k]
    return {"by_dept": dict(by), "totals": totals}


def pull_daily_reports(people: list[tuple[int, str, str]]) -> dict:
    """拉取本周日报摘要。people: (user_id, name, dept_label)"""
    out = {}
    cli = vertu_cli()
    for i, (uid, name, dept) in enumerate(people):
        if i:
            time.sleep(1.5)
        cmd = [
            cli,
            "report",
            "+user-summary",
            "--user-id",
            str(uid),
            "--start-time",
            WEEK_START.isoformat(),
            "--end-time",
            WEEK_END.isoformat(),
        ]
        print(f"daily {name}...", flush=True)
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        text = (proc.stdout or "") + (proc.stderr or "")
        idx = text.find("{")
        if idx < 0:
            out[name] = {"ok": False, "dept": dept, "error": text[:120]}
            continue
        try:
            payload = json.loads(text[idx:])
        except json.JSONDecodeError:
            out[name] = {"ok": False, "dept": dept, "error": "json"}
            continue
        out[name] = {"ok": True, "dept": dept, "payload": payload}
    return out


def fmt_bucket_table(buckets: dict, iot: dict) -> list[str]:
    lines = [
        "| 品类 | 销售额（万） | 数量 |",
        "|------|-------------|------|",
        f"| AlphaFold（新品） | {wan(buckets['alphafold']['amount'])} | {buckets['alphafold']['qty']:.0f} |",
        f"| AGENT Q | {wan(buckets['agentq']['amount'])} | {buckets['agentq']['qty']:.0f} |",
        f"| Meta2 | {wan(buckets['meta2']['amount'])} | {buckets['meta2']['qty']:.0f} |",
        f"| iVertu（清库存） | {wan(buckets['ivertu']['amount'])} | {buckets['ivertu']['qty']:.0f} |",
        f"| Meta1（清库存） | {wan(buckets['meta1']['amount'])} | {buckets['meta1']['qty']:.0f} |",
    ]
    iot_amt = sum(v["amount"] for v in iot.values())
    iot_qty = sum(v["qty"] for v in iot.values())
    lines.append(f"| IOT 合计 | {wan(iot_amt)} | {iot_qty:.0f} |")
    for k in ("腕表", "钢笔", "耳机", "戒指", "手链"):
        lines.append(f"| └ {k} | {wan(iot[k]['amount'])} | {iot[k]['qty']:.0f} |")
    return lines


def summarize_daily(payload: dict) -> str:
    """尽量从 user-summary 抽出可读摘要。"""
    if not payload:
        return "（无数据）"
    # 结构不确定，做稳健提取
    reports = (
        payload.get("daily_reports")
        or payload.get("reports")
        or payload.get("rows")
        or payload.get("data")
        or []
    )
    if isinstance(payload.get("result"), dict):
        reports = (
            payload["result"].get("daily_reports")
            or payload["result"].get("reports")
            or payload["result"].get("rows")
            or reports
        )
    if isinstance(reports, dict):
        reports = reports.get("rows") or reports.get("items") or []
    if not reports:
        # dump short keys
        keys = list(payload.keys())[:12]
        return f"（结构待解析 keys={keys}）"
    bits = []
    for row in reports[:14]:
        if not isinstance(row, dict):
            continue
        day = row.get("date") or row.get("day") or row.get("report_date") or row.get("create_date") or ""
        day = str(day)[:10]
        content = (
            row.get("content")
            or row.get("today")
            or row.get("work_content")
            or row.get("summary")
            or row.get("progress")
            or ""
        )
        if isinstance(content, list):
            content = "；".join(str(x) for x in content)
        content = str(content).replace("\n", " ").strip()
        if day or content:
            bits.append(f"- `{day}` {content[:160]}")
    return "\n".join(bits) if bits else "（本周无日报正文）"


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))

    overview_path = run_fetch()
    overview = json.loads(overview_path.read_text(encoding="utf-8"))
    depth = run_product_depth(config)
    prod_mtd = enrich_products(depth.get("mtd") or [], config)
    prod_week = enrich_products(depth.get("week") or [], config)

    # save intermediate
    depth_out = {
        "as_of": AS_OF.isoformat(),
        "week": [WEEK_START.isoformat(), WEEK_END.isoformat()],
        "prod_mtd": prod_mtd,
        "prod_week": {
            "total": prod_week["total"],
            "buckets": prod_week["buckets"],
            "iot": prod_week["iot"],
        },
    }
    (OUT_DIR / "2026-07_full_report_products.json").write_text(
        json.dumps(depth_out, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    meetings = load_meetings()

    # daily reports for key people
    people = [
        (13063, "于冰", "一部（于冰组）"),
        (13122, "杨晶晶", "二部（杨晶晶组）"),
        (14113, "何海文", "二部（杨晶晶组）"),
        (13050, "Lina/DEHDAHOUMAIMA", "三部（Lina组）"),
        (13551, "尤文静", "三部（Lina组）"),
        (14226, "欧阳英平", "新部"),
        (14454, "李浩然", "新部"),
    ]
    dailies = pull_daily_reports(people)
    daily_meta = {}
    for k, v in dailies.items():
        daily_meta[k] = {
            "ok": v.get("ok"),
            "dept": v.get("dept"),
            "error": v.get("error"),
            "payload_keys": list((v.get("payload") or {}).keys()),
        }
    (OUT_DIR / "2026-07_full_report_dailies.json").write_text(
        json.dumps(daily_meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # keep full separately
    (OUT_DIR / "2026-07_full_report_dailies_full.json").write_text(
        json.dumps(dailies, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    h = overview.get("headline_ppt") or overview.get("headline") or {}
    groups = {g["name"]: g for g in (overview.get("groups_ppt") or overview.get("groups") or [])}
    people_rows = overview.get("people") or []
    regions = overview.get("regions_mtd") or []
    top_dealers = overview.get("top_dealers_mtd") or []

    lines: list[str] = []
    lines += [
        "# 海外经销商周报（完整结构 · 第一版）",
        "",
        f"> **窗口**：本周 {WEEK_START} ~ {WEEK_END} · 月累计 2026-07-01 ~ {AS_OF}  ",
        f"> **业绩口径**：`ppt` = 经销商归属组 − 非团队记名（郑丽苹/陈晓霜）  ",
        f"> **组织标签**：一部=于冰组 · 二部=杨晶晶组 · 三部=Lina组 · 新部=HR经销商新部  ",
        f"> **取数文件**：`{overview_path.name}` + product depth sandbox  ",
        f"> **会议**：刘春梅账号可查范围（一部于冰 / 二部杨+海文 / 新部）；三部会议待补拉  ",
        f"> **待确认**：新部暂无 dealers 映射业绩；组目标合计 635 万 vs 总目标 695 万差额 60 万",
        "",
        "---",
        "",
        "## 一、总体",
        "",
        "### 1.1 业绩总览（同环比）",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 月目标 | {wan(float(h.get('okr_target') or 0))} 万 |",
        f"| MTD SI | **{wan(float(h.get('mtd_amount') or 0))} 万** |",
        f"| 达成率 | **{h.get('okr_rate')}%** |",
        f"| 本周 SI | **{wan(float(h.get('week_amount') or 0))} 万** |",
        f"| 上月同期 MTD | {wan(float(h.get('prev_month_amount') or 0))} 万 |",
        f"| 环比 | {pct(h.get('mom_pct'))} |",
        f"| 去年同期 MTD | {wan(float(h.get('yoy_mtd_amount') or 0))} 万 |",
        f"| 同比 | {pct(h.get('yoy_pct'))} |",
        "",
        "### 1.2 业绩情况分析",
        "",
        "| 组 | 月目标（万） | MTD（万） | 达成率 | 本周（万） | 环比 | 同比 |",
        "|----|-------------|----------|--------|----------|------|------|",
    ]
    for gname in GROUP_ORDER:
        g = groups.get(gname, {})
        lines.append(
            f"| {GROUP_LABEL[gname]} | {wan(float(g.get('okr_target') or 0))} | "
            f"{wan(float(g.get('mtd_amount') or 0))} | {g.get('okr_rate')}% | "
            f"{wan(float(g.get('week_amount') or 0))} | {pct(g.get('mom_pct'))} | {pct(g.get('yoy_pct'))} |"
        )
    lines += [
        "",
        f"- 本周结构：三部（Lina）贡献为主；一部本周 SI 见下表。",
        f"- 非团队记名剔除（MTD）：约 {wan(float(h.get('cross_mtd_amount') or h.get('cross_person_mtd') or 0))} 万（若字段存在）。",
        "",
        "### 1.3 总体产品情况",
        "",
        "| 商品大类 | 销售额（万） | 数量 |",
        "|----------|-------------|------|",
    ]
    for major, v in sorted(prod_mtd["by_major"].items(), key=lambda x: -x[1]["amount"]):
        lines.append(f"| {major} | {wan(v['amount'])} | {v['qty']:.0f} |")
    lines += [
        "",
        "### 1.4 AlphaFold（新品）及核心品类",
        "",
        *fmt_bucket_table(prod_mtd["buckets"], prod_mtd["iot"]),
        "",
        f"**本周 AlphaFold**：{wan(prod_week['buckets']['alphafold']['amount'])} 万 / "
        f"{prod_week['buckets']['alphafold']['qty']:.0f} 台",
        "",
        "---",
        "",
        "## 二、各组（一部 / 二部 / 三部 / 新部）",
        "",
    ]

    # people aligned table helper
    people_by_group = defaultdict(list)
    for p in people_rows:
        people_by_group[p.get("group")].append(p)

    for gname in ("于冰组", "杨晶晶组", "Lina组"):
        label = GROUP_LABEL[gname]
        g = groups.get(gname, {})
        gp = prod_mtd["by_group"].get(gname, {})
        lines += [
            f"### {label}",
            "",
            "#### 组总体业绩",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 月目标 | {wan(float(g.get('okr_target') or 0))} 万 |",
            f"| MTD | **{wan(float(g.get('mtd_amount') or 0))} 万**（{g.get('okr_rate')}%） |",
            f"| 本周 | {wan(float(g.get('week_amount') or 0))} 万 |",
            f"| 环比 / 同比 | {pct(g.get('mom_pct'))} / {pct(g.get('yoy_pct'))} |",
            "",
            "#### 个人业绩（salesperson_aligned）",
            "",
            "| 人员 | 本周（万） | 月累计（万） |",
            "|------|----------|-------------|",
        ]
        for p in sorted(people_by_group.get(gname, []), key=lambda x: -float(x.get("mtd_amount") or 0)):
            lines.append(
                f"| {p.get('name')} | {wan(float(p.get('week_amount') or 0))} | {wan(float(p.get('mtd_amount') or 0))} |"
            )
        if not people_by_group.get(gname):
            lines.append("| （无） | — | — |")

        # also from product depth people
        if gp.get("people"):
            lines += [
                "",
                "个人贡献（产品行汇总 · ppt 剔除后）",
                "",
                "| 记名销售 | MTD（万） |",
                "|----------|----------|",
            ]
            for person, v in sorted(gp["people"].items(), key=lambda x: -x[1]["amount"]):
                lines.append(f"| {person} | {wan(v['amount'])} |")

        buckets = gp.get("buckets") or {k: {"amount": 0, "qty": 0} for k in ("alphafold", "agentq", "meta2", "meta1", "ivertu")}
        iot = gp.get("iot") or {k: {"amount": 0, "qty": 0} for k in ("腕表", "钢笔", "耳机", "戒指", "手链")}
        majors = gp.get("majors") or {}
        lines += [
            "",
            "#### 本组产品情况",
            "",
            "| 商品大类 | 销售额（万） | 数量 |",
            "|----------|-------------|------|",
        ]
        for major, v in sorted(majors.items(), key=lambda x: -x[1]["amount"])[:12]:
            lines.append(f"| {major} | {wan(v['amount'])} | {v['qty']:.0f} |")
        if not majors:
            lines.append("| — | 0 | 0 |")
        lines += ["", "#### AlphaFold / AGENT Q / Meta2 / IOT / 清库存", "", *fmt_bucket_table(buckets, iot), ""]

        # meetings for this label
        mt = meetings["by_dept"].get(label, {})
        lines += [
            "#### 本组会议情况（本月可查）",
            "",
            "| 类型 | 场次 |",
            "|------|------|",
            f"| 外部会议 | {mt.get('外部会议', 0)} |",
            f"| 内部会议 | {mt.get('内部会议', 0)} |",
            f"| 面试 | {mt.get('面试', 0)} |",
            "",
        ]
        items = mt.get("items") or []
        # W3 only highlight
        w3 = [x for x in items if WEEK_START.isoformat() <= (x.get("day") or "") <= WEEK_END.isoformat()]
        if w3:
            lines.append("本周会议摘录：")
            lines.append("")
            for x in sorted(w3, key=lambda z: z.get("day") or "", reverse=True)[:10]:
                lines.append(
                    f"- `{x['day']}` · {x['cat']} · {x['person']} · {x['dur']}min · {x['title']}"
                )
            lines.append("")

        # dailies
        lines += ["#### 组内日报工作汇总（本周）", ""]
        any_daily = False
        for name, info in dailies.items():
            if info.get("dept") != label:
                continue
            any_daily = True
            lines.append(f"**{name}**")
            lines.append("")
            if not info.get("ok"):
                lines.append(f"- 拉取失败：{info.get('error')}")
            else:
                lines.append(summarize_daily(info.get("payload") or {}))
            lines.append("")
        if not any_daily:
            lines.append("（本周未配置或未拉到日报）")
            lines.append("")

    # 新部
    lines += [
        "### 新部",
        "",
        "#### 组总体业绩",
        "",
        "- **说明**：`dealers.json` 未配置新部销售归属经销商，**ppt 口径下 MTD/本周 SI 记为 0**（待确认是否应并入某组或单独建映射）。",
        "- HR 花名册：欧阳英平、向秋俊、李浩然、高永强、涂钢、廖静思、余蕊、李浩然-1、陈玲珑。",
        "",
        "#### 产品 / AF / AQ / Meta2 / IOT / 清库存",
        "",
        "- 无经销商映射行，产品桶均为 0。若新部有录单记在他人/未匹配客户名下，需补客户匹配。",
        "",
        "#### 会议情况（本月可查）",
        "",
    ]
    mt = meetings["by_dept"].get("新部", {})
    lines += [
        "| 类型 | 场次 |",
        "|------|------|",
        f"| 外部会议 | {mt.get('外部会议', 0)} |",
        f"| 内部会议 | {mt.get('内部会议', 0)} |",
        f"| 面试 | {mt.get('面试', 0)} |",
        "",
        "#### 日报汇总（本周）",
        "",
    ]
    for name, info in dailies.items():
        if info.get("dept") != "新部":
            continue
        lines.append(f"**{name}**")
        lines.append("")
        if not info.get("ok"):
            lines.append(f"- 拉取失败：{info.get('error')}")
        else:
            lines.append(summarize_daily(info.get("payload") or {}))
        lines.append("")

    # 代理商
    lines += [
        "---",
        "",
        "## 三、代理商业绩（先区域，再客户）",
        "",
        "### 3.1 按区域（MTD · ppt）",
        "",
        "| 区域 | 销售额（万） | 数量 | 代理商数 |",
        "|------|-------------|------|----------|",
    ]
    for region, v in sorted(prod_mtd["by_region"].items(), key=lambda x: -x[1]["amount"]):
        lines.append(
            f"| {region or '未标'} | {wan(v['amount'])} | {v['qty']:.0f} | {v['dealer_count']} |"
        )

    lines += [
        "",
        "### 3.2 按客户（MTD Top · 含产品桶）",
        "",
    ]
    dealers_sorted = sorted(prod_mtd["by_dealer"].items(), key=lambda x: -x[1]["amount"])
    for region, _ in sorted(prod_mtd["by_region"].items(), key=lambda x: -x[1]["amount"]):
        region_dealers = [(n, v) for n, v in dealers_sorted if v.get("region") == region]
        if not region_dealers:
            continue
        lines += [f"#### {region}", ""]
        for name, v in region_dealers[:12]:
            b = v["buckets"]
            lines.append(
                f"**{name}**（{GROUP_LABEL.get(v['group'], v['group'])} · {v.get('country','')}）· "
                f"MTD **{wan(v['amount'])} 万** / 数量 {v['qty']:.0f}"
            )
            lines.append(
                f"- AF {wan(b['alphafold']['amount'])}万/{b['alphafold']['qty']:.0f} · "
                f"AQ {wan(b['agentq']['amount'])}万/{b['agentq']['qty']:.0f} · "
                f"Meta2 {wan(b['meta2']['amount'])}万/{b['meta2']['qty']:.0f} · "
                f"iVertu {wan(b['ivertu']['amount'])}万/{b['ivertu']['qty']:.0f} · "
                f"Meta1 {wan(b['meta1']['amount'])}万/{b['meta1']['qty']:.0f}"
            )
            iot_bits = [
                f"{k}{wan(v['iot'][k]['amount'])}万/{v['iot'][k]['qty']:.0f}"
                for k in ("腕表", "钢笔", "耳机", "戒指", "手链")
                if v["iot"][k]["amount"] or v["iot"][k]["qty"]
            ]
            if iot_bits:
                lines.append("- IOT：" + " · ".join(iot_bits))
            lines.append("")

    # 总体会议
    lines += [
        "---",
        "",
        "## 四、总体会议情况（本月 · 可查范围）",
        "",
        "| 类型 | 场次 |",
        "|------|------|",
        f"| 外部会议 | {meetings['totals'].get('外部会议', 0)} |",
        f"| 内部会议 | {meetings['totals'].get('内部会议', 0)} |",
        f"| 面试 | {meetings['totals'].get('面试', 0)} |",
        "",
        "> 三部（Lina）会议未纳入本次 Vemory 批量文件，需用刘春梅账号补拉 Lina/尤文静等。",
        "",
        "---",
        "",
        "## 五、数据缺口（第一版标注）",
        "",
        "1. **新部业绩**：无经销商映射 → SI=0，待业务确认归属。",
        "2. **三部会议**：待补拉 Vemory。",
        "3. **日报**：若摘要显示「结构待解析」，需按 `+user-summary` 实际字段再映射一版。",
        "4. **Sell-out / 待收款台账**：系统仍拉不全，沿用各组业务 PPT/PDF。",
        "5. **数量口径**：`odoo_sale.数量` 汇总；辅料行可能与整机台数并存，解读时注意。",
        "",
    ]

    out = OUT_DIR / "2026-W29_完整结构周报_第一版.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
