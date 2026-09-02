# -*- coding: utf-8 -*-
"""9 月推进计划导入：十大任务 → 手动项目；前置 ToDo → pdca_tasks 待办。

来源：docs/2026-09_九月推进拆解.md（定责会 2026-08-31，口径 09-01 对齐）。
- 项目按 key（sept-0..sept-10）幂等：已存在则刷新名称/协调人/成员；
- 待办按 source='sept-plan' + title + owner 去重：已存在只刷新截止日，
  不动状态（人工已改 done 的不回退）；
- 多人负责的待办按人拆分为多条（每人收到自己的项目卡片催办）。

用法（在 pdca-workbench 目录）：
    python scripts/import_sept_plan.py           # 实际导入
    python scripts/import_sept_plan.py --dry-run # 只统计预览，不改库
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from app.database import check_db_connection, get_engine, init_db  # noqa: E402
from app.models.pdca_task import PdcaTask  # noqa: E402
from app.models.todo_project import TodoProject  # noqa: E402

SOURCE_TAG = "sept-plan"
MEETING_TAG = "9月推进定责会(08-31)"

# ── 项目：十大任务 + 数据支撑 ─────────────────────────────────────────────
PROJECTS: list[dict] = [
    {"key": "sept-0", "name": "数据支撑与台账", "coordinator": "付汪阳"},
    {"key": "sept-1", "name": "vemory 严打", "coordinator": "付汪阳"},
    {"key": "sept-2", "name": "下单必须 vps", "coordinator": "冯磊/刘雪梅"},
    {"key": "sept-3", "name": "丽娜：迪拜500万+哈罗德", "coordinator": "丽娜"},
    {"key": "sept-4", "name": "于冰：成都+越南+马来", "coordinator": "于冰"},
    {"key": "sept-5", "name": "杨晶晶组：印度300万+清库", "coordinator": "杨晶晶"},
    {"key": "sept-6", "name": "历史客户→三人组", "coordinator": "张倩"},
    {"key": "sept-7", "name": "c2b：打法+500客户", "coordinator": "孔健"},
    {"key": "sept-8", "name": "clay：打法+5000线索", "coordinator": "石瑞琪"},
    {"key": "sept-9", "name": "汽车：预付款150万", "coordinator": "谢涛"},
    {"key": "sept-10", "name": "招聘：业绩换Offer", "coordinator": "张倩"},
]

# ── 待办：(项目 key, 标题, 负责人列表, 截止日) ─────────────────────────────
# 负责人多人时按人拆分；「法务/gary/sissi/马总」等若 IM 匹配不到会被跳过
# 并在催办结果里报告（管理员手工处理），不影响其余人员。
TASKS: list[tuple] = [
    # 数据支撑（sept-0）
    ("sept-0", "经销商清单 38 家→VPS 云文档（vemory 跟踪目录）", ["付汪阳"], "2026-09-03"),
    ("sept-0", "PDCA 10 条建账", ["付汪阳"], "2026-09-04"),
    ("sept-0", "口径冲突数据工单（My shop/VNG-VMG/Bizon-Bizcon/GURU/Dar Al Sabaek）", ["付汪阳"], "2026-09-03"),
    ("sept-0", "每日提醒（三人组/clay/新部）（每日例行）", ["付汪阳"], "2026-09-04"),
    ("sept-0", "9 月 1300 万周五看板（每周五例行）", ["付汪阳"], "2026-09-04"),
    # P1 vemory 严打
    ("sept-1", "丽娜账号 DEHDAHOUMAIMA 确认", ["刘春梅", "付汪阳"], "2026-09-03"),
    ("sept-1", "周核查台账启动（每周例行）", ["付汪阳"], "2026-09-04"),
    # P2 下单必须 vps
    ("sept-2", "下单 SOP 成文", ["冯磊", "刘雪梅"], "2026-09-03"),
    ("sept-2", "经销商通知发出", ["冯磊", "刘雪梅"], "2026-09-03"),
    ("sept-2", "10 天内 vps 进入经销商+沟通盘点（C1）", ["付汪阳"], "2026-09-03"),
    ("sept-2", "客户有效性评判（C1）", ["gary"], "2026-09-04"),
    ("sept-2", "无效回池+未进入罚款规则成文（C1）", ["gary", "刘春梅"], "2026-09-04"),
    # P3 丽娜/迪拜/哈罗德
    ("sept-3", "迪拜客户+500 万口径", ["丽娜", "付汪阳"], "2026-09-02"),
    ("sept-3", "交易/库存/回款口径", ["付汪阳"], "2026-09-03"),
    ("sept-3", "Lina 新增 175 万对齐到代理商", ["丽娜"], "2026-09-02"),
    ("sept-3", "汽车「买车」联动方案（跟催老板拍板）", ["谢涛"], "2026-09-04"),
    ("sept-3", "哈罗德盘点报告（现状→改进→配合→标准）", ["丽娜"], "2026-09-04"),
    # P4 于冰
    ("sept-4", "成都日期确定", ["于冰"], "2026-09-03"),
    ("sept-4", "越南 JD/人数", ["张倩"], "2026-09-04"),
    ("sept-4", "马来 SWAP 对接", ["于冰"], "2026-09-04"),
    # P5 杨晶晶组
    ("sept-5", "印度 300 万口径", ["杨晶晶", "付汪阳"], "2026-09-02"),
    ("sept-5", "GURU 建档清洗", ["付汪阳"], "2026-09-03"),
    ("sept-5", "清仓配件清单（库存/价格）", ["杨晶晶"], "2026-09-04"),
    # P6 历史客户三人组
    ("sept-6", "历史客户总清单（C3）", ["付汪阳"], "2026-09-03"),
    ("sept-6", "新人分配表", ["张倩", "付汪阳"], "2026-09-04"),
    ("sept-6", "三人组分工确认", ["张倩"], "2026-09-02"),
    ("sept-6", "授信 SOP", ["付汪阳", "孔健"], "2026-09-04"),
    ("sept-6", "C转B 规则（分润/考核/流转）（C3）", ["付汪阳", "孔健"], "2026-09-04"),
    ("sept-6", "WhatsApp 全量名单+画像+投流方案（C3）", ["孔健", "付汪阳"], "2026-09-04"),
    ("sept-6", "中小企业主名单（C3）", ["邓琳莹", "王宇彤", "Safae"], "2026-09-04"),
    ("sept-6", "三人组清库清单（C3）", ["邓琳莹", "王宇彤", "Safae"], "2026-09-04"),
    # P7 c2b
    ("sept-7", "c2b 专题会定打法", ["孔健", "崔军华", "付汪阳"], "2026-09-04"),
    ("sept-7", "清洗范围确定（印度/马来等）", ["孔健"], "2026-09-03"),
    ("sept-7", "500 表结构", ["孔健", "付汪阳"], "2026-09-04"),
    ("sept-7", "海外私域 ≥30 万客户名单（C8）", ["刘春梅", "付汪阳"], "2026-09-03"),
    ("sept-7", "C转B 一对一触达信息（每日例行）（C2）", ["丽娜"], "2026-09-04"),
    ("sept-7", "C转B 一对一触达信息（每日例行）（C2）", ["于冰"], "2026-09-04"),
    ("sept-7", "C转B 一对一触达信息（每日例行）（C2）", ["杨晶晶"], "2026-09-04"),
    ("sept-7", "C转B 一对一触达信息（每日例行）（C2）", ["何海文"], "2026-09-04"),
    # P8 clay
    ("sept-8", "clay 专题会", ["石瑞琪", "金彪", "付汪阳"], "2026-09-04"),
    ("sept-8", "客户源清单（大疆/戴森/影石360/手机维修店/B&O/徕卡）（C4）", ["石瑞琪", "金彪"], "2026-09-03"),
    ("sept-8", "线索库结构", ["金彪"], "2026-09-04"),
    ("sept-8", "画像技术方案", ["金彪"], "2026-09-04"),
    ("sept-8", "线索入库 ≥100 条/天（每日例行）（C4）", ["石瑞琪"], "2026-09-04"),
    # P9 汽车
    ("sept-9", "预售方案（50 万/台）", ["谢涛", "丁晓茜"], "2026-09-04"),
    ("sept-9", "参数 PPT（9/5 硬日期）（C6）", ["徐豪"], "2026-09-05"),
    ("sept-9", "3 分钟视频（C7）", ["马总"], "2026-09-04"),
    ("sept-9", "出货合规路径（C5）", ["法务", "谢涛", "sissi"], "2026-09-03"),
    ("sept-9", "老板拍板（预售+买车联动）（跟催）", ["谢涛"], "2026-09-04"),
    ("sept-9", "预付款 3 台=150 万（全员推，线索汇总谢涛/丁晓茜）（C10）", ["谢涛"], "2026-09-30"),
    # P10 招聘
    ("sept-10", "国家经理两页纸（C9）", ["张倩"], "2026-09-04"),
    ("sept-10", "岗位业绩门槛表", ["张倩"], "2026-09-04"),
    ("sept-10", "董正早模式复盘", ["张倩", "刘春梅"], "2026-09-04"),
]

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计，不改库")
    args = parser.parse_args()

    if not check_db_connection():
        print("无法连接 PostgreSQL，请设置 PDCA_DATABASE_URL 后重试")
        return 1

    # 先确保 schema 补丁（如 todo_projects.kind）已应用，再导入
    init_db()

    projects_created = 0
    projects_updated = 0
    tasks_created = 0
    tasks_updated = 0
    by_owner: dict[str, int] = defaultdict(int)

    with Session(get_engine()) as session:
        # ── 项目：按 key 幂等 ────────────────────────────────────────────
        existing_projects = {
            row.key: row
            for row in session.exec(
                select(TodoProject).where(
                    TodoProject.key.in_([p["key"] for p in PROJECTS])
                )
            ).all()
        }
        projects: dict[str, TodoProject] = {}
        for spec in PROJECTS:
            row = existing_projects.get(spec["key"])
            if row is None:
                row = TodoProject(
                    key=spec["key"],
                    name=spec["name"],
                    kind="manual",
                    status="新建",
                    executors="[]",
                    coordinator=spec["coordinator"],
                )
                session.add(row)
                session.flush()
                projects_created += 1
            else:
                row.name = spec["name"]
                row.coordinator = spec["coordinator"]
                session.add(row)
                projects_updated += 1
            projects[spec["key"]] = row

        # ── 待办：source + title + owner 去重 ────────────────────────────
        existing_tasks = {
            (row.title, row.owner): row
            for row in session.exec(
                select(PdcaTask).where(PdcaTask.source == SOURCE_TAG)
            ).all()
        }
        seen_new: set[tuple] = set()
        for project_key, title, owners, task_date in TASKS:
            project = projects[project_key]
            for owner in owners:
                key = (title, owner)
                row = existing_tasks.get(key)
                if row is None and key not in seen_new:
                    row = PdcaTask(
                        task_date=task_date,
                        title=title,
                        owner=owner,
                        status="pending",
                        priority="normal",
                        source=SOURCE_TAG,
                        meeting_name=MEETING_TAG,
                        project_id=project.id,
                    )
                    session.add(row)
                    seen_new.add(key)
                    tasks_created += 1
                else:
                    # 已存在（或本轮已建）→ 刷新截止日与项目归属，不动状态
                    if row is not None:
                        row.task_date = task_date
                        row.project_id = project.id
                        row.meeting_name = MEETING_TAG
                        session.add(row)
                        tasks_updated += 1
                by_owner[owner] += 1

        # ── 项目成员（executors 展示用）───────────────────────────────────
        owners_by_project: dict[int, set] = defaultdict(set)
        for row in session.exec(
            select(PdcaTask).where(PdcaTask.source == SOURCE_TAG)
        ).all():
            if row.owner and row.project_id:
                owners_by_project[row.project_id].add(row.owner.strip())
        for spec in PROJECTS:
            row = projects[spec["key"]]
            executors = json.dumps(
                sorted(owners_by_project.get(row.id, set())), ensure_ascii=False
            )
            if row.executors != executors:
                row.executors = executors
                session.add(row)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print(f"项目：新建 {projects_created} / 刷新 {projects_updated}")
    print(f"待办：新建 {tasks_created} / 刷新 {tasks_updated}（共 {len(TASKS)} 组、按人拆分 {sum(by_owner.values())} 条）")
    print("按负责人分布：")
    for name, count in sorted(by_owner.items(), key=lambda kv: -kv[1]):
        print(f"  {count:3d}  {name}")
    print("模式：" + ("dry-run（未落库）" if args.dry_run else "已提交"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
