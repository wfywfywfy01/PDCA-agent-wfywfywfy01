"""Validate model claims against the frozen transcript before publication."""
from __future__ import annotations

import json


WEIGHTS = {
    "outcome": 25, "information": 12, "value": 12, "concessions": 12,
    "objections": 10, "listening": 8, "compliance": 10,
    "relationship": 6, "closure": 5,
}


def verify_quote(quote: dict, segments: dict[str, dict]) -> bool:
    segment = segments.get(str(quote.get("segment_id", "")))
    if not segment or quote.get("speaker") != segment.get("speaker"):
        return False
    start, end = quote.get("start"), quote.get("end")
    if (type(start) is not int or type(end) is not int
            or start < 0 or end <= start):
        return False
    content = segment.get("text", "")
    return end <= len(content) and content[start:end] == quote.get("text")


def validate_report(raw: str, segments: list[dict], *, goal_timing: str = "pre",
                    weights: dict[str, int] | None = None) -> dict:
    weights = weights or WEIGHTS
    try:
        report = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("报告不是完整 JSON") from exc
    if not isinstance(report, dict):
        raise ValueError("报告结构无效")
    if goal_timing != "pre":
        outcome = report.get("outcome")
        if isinstance(outcome, dict):
            outcome.update(status="unverified", reason="目标未能证明在会前确认；不评价目标达成度", quotes=[])
        for dim in report.get("dimensions", []):
            if isinstance(dim, dict) and dim.get("key") == "outcome":
                dim.update(score=None, reason="目标未能证明在会前确认", quotes=[])
    report["goal_timing"] = goal_timing
    source = {part["id"]: part for part in segments}

    def check_quotes(quotes, *, sales_required=False):
        if not isinstance(quotes, list):
            raise ValueError("引文列表无效")
        for quote in quotes:
            if not isinstance(quote, dict) or not verify_quote(quote, source):
                raise ValueError("引文与当前逐字稿不匹配")
        if sales_required and not any(q["speaker"] == "sales" for q in quotes):
            raise ValueError("销售评价缺少销售原话")

    outcome = report.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("status") not in {
        "achieved", "partial", "not_achieved", "unverified",
    }:
        raise ValueError("成果判定无效")
    check_quotes(outcome.get("quotes", []))
    if outcome["status"] in {"achieved", "partial"} and not outcome.get("quotes"):
        raise ValueError("成果判定缺少原话")
    dimensions = report.get("dimensions")
    if not isinstance(dimensions, list) or len(dimensions) != len(weights):
        raise ValueError("九维评分缺失")
    seen = set()
    earned = available = 0
    for dim in dimensions:
        if not isinstance(dim, dict):
            raise ValueError("评分结构无效")
        key = dim.get("key")
        if key not in weights or key in seen:
            raise ValueError("评分项重复或未知")
        seen.add(key)
        score = dim.get("score")
        quotes = dim.get("quotes", [])
        check_quotes(quotes, sales_required=score is not None)
        if score is None:
            if quotes:
                raise ValueError("证据不足的评分项不能附打分引文")
            continue
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= weights[key]:
            raise ValueError("评分越界")
        earned += score
        available += weights[key]
    for name in ("commitments", "concession_costs", "hard_limit_findings"):
        for item in report.get(name, []):
            if not isinstance(item, dict):
                raise ValueError("事实项结构无效")
            check_quotes(item.get("quotes", []))
            if not item.get("quotes"):
                raise ValueError("事实项缺少原话")
    report["score"] = {"earned": earned, "available": available,
                       "coverage_percent": available, "total": earned if available == 100 else None}
    report["score_weights"] = weights
    return report
