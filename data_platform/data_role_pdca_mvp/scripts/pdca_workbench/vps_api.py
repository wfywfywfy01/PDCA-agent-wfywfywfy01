# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：VPS 数据 API（今日计划/待办/会议/任务中心/重要事项）
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def fetch_pdca_today_plan(date_text):
    """今日待办：取昨日 IM 群日报 payload.tomorrow（vertu odoo daily-report user-summary）。"""
    yesterday_text = previous_date_text(date_text)
    if should_use_local_pdca_cache(date_text):
        yesterday = local_daily_report_cache(yesterday_text, "本地汇报缓存")
    else:
        yesterday = fetch_vps_daily_report(yesterday_text)
    rows = report_payload_items(yesterday, "tomorrow") if yesterday.get("ok") else []
    warning = yesterday.get("warning") or yesterday.get("error") or ""
    if yesterday.get("from_cache"):
        warning = warning or "VPS 暂不可用，已使用本地日报/待办缓存。"
    return {
        "ok": yesterday.get("ok", False),
        "rows": rows,
        "yesterday": yesterday_text,
        "report_count": len(yesterday.get("reports") or []),
        "warning": warning.strip(),
        "from_cache": bool(yesterday.get("from_cache")),
    }


def api_todos_today(date_text=None):
    date_text = date_text or today_text()
    plan = fetch_pdca_today_plan(date_text)
    if not plan["ok"]:
        detail = plan["warning"] or "昨日日报拉取失败"
        return [{
            "id": 0,
            "title": f"PDCA 日结：{detail[:100]}",
            "status": "异常",
            "source": "PDCA 日结",
            "yesterday": plan["yesterday"],
        }]
    rows = plan["rows"]
    if not rows:
        hint = "昨日日报未写入明日计划" if plan["report_count"] else "未查询到昨日群日报"
        return [{
            "id": 0,
            "title": f"PDCA 日结：{hint}（{plan['yesterday']}）",
            "status": "待补充",
            "source": "PDCA 日结",
            "yesterday": plan["yesterday"],
        }]
    items = []
    for index, row in enumerate(rows[:15], start=1):
        progress = task_progress(row)
        status = nested_value(row, "state_display", "status_name", "status.name", "stage_name") or "待处理"
        if progress >= 100:
            status = "已完成"
        elif progress > 0 and status in ("", "待处理", "未开始"):
            status = f"进行中 {progress}%"
        items.append({
            "id": index,
            "title": task_title(row) or "未命名事项",
            "status": status,
            "progress": progress,
            "deadline": task_deadline(row) or date_text,
            "source": "昨日日报·明日计划",
            "yesterday": plan["yesterday"],
            "from_cache": plan["from_cache"],
        })
    return items


def api_hermes_agent_tasks(date_text):
    todos = api_todos_today(date_text)
    tasks = []
    for row in todos[:3]:
        if "拉取失败" in row["title"]:
            continue
        tasks.append({"id": row["id"], "title": f"Hermes：跟进待办「{row['title']}」"})
    if not tasks:
        tasks = [
            {"id": 1, "title": "Hermes：运行今日 PDCA 并刷新数据看板"},
            {"id": 2, "title": "Hermes：核对代理商终销与 Walk-in 客流异常"},
        ]
    out = output_dir(date_text)
    if not (out / "dashboard.html").exists():
        tasks.insert(0, {"id": 0, "title": "Hermes：生成今日 dashboard.html"})
    return tasks[:5]


def api_customer_center_summary(session_user=None):
    dealers = filter_dealers_for_user(load_dealer_reference(), session_user)
    buckets = {"S": [], "A": [], "B": [], "C": []}
    for dealer in dealers:
        ctype = (dealer.get("customerType") or "S").upper()[:1]
        if ctype not in buckets:
            ctype = "C"
        buckets[ctype].append(dealer)
    result = []
    for level in ("S", "A", "B", "C"):
        rows = buckets[level]
        target = CUSTOMER_TIER_TARGETS[level]
        touched = None
        result.append({"level": level, "total": len(rows), "touched": touched, "target": target})
    return result


