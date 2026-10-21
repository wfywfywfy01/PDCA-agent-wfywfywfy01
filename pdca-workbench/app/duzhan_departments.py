"""Confirmed department cohorts and one combined report per department."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re

from loguru import logger

from app.duzhan_ledger import OWNERS, count_text, daily_target_progress, infer_status, vemory_aliases, wan_text


@dataclass(frozen=True)
class Department:
    name: str
    group: str
    members: tuple[str, ...]
    english_name: str
    task_only_members: tuple[str, ...] = ()

    @property
    def metric_members(self) -> tuple[str, ...]:
        return tuple(name for name in self.members if name not in self.task_only_members)


# Identity aliases remain in OWNERS; this is the current reporting cohort.
DEPARTMENTS = (
    Department("经销商一部", "于冰业绩达标群", ("于冰",), "Dealer Dept 1"),
    Department("经销商二部", "杨晶晶业绩达标群", ("杨晶晶", "何海文", "王宇彤"), "Dealer Dept 2"),
    Department("经销商三部", "Lina业绩达标群", ("Lina", "Safae", "冯磊"), "Dealer Dept 3", task_only_members=("冯磊",)),
    Department("经销商四部", "viki业绩达标群", ("尤文静", "Sana", "张月馨"), "Dealer Dept 4"),
    Department("经销商五部", "Q4五百万", ("邓琳莹", "刘春梅", "付汪阳"), "Dealer Dept 5", task_only_members=("刘春梅", "付汪阳")),
)


def department_for(group_name: str) -> Department | None:
    return next((item for item in DEPARTMENTS if item.group == group_name), None)


def aliases(department: Department, member: str) -> set[str]:
    owner = next((owner for owner in OWNERS if owner.group == department.group
                  and member.casefold() in {name.casefold() for name in vemory_aliases(owner)}), None)
    return vemory_aliases(owner) if owner else {member}


def is_task_only(group_name: str, display: str) -> bool:
    department = department_for(group_name)
    return bool(department and any(display.casefold() in {name.casefold() for name in aliases(department, member)}
                                   for member in department.task_only_members))


def task_scope_row(row: dict) -> dict:
    """Remove legacy routine quota reminders, keeping concrete business tasks and proof."""
    from app.duzhan_ledger import _outreach_titles

    if not is_task_only(str(row.get("group") or ""), str(row.get("display") or "")):
        return row

    def routine(title: str) -> bool:
        report = re.search(r"(?:补交|补齐|提交|填写|上报)\s*(?:正式|海外|工作|今日|今天|当日|销售|\s)*日报", title)
        quota = ("mto" in title.casefold() or "高奢方案" in title) and re.search(
            r"(?:每日|每天|每人|补交|补齐|凑齐)\s*(?:MTO\s*)?[0-9一二三四五六七八九十两]+\s*款|MTO\s*(?:配额|指标)|"
            r"^(?:请\s*)?(?:(?:今日|今天|每日|每天|每人)\s*)*(?:补交|补齐|提交|完成|凑齐)?\s*"
            r"(?:[0-9一二三四五六七八九十两]+\s*款\s*)?MTO(?=$|\s|方案|高奢|和|及)",
            title, re.I,
        )
        process = _outreach_titles(title) and re.search(r"\d+\s*(?:人|户|个|contacts?|accounts?|people)", title, re.I)
        return bool(report or quota or process)

    result = dict(row)
    if isinstance(row.get("collections"), list):
        result["collections"] = [item for item in row["collections"]
                                 if isinstance(item, dict) and not routine(str(item.get("title") or ""))]
    if isinstance(row.get("evidence"), list):
        result["evidence"] = [item for item in row["evidence"]
                              if not str(item).startswith(("海外日报已交", "MTO图 ")) and not routine(str(item))]
    return result


def member_rows(department: Department, ledger: dict | None, *, metrics_only: bool = False) -> list[tuple[str, dict]]:
    rows = [task_scope_row(row) for row in (ledger or {}).get("people") or []
            if isinstance(row, dict) and row.get("group") == department.group]
    return [(member, next((row for row in rows
                           if str(row.get("display") or "").casefold()
                           in {alias.casefold() for alias in aliases(department, member)}), {}))
            for member in (department.metric_members if metrics_only else department.members)]


def people_for(group_name: str, ledger: dict | None) -> list[dict]:
    """Current cohort for conditions and AI facts; never adds an absent person's data."""
    department = department_for(group_name)
    if department is None:
        from app.duzhan_ledger import people_for as legacy_people_for

        return legacy_people_for(group_name, ledger)
    return [row for _name, row in member_rows(department, ledger) if row]


