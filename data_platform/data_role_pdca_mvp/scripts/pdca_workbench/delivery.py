# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：交付检查、PDCA 待办更新与交付页面渲染
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def okr_rows(rows):
    return "".join(
        "<tr>"
        f"<td>{esc(nested_value(row, 'title', 'name'))}</td>"
        f"<td>{esc(nested_value(row, 'score'))}</td>"
        f"<td>{esc(len(row.get('key_results') or []))}</td>"
        "</tr>"
        for row in rows
    )


def task_title(row):
    return first_text(row, "title", "name", "description", "task_name", "content")


def normalized_task_text(value):
    return "".join(char.lower() for char in str(value or "") if char.isalnum())


def task_progress(row):
    raw = first_text(row, "progress", "progress_rate", "progress_percent", "completion_rate")
    if not raw:
        raw = first_text(row, "remark", "note", "description")
        match = re.search(r"进度[:：]\s*(\d+(?:\.\d+)?)\s*%", raw)
        raw = match.group(1) if match else ""
    try:
        return int(float(str(raw).replace("%", "").strip()))
    except ValueError:
        return 0


def task_deadline(row):
    return first_text(row, "deadline", "due_date", "date_deadline", "end_date")


def task_status(row):
    return first_text(row, "status_name", "status.name", "stage_name", "state", "status")


def todo_id_value(row):
    return first_text(row, "todo_id", "id")


def is_done_status(value):
    text = " ".join(str(value or "").strip().lower().split())
    return text in {"完成", "已完成", "done", "completed", "closed", "close"}


def find_matching_task(title, rows):
    needle = normalized_task_text(title)
    if not needle:
        return None
    for row in rows:
        candidate = normalized_task_text(task_title(row))
        if not candidate:
            continue
        # A partial title match can mark an unrelated task as delivered (and
        # even turns "未完成" into completion in combination with fuzzy status
        # parsing).  Only exact normalized titles are acceptable when no
        # stable todo_id is present.
        if needle == candidate:
            return row
    return None


def build_delivery_checks(planned_rows, today_done_rows, vps_todo_rows, date_text):
    checks = []
    for row in planned_rows:
        title = task_title(row) or "未命名事项"
        done_hit = find_matching_task(title, today_done_rows)
        todo_hit = find_matching_task(title, vps_todo_rows)
        progress = max(task_progress(row), task_progress(done_hit or {}), task_progress(todo_hit or {}))
        status_text = task_status(done_hit or {}) or task_status(todo_hit or {}) or task_status(row)
        due = task_deadline(todo_hit or {}) or task_deadline(row)
        has_delivery = bool(done_hit)
        has_done_status = is_done_status(status_text)
        if has_delivery or has_done_status or progress >= 100:
            level = "done"
            label = "已交付"
            advice = "已有今日日报或 VPS 待办完成记录，建议补齐最终交付物链接或结果摘要。"
        elif progress > 0:
            level = "progress"
            label = "进行中"
            advice = "已有进度但未形成完成记录，今天日结时需要补充交付结果和剩余阻塞。"
        elif due and due <= date_text:
            level = "risk"
            label = "高风险"
            advice = "截止日已到但没有完成证据，建议立即跟进负责人，补交结果或调整计划。"
        else:
            level = "pending"
            label = "待交付"
            advice = "尚未看到完成证据，建议在 VPS 待办或今日日报里补充进度。"
        checks.append({
            "title": title,
            "todo_id": todo_id_value(todo_hit or {}),
            "date_text": date_text,
            "level": level,
            "label": label,
            "progress": progress,
            "deadline": due,
            "status": status_text,
            "advice": advice,
            "report_evidence": compact_text(task_title(done_hit) if done_hit else "", 160),
            "todo_evidence": compact_text(task_title(todo_hit) if todo_hit else "", 160),
        })
    return checks


