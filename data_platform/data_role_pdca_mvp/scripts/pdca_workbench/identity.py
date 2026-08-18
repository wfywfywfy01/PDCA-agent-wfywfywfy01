# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：VPS 身份解析、日报/待办/OKR 缓存
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def workbench_role_label(role: str) -> str:
    """8767 登录角色 → 展示用岗位/权限文案。"""
    mapping = {
        "admin": "系统管理员",
        "manager": "海外中台主管",
        "sales": "经销商销售",
        "dealer": "经销商门店",
        "viewer": "只读访客",
    }
    return mapping.get((role or "").strip().lower(), role or "工作台用户")


def employee_job_label(row: dict) -> str:
    """从 hr.employee 行提取岗位/部门展示。"""
    job = many2one_name(row.get("job_id")) or row.get("job_title") or ""
    dept = many2one_name(row.get("department_id")) or ""
    if job and dept:
        return f"{dept} · {job}"
    return job or dept or ""


def lookup_vps_user_by_name(name_hint: str) -> dict | None:
    """按 res.users 显示名模糊匹配。"""
    text = (name_hint or "").strip()
    if not text:
        return None
    safe = quote_odoo_domain_value(text)
    rows, err = odoo_data_search("res.users", f"name ilike '{safe}'", "id,name,login", 3)
    if err or not rows:
        return None
    target = text.lower()
    for row in rows:
        if str(row.get("name") or "").lower() == target:
            return row
    return rows[0]


def lookup_vps_employee_by_hint(hint: str) -> dict | None:
    """
    按姓名在 VPS hr.employee 中模糊匹配。

    @param hint 姓名或登录名
    @returns 员工 dict 或 None
    """
    text = (hint or "").strip()
    if not text:
        return None
    safe = quote_odoo_domain_value(text)
    rows, err = odoo_data_search(
        "hr.employee",
        f"active = True AND name ilike '%{safe}%'",
        "id,name,department_id,job_id,job_title,work_email,user_id",
        8,
    )
    if err or not rows:
        return None
    target = text.lower()
    for row in rows:
        name = str(row.get("name") or "")
        if name.lower() == target:
            return row
    return rows[0]


def lookup_vps_user_by_login(login: str) -> dict | None:
    """按 res.users.login 精确匹配。"""
    text = (login or "").strip()
    if not text:
        return None
    safe = quote_odoo_domain_value(text)
    rows, err = odoo_data_search("res.users", f"login = '{safe}'", "id,name,login", 1)
    if err or not rows:
        return None
    return rows[0]


def is_generic_profile_label(text: str, role: str) -> bool:
    """是否为角色占位文案，不能当作真实姓名展示。"""
    label = (text or "").strip()
    if not label:
        return True
    if label == workbench_role_label(role):
        return True
    generic = {
        "系统管理员",
        "海外中台主管",
        "只读访客",
        "经销商销售",
        "经销商门店",
        "工作台用户",
        "数据岗",
        "PDCA 工作台",
    }
    return label in generic


def person_name_hints(session_user: dict) -> list[str]:
    """从登录会话提取可用于 VPS 姓名匹配的关键词（排除角色占位）。"""
    username = str(session_user.get("username") or "").strip()
    display_name = str(session_user.get("display_name") or "").strip()
    sales_name = str(session_user.get("sales_name") or "").strip()
    role = str(session_user.get("role") or "").strip()
    hints: list[str] = []
    for item in [sales_name, display_name, username]:
        if item and not is_generic_profile_label(item, role) and item not in hints:
            hints.append(item)
    return hints


def profile_from_vps_me(vu: dict, role: str) -> tuple[str, str]:
    """从 vertu odoo me 解析姓名与组织岗位。"""
    name = nested_value(vu, "employee_name", "name", "display_name")
    job = nested_value(vu, "job_title", "role") or ""
    employee_id = vu.get("employee_id") or vu.get("employeeId")
    if employee_id:
        rows, _ = odoo_data_search(
            "hr.employee",
            f"id = {int(employee_id)}",
            "id,name,department_id,job_id,job_title",
            1,
        )
        if rows:
            name = str(rows[0].get("name") or name)
            job = employee_job_label(rows[0]) or job
    if not job:
        job = workbench_role_label(role)
    return name, job


