# -*- coding: utf-8 -*-
"""生成经销商 PDCA 驾驶舱 snapshot JSON（供 web 前端消费）。"""
import argparse
import csv
import importlib.util
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TEAM_PATH = REPO_ROOT / "teams" / "yang-jingjing"
CHECK_SCRIPT = REPO_ROOT / "scripts" / "daily-team-check.py"
SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "snapshots"

MEMBERS = ["杨晶晶", "何海文", "王宇彤"]
SLUGS = {"杨晶晶": "yang-jingjing", "何海文": "he-haiwen", "王宇彤": "wang-yutong"}
MEMBER_TARGETS_MAY = {"杨晶晶": 125, "何海文": 45, "王宇彤": 10}
TEAM_TARGET_MAY = 190


def load_check_module():
    spec = importlib.util.spec_from_file_location("daily_team_check", CHECK_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def number_from_line(lines, label):
    pattern = re.compile(rf"^\s*-\s*{re.escape(label)}\s*[:：]\s*(\d+(?:\.\d+)?)")
    for line in lines:
        match = pattern.match(line)
        if match:
            return float(match.group(1))
    return None


def read_monthly_targets(month):
    path = TEAM_PATH / "monthly_targets" / f"{month}.md"
    if not path.exists():
        return {}
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    targets = {"team": None}
    current = None
    for line in lines:
        if line.startswith("### "):
            current = line.replace("### ", "").strip()
            targets[current] = None
        elif current and "月度实际业绩目标" in line:
            val = number_from_line([line], "月度实际业绩目标")
            if val is not None:
                targets[current] = val
        elif "团队结果目标" in line or line.startswith("## 团队"):
            current = "__team__"
        elif current == "__team__" and "月度实际业绩目标" in line:
            val = number_from_line([line], "月度实际业绩目标")
            if val is not None:
                targets["team"] = val
    return targets


def load_customers(check_date):
    path = TEAM_PATH / "customers.csv"
    rows = []
    check_dt = datetime.strptime(check_date, "%Y-%m-%d")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            last = (row.get("last_followup_date") or "").strip()
            days = None
            overdue = False
            limit = 7 if row.get("priority") == "A" else 14
            if last:
                days = (check_dt - datetime.strptime(last, "%Y-%m-%d")).days
                overdue = days > limit
            rows.append({
                "name": row["dealer_name"],
                "nickname": row.get("dealer_nickname") or "",
                "region": row.get("region") or "",
                "country": row.get("country") or "",
                "owner": row.get("owner") or "",
                "priority": row.get("priority") or "",
                "last_followup": last or None,
                "days_since": days,
                "overdue": overdue,
                "next_action": row.get("next_action") or "",
            })
    return rows


def parse_team_check_table(path):
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    members = []
    for line in text.splitlines():
        if not line.startswith("|") or "---" in line or "成员" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 5 and cells[0] in MEMBERS:
            members.append({
                "name": cells[0],
                "log_submitted": cells[1] == "已提交",
                "process_rate": float(cells[2].replace("%", "") or 0),
                "risk": cells[4],
            })
    return members


def parse_personal_metrics(check_path):
    if not check_path.exists():
        return {}
    lines = check_path.read_text(encoding="utf-8-sig").splitlines()
    metrics = {}
    in_table = False
    for line in lines:
        if line.startswith("| 指标 |"):
            in_table = True
            continue
        if in_table and line.startswith("|") and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 3 and cells[0] not in ("指标", ""):
                try:
                    metrics[cells[0]] = {"actual": float(cells[1]), "target": float(cells[2])}
                except ValueError:
                    pass
        elif in_table and not line.startswith("|"):
            break
    return metrics


def build_insights(team_rows, customers, leader_share):
    insights = []
    if leader_share > 60:
        insights.append(f"客户资源高度集中在组长（{leader_share}%），建议向组员分配 B/C 类客户。")
    overdue = [c for c in customers if c["overdue"]]
    for c in overdue[:5]:
        insights.append(f"超期跟进：{c['name']}（{c['days_since']} 天）")
    for row in team_rows:
        if "过程指标不足" in row.get("risk", ""):
            insights.append(f"{row['name']}：过程指标未达标，需加强有效触达与报价。")
        if "未提交" in row.get("risk", ""):
            insights.append(f"{row['name']}：未提交日报，标记高风险。")
    if not insights:
        insights.append("暂无明显风险，继续保持日报与客户动作记录。")
    return insights


def aggregate_regions(customers):
    by_region = defaultdict(lambda: {"dealer_count": 0, "overdue": 0, "owners": set()})
    for c in customers:
        rg = c["region"] or "未分区"
        by_region[rg]["dealer_count"] += 1
        by_region[rg]["owners"].add(c["owner"])
        if c["overdue"]:
            by_region[rg]["overdue"] += 1
    regions = []
    for name, data in sorted(by_region.items()):
        regions.append({
            "name": name,
            "dealer_count": data["dealer_count"],
            "overdue_count": data["overdue"],
            "owner_count": len(data["owners"]),
        })
    return regions


def build_snapshot(date_text, run_check=True):
    mod = load_check_module()
    if run_check:
        mod.generate(str(TEAM_PATH), date_text)

    month = date_text[:7]
    targets = read_monthly_targets(month)
    if not targets.get("team"):
        targets["team"] = TEAM_TARGET_MAY if month == "2026-05" else None
    for m in MEMBERS:
        if targets.get(m) is None and month == "2026-05":
            targets[m] = MEMBER_TARGETS_MAY.get(m)

    defaults = mod.daily_defaults(TEAM_PATH / "monthly_targets" / f"{month}.md")
    customers = load_customers(date_text)
    owner_counts = {m: sum(1 for c in customers if c["owner"] == m) for m in MEMBERS}
    total = len(customers) or 1
    leader_share = round((owner_counts["杨晶晶"] / total) * 100, 1)

    team_check_path = TEAM_PATH / "check_reports" / f"{date_text}_team_check.md"
    team_rows = parse_team_check_table(team_check_path)

    sales = []
    for member in MEMBERS:
        slug = SLUGS[member]
        personal = TEAM_PATH / "check_reports" / f"{date_text}_{slug}_check.md"
        metrics = parse_personal_metrics(personal)
        row = next((r for r in team_rows if r["name"] == member), {})
        anomalies = []
        if row.get("risk") and row["risk"] != "正常":
            anomalies = [x for x in row["risk"].split("；") if x]
        sales.append({
            "id": slug,
            "name": member,
            "target_wan": targets.get(member),
            "process_rate": row.get("process_rate", 0),
            "log_submitted": row.get("log_submitted", False),
            "owned_customers": owner_counts[member],
            "metrics": metrics,
            "anomalies": anomalies,
            "risk": row.get("risk", "正常"),
        })

    pdca_actions = []
    action_dir = TEAM_PATH / "pdca_actions"
    next_day = (datetime.strptime(date_text, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    leader_path = action_dir / f"{next_day}_team_leader_actions.md"
    if leader_path.exists():
        for line in leader_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                pdca_actions.append(line[2:].strip())

    submitted = sum(1 for s in sales if s["log_submitted"])
    overdue_count = sum(1 for c in customers if c["overdue"])

    snapshot = {
        "meta": {
            "team": "杨晶晶小组",
            "as_of_date": date_text,
            "month": month,
            "source": "local:teams/yang-jingjing",
            "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        },
        "team": {
            "target_wan": targets.get("team"),
            "leader_share_pct": leader_share,
            "dealer_total": len(customers),
            "status": "需关注" if overdue_count or leader_share > 60 else "正常",
        },
        "kpis": [
            {"key": "logs", "label": "日报提交", "value": f"{submitted}/{len(MEMBERS)}", "tone": "ok" if submitted == len(MEMBERS) else "warn"},
            {"key": "overdue", "label": "超期客户", "value": str(overdue_count), "tone": "bad" if overdue_count else "ok"},
            {"key": "leader_share", "label": "组长客户占比", "value": f"{leader_share}%", "tone": "warn" if leader_share > 60 else "ok"},
            {"key": "dealers", "label": "负责客户总数", "value": str(len(customers)), "tone": "neutral"},
        ],
        "process_defaults": dict(defaults),
        "sales": sales,
        "dealers": customers,
        "regions": aggregate_regions(customers),
        "ai_insights": build_insights(team_rows, customers, leader_share),
        "pdca": {
            "team_check": str(team_check_path.relative_to(REPO_ROOT)) if team_check_path.exists() else None,
            "actions": pdca_actions[:8],
        },
    }
    return snapshot


def write_snapshot(snapshot, date_text):
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dated = SNAPSHOT_DIR / f"dealer-{date_text}.json"
    latest = SNAPSHOT_DIR / "dealer-latest.json"
    payload = json.dumps(snapshot, ensure_ascii=False, indent=2)
    dated.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    return dated, latest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--no-check", action="store_true", help="不重新跑 daily-team-check")
    args = parser.parse_args()
    snapshot = build_snapshot(args.date, run_check=not args.no_check)
    paths = write_snapshot(snapshot, args.date)
    print(f"Snapshot written: {paths[0]}")
    print(f"Latest: {paths[1]}")


if __name__ == "__main__":
    main()
