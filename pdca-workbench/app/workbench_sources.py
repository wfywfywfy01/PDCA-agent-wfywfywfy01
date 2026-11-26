"""Read-only sales workspace queries under a verified VPS identity."""
import os
from datetime import date, datetime, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from app.auth.models import User
from app.config import get_settings
from app.knowledge.client import request_json, require_knowledge_access
from app.todos.vemory import fetch_vemory_todos, load_vemory_users


class SourceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeQuery(SourceQuery):
    kind: Literal["knowledge-search"]
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class DateQuery(SourceQuery):
    start: date
    end: date

    @model_validator(mode="after")
    def check_date_order(self):
        if self.start > self.end:
            raise ValueError("开始日期不能晚于结束日期")
        return self


class VemoryQuery(DateQuery):
    kind: Literal["vemory-todos"]

    @model_validator(mode="after")
    def check_vemory_window(self):
        if (self.end - self.start).days > 6:
            raise ValueError("Vemory 一次最多查询七天")
        return self


class SalesQuery(DateQuery):
    kind: Literal["ainative-sales"]
    report: Literal["performance", "customers", "reach"]

    @model_validator(mode="after")
    def check_sales_window(self):
        if (self.end - self.start).days > 30:
            raise ValueError("AINativeSales 一次最多查询三十一天")
        return self


WorkbenchSourceQuery = Annotated[KnowledgeQuery | VemoryQuery | SalesQuery, Field(discriminator="kind")]


def _result(source: str, columns: list[str], rows: list[dict], detail: str) -> dict:
    return {"source": source, "columns": columns, "rows": rows, "total": len(rows),
            "detail": detail, "checkedAt": datetime.now(timezone.utc).isoformat()}


async def _knowledge(query: KnowledgeQuery, request: Request, user: User, session: Session) -> dict:
    require_knowledge_access(user, session)
    payload = await request_json(
        "POST", "/v1/search", user=user, session=session,
        request_id=getattr(request.state, "request_id", ""), body={"query": query.query, "top_k": 8},
    )
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or any(not isinstance(item, dict) or not isinstance(item.get("citation"), dict) for item in items):
        raise HTTPException(502, "知识库检索返回格式异常")
    rows = []
    for item in items:
        cite = item["citation"]
        page = cite.get("page_start")
        ending = cite.get("page_end")
        rows.append({"资料": cite.get("title") or cite.get("original_name"), "摘录": item.get("text"),
                     "位置": f"{page}–{ending}" if page is not None and ending not in (None, page) else page,
                     "版本": cite.get("version_number"), "资料编号": cite.get("asset_id") or item.get("asset_id")})
    return _result("PDCA 企业知识库", ["资料", "摘录", "位置", "版本", "资料编号"], rows, "当前账号可见的引用资料，最多 8 条")


def _vemory(query: VemoryQuery, directory_id: int) -> dict:
    api_key = os.environ.get("VEMORY_OPENAPI_KEY", "").strip()
    if not api_key:
        raise HTTPException(503, "Vemory 服务尚未配置")
    roster = [row for row in load_vemory_users()
              if str(row.get("vpsUserId") or row.get("vps_user_id") or row.get("im_user_id") or "") == str(directory_id)]
    if len(roster) != 1:
        raise HTTPException(403, "当前 VPS 账号没有唯一的 Vemory 绑定")
    try:
        items = fetch_vemory_todos(roster[0], api_key, get_settings().vemory_openapi_url,
                                  f"{query.start} 00:00:00", f"{query.end} 23:59:59")
    except (RuntimeError, ValueError, OSError, httpx.HTTPError) as error:
        raise HTTPException(502, "Vemory 暂时无法读取会议待办") from error
    rows = []
    for item in items:
        meeting = item["_meeting"]
        timestamp = meeting.get("start_record_time")
        when = datetime.fromtimestamp(timestamp / 1000, ZoneInfo("Asia/Shanghai")).isoformat() if isinstance(timestamp, (int, float)) and timestamp > 0 else None
        status = "待办" if item.get("status") == 0 else "已完成" if item.get("status") == 1 else None
        rows.append({"会议": meeting.get("meeting_name"), "会议时间": when, "待办": item.get("content"),
                     "期限": item.get("deadline") or None, "状态": status, "待办编号": item.get("id")})
    return _result("Vemory 会议与待办", ["会议", "会议时间", "待办", "期限", "状态", "待办编号"], rows,
                   f"{query.start} 至 {query.end}，北京时间，当前账号的会议待办")


