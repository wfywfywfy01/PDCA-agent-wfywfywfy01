# -*- coding: utf-8 -*-
"""把《事项跟进表.xlsx》解析成规范化 JSON（一次性转换，产物入库 data/）。

规则：
- 板块 → 项目（fup-car / fup-newbie / fup-senior）；任务 → 分组（group 字段）
- 子任务 → 待办标题（附交付物/备注）；检查点 → 截止日
- 日期：Excel 序列号转日期；9/4 18:00 → 09-04；9.14 → 09-14；12月 → 12-31
  每日/每周五 → 今天 + 【每日】/【每周五】标记
- 负责人：谢涛和丁晓茜 → 拆分两人；lina → DEHDAHOUMAIMA；
  「软件团队」等非人名从负责人里剔除（保留到备注）
- 「已划掉」行不导入

用法：
    python scripts/convert_followup_table.py --input 事项跟进表.xlsx \
        --output data/sept_followup_table.json
"""
import argparse
import io
import json
import re
import sys
from datetime import date, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import openpyxl

EXCEL_EPOCH = date(1899, 12, 30)
TODAY = date.today()

SECTION_PROJECTS = {
    "汽车板块": "fup-car",
    "新人销售板块": "fup-newbie",
    "老人销售板块": "fup-senior",
}

PERSON_ALIAS = {"lina": "DEHDAHOUMAIMA", "丽娜": "DEHDAHOUMAIMA"}

NON_PERSON = {"软件团队", "sana组", "新人代表", "老板", "法务"}


def parse_checkpoint(raw: str) -> str:
    """检查点 → YYYY-MM-DD；返回 ('date', '例行标记')。"""
    text = (raw or "").strip().replace("。", "").replace("，", "")
    if not text:
        return TODAY.isoformat(), ""
    if text in ("每日", "每天", "持续进行", "每日推进", "每日19:00", "每日早会"):
        return TODAY.isoformat(), "【每日】"
    if "每周" in text or text == "每周五":
        next_friday = TODAY + timedelta(days=(4 - TODAY.weekday()) % 7)
        return next_friday.isoformat(), "【每周五】"
    if "起每日" in text:
        m = re.search(r"(\d+)/(\d+)", text)
        if m:
            return f"2026-{int(m.group(1)):02d}-{int(m.group(2)):02d}", "【每日】"
        return TODAY.isoformat(), "【每日】"
    if text in ("12月", "Q4"):
        return "2026-12-31", ""
    # 9/4 18:00、9/4、9.4、9.14、10/15、12/1、9/3 晚
    m = re.search(r"(\d{1,2})[/.](\d{1,2})", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        return f"2026-{month:02d}-{day:02d}", ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return text, ""
    return TODAY.isoformat(), ""


def split_owners(raw: str) -> list[str]:
    text = (raw or "").strip()
    if not text:
        return []
    parts = re.split(r"[和、/+,，\s]+", text)
    owners = []
    for part in parts:
        part = part.strip()
        if not part or part in NON_PERSON:
            continue
        owners.append(PERSON_ALIAS.get(part, part))
    return owners


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="事项跟进表 xlsx 路径")
    parser.add_argument("--output", default="scripts/sept_followup_table.json", help="输出 JSON 路径")
    args = parser.parse_args()
    src = args.input
    out_path = args.output

    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb.active
    projects: dict[str, dict] = {}
    groups: dict[str, list] = {}
    current_section = ""
    current_task = ""
    skipped = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        section, task, subtask, owner_raw, checkpoint, deliverable, note = (
            list(row) + [None] * 7
        )[:7]
        section = str(section or "").strip()
        task = str(task or "").strip()
        subtask = str(subtask or "").strip()
        owner_raw = str(owner_raw or "").strip()
        checkpoint_raw = str(checkpoint or "").strip()
        deliverable = str(deliverable or "").strip()
        note = str(note or "").strip()
        if section:
            current_section = section
            if section not in projects:
                projects[section] = {
                    "key": SECTION_PROJECTS[section],
                    "name": section,
                    "coordinator": "",
                }
        if task:
            current_task = task
        if not subtask:
            continue
        note_text = " ".join(x for x in (deliverable, note) if x)
        if "已划掉" in note_text or "已划掉" in subtask:
            skipped += 1
            continue
        # 检查点可能是 Excel 序列号
        if checkpoint_raw:
            m = re.fullmatch(r"(\d{5})", checkpoint_raw.replace(".0", ""))
            if m:
                serial = int(m.group(1))
                due = (EXCEL_EPOCH + timedelta(days=serial)).isoformat()
                routine = ""
            else:
                due, routine = parse_checkpoint(checkpoint_raw)
        else:
            due, routine = parse_checkpoint("")
        owners = split_owners(owner_raw)
        title = subtask
        if deliverable:
            title += f"｜交付：{deliverable}"
        if routine:
            title += routine
        groups.setdefault(SECTION_PROJECTS[current_section], []).append(
            {
                "group": current_task,
                "title": title[:500],
                "owners": owners,
                "task_date": due,
                "note": note_text[:200],
            }
        )

    result = {"projects": list(projects.values()), "items": groups}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in groups.values())
    print("板块:", {k: len(v) for k, v in groups.items()})
    print("总子任务:", total, "已划掉跳过:", skipped)
    print("输出:", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
