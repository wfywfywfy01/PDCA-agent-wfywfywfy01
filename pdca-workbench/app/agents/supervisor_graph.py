# -*- coding: utf-8 -*-
"""主 Agent（Supervisor）：结构化决策、确定性路由与事实校验（第 7 节）。

分层：
- 确定性路由（classify_intent）：已知命令直接走工具，不调 LLM；
- LLM 决策（decision_with_llm）：理解、拆解、冲突处理，输出 SupervisorDecision
  契约，解析失败回退确定性分类（模型故障不吞任务）；
- 事实校验（fact_check_summary）：金额/人名/来源/None-0 的确定性检查。
"""
from __future__ import annotations

import json
import re

from loguru import logger

from app.agents.schemas import SupervisorAction, SupervisorDecision

# 确定性路由：已知命令 -> (intent, 工具计划)。命中即不再调用 LLM。
_ROUTES: tuple[tuple[tuple[str, ...], str, list[tuple[str, str]]], ...] = (
    (("今日待办", "谁有多少待办", "待办统计", "闭环", "闭环率"), "known_readonly_query",
     [("task_stats", "all")]),
    (("群状态", "群 state", "group state", "各群"), "known_readonly_query",
     [("group_state", "all")]),
    (("健康检查", "slot health", "档位健康", "健康状态"), "known_readonly_query",
     [("slot_health", "all")]),
    (("部门总结", "部门早会", "早会提纲", "department summary"), "department_summary",
     [("collect", "all"), ("draft_summary", "department")]),
    (("审批", "outbox", "待批准"), "known_readonly_query",
     [("outbox_list", "pending")]),
)


def classify_intent(text: str) -> SupervisorDecision | None:
    """确定性意图路由；命中返回决策，未命中返回 None（交给 LLM）。"""
    normalized = (text or "").strip().casefold()
    if not normalized:
        return SupervisorDecision(intent="ask_user", summary="任务为空")
    for keywords, intent, actions in _ROUTES:
        if any(keyword.casefold() in normalized for keyword in keywords):
            return SupervisorDecision(
                intent=intent,
                summary=text[:500],
                actions=[SupervisorAction(action_type=name, target=target) for name, target in actions],
                unknowns=[],
            )
    return None


def decision_with_llm(text: str, context: dict | None = None) -> SupervisorDecision:
    """用本地 Qwen 输出结构化决策；失败回退保守分类（不吞任务）。"""
    fallback = SupervisorDecision(
        intent="ask_user",
        summary=(text or "")[:500],
        unknowns=["模型不可用，需人工确认任务范围"],
    )
    try:
        from app.agents.llm_client import QwenUnavailable, supervisor_client
        from app.agents.prompts import load_supervisor

        client = supervisor_client()
        if not client.configured:
            return fallback
        context_text = json.dumps(context or {}, ensure_ascii=False)[:6000]
        reply = client.chat(
            [
                {"role": "system", "content": load_supervisor()},
                {
                    "role": "user",
                    "content": (
                        "任务：" + text[:4000] + "\n\n当前上下文（JSON）：\n" + context_text
                        + "\n\n请输出 SupervisorDecision JSON（字段：intent, summary, "
                        "target_groups, actions[{action_type,target,deadline,reason}], "
                        "approval_required, unknowns）。"
                    ),
                },
            ],
            max_tokens=8192,  # deepseek-flash 为推理模型：reasoning 可能占 10K+ token，预算必须够大否则 content 为空
            temperature=0.1,
        )
        raw = (reply.get("content") or "").strip()
        decision = _parse_decision(raw)
        if decision is not None:
            return decision
        logger.warning("Supervisor 决策 JSON 解析失败，回退 ask_user; raw={}", raw[:200])
        return fallback
    except QwenUnavailable as exc:
        logger.warning("Supervisor 模型不可用，回退 ask_user: {}", exc)
        return fallback
    except Exception as exc:  # noqa: BLE001
        logger.warning("Supervisor 决策异常，回退 ask_user: {}", exc)
        return fallback


def _parse_decision(raw: str) -> SupervisorDecision | None:
    """宽容解析 LLM 输出：剥离代码围栏后按 Pydantic 校验。"""
    text = (raw or "").strip()
    fence = re.search(r"\{[\s\S]*\}", text)
    candidate = fence.group(0) if fence else text
    try:
        payload = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    try:
        return SupervisorDecision.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.debug("SupervisorDecision 校验失败: {}", exc)
        return None



# 人名注册表：事实代码（duzhan_ledger.OWNERS / ctob.OWNERS）为准。
_ALLOWED_OWNERS: tuple[str, ...] = (
    "邓琳莹", "Safae", "王宇彤", "张月馨", "于冰", "杨晶晶", "何海文", "Viki", "Lina",
    "张心言", "刘佳鑫", "周佳丽", "刘彦麟", "陈晓霜", "郑丽苹", "许淋玲", "陈莉",
    "李玉琴", "贾梦林", "李晓悦", "向俞金", "夏欢", "宋依亭", "何川", "陈玉霞",
)


def known_owners() -> frozenset[str]:
    """全部已知人名（注册表 + 兜底名单）。"""
    return frozenset(name for name in _ALLOWED_OWNERS if name)