def _finite_number(value: object) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def total(rows: list[tuple[str, dict]], key: str) -> float | None:
    values = [row.get(key) for _name, row in rows]
    try:
        if not values or not all(_finite_number(value) for value in values):
            return None
        result = sum(values)
        return round(result, 2) if _finite_number(result) else None
    except (OverflowError, ValueError):
        return None


def _clip(text: object, limit: int = 90) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[:limit - 1] + "…"


def _items_line(items: list[str], fallback: str, limit: int = 3) -> str:
    items = list(dict.fromkeys(items))
    return ("；".join(_clip(item) for item in items[:limit])
            + (f" (+{len(items) - limit})" if len(items) > limit else "")) if items else fallback


def _belongs(who: str, department: Department) -> bool:
    return not who or any(alias.casefold() in who.casefold() for member in department.members
                          for alias in aliases(department, member) if len(alias) >= 2)


def _target(department: Department, day: str) -> dict:
    from app import daily_report

    try:
        if daily_report._configured_sales_target(day[:7]) is None:
            return {}
        payload = json.loads(daily_report._SALES_TARGETS_FILE.read_text(encoding="utf-8"))
        plan = next((dict(row) for row in payload[day[:7]].get("departments", [])
                     if row.get("name") == department.name), {})
        if plan.get("goal") == "break_zero":
            plan.pop("target_wan", None)
        elif "target_wan" in plan:
            plan["target_wan"] = float(plan["target_wan"])
            if not math.isfinite(plan["target_wan"]) or plan["target_wan"] < 0:
                return {}
        return plan
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        logger.warning("部门目标待确认 {} {}: {}", day, department.name, exc)
        return {}