def normalize_deadline_for_vps(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return f"{text} 18:00:00"
    return text


def save_pdca_task_update(form):
    title = (form.get("title", [""])[0] or "").strip()
    todo_id = (form.get("todo_id", [""])[0] or "").strip()
    status = (form.get("status", [""])[0] or "").strip()
    progress = (form.get("progress", ["0"])[0] or "0").strip()
    deadline = normalize_deadline_for_vps(form.get("deadline", [""])[0])
    note = (form.get("note", [""])[0] or "").strip()
    if not title and not todo_id:
        return "缺少待办标题，无法保存。"
    try:
        progress_value = max(0, min(100, int(float(progress))))
    except ValueError:
        return "进度必须是 0 到 100 的数字。"
    remark_parts = [f"进度：{progress_value}%"]
    if note:
        remark_parts.append(f"备注：{note}")
    remark = "；".join(remark_parts)
    if not todo_id:
        args = ["odoo", "project", "todo", "create", "--title", title, "--remark", remark]
        if deadline:
            args.extend(["--deadline", deadline])
        payload, _ = run_vertu_write_json(args)
        todo_id = str(payload.get("id") or payload.get("todo_id") or nested_value(payload, "result.id", "data.id"))
        if not todo_id:
            return "已创建待办，但 VPS 没有返回 todo_id，请刷新后再改状态。"
    update_args = ["odoo", "project", "todo", "update", "--todo-id", todo_id, "--remark", remark]
    if status:
        update_args.extend(["--status", status])
    if deadline:
        update_args.extend(["--deadline", deadline])
    run_vertu_write_json(update_args)
    if status == "已完成" or progress_value >= 100:
        run_vertu_write_json(["odoo", "project", "todo", "complete", "--todo-id", todo_id])
    return f"已保存进度 {progress_value}% 和状态「{status or '未填写'}」。Agent 判断已刷新。"


def render_delivery_agent(checks, daily_ok=True):
    if not checks:
        return '<section><h2>交付检查 Agent</h2><p>没有可检查的今日计划。请先在「经销商-日报推送」群的昨日日报里写入“明日计划”。</p></section>'
    summary = {
        "done": sum(1 for item in checks if item["level"] == "done"),
        "progress": sum(1 for item in checks if item["level"] == "progress"),
        "pending": sum(1 for item in checks if item["level"] == "pending"),
        "risk": sum(1 for item in checks if item["level"] == "risk"),
    }
    cards = "".join([
        metric_card("已交付", f"{summary['done']} 项", "有今日 IM 日报或 VPS 完成记录", summary["risk"] == 0),
        metric_card("进行中", f"{summary['progress']} 项", "有进度但还缺交付结果", summary["progress"] == 0),
        metric_card("高风险", f"{summary['risk']} 项", "到期但没有完成证据", summary["risk"] == 0),
    ])
    item_cards = []
    for item in checks:
        item_cards.append(f"""
        <details class="delivery-card {esc(item['level'])}" data-delivery-card data-status="{esc(item['level'])}">
          <summary>
            <span class="delivery-title">{esc(item['title'])}</span>
            <span class="delivery-badge">{esc(item['label'])}</span>
          </summary>
          <div class="delivery-body">
            <p><strong>Agent 判断：</strong>{esc(item['advice'])}</p>
            <p><strong>当前进度：</strong>{esc(item['progress'])}%　<strong>截止：</strong>{esc(item['deadline'] or '未填写')}　<strong>状态：</strong>{esc(item['status'] or '未填写')}</p>
            <p><strong>今日 IM 日报证据：</strong>{esc(item['report_evidence'] or '未匹配到完成记录')}</p>
            <p><strong>VPS 待办证据：</strong>{esc(item['todo_evidence'] or '未匹配到待办记录')}</p>
            <form class="progress-form" method="post" action="/pdca-task">
              <input type="hidden" name="date" value="{esc(item.get('date_text', ''))}">
              <input type="hidden" name="title" value="{esc(item['title'])}">
              <input type="hidden" name="todo_id" value="{esc(item.get('todo_id', ''))}">
              <input type="hidden" name="deadline" value="{esc(item.get('deadline', ''))}">
              <label>进度 %<input name="progress" type="number" min="0" max="100" value="{esc(item['progress'])}"></label>
              <label>状态
                <select name="status">
                  <option value="未开始" {"selected" if item["status"] == "未开始" else ""}>未开始</option>
                  <option value="进行中" {"selected" if item["status"] == "进行中" else ""}>进行中</option>
                  <option value="阻塞" {"selected" if item["status"] == "阻塞" else ""}>阻塞</option>
                  <option value="已完成" {"selected" if item["status"] == "已完成" or item["level"] == "done" else ""}>已完成</option>
                </select>
              </label>
              <label>交付/阻塞说明<input name="note" placeholder="例如：已完成资料核查，等销售确认"></label>
              <button type="submit">保存进度和状态</button>
            </form>
          </div>
        </details>
        """)
    daily_note = "" if daily_ok else '<p class="message">注意：未查询到「经销商-日报推送」群的今日日报，Agent 只能根据 VPS 待办进度做临时判断。</p>'
    return f"""
    <section>
      <h2>交付检查 Agent</h2>
      <p>自动对比「经销商-日报推送」群中昨日日报的今日计划、今日日报完成事项和 VPS 待办进度，判断今天每项待办交付到什么程度。</p>
      {daily_note}
      <div class="grid">{cards}</div>
      <div class="actions">
        <button type="button" class="button light" onclick="filterDelivery('all')">全部</button>
        <button type="button" class="button light" onclick="filterDelivery('done')">只看已交付</button>
        <button type="button" class="button light" onclick="filterDelivery('progress')">只看进行中</button>
        <button type="button" class="button light" onclick="filterDelivery('risk')">只看高风险</button>
      </div>
      <div class="delivery-list">{''.join(item_cards)}</div>
      <script>
      /** Filters delivery check cards by Agent status. */
      function filterDelivery(status) {{
        document.querySelectorAll('[data-delivery-card]').forEach(function(card) {{
          card.style.display = status === 'all' || card.dataset.status === status ? '' : 'none';
        }});
      }}
      </script>
    </section>
    """
