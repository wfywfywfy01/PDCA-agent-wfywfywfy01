# -*- coding: utf-8 -*-
"""PDCA 智能体静态注册表与运行时状态探测。

数据来源：
- PDCA 智能体分工以 AGENTS.md《Agent 分工》为准，这里固化 7 个角色的元数据；
- Hermes 档案以本机 profiles 目录探测存在性；
- 模型路由只读展示环境变量（PDCA_SUPERVISOR_* / PDCA_QWEN_*），未配置不猜测。
"""
from __future__ import annotations

import os
from pathlib import Path

# 7 个 PDCA 智能体（与 AGENTS.md 一致）。
# status: active=日常运行 / planned=规划中
PDCA_AGENTS: list[dict] = [
    {
        "key": "team-pdca-planner",
        "name": "小组目标规划师",
        "role": "维护小组目标、默认过程指标和月度指标模板",
        "outputs": ["monthly_targets/", "teams/yang-jingjing/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "daily-sales-log-checker",
        "name": "销售日报检查员",
        "role": "检查销售日报是否提交、字段是否完整；缺失时标记高风险并生成补交动作",
        "outputs": ["daily_logs/", "check_reports/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "team-kpi-checker",
        "name": "团队 KPI 检查员",
        "role": "检查团队和个人业绩、回款、过程指标完成情况",
        "outputs": ["check_reports/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "customer-coverage-checker",
        "name": "客户覆盖检查员",
        "role": "检查客户负责人分布、重点客户跟进日期和资源失衡",
        "outputs": ["check_reports/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "pdca-action-agent",
        "name": "明日行动建议员",
        "role": "根据 Check 结果生成个人明日行动建议",
        "outputs": ["pdca_actions/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "coaching-agent",
        "name": "组长辅导教练",
        "role": "生成组长辅导动作和成员培养建议",
        "outputs": ["coaching/"],
        "status": "active",
        "model_task": "text",
    },
    {
        "key": "quota-allocation-agent",
        "name": "目标分配规划师",
        "role": "根据销售画像、客户池和区域机会分配目标（规划中）",
        "outputs": ["monthly_targets/"],
        "status": "planned",
        "model_task": "text",
    },
]

# 视觉任务（MTO 报价图 OCR 等）只用本地 Qwen 网关；其余文本任务只用 DeepSeek flash。
MODEL_ROUTING_RULES: list[dict] = [
    {
        "task": "text",
        "label": "文本任务（主 Agent 决策、群草稿润色等）",
        "provider_env": "PDCA_SUPERVISOR_PROVIDER",
        "model_env": "PDCA_SUPERVISOR_MODEL",
        "default_note": "DeepSeek flash",
    },
    {
        "task": "vision",
        "label": "图像 / OCR / 视觉任务（MTO 报价图）",
        "provider_env": "PDCA_QWEN_BASE_URL",
        "model_env": "PDCA_QWEN_MODEL",
        "default_note": "本地 Qwen 网关 qwen3.8-27b",
    },
]


def hermes_home_candidates() -> list[Path]:
    """Hermes profiles 目录候选（与 scripts/init-hermes-profiles.ps1 的口径一致）。"""
    candidates: list[Path] = []
    env_home = os.environ.get("HERMES_HOME")
    if env_home:
        candidates.append(Path(env_home))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "hermes")
    candidates.append(Path.home() / ".hermes")
    return candidates


def hermes_profiles_root() -> Path | None:
    """返回本机实际使用的 Hermes profiles 根目录（不存在返回 None）。"""
    for base in hermes_home_candidates():
        root = base / "profiles"
        if root.is_dir():
            return root
        # 兼容直接把 profile 放在 HERMES_HOME 下的部署
        if base.is_dir() and any(p.is_dir() for p in base.iterdir() if not p.name.startswith(".")):
            return base
    return None


def hermes_profiles_snapshot() -> list[dict]:
    """本机 Hermes 档案列表（探测存在性，只读）。"""
    root = hermes_profiles_root()
    if root is None:
        return []
    items: list[dict] = []
    for path in sorted(root.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        soul = path / "SOUL.md"
        env_file = path / ".env"
        items.append(
            {
                "name": path.name,
                "path": str(path),
                "soul_exists": soul.is_file(),
                "env_exists": env_file.is_file(),
            }
        )
    return items


def model_routing_snapshot() -> list[dict]:
    """模型路由只读快照：展示环境变量当前值，缺失标注为未配置。"""
    items: list[dict] = []
    for rule in MODEL_ROUTING_RULES:
        provider = os.environ.get(rule["provider_env"], "")
        model = os.environ.get(rule["model_env"], "")
        items.append(
            {
                "task": rule["task"],
                "label": rule["label"],
                "provider": provider,
                "model": model,
                "configured": bool(provider or model),
                "default_note": rule["default_note"],
            }
        )
    return items


def pdca_agents_snapshot() -> list[dict]:
    """PDCA 智能体清单（注册表元数据 + 只读运行时状态）。"""
    hermes = {item["name"]: item for item in hermes_profiles_snapshot()}
    items: list[dict] = []
    for agent in PDCA_AGENTS:
        entry = dict(agent)
        entry["hermes_profile_linked"] = agent["key"] in hermes
        items.append(entry)
    return items