def resolve_workbench_profile(session_user: dict | None) -> tuple[str, str, str]:
    """
    根据 8767 登录账号解析姓名与岗位（优先 VPS）。

    @returns (name, job_title, source)
    """
    if not session_user:
        return "", "", "none"
    username = str(session_user.get("username") or "").strip()
    display_name = str(session_user.get("display_name") or "").strip()
    sales_name = str(session_user.get("sales_name") or "").strip()
    role = str(session_user.get("role") or "").strip()
    hints = person_name_hints(session_user)
    # 注意：这里不能无条件用 fetch_vps_identity()（服务器本机 vertu 会话）去猜"这是谁"——
    # 那是运行这个进程的机器当前登录的 VPS 账号，和实际发请求登录 8767 的人没有任何绑定关系。
    # 之前这里对 admin/manager/viewer 三个角色无条件信任它，导致不管谁用这几个账号登录，
    # 姓名都被覆盖成服务器机器上 vertu 登录的那个人（一直显示"付汪阳"）。
    # 下面 username==me_login 或姓名命中 hints 才采信的那次 fetch_vps_identity() 调用才是安全的。

    for hint in hints:
        employee = lookup_vps_employee_by_hint(hint)
        if employee:
            name = str(employee.get("name") or hint)
            job = employee_job_label(employee) or workbench_role_label(role)
            return name, job, "vps-hr.employee"

    if username:
        odoo_user = lookup_vps_user_by_login(username)
        if odoo_user:
            name = str(odoo_user.get("name") or "")
            if name and not is_generic_profile_label(name, role):
                return name, workbench_role_label(role), "vps-res.users"

    for hint in hints:
        odoo_user = lookup_vps_user_by_name(hint)
        if odoo_user:
            name = str(odoo_user.get("name") or hint)
            return name, workbench_role_label(role), "vps-res.users-name"

    identity = fetch_vps_identity()
    if identity.get("ok"):
        vu = identity.get("user") or {}
        me_name, me_job = profile_from_vps_me(vu, role)
        me_login = str(vu.get("login") or "").strip()
        if me_name and (
            username and me_login == username
            or any(h and (h in me_name or me_name in h) for h in hints)
        ):
            return me_name, me_job, "vps-me"

    name = hints[0] if hints else (username or "工作台用户")
    if is_generic_profile_label(name, role):
        name = username or "工作台用户"
    return name, workbench_role_label(role), "session"


def fetch_vps_identity():
    try:
        payload, _ = run_vertu_json("current_user", ["odoo", "me"])
        return {"ok": True, "user": payload, "error": ""}
    except Exception as exc:
        return {"ok": False, "user": {}, "error": str(exc)}


def fetch_vps_all_todos():
    try:
        payload, _ = run_vertu_json(
            "all_todos",
            ["odoo", "project", "todo", "list", "--for-me", "--all-pages", "--limit", "100"],
        )
        rows = payload.get("results") or payload.get("items") or []
        return {"ok": True, "rows": rows, "count": int(payload.get("count") or len(rows)), "error": ""}
    except Exception as exc:
        return {"ok": False, "rows": [], "count": 0, "error": str(exc)}


def fetch_vps_daily_report(date_text):
    identity = fetch_vps_identity()
    if not identity["ok"]:
        return local_daily_report_cache(date_text, identity["error"])
    user_id = identity["user"].get("user_id")
    if not user_id:
        return local_daily_report_cache(date_text, "VPS 当前用户缺少 user_id")
    try:
        payload, _ = run_vertu_json(
            f"daily_report_{user_id}_{date_text}",
            [
                "odoo",
                "daily-report",
                "user-summary",
                "--user-id",
                str(user_id),
                "--start-time",
                date_text,
                "--end-time",
                date_text,
            ],
            timeout=45,
        )
        return {
            "ok": True,
            "identity": identity,
            "reports": payload.get("daily_reports") or [],
            "okrs": payload.get("okrs") or [],
            "raw": payload,
            "error": "",
        }
    except Exception as exc:
        return local_daily_report_cache(date_text, str(exc), identity)


def local_identity_cache(identity=None):
    if identity and identity.get("ok"):
        return identity
    return {"ok": True, "user": {"name": "本地缓存用户", "user_id": "local-cache", "employee_id": "local-cache"}, "error": ""}


def local_todo_payload_rows(date_text):
    rows = read_csv_rows(todo_path(date_text))
    return [
        {
            "title": row.get("title", ""),
            "status": row.get("status", ""),
            "status_name": row.get("status", ""),
            "deadline": row.get("due_date", ""),
            "due_date": row.get("due_date", ""),
            "progress": "100" if str(row.get("status", "")).lower() in {"done", "completed", "已完成", "完成"} else "0",
            "source": row.get("source", "local-cache"),
            "priority": row.get("priority", ""),
            "note": row.get("notes", ""),
        }
        for row in rows
        if row.get("title")
    ]


