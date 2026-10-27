"""Read-only route-5 traffic evidence; no customer or revenue inference."""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ga4

METRICS = ("screenPageViews", "sessions", "activeUsers", "engagedSessions")
SNAPSHOT_ENV = "PDCA_GROWTH_PARTNER_GA4_SNAPSHOT"
SCOPES = {
    "recruitment": {"label": "Partner 招募入口", "pattern": r"^(/[a-z]{2}(-[A-Za-z]{2})?)?/partners/?$"},
    "content": {"label": "Partner 内容文章", "pattern": r"^/+([a-z]{2}(-[A-Za-z]{2})?/)?news/partners(/.*)?$"},
}
AI_SOURCE = r"^((www\.)?(chatgpt\.com|chat\.openai\.com|perplexity\.ai|claude\.ai|copilot\.microsoft\.com|gemini\.google\.com|poe\.com|you\.com)|chatgpt|perplexity|claude|copilot|gemini)$"


def _filter(field, value, match="EXACT"):
    return {"filter": {"fieldName": field, "stringFilter": {
        "matchType": match, "value": value, "caseSensitive": False}}}


def qa_filter():
    return {"orGroup": {"expressions": [
        _filter("sessionMedium", "qa"),
        {"filter": {"fieldName": "sessionSource", "inListFilter": {
            "values": ["codex_prod_canary", "codex_release_test"], "caseSensitive": False}}},
    ]}}


def scope_filter(scope, *, include_qa=False):
    expressions = [
        {"filter": {"fieldName": "hostName", "inListFilter": {
            "values": ["vertu.com", "www.vertu.com"], "caseSensitive": False}}},
        _filter("pagePath", SCOPES[scope]["pattern"], "FULL_REGEXP"),
    ]
    if not include_qa:
        expressions.append({"notExpression": qa_filter()})
    return {"andGroup": {"expressions": expressions}}