def api_hr_summary():
    return [
        {"key": "resume", "label": "简历数", "value": 0},
        {"key": "interview", "label": "面试数", "value": 0},
        {"key": "onboard", "label": "到岗数", "value": 0},
        {"key": "leave", "label": "离职数", "value": 0},
        {"key": "leaveRate", "label": "离职率", "value": "—"},
    ]


def api_exceptions(date_text):
    business = []
    affair = []
    dealers = load_dealer_reference()
    low_sell = [d for d in dealers if float(d.get("sellOutAmount") or 0) <= 0]
    if low_sell:
        business.append({
            "owner": "代理商终销",
            "content": f"{len(low_sell)} 家代理商终销金额为 0，请更新 Excel 后重跑导入脚本",
        })
    out = output_dir(date_text)
    pdca_path = out / "pdca_daily_check.md"
    if pdca_path.is_file():
        for line in pdca_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if not text.startswith("-") and "风险" not in text and "异常" not in text:
                continue
            if "日报" in text or "待办" in text:
                affair.append({"owner": "PDCA", "content": text.lstrip("- ").strip()[:120]})
            else:
                business.append({"owner": "PDCA", "content": text.lstrip("- ").strip()[:120]})
            if len(business) + len(affair) >= 6:
                break
    im_unread = fetch_vps_im_unread(with_latest=False)
    if im_unread["ok"] and im_unread["unread_count"] > 0:
        affair.append({
            "owner": "IM",
            "content": f"{im_unread['unread_count']} 条未读消息分布在 {im_unread['channel_count']} 个会话",
        })
    todos = fetch_vps_today_todos()
    if todos["ok"] and todos["count"] > 8:
        affair.append({"owner": "待办", "content": f"今日待办 {todos['count']} 项，存在积压风险"})
    if not (out / "dashboard.html").exists():
        business.append({"owner": "数据看板", "content": f"{date_text} 数据看板尚未生成，请运行 PDCA"})
    return {"business": business[:6], "affair": affair[:6]}


def api_important_matters(date_text):
    matters = []
    dealers = load_dealer_reference()
    if dealers:
        teams = {}
        for d in dealers:
            teams[d.get("team") or "未分组"] = teams.get(d.get("team") or "未分组", 0) + 1
        top_team = max(teams.items(), key=lambda item: item[1])[0]
        matters.append({
            "id": 1,
            "title": f"{top_team} 组代理商覆盖 {teams[top_team]} 家",
            "desc": "建议对照 Walk-in 客流分析台检查低留资率代理商。",
            "suggestion": "今日打开海外客流看板，筛选留资率偏低代理商并安排督导跟进。",
        })
    todos = fetch_vps_today_todos()
    if todos["ok"] and todos["rows"]:
        first = todos["rows"][0]
        title = nested_value(first, "title", "name") or "待办"
        matters.append({
            "id": 2,
            "title": f"优先待办：{title}",
            "desc": "来自 VPS 今日待办列表。",
            "suggestion": "今日内更新状态并同步到 PDCA 日结。",
        })
    if not matters:
        matters.append({
            "id": 1,
            "title": "运行今日 PDCA",
            "desc": "产出 Excel、报告与看板后驾驶舱指标将自动丰富。",
            "suggestion": "执行 run_data_role_pdca_daily.ps1 或从经典首页触发运行。",
        })
    return matters[:4]