def _tasks(rows: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    return [(name, item) for name, row in rows for item in row.get("collections") or []
            if isinstance(item, dict) and str(item.get("title") or "").strip()]


def _mto_summary(rows: list[tuple[str, dict]], english: bool) -> str:
    captured, counts, pending = [], [], []
    for name, row in rows:
        quotes = row.get("mto_quotes")
        source_count = row.get("mto_count")  # OCR returns qualified count, not submissions.
        quotes_known = isinstance(quotes, list) and all(isinstance(quote, dict) for quote in quotes)
        quotes = quotes if quotes_known else []
        checked = [quote for quote in quotes if _finite_number(quote.get("wan"))
                   and isinstance(quote.get("qualifies"), bool) and quote.get("raw_ok") is not False]
        qualified = sum(quote["qualifies"] and quote["wan"] >= 30 for quote in checked)
        counts.append(qualified)
        source_known = row.get("history_ok") is True and _finite_number(source_count) and source_count >= 0
        captured.append((name, {"count": len(quotes)
                                if quotes_known and source_known and source_count <= len(quotes) else None}))
        if not source_known or not quotes_known or len(checked) != len(quotes) or source_count != qualified:
            pending.append(name)
    seen = total(captured, "count")
    seen_text = ("pending" if english else "待确认") if seen is None else f"{seen:g}" + (" records" if english else "条")
    qualified_members = sum(count >= 4 for count in counts)
    text = (f"MTO: captured {seen_text} | verified {sum(counts)} qualified | {qualified_members}/{len(rows)} members at 4 each"
            if english else f"MTO核验：采集数{seen_text}｜已核达标{sum(counts)}款｜达标成员{qualified_members}/{len(rows)}（每人4款，单款≥30万）")
    return text + (("; pending: " if english else "；待核：") + "、".join(pending) if pending else "")


def render(department: Department, group, stage: int, day: str, slot: str, title: str,
           ledger: dict | None, prev_ledger: dict | None, *, previous_slot: str | None = None,
           focus_override: str | None = None) -> str:
    from app.meeting_todos import items_for_group
    from app.weekly_focus import items_for

    english = group.lang == "en"
    pending = "pending" if english else "待确认"
    rows = member_rows(department, ledger)
    previous = member_rows(department, prev_ledger)
    metric_rows = member_rows(department, ledger, metrics_only=True)
    arrived = total(rows, "perf_arrived_wan")
    tasks = _tasks(rows)
    open_tasks = [(name, item) for name, item in tasks if infer_status(item) != "done"]
    lines = [(f"[{title}] {department.english_name} | {day} {slot} ({group.tz})" if english
              else f"【{title}】{department.name}｜{day} {slot}（{group.tz}）")]
    if focus_override:
        lines.append(("Focus: " if english else "重点：") + _clip(focus_override, 100))

    def task_name(name: str, item: dict) -> str:
        text = str(item.get("text_en") or item.get("title") or "") if english else str(item.get("title") or "")
        return f"{name}：{text}"

    missing_amounts = sum(item.get("wan") is None for _name, row in metric_rows
                          for key in ("perf_slip", "perf_intent") for item in row.get(key) or []
                          if isinstance(item, dict))
    amount_note = ((f"; {missing_amounts} amount(s) pending" if english else f"；待补金额{missing_amounts}条")
                   if missing_amounts else "")

    if stage == 15:
        prior_arrived = total(previous, "perf_arrived_wan")
        if previous_slot == "":
            change = (f"Current booked: {wan_text(arrived, group.lang)} wan CNY" if english
                      else f"当前已录单：{wan_text(arrived)}万")
        else:
            delta = (round(arrived - prior_arrived, 2)
                     if arrived is not None and prior_arrived is not None else None)
            change = ("New this slot: " if english else "本档新增：") + (
                pending if delta is None else f"{delta:+g}" + (" wan CNY" if english else "万"))
        baseline = previous_slot if previous_slot is not None else "10:00"
        reply = (f"Reply: changes vs {baseline}, blockers and next deadline." if english
                 else f"请回：相对 {baseline} 的变化、卡点和下一步截止时间。") if baseline else (
                     "Reply: current progress, blockers and next deadline." if english
                     else "请回：当前进展、卡点和下一步截止时间。")
        lines.extend([change,
                      ("Open: " if english else "未闭环：")
                      + _items_line([task_name(name, item) for name, item in open_tasks],
                                    "status update needed" if english else "状态待回报", 3) + amount_note,
                      reply])
        return "\n".join(lines)

    plan = _target(department, day)
    goal = None if plan.get("goal") == "break_zero" else plan.get("target_wan")
    progress = daily_target_progress(goal, arrived, day)
    goal_text = ("first sale" if english else "破零") if plan.get("goal") == "break_zero" else (
        wan_text(goal) + (" wan CNY" if english else "万") if goal is not None else pending)
    booked = pending if arrived is None else wan_text(arrived) + (" wan CNY" if english else "万")
    sales_line = (f"Monthly target: {goal_text} | MTD booked: {booked}" if english
                  else f"部门月目标：{goal_text}｜累计已录单{booked}")
    unknown = [name for name, row in rows if not _finite_number(row.get("perf_arrived_wan"))]
    if unknown:
        sales_line += (" | confirm: " if english else "（待确认：") + "、".join(unknown) + ("" if english else "）")
    if stage == 10 and progress["daily_target"] is not None:
        sales_line += (f" | Daily: {progress['daily_target']:g} wan CNY" if english
                       else f"｜今日目标{progress['daily_target']:g}万")
    lines.append(sales_line)

    if stage == 10:
        lines.append(("Todo owners: " if english else "待办负责人：") + "、".join(department.members))
        daily = [task_name(name, item) for name, item in open_tasks]
        current_keys = {(name, item["title"]) for name, item in tasks}
        daily.extend(task_name(name, item) for name, item in _tasks(previous)
                     if infer_status(item) != "done" and (name, item["title"]) not in current_keys)
        for item in items_for_group(day, department.group):
            who = str(item.get("who") or "").strip()
            if _belongs(who, department) and str(item.get("text") or "").strip():
                text = (item.get("text_en") or item["text"]) if english else item["text"]
                daily.append((f"{who}：" if who else "") + str(text))
        lines.append(("Today's tasks: " if english else "今日待办：")
                     + _items_line(daily, "plan pending" if english else "待报本部今日计划", 5) + amount_note)
        weekly = []
        for member in department.members:
            for alias in sorted(aliases(department, member) | {member}):
                for item in items_for(day, department.group, alias):
                    who = str(item.get("who") or "").strip()
                    if _belongs(who, department):
                        text = str(item.get("text_en") or item.get("text") or "") if english else str(item.get("text") or "")
                        weekly.append((f"{who}：" if who else "") + text)
        lines.append(("This week: " if english else "本周待办：")
                     + _items_line(weekly, "reply with deliverables and due dates" if english else "请补本周交付事项和截止日"))
        lines.append((f"MTO plan: {4 * len(metric_rows)} proposals, 4 per person, each ≥ CNY 300k." if english
                      else f"MTO计划：共{4 * len(metric_rows)}款高奢方案（每人4款，单款≥30万），报客户与提交时间。")
                     + ((" Owners: " if english else "负责人：") + "、".join(department.metric_members)
                        if department.task_only_members else ""))
        lines.append("Reply with 3–5 department deliverables and deadlines." if english else "请回：本部今日3–5项交付物和截止时间。")
        return "\n".join(lines)

    done = len(tasks) - len(open_tasks)
    unknown_tasks = [name for name, row in rows
                     if row.get("history_ok") is not True or not isinstance(row.get("collections"), list)]
    if unknown_tasks:
        lines.append(("Closure: pending for " if english else "闭环核对：待确认：") + "、".join(unknown_tasks))
    else:
        lines.append((f"Closure: {done} done | {len(open_tasks)} open" if english
                      else f"闭环核对：已完成{done}项｜未闭环{len(open_tasks)}项") if tasks
                     else ("Closure: task status pending" if english else "闭环核对：待报事项状态"))
    for name, item in (open_tasks + [(name, item) for name, item in tasks if infer_status(item) == "done"])[:5]:
        status = ("done" if infer_status(item) == "done" else "open") if english else (
            "已完成" if infer_status(item) == "done" else "未闭环")
        lines.append(f"- {status}｜" + _clip(task_name(name, item)))
    lines.append(_mto_summary(metric_rows, english))
    missing, unverified, incomplete = [], [], []
    for name, row in metric_rows:
        if not row or row.get("daily_report_ok") is False:
            unverified.append(name)
        elif not row.get("daily_report"):
            missing.append(name)
        elif not (row["daily_report"].get("template") or {}).get("ok"):
            incomplete.append(name)
    report_parts = []
    for names, label in ((unverified, "pending" if english else "待确认"),
                         (missing, "not found" if english else "未见提交"),
                         (incomplete, "incomplete" if english else "缺项")):
        if names:
            report_parts.append(label + "：" + "、".join(names))
    lines.append(("Daily report check: " if english else "日报核对：")
                 + ("；".join(report_parts) if report_parts else (
                     "all sales process members complete" if english else "专项考核成员已提交且字段齐全")))
    reached, intent, minutes = (total(metric_rows, key) for key in ("wa_reached", "intent_count", "hours_minutes"))
    hours = pending if minutes is None else wan_text(minutes / 60) + (" person-hours" if english else "人时")
    reached_text = count_text(reached, lower_bound=any(row.get("wa_lower_bound") is True for _name, row in metric_rows),
                              lang=group.lang)
    if english:
        lines.append(f"Sales process totals: WhatsApp {reached_text} contacts | intent {wan_text(intent, group.lang)} | estimated {hours}")
    else:
        wa_text = pending if reached is None else reached_text + "户次"
        intent_text = pending if intent is None else wan_text(intent) + "户次"
        lines.append(f"成员合计（专项考核）：WhatsApp触达{wa_text}（明确意向{intent_text}）｜留痕折算{hours}")
    for key, label in (("perf_slip", "Payment slips: " if english else "水单："),
                       ("perf_intent", "Intent amounts: " if english else "意向金额：")):
        entries = [f"{name}：{item.get('amount_text') or pending}" for name, row in metric_rows
                   for item in row.get(key) or [] if isinstance(item, dict)]
        if entries:
            lines.append(label + _items_line(entries, pending, 2))
    for key, label in (("blockers", "Blockers: " if english else "卡点："),
                       ("evidence", "Evidence: " if english else "证据：")):
        entries = [f"{name}：{item}" for name, row in rows for item in row.get(key) or []]
        lines.append(label + _items_line(entries, "pending" if english else "待补", 3))
    lines.append(("First action tomorrow: " if english else "明日第一动作：")
                 + _items_line([task_name(name, item) for name, item in open_tasks],
                               "confirm the department plan" if english else "确认本部明日计划", 3))
    return "\n".join(lines)
