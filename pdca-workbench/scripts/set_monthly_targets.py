# -*- coding: utf-8 -*-
"""月度目标维护脚本（单一来源：app/monthly_sales_targets.json）。

月度目标每月由用户更新，这个脚本只做「确定性写文件 + 校验」，不猜数字。

常用用法::

    # 看当前文件
    python scripts/set_monthly_targets.py --show

    # 用上月条目起底，再把本月改动的写进去（最省事）
    python scripts/set_monthly_targets.py --month 2026-10 --copy-from 2026-09 \
        --dept 1500 --person 于冰=260 --person 杨晶晶=400 \
        --group 新部=100:邓琳莹,Safae,王宇彤,张月馨

    # 只预演不落盘
    python scripts/set_monthly_targets.py --month 2026-10 --copy-from 2026-09 --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS_FILE = ROOT / "app" / "monthly_sales_targets.json"


def load() -> dict:
    try:
        data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"目标文件不是合法 JSON：{TARGETS_FILE}（{exc}）")
    if not isinstance(data, dict):
        raise SystemExit(f"目标文件顶层必须是对象：{TARGETS_FILE}")
    return data


def parse_person(raw: str) -> tuple[str, float]:
    if "=" not in raw:
        raise SystemExit(f"--person 需要 姓名=目标万 的格式，收到：{raw}")
    name, _, value = raw.partition("=")
    name = name.strip()
    if not name:
        raise SystemExit(f"--person 姓名为空：{raw}")
    return name, _num(value, raw)


def _num(value: str, raw: str) -> float:
    try:
        num = float(str(value).strip())
    except ValueError:
        raise SystemExit(f"目标必须是数字（万），收到：{raw}")
    if num <= 0:
        raise SystemExit(f"目标必须大于 0，收到：{raw}")
    return int(num) if num.is_integer() else num


def parse_group(raw: str) -> dict:
    """新部=100:邓琳莹,Safae → {"name": "新部", "target_wan": 100, "members": [...]}"""
    head, _, members_raw = raw.partition(":")
    name, target = parse_person(head)
    members = [item.strip() for item in members_raw.split(",") if item.strip()]
    if not members:
        raise SystemExit(f"--group 需要 组名=目标万:成员1,成员2 的格式，收到：{raw}")
    return {"name": name, "target_wan": target, "members": members}


def merge(existing: list[dict], people: list[tuple[str, float]], groups: list[dict]) -> list[dict]:
    """按 name 覆盖/追加，保留文件原有顺序，避免每次更新把顺序打乱。"""
    entries = [dict(item) for item in existing]
    index = {str(item.get("name")): pos for pos, item in enumerate(entries)}
    for name, target in people:
        if name in index:
            entries[index[name]]["target_wan"] = target
            entries[index[name]].pop("members", None)
        else:
            entries.append({"name": name, "target_wan": target})
    for group in groups:
        name = group["name"]
        if name in index:
            entries[index[name]].update(group)
        else:
            entries.append(group)
    return entries


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="维护 app/monthly_sales_targets.json")
    parser.add_argument("--month", help="目标月份，格式 YYYY-MM")
    parser.add_argument("--dept", help="部门月目标（万）")
    parser.add_argument("--person", action="append", default=[], help="姓名=目标万，可重复")
    parser.add_argument("--group", action="append", default=[], help="组名=目标万:成员1,成员2，可重复")
    parser.add_argument("--copy-from", dest="copy_from", help="用这个月份（YYYY-MM）的条目作为底稿")
    parser.add_argument("--show", action="store_true", help="只打印当前文件内容")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    parser.add_argument("--allow-mismatch", dest="allow_mismatch", action="store_true",
                        help="明细合计与部门目标不一致时也允许写入（默认拒绝）")
    parser.add_argument("--file", help="覆盖目标文件路径（测试用）")
    args = parser.parse_args(argv)
    global TARGETS_FILE
    if args.file:
        TARGETS_FILE = Path(args.file)
    data = load()
    if args.show or (not args.month and not args.copy_from):
        print(json.dumps(data, ensure_ascii=False, indent=2))
        if args.show:
            return 0
        print("\n提示：带 --month 才会写入。", file=sys.stderr)
        return 0
    if not args.month:
        raise SystemExit("--copy-from 需要同时给 --month")
    month = args.month.strip()
    base = []
    if args.copy_from:
        src = (data.get(args.copy_from.strip()) or {}).get("entries") or []
        if not src:
            raise SystemExit(f"--copy-from {args.copy_from} 在目标文件里没有 entries")
        base = [dict(item) for item in src]
    elif (data.get(month) or {}).get("entries"):
        base = [dict(item) for item in data[month]["entries"]]
    entries = merge(base, [parse_person(raw) for raw in args.person], [parse_group(raw) for raw in args.group])
    block = {"entries": entries}
    dept = data.get(month, {}).get("department_target_wan")
    if args.copy_from:
        dept = (data.get(args.copy_from.strip()) or {}).get("department_target_wan", dept)
    if args.dept:
        dept = _num(args.dept, args.dept)
    if dept is not None:
        block["department_target_wan"] = dept
    # 与 app/daily_report.py 同一条不变量：明细合计必须等于部门目标，
    # 否则日报任务会直接抛错。写盘前先拦下来，别等生产定时任务失败。
    total = sum(float(item.get("target_wan") or 0) for item in entries)
    declared = block.get("department_target_wan")
    if declared is not None and abs(total - float(declared)) > 0.01 and not args.allow_mismatch:
        raise SystemExit(
            f"明细合计 {total:g} 万 ≠ 部门目标 {float(declared):g} 万：请调整个别目标，"
            "或确认确实不一致时加 --allow-mismatch"
        )
    data[month] = block
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.dry_run:
        print(text)
        return 0
    tmp = TARGETS_FILE.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(TARGETS_FILE)
    print(f"已写入 {TARGETS_FILE}（{month}：{len(entries)} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())