def fetch_pdca_delivery_summary(date_text):
    """今日计划交付统计（昨日明日计划 vs 今日完成 vs VPS 待办）。"""
    yesterday_text = previous_date_text(date_text)
    if should_use_local_pdca_cache(date_text):
        daily = local_daily_report_cache(date_text, "本地汇报缓存")
        yesterday = local_daily_report_cache(yesterday_text, "本地汇报缓存")
        all_todos = {"ok": True, "rows": local_todo_payload_rows(date_text), "count": 0, "error": ""}
    else:
        daily = fetch_vps_daily_report(date_text)
        yesterday = fetch_vps_daily_report(yesterday_text)
        all_todos = fetch_vps_all_todos()
    today_plan_rows = report_payload_items(yesterday, "tomorrow") if yesterday.get("ok") else []
    today_done_rows = report_payload_items(daily, "today") if daily.get("ok") else []
    checks = build_delivery_checks(
        today_plan_rows,
        today_done_rows,
        all_todos["rows"] if all_todos["ok"] else [],
        date_text,
    )
    stats = {"done": 0, "progress": 0, "pending": 0, "risk": 0}
    for item in checks:
        level = item.get("level") or "pending"
        stats[level] = stats.get(level, 0) + 1
    return {
        "yesterday": yesterday_text,
        "plan_count": len(today_plan_rows),
        "stats": stats,
    }


def api_task_center_panel(date_text=None):
    """任务中心：统计 + 昨日日报明日计划列表。"""
    date_text = date_text or today_text()
    plan = fetch_pdca_today_plan(date_text)
    delivery = fetch_pdca_delivery_summary(date_text)
    items = api_todos_today(date_text)
    stats = delivery["stats"]
    total = delivery["plan_count"]
    if total == 0 and items and not str(items[0].get("title", "")).startswith("PDCA 日结："):
        total = len(items)
    done = stats.get("done", 0)
    return {
        "summary": [
            {"key": "total", "label": "总任务数", "value": total},
            {"key": "done", "label": "已完成", "value": done},
            {"key": "undone", "label": "未完成", "value": max(0, total - done)},
        ],
        "yesterday": plan.get("yesterday") or delivery["yesterday"],
        "sourceNote": "vertu odoo daily-report · 昨日群日报「明日计划」",
        "items": items,
    }


def api_task_center_summary(date_text=None):
    """任务中心入口统计：今日计划交付概况（点击进入 PDCA 日结页）。"""
    date_text = date_text or today_text()
    delivery = fetch_pdca_delivery_summary(date_text)
    stats = delivery["stats"]
    total = delivery["plan_count"]
    done = stats.get("done", 0)
    return [
        {"key": "total", "label": "总任务数", "value": total},
        {"key": "done", "label": "已完成", "value": done},
        {"key": "undone", "label": "未完成", "value": max(0, total - done)},
    ]


def enrich_vemory_meetings(payload: dict) -> dict:
    """为会议列表附加首页分类与任务分配建议。"""
    if not payload or not isinstance(payload.get("meetings"), list):
        return payload or {}
    meetings = []
    for meeting in payload["meetings"]:
        row = dict(meeting)
        if classify_meeting_bucket:
            row["bucket"] = classify_meeting_bucket(row)
        if todo_assignments:
            row["assignments"] = todo_assignments(row)
        meetings.append(row)
    payload = dict(payload)
    payload["meetings"] = meetings
    if meeting_center_counts:
        payload["counts"] = meeting_center_counts(meetings)
    return payload


def api_meeting_center_summary(date_text=None, end_date=None):
    date_text = date_text or today_text()
    if not fetch_vemory_meetings:
        return [
            {"key": "total", "label": "总会议数", "value": 0},
            {"key": "interview", "label": "面试会议", "value": 0},
            {"key": "report", "label": "汇报会议", "value": 0},
            {"key": "customer", "label": "客户会议", "value": 0},
        ]
    payload = enrich_vemory_meetings(
        fetch_vemory_meetings(date_text, vertu_cmd=vertu_command(), end_date=end_date or "")
    )
    counts = payload.get("counts") or meeting_center_counts(payload.get("meetings") or [])
    labels = {
        "total": "总会议数",
        "interview": "面试会议",
        "report": "汇报会议",
        "customer": "客户会议",
    }
    return [{"key": key, "label": labels[key], "value": counts.get(key, 0)} for key in labels]


