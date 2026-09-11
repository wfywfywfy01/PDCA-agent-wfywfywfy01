# -*- coding: utf-8 -*-
"""待办/项目 ↔ 个人月度 OKR 挂接：从系统 OKR 目录按人建池、按主题归入。

对齐「收敛到 OKR」口径：每条未完成待办归入其负责人最相关的 OKR 条目；
项目取其名下待办的主流 OKR 归属。
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine
from app.models.pdca_task import PdcaTask
from app.models.todo_project import TodoProject
from app.statuses import is_done as _is_done
from app.todos.compose import _containment, _tokens
from app.todos.owners import apply_alias, split_owners
from app.vertu.client import run_vertu_sync_json

PERSON_ALIASES = {
    "DEHDAHOUMAIMA": ["dehdahoumaima", "lina", "丽娜"],
    "丁晓茜": ["丁晓茜", "sissi"],
    "于冰": ["于冰"],
    "付汪阳": ["付汪阳"],
    "何海文": ["何海文"],
    "冯磊": ["冯磊"],
    "刘春梅": ["刘春梅"],
    "刘雪梅": ["刘雪梅"],
    "尤文静": ["尤文静"],
    "张倩": ["张倩"],
    "张慧": ["张慧"],
    "张琪": ["张琪"],
    "李浩然-1": ["李浩然"],
    "杨晶晶": ["杨晶晶"],
    "王宇彤": ["王宇彤"],
    "谢涛": ["谢涛"],
    "邓琳莹": ["邓琳莹"],
    "Safae": ["safae"],
}

DEPT_OF = {
    "DEHDAHOUMAIMA": "经销商三部",
    "Safae": "经销商三部",
    "尤文静": "经销商三部",
    "丁晓茜": "汽车事业部",
    "谢涛": "汽车事业部",
    "于冰": "经销商一部",
    "杨晶晶": "经销商二部",
    "何海文": "经销商二部",
    "李浩然-1": "经销商新部",
    "付汪阳": "海外渠道中台",
    "刘春梅": "海外渠道中台",
    "冯磊": "海外渠道中台",
    "刘雪梅": "海外渠道中台",
    "张倩": "海外渠道中台",
    "张琪": "海外渠道中台",
    "王宇彤": "海外渠道中台",
    "张慧": "经销商一部",
    "邓琳莹": "经销商一部",
}

MENTION_RE = re.compile(r"@([^@\s，,]+)")
SHARED_MENTIONS = ("所有经销商", "所有经销商人员", "海外渠道所有人")

THEME_BRIDGE = [
    (("pdca", "vps", "账号", "系统", "memory", "vemory", "会议录音", "操作台"), ("pdca", "vps", "memory", "操作台", "账号")),
    (("sell out", "sellout", "销售数据"), ("sell out", "sellout")),
    (("清库", "清仓", "m2", "库存"), ("清库", "m2")),
    (("新人", "带教", "培训", "sop"), ("培训", "招聘")),
    (("招聘", "面试", "offer"), ("招聘",)),
    (("订单", "发货", "物流", "进出口", "报关", "发票", "账", "资产盘点"), ("商务", "物流", "发货", "进出口", "资产", "账单")),
    (("周报", "月报"), ("周报", "月报")),
    (("汽车", "买车", "预售"), ("汽车",)),
    (("客户源", "触达", "独代", "总代", "代理", "客户"), ("客户源", "触达", "业绩目标")),
]


def _period() -> str:
    return datetime.now().strftime("%Y-%m")


def fetch_okr_catalog() -> list[dict]:
    """运行时从系统拉 OKR 目录：部门树 + 在跟进人员的员工 OKR。"""
    catalog: dict[str, dict] = {}
    period = _period()
    # 1) 部门树
    payload = run_vertu_sync_json(["okr", "+dept-okr", "--okr-period", period], timeout=45.0)
    tree = (payload or {}).get("department_tree") or []

    def walk(nodes, scoped=False):
        for n in nodes:
            s = scoped or n.get("department_id") == 1569
            if s:
                for o in n.get("objectives") or []:
                    catalog[str(o["id"])] = {
                        "id": str(o["id"]),
                        "title": o.get("title", ""),
                        "krs": [k.get("title", "") for k in o.get("key_results") or []],
                        "dept": n.get("name", ""),
                        "employee": o.get("employee_name") or "",
                    }
            walk(n.get("children") or [], s)

    walk(tree)
    # 2) 员工 OKR（在跟进人员）
    settings = get_settings()
    skip = {n.strip().casefold() for n in settings.todo_remind_skip_owners if n.strip()}
    aliases = settings.todo_owner_aliases
    people = set()
    with Session(get_engine()) as session:
        for row in session.exec(select(PdcaTask)).all():
            for part in split_owners(row.owner):
                name = apply_alias(part, aliases)
                if name.casefold() not in skip and name:
                    people.add(name)
    for person in sorted(people):
        payload = run_vertu_sync_json(
            ["okr", "+employee-okr", "--okr-period", period, "--employee-name", person],
            timeout=45.0,
        )
        for o in ((payload or {}).get("objectives") or []):
            oid = str(o.get("id"))
            if oid in catalog:
                entry = catalog[oid]
                if not entry["employee"] and (o.get("employee_name") or ""):
                    entry["employee"] = o["employee_name"]
                continue
            catalog[oid] = {
                "id": oid,
                "title": o.get("title", ""),
                "krs": [k.get("title", "") for k in o.get("key_results") or []],
                "dept": o.get("department_name") or "",
                "employee": o.get("employee_name") or person,
            }
    return list(catalog.values())


def okr_pool_for(person: str, okrs: list[dict]) -> list[dict]:
    aliases = PERSON_ALIASES.get(person, [person.casefold()])
    dept = DEPT_OF.get(person, "")
    seen: dict[str, tuple[int, str]] = {}
    by_id = {o["id"]: o for o in okrs}
    for okr in okrs:
        text = (okr["title"] + " " + " ".join(okr["krs"])).casefold()
        mentions = MENTION_RE.findall(okr["title"] + " " + " ".join(okr["krs"]))
        hit = False
        priority = 0
        if any(alias in text for alias in aliases):
            hit, priority = True, 3
        elif okr["employee"] and okr["employee"].casefold() in aliases:
            hit, priority = True, 3
        elif okr["dept"] == dept and not mentions:
            hit, priority = True, 2
        elif any(m in SHARED_MENTIONS for m in mentions):
            hit, priority = True, 1
        if not hit:
            continue
        norm = re.sub(r"对齐[:：]|@[^@\s，,]+", "", okr["title"]).strip().casefold()
        cur = seen.get(norm)
        if cur is None or priority > cur[0]:
            seen[norm] = (priority, okr["id"])
    return [dict(by_id[oid], priority=pri) for pri, oid in seen.values()]


def _theme_rank(title: str, okr: dict) -> Optional[int]:
    """返回首个命中的主题桥序号（越小越具体：账号/PDCA > 清库 > 培训 > … > 客户源）。"""
    t = (title or "").casefold()
    okt = (okr["title"] + " " + " ".join(okr["krs"])).casefold()
    for rank, (keys, okeys) in enumerate(THEME_BRIDGE):
        if any(k in t for k in keys) and any(k in okt for k in okeys):
            return rank
    return None


def assign_okr(title: str, pool: list[dict], dealer_fallback: bool = False) -> Optional[dict]:
    tokens = _tokens(title)

    def score_of(okr: dict) -> float:
        best = 0.0
        for t in [okr["title"]] + okr["krs"]:
            s = _containment(tokens, _tokens(t))
            if s > best:
                best = s
        return best

    themed = [(okr, rank) for okr in pool if (rank := _theme_rank(title, okr)) is not None]
    if themed:
        # 主题桥命中：更具体的桥优先，其次文本相似度，再其次优先级
        themed.sort(key=lambda pair: (
            pair[1],
            -score_of(pair[0]),
            -pair[0].get("priority", 0),
        ))
        return themed[0][0]
    best_score = 0.0
    best_okr = None
    for okr in pool:
        score = score_of(okr)
        if score > best_score or (
            score == best_score
            and best_okr is not None
            and okr.get("priority", 0) > best_okr.get("priority", 0)
        ):
            best_score = score
            best_okr = okr
    if best_okr is not None and best_score > 0:
        # 经销商弱匹配碎片不硬塞共享 OKR，落到本部门客户源/业绩目标
        if dealer_fallback and best_score < 0.35:
            fb = fallback_okr(pool)
            if fb is not None:
                return fb
        return best_okr
    # 经销商未匹配碎片 → 客户源/业绩 OKR（执行动作归母目标）
    return fallback_okr(pool)


def fallback_okr(pool: list[dict]) -> Optional[dict]:
    for o in pool:
        t = o["title"].casefold()
        if "客户源" in t or "触达" in t:
            return o
    for o in pool:
        if "业绩目标" in o["title"]:
            return o
    return None


def link_tasks_and_projects(dry_run: bool = False) -> dict:
    """收敛：待办 → OKR；项目 → 待办主流 OKR。返回统计。"""
    okrs = fetch_okr_catalog()
    if not okrs:
        logger.warning("OKR 目录为空，跳过挂接")
        return {"ok": False, "reason": "okr catalog empty"}
    pool_cache: dict[str, list[dict]] = {}
    task_linked = 0
    project_linked = 0
    with Session(get_engine()) as session:
        tasks = list(session.exec(select(PdcaTask)).all())
        projects = list(session.exec(select(TodoProject)).all())
        settings = get_settings()
        skip = {n.strip().casefold() for n in settings.todo_remind_skip_owners if n.strip()}
        aliases = settings.todo_owner_aliases

        def parts(row) -> list[str]:
            out = []
            for part in split_owners(row.owner):
                name = apply_alias(part, aliases)
                if name.casefold() not in skip and name not in out:
                    out.append(name)
            return out

        project_titles: dict[int, Counter] = defaultdict(Counter)
        for task in sorted(tasks, key=lambda r: r.id or 0):
            if _is_done(task.status):
                continue
            owners = parts(task)
            if not owners:
                continue
            okr = None
            for person in owners:
                pool = pool_cache.setdefault(person, okr_pool_for(person, okrs))
                is_dealer = DEPT_OF.get(person, "").startswith("经销商")
                candidate = assign_okr(task.title, pool, dealer_fallback=is_dealer)
                if candidate is not None:
                    okr = candidate
                    break
            title = okr["title"] if okr else ""
            if title != task.okr_title:
                task.okr_title = title
                task.updated_at = datetime.utcnow()
                session.add(task)
                task_linked += 1
            if task.project_id:
                project_titles[task.project_id][title] += 1
        for project in projects:
            counter = project_titles.get(project.id)
            title = counter.most_common(1)[0][0] if counter and counter.most_common(1)[0][0] else ""
            if title != project.okr_title:
                project.okr_title = title
                project.updated_at = datetime.utcnow()
                session.add(project)
                project_linked += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    logger.info("OKR 挂接完成: tasks={} projects={}", task_linked, project_linked)
    return {"ok": True, "tasks_linked": task_linked, "projects_linked": project_linked, "dry_run": dry_run}
