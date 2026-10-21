"""One monthly policy for collection, group reports, previews and AI facts.

OCR amounts remain evidence. Qualification is recalculated without changing the
archived ledger or making another model call. Database errors propagate so a
saved rule can never silently turn back into a bundled default.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.duzhan_monthly_metric import DuzhanMonthlyMetric


def validate_month(value: str) -> str:
    try:
        if len(value) != 7 or date.fromisoformat(value + "-01").strftime("%Y-%m") != value:
            raise ValueError
    except ValueError:
        raise ValueError("月份格式应为 YYYY-MM，且月份必须存在") from None
    return value


def department_group(channel_id: str):
    from app.duzhan import GROUPS
    from app.duzhan_departments import department_for

    group = next((group for group in GROUPS if group.channel_id == channel_id), None)
    if group is None or department_for(group.name) is None:
        raise ValueError("请选择已有的督战部门群")
    return group


class MonthlyMetricsIn(BaseModel):
    channel_id: str
    month: str
    goal: Literal["amount", "break_zero"]
    sales_target_wan: float | None = Field(default=None, gt=0, le=1e9, allow_inf_nan=False)
    mto_daily_count: int = Field(ge=1, le=100, strict=True)
    mto_min_wan: float = Field(gt=0, le=1e6, allow_inf_nan=False)
    version: int = Field(default=0, ge=0, strict=True)

    _month = field_validator("month")(validate_month)

    @field_validator("sales_target_wan", "mto_min_wan", mode="before")
    @classmethod
    def _numeric(cls, value):
        if isinstance(value, bool):
            raise ValueError("金额必须是数值")
        return value

    @field_validator("channel_id")
    @classmethod
    def _channel(cls, value: str) -> str:
        department_group(value)
        return value

    @model_validator(mode="after")
    def _goal(self):
        if self.goal == "amount" and self.sales_target_wan is None:
            raise ValueError("请填写业绩目标，单位为人民币万元")
        if self.goal == "break_zero":
            self.sales_target_wan = None
        return self


def _default_metrics(channel_id: str, month: str) -> dict:
    from app.duzhan_departments import _file_target, department_for

    group = department_group(channel_id)
    plan = _file_target(department_for(group.name), month + "-01")
    return dict(channel_id=channel_id, month=month,
                goal="break_zero" if plan.get("goal") == "break_zero" else "amount",
                sales_target_wan=plan.get("target_wan"), mto_daily_count=4, mto_min_wan=30,
                version=0, updated_at=None, source="bundled" if plan else "unset")


def _row_metrics(row: DuzhanMonthlyMetric) -> dict:
    stamp = row.updated_at.replace(tzinfo=timezone.utc) if row.updated_at.tzinfo is None else row.updated_at
    return {**row.model_dump(exclude={"id", "updated_at"}), "updated_at": stamp.isoformat(), "source": "saved"}


def effective_metrics(channel_id: str, month: str, *, session: Session | None = None) -> dict:
    validate_month(month)
    if session is None:
        from app.duzhan_admin.runtime import using_db

        if not using_db():
            return _default_metrics(channel_id, month)
        from app.database import get_engine

        with Session(get_engine()) as current:
            return effective_metrics(channel_id, month, session=current)
    row = session.exec(select(DuzhanMonthlyMetric).where(
        DuzhanMonthlyMetric.channel_id == channel_id, DuzhanMonthlyMetric.month == month)).first()
    return _row_metrics(row) if row else _default_metrics(channel_id, month)


def monthly_response(session: Session, channel_id: str, month: str) -> dict:
    department_group(channel_id)
    months = session.exec(select(DuzhanMonthlyMetric.month).where(
        DuzhanMonthlyMetric.channel_id == channel_id).order_by(DuzhanMonthlyMetric.month.desc())).all()
    return {"metrics": effective_metrics(channel_id, month, session=session), "saved_months": list(months)}


def save_metrics(session: Session, payload: MonthlyMetricsIn) -> dict:
    fields = payload.model_dump(exclude={"version"})
    try:
        if payload.version == 0:
            session.add(DuzhanMonthlyMetric(**fields))
        else:
            result = session.execute(update(DuzhanMonthlyMetric).where(
                DuzhanMonthlyMetric.channel_id == payload.channel_id,
                DuzhanMonthlyMetric.month == payload.month,
                DuzhanMonthlyMetric.version == payload.version,
            ).values(**fields, version=payload.version + 1, updated_at=datetime.now(timezone.utc)))
            if result.rowcount != 1:
                session.rollback()
                raise HTTPException(409, "本月指标已被其他页面修改，请重新载入后再保存")
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "本月指标已被其他页面修改，请重新载入后再保存") from None
    session.expire_all()
    return monthly_response(session, payload.channel_id, payload.month)


def metrics_for_owner(group_name: str, day: str) -> dict:
    from app.duzhan import GROUPS

    group = next(group for group in GROUPS if group.name == group_name)
    return effective_metrics(group.channel_id, day[:7])


def _amount(value) -> bool:
    try:
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def recheck_row(row: dict, metrics: dict) -> dict:
    """Reclassify known quote amounts, preserving unavailable/incomplete sources."""
    result = {**row, "mto_daily_goal": metrics["mto_daily_count"], "mto_min_wan": metrics["mto_min_wan"]}
    quotes = row.get("mto_quotes")
    if not isinstance(quotes, list) or any(not isinstance(quote, dict) for quote in quotes):
        return {**result, "mto_count": None}
    result["mto_quotes"] = [dict(quote, qualifies=_amount(quote.get("wan"))
                                  and quote.get("raw_ok") is not False
                                  and quote["wan"] >= metrics["mto_min_wan"]) for quote in quotes]
    for quote in result["mto_quotes"]:
        quote["verdict"] = ("达标" if quote["qualifies"] else
                            f"未满{metrics['mto_min_wan']:g}万" if _amount(quote.get("wan"))
                            and quote.get("raw_ok") is not False else "金额待确认")
    from app.mto_ocr import summarize_quotes

    _, result["mto_names"] = summarize_quotes(result["mto_quotes"], min_wan=metrics["mto_min_wan"])
    source_count = row.get("mto_count")
    source_known = (row.get("history_ok") is True and _amount(source_count)
                    and source_count <= len(quotes))
    complete = all(_amount(quote.get("wan")) and quote.get("raw_ok") is not False for quote in quotes)
    result["mto_count"] = (sum(quote["qualifies"] for quote in result["mto_quotes"])
                           if source_known and complete else None)
    return result


def policy_rows(rows: list[dict], day: str) -> list[dict]:
    from app.duzhan_departments import department_for, is_task_only

    policies = {}
    result = []
    for row in rows:
        group_name = str(row.get("group") or "")
        if department_for(group_name) and not is_task_only(group_name, str(row.get("display") or "")):
            if group_name not in policies:
                policies[group_name] = metrics_for_owner(group_name, day)
            metrics = policies[group_name]
            row = (recheck_row(row, metrics) if metrics["source"] == "saved" else
                   {**row, "mto_daily_goal": metrics["mto_daily_count"], "mto_min_wan": metrics["mto_min_wan"]})
        result.append(row)
    return result


def configured_sales_target(month: str) -> tuple[float, list[str]] | None:
    """Keep the legacy file for untouched months; sum saved department rules."""
    from app.daily_report import _bundled_sales_target
    from app.duzhan import GROUPS
    from app.duzhan_admin.runtime import using_db
    from app.duzhan_departments import department_for

    if not using_db():
        return _bundled_sales_target(month)
    from app.database import get_engine

    with Session(get_engine()) as session:
        metrics = [(department_for(group.name), effective_metrics(group.channel_id, month, session=session))
                   for group in GROUPS if department_for(group.name)]
    if not any(values["source"] == "saved" for _, values in metrics):
        return _bundled_sales_target(month)
    if any(values["goal"] == "amount" and values["sales_target_wan"] is None for _, values in metrics):
        raise ValueError("部分部门本月业绩目标未设置，海外合计待确认")
    total = sum(values["sales_target_wan"] or 0 for _, values in metrics)
    details = [f"{department.name} " + ("破零" if values["goal"] == "break_zero"
               else f"{values['sales_target_wan']:g} 万") for department, values in metrics]
    return total * 10000, details