def local_daily_report_cache(date_text, reason="", identity=None):
    report_path = output_dir(date_text) / "pdca_daily_check.md"
    report_text = compact_text(read_text(report_path), 240) if report_path.exists() else "本地暂未生成 PDCA 日结。"
    today_rows = local_todo_payload_rows(date_text)
    tomorrow_rows = local_todo_payload_rows((datetime.strptime(date_text, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text) else []
    reports = [
        {
            "created_at": f"{date_text} 本地缓存",
            "status": "本地缓存",
            "summary": f"VPS 暂不可用，展示本地 PDCA/待办缓存。{reason}",
            "payload": {"today": today_rows, "tomorrow": tomorrow_rows or today_rows},
        }
    ]
    if today_rows or report_path.exists():
        reports[0]["content"] = report_text
    return {
        "ok": True,
        "from_cache": True,
        "identity": local_identity_cache(identity),
        "reports": reports,
        "okrs": [],
        "raw": {"source": "local-cache", "reason": reason},
        "error": "",
        "warning": f"VPS 暂不可用，已显示本地缓存：{reason}",
    }


def previous_date_text(date_text):
    try:
        return (datetime.strptime(date_text, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def report_payload_items(daily, key):
    rows = []
    for report in daily.get("reports", []):
        payload = report.get("payload") or {}
        values = payload.get(key) or []
        if isinstance(values, list):
            rows.extend(values)
    return rows


def fetch_vps_month_okr(date_text):
    identity = fetch_vps_identity()
    if not identity["ok"]:
        return local_month_okr_cache(date_text, identity["error"])
    employee_id = identity["user"].get("employee_id") or identity["user"].get("user_id")
    period = date_text[:7]
    try:
        payload, _ = run_vertu_json(
            f"month_okr_{employee_id}_{period}",
            ["odoo", "okr", "employee-okr-list", "--okr-period", period, "--employee-ids", str(employee_id)],
        )
        results = payload.get("results") or []
        objectives = []
        for item in results:
            objectives.extend(item.get("objectives") or [])
        return {"ok": True, "rows": objectives, "count": len(objectives), "error": ""}
    except Exception as exc:
        return local_month_okr_cache(date_text, str(exc))


def local_month_okr_cache(date_text, reason=""):
    rows = [
        {
            "title": row.get("title", ""),
            "name": row.get("title", ""),
            "score": "本地待办",
            "key_results": [{"name": row.get("notes", "") or row.get("source", "local-cache")}],
        }
        for row in read_csv_rows(todo_path(date_text))
        if row.get("title")
    ]
    return {"ok": True, "from_cache": True, "rows": rows, "count": len(rows), "error": "", "warning": reason}


def should_use_local_pdca_cache(date_text):
    """正式口径优先 vertu CLI；仅演示或显式环境变量时使用本地 CSV/输出缓存。"""
    force = os.environ.get("PDCA_USE_LOCAL_CACHE", "").strip().lower()
    if force in ("1", "true", "yes"):
        return True
    data_sources = read_json(WORKSPACE / "config" / "data_sources.json")
    if str(data_sources.get("official_source", "")).strip().lower() == "vps":
        return False
    return bool(data_sources.get("sales_json")) and (
        todo_path(date_text).exists() or (output_dir(date_text) / "pdca_daily_check.md").exists()
    )


def pdca_vps_source_note(daily, yesterday, month_okr, all_todos):
    """页面上标注当前 PDCA 日结数据来源（VPS 真数 vs 本地回退）。"""
    parts = []
    if daily.get("from_cache") or yesterday.get("from_cache"):
        hint = daily.get("warning") or yesterday.get("warning") or "VPS 暂不可用"
        parts.append(f"群日报：本地缓存（{hint}）")
    elif daily.get("ok") or yesterday.get("ok"):
        parts.append("群日报：vertu odoo daily-report user-summary")
    if month_okr.get("from_cache"):
        parts.append("月待办：本地 CSV 回退")
    elif month_okr.get("ok"):
        parts.append(f"月待办：vertu okr employee-okr-list（{month_okr.get('count', 0)} 项）")
    if all_todos.get("ok"):
        parts.append(f"VPS 待办：vertu project todo list（{all_todos.get('count', 0)} 项）")
    elif all_todos.get("error"):
        parts.append(f"VPS 待办拉取失败：{all_todos['error'][:80]}")
    return " · ".join(parts) if parts else "数据来源：vertu CLI（加载中）"


def nested_value(row, *paths):
    for path in paths:
        value = row
        for part in path.split("."):
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(part)
        if value not in (None, ""):
            return value
    return ""


def todo_table_rows(rows):
    return "".join(
        "<tr>"
        f"<td>{esc(nested_value(row, 'priority', 'priority_name'))}</td>"
        f"<td>{esc(nested_value(row, 'title', 'name'))}</td>"
        f"<td>{esc(nested_value(row, 'status_name', 'status.name', 'stage_name'))}</td>"
        f"<td>{esc(nested_value(row, 'deadline', 'due_date', 'date_deadline'))}</td>"
        "</tr>"
        for row in rows
    )


def first_text(row, *paths):
    value = nested_value(row, *paths)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "")


def daily_report_table_rows(rows):
    return "".join(
        "<tr>"
        f"<td>{esc(first_text(row, 'created_at', 'create_date', 'date'))}</td>"
        f"<td>{esc(first_text(row, 'status', 'state', 'report_status'))}</td>"
        f"<td>{esc(compact_text(first_text(row, 'content', 'summary', 'content_summary', 'body', 'report_content'), 180))}</td>"
        "</tr>"
        for row in rows
    )


def pdca_todo_rows(rows):
    return "".join(
        "<tr>"
        f"<td>{esc(nested_value(row, 'title', 'name', 'description'))}</td>"
        f"<td>{esc(nested_value(row, 'status_name', 'status.name', 'stage_name'))}</td>"
        f"<td>{esc(nested_value(row, 'deadline', 'due_date', 'date_deadline', 'end_date'))}</td>"
        f"<td>{esc(nested_value(row, 'progress', 'progress_rate'))}</td>"
        "</tr>"
        for row in rows
    )
