# -*- coding: utf-8 -*-
"""待办提炼（推送层）：同类碎片合并成一条可执行事项。

Vemory 会议待办是逐句摘录的原始发言，同一事项常被拆成多条：
- 完全重复（同一句话被不同参会人各记一条 / 中英双版本之一）
- 同一事项的碎片（「下班之前完善投流方案」+「完成领英投流方案整理并发给团队」）

compose_tasks() 把同一负责人名下的待办聚类：同簇合并为一条「组合事项」，
消息只推组合件（标题取簇内最具信息量的原始句，标注同项条数）；
原始条目保留在库（回复闭环/状态机仍按原始行驱动，互不影响）。
"""
from __future__ import annotations

import re
from collections import defaultdict

from app.models.pdca_task import PdcaTask

_LATIN_RE = re.compile(r"[a-z0-9+.-]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

# 停用词：不参与相似度计算（避免「跟进/安排」这类泛词造成误合并）
_STOP_TOKENS = {
    "继续", "跟进", "一下", "这个", "相关", "进行", "项目", "我们", "他们",
    "需要", "安排", "情况", "推进", "工作", "今天", "之后", "完成", "处理",
    "一起", "问题", "一个", "已经", "后续", "确认", "对接", "沟通", "联系",
    "同步", "落实", "了解", "看看", "讨论", "准备", "发送", "发给", "大家",
    "团队", "回复",
}


def _tokens(title: str) -> set[str]:
    """英文词 + 中文二字组（去停用词）→ 相似度比较的 token 集。"""
    text = (title or "").strip().lower()
    latin = _LATIN_RE.findall(text)
    bigrams: list[str] = []
    for run in _CJK_RE.findall(text):
        for i in range(max(0, len(run) - 1)):
            bigrams.append(run[i : i + 2])
    return {token for token in [*latin, *bigrams] if token not in _STOP_TOKENS}


def _containment(a: set[str], b: set[str]) -> float:
    """重叠占较短者比例（长句与短句同义时也能命中）。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / min(len(a), len(b))


def _repr_title(tasks: list[PdcaTask]) -> str:
    """簇内代表标题：8~48 字符的中长句优先，含数字/英文加分，同分取更长。"""
    best = ""
    best_score = -1
    for task in tasks:
        title = (task.title or "").strip()
        if not title:
            continue
        length = len(title)
        score = 3 if 8 <= length <= 48 else (1 if length < 8 else 2)
        if re.search(r"\d", title):
            score += 2
        if _LATIN_RE.search(title):
            score += 1
        if score > best_score or (score == best_score and length > len(best)):
            best_score = score
            best = title
    return best or (tasks[0].title or "")


def _norm(title: str) -> str:
    """标准化标题（去标点空白小写）：完全重复判定用。"""
    return re.sub(r"[\s,，。.!！?？;；:：()（）'\"“”‘’]+", "", (title or "").lower())


def compose_tasks(tasks: list[PdcaTask]) -> list[dict]:
    """同一负责人名下的待办 → 组合事项列表（调用方已按 owner 分组）。

    返回 [{"title", "task_ids", "count", "merged", "rep"}]，
    按最早 task_date 升序（逾期在前）；rep 为代表性原始行（日期/状态标记用）。
    """
    items = [t for t in tasks if t and (t.title or "").strip()]
    if not items:
        return []

    # 1) 完全重复 → 直接合并
    norm_groups: dict[str, list[PdcaTask]] = defaultdict(list)
    leftovers: list[PdcaTask] = []
    for task in items:
        norm = _norm(task.title)
        if norm:
            norm_groups[norm].append(task)
        else:
            leftovers.append(task)

    clusters: list[list[PdcaTask]] = [
        group for group in norm_groups.values() if len(group) > 1
    ]
    leftovers += [group[0] for group in norm_groups.values() if len(group) == 1]

    # 2) 相似碎片：共同非停用 token ≥2 且重叠占较短者 ≥30% → 合并
    used: set[int] = set()
    for i, task in enumerate(leftovers):
        if i in used:
            continue
        cluster = [task]
        ti = _tokens(task.title)
        for j in range(i + 1, len(leftovers)):
            if j in used:
                continue
            tj = _tokens(leftovers[j].title)
            if len(ti & tj) >= 2 and _containment(ti, tj) >= 0.3:
                cluster.append(leftovers[j])
                used.add(j)
        used.add(i)
        clusters.append(cluster)

    # 3) 组装并按最早日期排序
    result: list[dict] = []
    for cluster in clusters:
        cluster.sort(key=lambda t: t.task_date or "")
        rep = cluster[0]
        result.append(
            {
                "title": _repr_title(cluster),
                "task_ids": [t.id for t in cluster if t.id],
                "count": len(cluster),
                "merged": len(cluster) > 1,
                "rep": rep,
            }
        )
    result.sort(key=lambda item: item["rep"].task_date or "")
    return result