def _integer(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number != number.to_integral_value():
            raise ValueError
        return int(number)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ga4.Ga4Error("GA4 返回无效计数，未替换为零") from exc


def query(token, prop, start, end, filt, dimensions):
    """Paginate fully and preserve the exact requests/responses, without auth headers."""
    rows, requests, responses, quality = [], [], [], set()
    expected_count, report_zone = None, None
    while True:
        body = {"dateRanges": [{"startDate": start, "endDate": end}],
                "dimensions": [{"name": name} for name in dimensions],
                "metrics": [{"name": name} for name in METRICS], "dimensionFilter": filt,
                "orderBys": ([{"dimension": {"dimensionName": name}} for name in dimensions]
                             if dimensions else []), "limit": "1000", "offset": str(len(rows))}
        raw = ga4._post(f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport",
                        json.dumps(body).encode(), "application/json", token)
        if ([h.get("name") for h in raw.get("dimensionHeaders", [])] != dimensions
                or [h.get("name") for h in raw.get("metricHeaders", [])] != list(METRICS)):
            raise ga4.Ga4Error("GA4 返回字段与查询不一致，未采用结果")
        batch = raw.get("rows") or []
        count = _integer(raw.get("rowCount", 0))
        if expected_count is not None and count != expected_count:
            raise ga4.Ga4Error("GA4 分页总数变化，请重试完整查询")
        expected_count = count
        metadata = raw.get("metadata") or {}
        zone = metadata.get("timeZone")
        if not zone or (report_zone and report_zone != zone):
            raise ga4.Ga4Error("GA4 缺少或返回不一致的报表时区")
        report_zone = zone
        for flag in ("subjectToThresholding", "dataLossFromOtherRow", "samplingMetadatas"):
            if metadata.get(flag):
                quality.add(flag)
        for row in batch:
            dims, metrics = row.get("dimensionValues", []), row.get("metricValues", [])
            if len(dims) != len(dimensions) or len(metrics) != len(METRICS):
                raise ga4.Ga4Error("GA4 数据行缺字段，未采用结果")
            rows.append({**{name: item.get("value", "") for name, item in zip(dimensions, dims)},
                         **{name: _integer(item.get("value")) for name, item in zip(METRICS, metrics)}})
        requests.append(body)
        responses.append(raw)
        if len(rows) == count:
            break
        if not batch or len(rows) > count or len(rows) >= 20000:
            raise ga4.Ga4Error("GA4 明细未读取完整，未用截断结果代替总量")
    return {"rows": rows, "row_count": count, "time_zone": report_zone,
            "quality": sorted(quality), "requests": requests, "responses": responses}


def summary(result):
    if not result["rows"]:
        return dict.fromkeys(METRICS)
    if len(result["rows"]) != 1:
        raise ga4.Ga4Error("GA4 汇总返回多行，不能相加去重用户数")
    return {name: result["rows"][0][name] for name in METRICS}


def collect(days=28, *, end_date=None):
    if not 1 <= days <= 90:
        raise ga4.Ga4Error("统计周期须为1至90天")
    today = datetime.now(ZoneInfo("Asia/Hong_Kong")).date()
    end = date.fromisoformat(end_date) if end_date else today - timedelta(days=1)
    if end >= today:
        raise ga4.Ga4Error("只查询已结束的自然日")
    start = end - timedelta(days=days - 1)
    prop, account = ga4._property_id(), ga4._service_account()
    if not re.fullmatch(r"[0-9]+", prop) or not account:
        raise ga4.Ga4Error("GA4 属性与后端服务账号尚未配置")
    token = ga4._access_token(account)
    scopes, evidence, quality = {}, {}, set()
    for key, definition in SCOPES.items():
        base = scope_filter(key)
        raw_base = scope_filter(key, include_qa=True)
        reports = {}
        for kind, dimensions, extra in (
            ("summary", [], None),
            ("seo", [], _filter("sessionDefaultChannelGroup", "Organic Search")),
            ("ai", [], _filter("sessionSource", AI_SOURCE, "FULL_REGEXP")),
            ("daily", ["date"], None),
            ("pages", ["pagePath"], None),
            ("sources", ["sessionSource", "sessionMedium", "sessionDefaultChannelGroup"], None),
            ("raw_summary", [], None),
            ("excluded_qa", [], qa_filter()),
        ):
            scoped = raw_base if kind in ("raw_summary", "excluded_qa") else base
            filt = {"andGroup": {"expressions": [scoped, extra]}} if extra else scoped
            result = query(token, prop, start.isoformat(), end.isoformat(), filt, dimensions)
            if result["time_zone"] != "Asia/Hong_Kong":
                raise ga4.Ga4Error("GA4 属性时区已改变，需重新核对自然日口径")
            quality.update(result["quality"])
            reports[kind] = summary(result) if not dimensions else result["rows"]
            evidence[f"{key}.{kind}"] = result
        for row in reports["sources"]:
            row["source_type"] = ("ai" if re.fullmatch(AI_SOURCE, row["sessionSource"], re.I)
                                  else "seo" if row["sessionDefaultChannelGroup"] == "Organic Search" else "other")
        scopes[key] = {**definition, **reports}
    return {"schema_version": 1, "route": 5, "source": "GA4 Data API", "property_id": prop,
            "site_hosts": ["vertu.com", "www.vertu.com"], "days": days,
            "test_traffic_excluded": True, "test_filter": qa_filter(),
            "period": {"start_date": start.isoformat(), "end_date": end.isoformat(), "time_zone": "Asia/Hong_Kong"},
            "fetched_at": datetime.now(timezone.utc).isoformat(), "scopes": scopes,
            "quality": sorted(quality), "evidence": evidence,
            "notes": ["页面流量归第5路径，仅是获客上游指标，不是独立客户、线索、订单或回款。",
                      "主报告排除medium=qa或来源codex_prod_canary/codex_release_test；原始和已标记QA汇总分别查询，用户数不相减。",
                      "仍可能包含未标记内部访问；保留原始来源供核查，不按来源名称推断真实客户。",
                      "SEO按GA4会话默认渠道Organic Search识别；AI来源为显式来源白名单，仅作GEO观察。",
                      "来源丢失、应用内访问及搜索内AI结果不能由此完整识别；未返回匹配行显示N/A。",
                      "汇总独立查询；会话和用户不相加页面或每日明细。招募入口与文章范围也不相加去重用户。",
                      "日界线按GA4属性时区；截至昨天的数据仍可能被GA4后续处理修订。"], "stale": False}


def write_snapshot(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                     prefix=target.name + ".", suffix=".tmp", delete=False) as fh:
        temporary = Path(fh.name)
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _cached(days):
    path = os.environ.get(SNAPSHOT_ENV, "").strip()
    if not path or not Path(path).is_file():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if (data.get("schema_version") != 1 or data.get("route") != 5
                or data.get("source") != "GA4 Data API" or data.get("days") != days
                or data.get("test_traffic_excluded") is not True
                or not {"recruitment", "content"}.issubset(data.get("scopes", {}))):
            raise ValueError
        fetched = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            raise ValueError
        age = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600
        if age < -0.1:
            raise ValueError
        end = date.fromisoformat(data["period"]["end_date"])
        start = date.fromisoformat(data["period"]["start_date"])
        if (end - start).days + 1 != days or data["period"]["time_zone"] != "Asia/Hong_Kong":
            raise ValueError
        data["age_hours"] = round(max(0, age), 1)
        data["stale"] = age > 24 or end < datetime.now(ZoneInfo("Asia/Hong_Kong")).date() - timedelta(days=1)
        data["delivery"] = "snapshot"
        return data
    except (KeyError, TypeError, ValueError) as exc:
        raise ga4.Ga4Error("Partner流量快照版本或统计周期不匹配，请重新同步") from exc


def briefing(days=28, *, force=False):
    try:
        cached = _cached(days)
    except ga4.Ga4Error:
        if not force:
            raise
        cached = None  # An incompatible snapshot cannot be used as a fallback.
    if cached and not force:
        return cached
    try:
        data = collect(days)
    except ga4.Ga4Error as exc:
        if not cached:
            raise
        return {**cached, "stale": True, "error": str(exc)}
    path = os.environ.get(SNAPSHOT_ENV, "").strip()
    if path:
        write_snapshot(path, data)
    return {**data, "delivery": "live", "age_hours": 0}
