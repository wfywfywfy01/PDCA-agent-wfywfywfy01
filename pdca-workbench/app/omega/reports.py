"""Validate model claims against the frozen transcript before publication."""
from __future__ import annotations

import json
from fractions import Fraction


WEIGHTS = {
    "outcome": 25, "information": 12, "value": 12, "concessions": 12,
    "objections": 10, "listening": 8, "compliance": 10,
    "relationship": 6, "closure": 5,
}


def report_summary(report: dict) -> dict:
    """Pick evidence-backed skills by relative score, using stable rubric order for ties."""
    weights = report.get("score_weights") or WEIGHTS
    by_key = {item["key"]: item for item in report.get("dimensions", [])}
    eligible = [by_key[key] for key in WEIGHTS if key != "outcome" and key in by_key
                and by_key[key].get("score") is not None and by_key[key].get("quotes")]
    ratio = lambda item: Fraction(item["score"], weights[item["key"]])
    return {"score": report.get("score", {}), "goal_progress": report.get("outcome", {}),
            "strength": max(eligible, key=ratio) if eligible else None,
            "blocker": min(eligible, key=ratio) if eligible else None,
            "next_step": report.get("next_practice", "")}


def verify_quote(quote: dict, segments: dict[str, dict]) -> bool:
    segment = segments.get(str(quote.get("segment_id", "")))
    if not segment or quote.get("speaker") != segment.get("speaker"):
        return False
    if "speaker_id" in quote and quote["speaker_id"] != segment.get("speaker_id"):
        return False
    start, end = quote.get("start"), quote.get("end")
    if (type(start) is not int or type(end) is not int
            or start < 0 or end <= start):
        return False
    content = segment.get("text", "")
    return end <= len(content) and content[start:end] == quote.get("text")


def validate_next_practice(raw: str) -> str:
    try:
        action = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("下轮练习建议无效") from exc
    if (not isinstance(action, dict) or set(action) != {"next_practice"}
            or not isinstance(action["next_practice"], str)
            or not 1 <= len(action["next_practice"].strip()) <= 1000):
        raise ValueError("下轮练习建议无效")
    return action["next_practice"].strip()


def report_audit_claims(report: dict) -> list[dict]:
    """Enumerate every narrative slot without changing or shortening its text."""
    if not isinstance(report, dict):
        raise ValueError("复盘事实核验无效")
    outcome, dimensions = report.get("outcome"), report.get("dimensions")
    if (not isinstance(outcome, dict) or outcome.get("status") not in {
            "achieved", "partial", "not_achieved", "unverified"}
            or not isinstance(dimensions, list) or len(dimensions) != len(WEIGHTS)):
        raise ValueError("复盘事实核验无效")
    claims = []

    def add(claim_id, text, *, required):
        if text is None and not required:
            claims.append({"claim_id": claim_id, "text": None})
            return
        if not isinstance(text, str) or (required and not text.strip()):
            raise ValueError("复盘事实核验无效")
        claims.append({"claim_id": claim_id, "text": text})

    add("outcome.reason", outcome.get("reason"), required=outcome["status"] != "unverified")
    for index, dimension in enumerate(dimensions):
        if not isinstance(dimension, dict):
            raise ValueError("复盘事实核验无效")
        add(f"dimensions[{index}].reason", dimension.get("reason"), required=dimension.get("score") is not None)
    for name in ("commitments", "concession_costs", "hard_limit_findings"):
        items = report.get(name, [])
        if not isinstance(items, list):
            raise ValueError("复盘事实核验无效")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError("复盘事实核验无效")
            add(f"{name}[{index}].description", item.get("description"), required=True)
    return claims


def validate_report_audit(raw: str, report: dict) -> None:
    """Require an exact, positive check for every slot in the same validated report."""
    expected = {claim["claim_id"] for claim in report_audit_claims(report)}
    def unique_object(pairs):
        if len(dict(pairs)) != len(pairs):
            raise ValueError("复盘事实核验无效")
        return dict(pairs)

    try:
        audit = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("复盘事实核验无效") from exc
    codes = {"speaker_mismatch", "chronology", "condition_unconfirmed",
             "answered_fact_omitted", "unsupported_fact"}
    if not isinstance(audit, dict) or set(audit) != {"checks"} or not isinstance(audit["checks"], list):
        raise ValueError("复盘事实核验无效")
    seen, consistent = set(), True
    for check in audit["checks"]:
        if (not isinstance(check, dict) or set(check) != {"claim_id", "consistent", "issues"}
                or not isinstance(check["claim_id"], str) or check["claim_id"] not in expected
                or check["claim_id"] in seen or type(check["consistent"]) is not bool
                or not isinstance(check["issues"], list) or len(check["issues"]) > 5
                or not all(isinstance(code, str) and code in codes for code in check["issues"])
                or len(set(check["issues"])) != len(check["issues"])
                or check["consistent"] != (not check["issues"])):
            raise ValueError("复盘事实核验无效")
        seen.add(check["claim_id"])
        consistent = consistent and check["consistent"]
    if seen != expected:
        raise ValueError("复盘事实核验无效")
    if not consistent:
        raise ValueError("复盘事实核验未通过")


def validate_report(raw: str, segments: list[dict], *, goal_timing: str = "pre",
                    weights: dict[str, int] | None = None) -> dict:
    weights = weights or WEIGHTS
    try:
        report = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("报告不是完整 JSON") from exc
    if not isinstance(report, dict):
        raise ValueError("报告结构无效")
    report["goal_timing"] = goal_timing
    source = {part["id"]: part for part in segments}

    def check_quotes(quotes, *, sales_required=False):
        if not isinstance(quotes, list):
            raise ValueError("引文列表无效")
        for quote in quotes:
            if not isinstance(quote, dict) or not verify_quote(quote, source):
                raise ValueError("引文与当前逐字稿不匹配")
            speaker_id = source[str(quote["segment_id"])].get("speaker_id")
            if speaker_id:
                quote["speaker_id"] = speaker_id
        if sales_required and not any(q["speaker"] == "sales" for q in quotes):
            raise ValueError("销售评价缺少销售原话")

    outcome = report.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("status") not in {
        "achieved", "partial", "not_achieved", "unverified",
    }:
        raise ValueError("成果判定无效")
    check_quotes(outcome.get("quotes", []))
    if goal_timing != "pre":
        outcome.update(status="unverified", reason="目标未能证明在会前确认；不评价目标达成度", quotes=[])
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
        check_quotes(quotes, sales_required=score is not None and (key != "outcome" or goal_timing == "pre"))
        if key == "outcome" and goal_timing != "pre":
            dim.update(score=None, reason="目标未能证明在会前确认", quotes=[])
            continue
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
    next_practice = report.get("next_practice", "")
    if isinstance(next_practice, dict):
        next_practice = next_practice.get("动作", next_practice.get("action", ""))
    report["next_practice"] = next_practice.strip()[:1000] if isinstance(next_practice, str) else ""
    report["score"] = {"earned": earned, "available": available,
                       "coverage_percent": available, "total": earned if available == 100 else None}
    report["score_weights"] = weights
    report["summary"] = report_summary(report)
    return report
