# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：经销商驾驶舱数据聚合
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def filter_dealers_for_user(dealers, session_user):
    """Apply the server-resolved dealer scope; restricted users fail closed."""
    if not session_user:
        return dealers
    mode = str(session_user.get("data_scope") or "none").strip().lower()
    if mode == "all":
        return dealers
    allowed_names = {
        str(value or "").strip().casefold()
        for value in (session_user.get("allowed_dealer_names") or [])
        if str(value or "").strip()
    }
    if not allowed_names:
        return []
    return [
        d for d in dealers
        if str(d.get("dealerName") or d.get("name") or "").strip().casefold() in allowed_names
    ]


def load_dealer_reference():
    if not DEALER_REF_JSON.is_file():
        return []
    try:
        payload = json.loads(DEALER_REF_JSON.read_text(encoding="utf-8"))
        return payload.get("dealers") or []
    except (json.JSONDecodeError, OSError):
        return []


def fmt_cny(amount):
    if amount is None:
        return "—"
    value = int(round(float(amount or 0)))
    return f"¥ {value:,}"


def dealer_sell_out_total(dealers):
    values = [
        d.get("sellOutAmount")
        for d in dealers
        if d.get("sellOutAmount") not in (None, "")
    ]
    if not values:
        return None, "未同步终销数据"
    return sum(float(value or 0) for value in values), "代理商终销汇总"


def load_chart_data(date_text):
    """读取当日 PDCA 生成的 chart_data.json（与数据看板同源）。"""
    path = output_dir(date_text) / "chart_data.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def chart_performance_total(chart_data, period, date_text, sales_name=""):
    """
    与数据看板「实际达成」同口径：VPS 销售员业绩合计。
    月视图 = salesperson_top（看板本月 583.76万 即此字段之和）。
    sales_name 非空时只汇总 dimension 匹配该销售员的行。
    """
    period_rows = {
        "day": ("salesperson_daily", "今日"),
        "week": ("salesperson_week", "本周"),
        "month": ("salesperson_top", "本月"),
        "quarter": ("salesperson_top", "本月累计"),
    }
    key, label = period_rows.get(period, period_rows["month"])
    rows = chart_data.get(key) or []
    if sales_name:
        rows = [r for r in rows if str(r.get("dimension") or "").strip() == sales_name]
    total_yuan = sum(float(row.get("performance") or 0) for row in rows)
    wan = round(total_yuan / 10000, 2)
    return total_yuan, wan, f"{label}实际达成"


def sell_in_from_chart(date_text, period, sales_name=""):
    chart = load_chart_data(date_text)
    if not chart:
        return None
    return chart_performance_total(chart, period, date_text, sales_name=sales_name)


def api_dashboard_overview(date_text, period, session_user=None):
    if session_user:
        name, role, _source = resolve_workbench_profile(session_user)
    else:
        identity = fetch_vps_identity()
        user = identity.get("user") or {} if identity.get("ok") else {}
        name = nested_value(user, "employee_name", "name", "display_name") or nested_value(user, "name", "display_name") or "数据岗"
        role = nested_value(user, "job_title", "role") or "PDCA 工作台"
    dealers = filter_dealers_for_user(load_dealer_reference(), session_user)
    sell_out, sell_out_sub = dealer_sell_out_total(dealers)
    sell_in_sub = "未同步业绩数据"
    sell_in_wan = None
    scope_sales_name = ""
    if session_user and session_user.get("role") == "sales":
        scope_sales_name = str(session_user.get("sales_name") or "").strip()
    chart_sell_in = sell_in_from_chart(date_text, period, sales_name=scope_sales_name)
    if chart_sell_in:
        sell_in, sell_in_wan, sell_in_sub = chart_sell_in
    else:
        sell_in = None
    unrestricted = not session_user or session_user.get("data_scope") == "all"
    im_unread = fetch_vps_im_unread(with_latest=False) if unrestricted else {"ok": False, "unread_count": 0}
    pdca_plan = fetch_pdca_today_plan(date_text) if unrestricted else {
        "ok": False,
        "rows": [],
        "yesterday": previous_date_text(date_text),
        "warning": "共享 IM 日报未纳入当前账号的数据范围",
    }
    out = output_dir(date_text)
    pdca_path = out / "pdca_daily_check.md"
    score = None
    comment = "评分未接入可验证证据，暂不计算。"
    if unrestricted and pdca_path.is_file():
        text = pdca_path.read_text(encoding="utf-8", errors="ignore")[:800]
        if "风险" in text or "高风险" in text:
            score = None
            comment = "PDCA 日结提示存在风险项，请优先处理检查报告中的异常。"
        elif text.strip():
            comment = "已读取今日 PDCA 检查摘要，建议结合数据看板核对 Sell out 与过程指标。"
    if not unrestricted:
        comment += " 当前账号只展示已明确归属的数据，未读取服务器共享 IM/日报。"
    elif not pdca_plan["ok"]:
        score = None
        comment += f" 昨日日报拉取异常：{pdca_plan['warning'][:60]}"
    elif not pdca_plan["rows"]:
        score = None
        comment += f" 昨日（{pdca_plan['yesterday']}）日报未写入明日计划，请补交或打开 PDCA 日结。"
    elif len(pdca_plan["rows"]) > 8:
        score = None
        comment += f" 今日计划 {len(pdca_plan['rows'])} 项（来自昨日日报明日计划），建议按优先级闭环。"
    else:
        comment += f" 今日计划 {len(pdca_plan['rows'])} 项来自昨日日报明日计划。"
    if im_unread["ok"] and im_unread["unread_count"] > 0:
        score = None
        comment += f" IM 未读 {im_unread['unread_count']} 条待处理。"
    period_note = {"day": "日", "week": "周", "month": "月", "quarter": "季"}.get(period, "日")
    return {
        "managerName": name,
        "managerRole": f"{role} · {period_note}视图 · {date_text}",
        "sellInAmount": fmt_cny(sell_in),
        "sellInWan": sell_in_wan,
        "sellOutAmount": fmt_cny(sell_out),
        "sellOutWan": round(sell_out / 10000, 2) if sell_out is not None else None,
        "sellInSub": sell_in_sub,
        "sellOutSub": sell_out_sub,
        "agentScore": score,
        "scoreComment": comment,
        "dataState": {
            "sellIn": "live" if sell_in is not None else "missing",
            "sellOut": "live" if sell_out is not None else "missing",
            "agentScore": "missing",
        },
    }