def _sales(query: SalesQuery, directory_id: int) -> dict:
    from app.duzhan_ledger import mcp_call

    integration = os.environ.get("PDCA_WORKBENCH_AISALES_VPS_TOKEN", "").strip()
    if not integration and not get_settings().aisales_mcp_token:
        raise HTTPException(503, "AINativeSales 尚未配置工作台授权")

    def call(name: str, args: dict) -> dict:
        if integration:
            args = {**args, "vps_user_id": directory_id}
        reply = mcp_call(name, args, vps_integration_token=integration)
        if isinstance(reply, dict) and "权限不足" in str(reply.get("error") or ""):
            raise HTTPException(403, "当前账号没有这个 AINativeSales 查询权限")
        if not isinstance(reply, dict) or not isinstance(reply.get("rows"), list):
            raise HTTPException(502, "AINativeSales 查询失败，请检查上游权限或连接")
        return reply

    directory = call("business.resolve_subject", {"keyword": str(directory_id), "identifier_type": "vps_user_id"})
    matches = [row.get("employee_id") for row in directory["rows"] if isinstance(row, dict)
               and row.get("subject_type") == "employee" and row.get("exact_match") is True and row.get("employee_id")]
    if len(matches) != 1:
        raise HTTPException(403, "当前 VPS 账号没有唯一的 AINativeSales 绑定")
    employee_id = matches[0]
    if not integration:
        catalog = call("business.catalog", {"domain": "directory"})
        principal = (catalog.get("permission_scope") or {}).get("mapped_local_user_id")
        if principal is None or str(principal) != str(employee_id):
            raise HTTPException(403, "当前 VPS 账号需要单独配置 AINativeSales 授权")

    domain, mode = {"performance": ("stats", "summary"), "customers": ("conversations", "customers"),
                    "reach": ("conversations", "reach_summary")}[query.report]
    args = {"domain": domain, "query_mode": mode, "subject": {"employee_id": employee_id},
            "period": {"start_date": str(query.start), "end_date": str(query.end)}}
    if query.report == "customers":
        args["filters"] = {"page_size": 20}
    payload = call("business.query", args)
    rows = [{key: value for key, value in row.items() if value is None or type(value) in (str, int, float)}
            for row in payload["rows"] if isinstance(row, dict)][:20]
    summary = payload.get("summary")
    if not rows and query.report != "customers" and isinstance(summary, dict):
        rows = [{"指标": key, "数值": value} for key, value in summary.items() if value is None or type(value) in (str, int, float)]
    columns = list(dict.fromkeys(key for row in rows for key in row))
    complete = all(payload.get(key) is True for key in ("is_complete", "total_is_exact"))
    page = payload.get("pagination") or {}
    completeness = "仅当前页" if page.get("has_more") or len(payload["rows"]) > 20 else "完整性已核验"
    if not complete:
        completeness = "来源覆盖或总数未核验，仅供样本参考"
    return _result("AINativeSales", columns, rows,
                   f"{query.start} 至 {query.end} · {domain}.{mode} · {completeness}")


async def read_workbench_source(query: WorkbenchSourceQuery, request: Request, user: User, session: Session) -> dict:
    if isinstance(query, KnowledgeQuery):
        return await _knowledge(query, request, user, session)
    if isinstance(query, VemoryQuery):
        return await run_in_threadpool(_vemory, query, user.vps_user_id)
    return await run_in_threadpool(_sales, query, user.vps_user_id)
