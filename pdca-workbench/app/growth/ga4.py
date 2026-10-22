# -*- coding: utf-8 -*-
"""只读拉取 GA4 Data API（服务账号 JWT）。

凭据不入库：PDCA_GROWTH_GA4_PROPERTY_ID + PDCA_GROWTH_GA4_SA_FILE（或 SA_JSON）。
国内/阿里云出口访问不了 googleapis.com 时会失败；可设 PDCA_GROWTH_HTTPS_PROXY。
选题表是一份 TSV（title\\turl），路径 PDCA_GROWTH_SEO_TOPICS_FILE，用来和页面流量对齐。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
_METRICS = ("screenPageViews", "sessions", "activeUsers", "engagementRate", "keyEvents")
_CONTENT = ("/news/", "/lifestyle/", "/guides/", "/blog")
SNAPSHOT_VERSION = 2  # Older snapshots substituted zero for unreported topic paths.


class Ga4Error(RuntimeError):
    """GA4 未配置、认证失败或网络不可达。"""


def _property_id() -> str:
    return os.environ.get("PDCA_GROWTH_GA4_PROPERTY_ID", "").strip()


def _service_account() -> dict | None:
    raw = os.environ.get("PDCA_GROWTH_GA4_SA_JSON", "").strip()
    if raw:
        return json.loads(raw)
    path = os.environ.get("PDCA_GROWTH_GA4_SA_FILE", "").strip()
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return None


def configured() -> bool:
    """属性 ID 和服务账号都有才算可拉取。"""
    return bool(_property_id()) and _service_account() is not None


def _opener() -> urllib.request.OpenerDirector:
    proxy = (os.environ.get("PDCA_GROWTH_HTTPS_PROXY") or os.environ.get("HTTPS_PROXY") or "").strip()
    if not proxy:
        return urllib.request.build_opener()
    return urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))


def _post(url: str, body: bytes, content_type: str, token: str = "") -> dict:
    headers = {"Content-Type": content_type}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with _opener().open(req, timeout=40) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")
        try:
            detail = json.loads(detail).get("error", {}).get("message") or detail
        except json.JSONDecodeError:
            pass
        raise Ga4Error(f"GA4 HTTP {exc.code}: {detail[:300]}") from exc
    except urllib.error.URLError as exc:
        raise Ga4Error(
            "连不上 Google Analytics（当前出口访问不了 googleapis.com，"
            f"需要 PDCA_GROWTH_HTTPS_PROXY）：{exc.reason}"
        ) from exc


def _access_token(account: dict) -> str:
    from jose import jwt

    now = int(time.time())
    claims = {
        "iss": account["client_email"],
        "scope": SCOPE,
        "aud": account["token_uri"],
        "iat": now,
        "exp": now + 3600,
    }
    assertion = jwt.encode(claims, account["private_key"], algorithm="RS256")
    if isinstance(assertion, bytes):
        assertion = assertion.decode()
    payload = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": assertion,
    }).encode()
    data = _post(account["token_uri"], payload, "application/x-www-form-urlencoded")
    token = data.get("access_token")
    if not token:
        raise Ga4Error("OAuth 没有返回 access_token")
    return token


def _rows(report: dict) -> list[dict]:
    out = []
    for row in report.get("rows") or []:
        dims, mets = row.get("dimensionValues") or [], row.get("metricValues") or []
        if not dims or len(mets) < 5:
            continue
        out.append({
            "page": dims[0].get("value") or "",
            "views": int(float(mets[0].get("value") or 0)),
            "sessions": int(float(mets[1].get("value") or 0)),
            "users": int(float(mets[2].get("value") or 0)),
            "engRate": round(float(mets[3].get("value") or 0), 3),
            "keyEvents": int(float(mets[4].get("value") or 0)),
        })
    return out


def _report(days: int, limit: int, dimension_filter: dict) -> list[dict]:
    account = _service_account()
    prop = _property_id()
    if not account or not prop:
        raise Ga4Error("GA4 未配置")
    token = _access_token(account)
    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "yesterday"}],
        "dimensions": [{"name": "pagePath"}],
        "metrics": [{"name": name} for name in _METRICS],
        "dimensionFilter": dimension_filter,
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
        "limit": str(limit),
    }
    url = f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport"
    return _rows(_post(url, json.dumps(body).encode(), "application/json", token))


def content_rows(days: int = 28, limit: int = 40) -> list[dict]:
    """内容频道（news/lifestyle/guides/blog）按浏览量倒序。"""
    exprs = [
        {"filter": {"fieldName": "pagePath", "stringFilter": {"matchType": "CONTAINS", "value": p}}}
        for p in _CONTENT
    ]
    return _report(days, limit, {"orGroup": {"expressions": exprs}})


def path_rows(days: int, contains: str, limit: int = 100) -> list[dict]:
    """pagePath 包含某段的全部页面。"""
    filt = {"filter": {"fieldName": "pagePath", "stringFilter": {"matchType": "CONTAINS", "value": contains}}}
    return _report(days, limit, filt)


def _norm(path: str) -> str:
    path = path.split("?", 1)[0].strip()
    if path.startswith("http"):
        path = urllib.parse.urlparse(path).path
    while "//" in path:
        path = path.replace("//", "/")
    if path and not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def load_topics() -> list[dict]:
    """选题表 TSV：title、url。文件不存在则空列表。"""
    path = os.environ.get("PDCA_GROWTH_SEO_TOPICS_FILE", "").strip()
    if not path or not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or line.lower().startswith("title\t"):
                continue
            title, _, url = line.partition("\t")
            title, url = title.strip(), url.strip()
            if title:
                out.append({"title": title, "url": url, "path": _norm(url) if url else ""})
    return out


def _fmt(row: dict) -> str:
    return f"{row['page']}\t{row['views']}\t{row['sessions']}\t{row['users']}\t{row['engRate']}\t{row['keyEvents']}"


def _snapshot_path() -> str:
    return os.environ.get("PDCA_GROWTH_GA4_SNAPSHOT", "").strip()


def _read_snapshot() -> dict | None:
    path = _snapshot_path()
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data.get("table"):
        return None
    if data.get("schema_version") != SNAPSHOT_VERSION:
        raise Ga4Error("旧版 GA4 快照无法区分未查到与零流量，请用更新后的同步脚本重新生成快照")
    data["stale"] = True
    return data


def _write_snapshot(payload: dict) -> None:
    path = _snapshot_path()
    if not path:
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    os.replace(tmp, path)


def _snapshot_age_hours() -> float | None:
    path = _snapshot_path()
    if not path or not os.path.isfile(path):
        return None
    return (time.time() - os.path.getmtime(path)) / 3600


def briefing(days: int = 28, limit: int = 40, *, force: bool = False) -> dict:
    """有快照就直接返回。杭州服务器访问不了 Google，刷新由能连 Google 的机器写入快照。"""
    if not force:
        cached = _read_snapshot()
        if cached:
            age = _snapshot_age_hours()
            cached["age_hours"] = round(age, 1) if age is not None else None
            return cached
    try:
        payload = _live_briefing(days, limit)
    except Ga4Error as exc:
        cached = _read_snapshot()
        if not cached:
            raise
        cached["error"] = str(exc)
        cached["age_hours"] = None
        return cached
    payload["stale"] = False
    payload["fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _write_snapshot(payload)
    return payload


def _live_briefing(days: int = 28, limit: int = 40) -> dict:
    """直接调 GA4。"""
    days = min(max(int(days), 1), 90)
    top = content_rows(days, limit)
    partners = path_rows(days, "/news/partners/", 100)
    by_path: dict[str, dict] = {}
    for row in partners:
        key = _norm(row["page"])
        prev = by_path.get(key)
        if not prev:
            by_path[key] = dict(row)
            continue
        for field in ("views", "sessions", "users", "keyEvents"):
            prev[field] += row[field]
    lines = [
        f"GA4 content pages, last {days} days. key_events = configured conversions (0 means none or not set).",
        f"Source: GA4 Data API pagePath report; top {limit} content pages and top 100 partner pages. "
        "N/A = not reported in this limited result, NOT zero traffic.",
        "page\tviews\tsessions\tusers\tengagement_rate\tkey_events",
        *[_fmt(row) for row in top],
        "",
        "dealer topic sheet joined to GA4 (/news/partners/)",
        "topic\turl\tviews\tsessions\tengagement_rate",
    ]
    topics = load_topics()
    if not topics:
        lines.append("(topic sheet not configured)")
    for topic in topics:
        hit = by_path.get(topic["path"]) if topic["path"] else None
        if not topic["url"]:
            lines.append(f"{topic['title']}\t(not published)\t\t\t")
        elif not hit:
            lines.append(f"{topic['title']}\t{topic['url']}\tN/A\tN/A\tN/A")
        else:
            lines.append(
                f"{topic['title']}\t{topic['url']}\t{hit['views']}\t{hit['sessions']}\t{hit['engRate']}"
            )
    return {"days": days, "top": len(top), "topics": len(topics), "table": "\n".join(lines),
            "schema_version": SNAPSHOT_VERSION,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
