# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：每日问卷与待办/物流 CSV 追加
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def ensure_questionnaire(date_text):
    path = questionnaire_path(date_text)
    if not path.exists():
        template = read_text(QUESTION_TEMPLATE).replace("YYYY-MM-DD", date_text)
        write_text(path, template)
    return path


def parse_questionnaire(date_text):
    # Rendering a GET page must stay read-only.  Production mounts the release
    # tree read-only and overlays only the runtime input directories as writable.
    # Use the template in memory until the first explicit save creates the file.
    path = questionnaire_path(date_text)
    text = (
        read_text(path)
        if path.exists()
        else read_text(QUESTION_TEMPLATE).replace("YYYY-MM-DD", date_text)
    )
    result = {title: "" for title in QUESTION_TITLES}
    current = None
    buffer = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                result[current] = "\n".join(buffer).strip()
            title = line[3:].strip()
            current = title if title in result else None
            buffer = []
        elif current:
            buffer.append(line)
    if current:
        result[current] = "\n".join(buffer).strip()
    return result


def save_questionnaire(date_text, form):
    lines = [f"# 数据岗位每日 PDCA 问卷 {date_text}", ""]
    for index, title in enumerate(QUESTION_TITLES):
        value = (form.get(f"q{index}", [""])[0] or "").strip()
        lines.extend([f"## {title}", value if value else "-", ""])
    write_text(questionnaire_path(date_text), "\n".join(lines))


def append_todo(date_text, form):
    path = todo_path(date_text)
    fieldnames = ["date", "source", "title", "priority", "status", "owner", "due_date", "notes"]
    rows = read_csv_rows(path)
    rows.append({
        "date": date_text,
        "source": "workbench",
        "title": csv_safe((form.get("title", [""])[0] or "").strip()),
        "priority": csv_safe(form.get("priority", ["MEDIUM"])[0]),
        "status": csv_safe(form.get("status", ["pending"])[0]),
        "owner": csv_safe((form.get("owner", ["frank"])[0] or "frank").strip()),
        "due_date": (form.get("due_date", [date_text])[0] or date_text).strip(),
        "notes": csv_safe((form.get("notes", [""])[0] or "").strip()),
    })
    rows = [row for row in rows if row.get("title")]
    write_csv_rows(path, fieldnames, rows)


def append_logistics(date_text, form):
    path = logistics_path(date_text)
    fieldnames = ["tracking_number", "carrier", "customer", "salesperson", "ship_date", "expected_status", "current_status", "note"]
    rows = read_csv_rows(path)
    rows.append({
        "tracking_number": csv_safe((form.get("tracking_number", [""])[0] or "").strip()),
        "carrier": csv_safe(form.get("carrier", ["UPS"])[0]),
        "customer": csv_safe((form.get("customer", [""])[0] or "").strip()),
        "salesperson": csv_safe((form.get("salesperson", [""])[0] or "").strip()),
        "ship_date": (form.get("ship_date", [date_text])[0] or date_text).strip(),
        "expected_status": csv_safe((form.get("expected_status", [""])[0] or "").strip()),
        "current_status": csv_safe((form.get("current_status", [""])[0] or "").strip()),
        "note": csv_safe((form.get("note", [""])[0] or "").strip()),
    })
    rows = [row for row in rows if row.get("tracking_number")]
    write_csv_rows(path, fieldnames, rows)
