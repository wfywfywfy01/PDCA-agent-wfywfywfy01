# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：CSV 读写与公式注入防护（csv_safe）
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def read_csv_rows(path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_rows(path, fieldnames, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def safe_name(value):
    return "".join(char if char.isalnum() or char in "-_." else "-" for char in str(value or "")).strip(".-") or "item"

def csv_safe(value):
    """防止用户输入被 Excel 当作公式执行。"""
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