def fact_check_summary(summary: str, evidence_map: dict[str, str] | None = None) -> list[dict]:
    """对部门总结做确定性事实校验；返回问题列表（空列表 = 通过）。

    检查项（规格 7.6）：
    - 总结中的人名必须在注册表（或证据来源）中；
    - “None/无数据”不得写成 0；
    - 出现金额时必须能在 evidence_map 证据文本中找到同额；
    - 出现合同/折扣/圣诞/黑五/提前备货类结论必须附证据引用。
    """
    problems: list[dict] = []
    if not summary:
        return [{"rule": "empty_summary", "detail": "总结为空"}]
    text = summary
    owners = known_owners()
    _PERSON_STOPWORDS = re.compile(
        r"今日|今天|昨日|明天|已|的|了|在|要|将|是|请|给|与|和|及|等|向|从|对|还|也|就|都|不|未|无|有|没|为|由|经|需|可|并|或|但|而|其|这|那|于|按|把|被|说|报|提|交|完|成|回|款|数|量|率|总|人|员|组|群|单|项|条"
    )
    _PERSON_EXCEPTIONS = {
        "待确认", "红黑榜", "早会", "督战", "部门", "达标", "日报", "回款", "客户", "卡点",
        "海外", "渠道", "会议", "复盘", "总结", "汇总",
    }
    for run in re.findall(r"[\u4e00-\u9fffA-Za-z]{2,30}", text):
        if re.fullmatch(r"[A-Za-z]+", run) and run.casefold() in {
            "mto", "vps", "okr", "whatsapp", "vemory", "im", "pdca", "ok", "wa",
        }:
            continue
        if not re.search(r"[\u4e00-\u9fff]", run):
            continue
        # 把长中文串按高频动作/状态词切分，只对 2-3 字的人名候选做注册表校验。
        for name in _PERSON_STOPWORDS.split(run):
            if not 2 <= len(name) <= 3:
                continue
            if name in owners or name in _PERSON_EXCEPTIONS:
                continue
            problems.append({"rule": "unknown_person", "detail": "未知人名: " + name})
    # None 当 0 检测：出现 0 且上下文有“无/未/缺失”则提示复核。
    for match in re.finditer(r".{0,12}(?:无|未|缺失|没).{0,6}0(?:万|个|条|项|次)?", text):
        problems.append({"rule": "none_as_zero_suspect", "detail": match.group(0).strip()})
    risky_terms = ("合同", "折扣", "返点", "权益", "圣诞", "黑五", "提前备货", "扣罚", "红黑榜")
    for term in risky_terms:
        if term in text:
            problems.append({"rule": "risky_term_needs_source", "detail": term})
    evidence_map = evidence_map or {}
    for amount in re.findall(r"\d+(?:\.\d+)?\s*(?:万|w|W|usd|USD|美元|美刀)", text):
        if not any(amount in value for value in evidence_map.values()):
            problems.append({"rule": "amount_without_source", "detail": amount})
    return problems


def build_department_summary(day: str) -> dict:
    """部门总结的确定性聚合（LLM 只做措辞；数据全部来自状态库）。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.agents.group_context import (
        ctob_group_configs,
        load_open_tasks,
        load_slot_snapshot,
        performance_group_configs,
    )
    from app.agents.outbox import list_outbox

    sections: dict[str, object] = {}
    open_tasks = load_open_tasks()
    by_owner: dict[str, list[dict]] = {}
    for task in open_tasks:
        by_owner.setdefault(task.get("owner") or "未指定", []).append(task)
    sections["open_tasks_by_owner"] = {
        owner: {"open": len(tasks), "blocked": sum(1 for t in tasks if t.get("blocked_reason"))}
        for owner, tasks in sorted(by_owner.items(), key=lambda item: -len(item[1]))
    }
    sections["ctob_groups"] = len(ctob_group_configs(day))
    sections["performance_groups"] = len(performance_group_configs(day))
    latest_snapshot = None
    for hour in (20, 15, 10):
        latest_snapshot = load_slot_snapshot("Asia/Shanghai", day, hour)
        if latest_snapshot:
            sections["latest_slot"] = {
                "hour": latest_snapshot["hour"],
                "prepared_at": latest_snapshot["prepared_at"],
                "red": latest_snapshot["red"][:5],
                "black": latest_snapshot["black"][:5],
            }
            break
    if latest_snapshot is None:
        sections["latest_slot"] = None
    pending = list_outbox(approval_status="pending", limit=20)
    sections["pending_approvals"] = len(pending)
    sections["data_unknowns"] = [
        "WhatsApp 私聊正文是否完整覆盖：待确认",
        "ASR 转写覆盖范围：待确认",
    ]
    return {
        "date": day,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "sections": sections,
        "summary_draft": (
            "海外渠道今日督战汇总（请人工复核后发布）：\n"
            f"- 达标群 {sections['performance_groups']} 个、C转B 群 {sections['ctob_groups']} 个；\n"
            f"- 未闭环待办按人统计见 open_tasks_by_owner；\n"
            f"- 待批准外发 {sections['pending_approvals']} 条；\n"
            "- 合同/折扣/权益相关结论非正式法律意见，须人工复核；\n"
            "- 数据缺失项见 data_unknowns（写“待确认”，不当作 0）。"
        ),
    }