def api_meeting_center_meetings(date_text, person_phone="", person_name="", end_date=""):
    if not fetch_vemory_meetings:
        return {"ok": False, "error": "vemory_bridge 未加载", "meetings": [], "counts": {}, "summary": {}}
    payload = enrich_vemory_meetings(
        fetch_vemory_meetings(date_text, person_phone, person_name, vertu_cmd=vertu_command(), end_date=end_date or "")
    )
    return payload


def api_meeting_center_people():
    if not vemory_people:
        return {"ok": True, "people": []}
    return {"ok": True, "people": vemory_people()}


def api_meeting_center_dispatch(body: dict, date_text: str):
    assignments = body.get("assignments") or []
    meeting_title = body.get("meeting_title") or "会议"
    if not assignments:
        return {"ok": False, "error": "没有待分配事项"}
    created = 0
    errors = []
    for item in assignments:
        todo = item.get("todo") or {}
        title = (todo.get("text") or "").strip() or "会议待办"
        assignee = (item.get("assignee") or "").strip()
        customer = (item.get("customer") or "").strip()
        reason = (item.get("reason") or "").strip()
        remark_parts = [f"来源：Vemory 会议「{meeting_title}」", reason]
        if assignee:
            remark_parts.append(f"建议负责人：{assignee}")
        if customer:
            remark_parts.append(f"关联客户：{customer}")
        remark = "；".join(part for part in remark_parts if part)
        due = normalize_deadline_for_vps(todo.get("due") or date_text)
        try:
            args = ["odoo", "project", "todo", "create", "--title", title, "--remark", remark]
            if due:
                args.extend(["--deadline", due])
            run_vertu_write_json(args)
            created += 1
        except Exception as exc:
            errors.append(f"{title}：{exc}")
    if created and not errors:
        return {"ok": True, "message": f"已从会议「{meeting_title}」写入 {created} 条 VPS 待办。"}
    if created:
        return {
            "ok": True,
            "message": f"已写入 {created} 条，{len(errors)} 条失败：{'；'.join(errors[:3])}",
        }
    return {"ok": False, "error": errors[0] if errors else "VPS 待办写入失败"}


def dispatch_home_dashboard_api(path, query):
    date_text = query.get("date", [today_text()])[0] or today_text()
    period = query.get("period", ["day"])[0] or "day"
    routes = {
        "/api/dashboard/overview": lambda: api_dashboard_overview(date_text, period),
        "/api/dashboard/sell-in": lambda: {
            "amount": api_dashboard_overview(date_text, period)["sellInAmount"],
            "wan": api_dashboard_overview(date_text, period)["sellInWan"],
            "note": api_dashboard_overview(date_text, period)["sellInSub"],
        },
        "/api/dashboard/sell-out": lambda: {
            "amount": api_dashboard_overview(date_text, period)["sellOutAmount"],
        },
        "/api/todos/today": lambda: api_todos_today(date_text),
        "/api/hermes-agent/tasks": lambda: api_hermes_agent_tasks(date_text),
        "/api/customer-center/summary": api_customer_center_summary,
        "/api/hr/summary": api_hr_summary,
        "/api/exceptions": lambda: api_exceptions(date_text),
        "/api/important-matters": lambda: api_important_matters(date_text),
        "/api/task-center/summary": lambda: api_task_center_summary(date_text),
        "/api/task-center/panel": lambda: api_task_center_panel(date_text),
        "/api/meeting-center/summary": lambda: api_meeting_center_summary(date_text),
        "/api/meeting-center/meetings": lambda: api_meeting_center_meetings(
            date_text,
            (query.get("phone") or [""])[0],
            (query.get("name") or [""])[0],
        ),
        "/api/meeting-center/people": api_meeting_center_people,
    }
    factory = routes.get(path)
    if not factory:
        return None
    return factory()
