# -*- coding: utf-8 -*-
"""新人培训 · SignalSeller × PDCA 课表与进度。"""
from __future__ import annotations

import json
from datetime import datetime

from loguru import logger
from sqlmodel import Session, select

from app.config import get_settings
from app.database import get_engine


def _curriculum_path():
    return get_settings().config_dir / "onboarding_curriculum.json"


def load_curriculum() -> dict:
    path = _curriculum_path()
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"title": "新人培训", "tracks": [], "pass_criteria": {}}


def _all_module_ids(curriculum: dict) -> list[dict]:
    items = []
    for track in curriculum.get("tracks", []):
        for mod in track.get("modules", []):
            items.append({
                "day": track.get("day", 0),
                "module_id": mod.get("id", ""),
                "title": mod.get("title", ""),
            })
    return items


def build_progress(username: str, role: str) -> dict:
    """读取用户培训进度。"""
    from app.models.onboarding_progress import OnboardingProgress

    curriculum = load_curriculum()
    modules = _all_module_ids(curriculum)
    total = len(modules)
    completed_ids: set[str] = set()
    try:
        with Session(get_engine()) as session:
            rows = session.exec(
                select(OnboardingProgress).where(OnboardingProgress.username == username),
            ).all()
            completed_ids = {r.module_id for r in rows}
    except Exception as exc:
        logger.warning("读取 onboarding_progress 失败: {}", exc)

    completed = len(completed_ids)
    current_day = 1
    for track in curriculum.get("tracks", []):
        day_mods = [m.get("id") for m in track.get("modules", [])]
        if all(mid in completed_ids for mid in day_mods if mid):
            current_day = max(current_day, track.get("day", 1) + 1)
        elif any(mid in completed_ids for mid in day_mods if mid):
            current_day = track.get("day", 1)
            break

    pass_criteria = curriculum.get("pass_criteria", {})
    min_modules = total
    # 之前对非 sales 角色（viewer/dealer/manager/admin）无条件判定 graduated=True，
    # 结果比如 manager 账号进度 1/20（5%）也显示"已完成上岗课表"，具有误导性——
    # 毕业与否统一按实际完成数判断，不再按角色开后门
    graduated = completed >= min_modules if min_modules else True

    return {
        "username": username,
        "role": role,
        "total_days": len(curriculum.get("tracks", [])),
        "total_modules": total,
        "completed_modules": completed,
        "completed_module_ids": sorted(completed_ids),
        "progress_pct": round(completed / total * 100) if total else 0,
        "current_day": min(current_day, len(curriculum.get("tracks", [])) or 1),
        "graduated": graduated,
    }


def complete_module(username: str, module_id: str, day: int = 1, score: int = 0, role: str = "sales") -> dict:
    """打卡完成一个培训模块。"""
    from app.models.onboarding_progress import OnboardingProgress

    if not module_id.strip():
        return {"ok": False, "detail": "module_id 不能为空"}
    score = max(0, min(100, score))
    try:
        with Session(get_engine()) as session:
            exists = session.exec(
                select(OnboardingProgress).where(
                    OnboardingProgress.username == username,
                    OnboardingProgress.module_id == module_id.strip(),
                ),
            ).first()
            if exists:
                exists.score = score
                exists.completed_at = datetime.utcnow()
                session.add(exists)
            else:
                session.add(
                    OnboardingProgress(
                        username=username,
                        day=day,
                        module_id=module_id.strip(),
                        score=score,
                    ),
                )
            session.commit()
        return {"ok": True, **build_progress(username, role)}
    except Exception as exc:
        logger.warning("写入 onboarding_progress 失败: {}", exc)
        return {"ok": False, "detail": str(exc)}
