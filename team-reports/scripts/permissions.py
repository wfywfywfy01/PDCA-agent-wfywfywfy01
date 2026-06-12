# -*- coding: utf-8 -*-
"""组织架构与查看权限。"""

from __future__ import annotations

from typing import Any

from report_io import read_json, team_reports_root


def load_org() -> dict[str, Any]:
    """读取组织架构配置。"""
    org_path = team_reports_root() / "config" / "org.json"
    if not org_path.exists():
        raise ValueError("未找到 team-reports/config/org.json")
    return read_json(org_path)


def load_team_members() -> list[str]:
    """读取全员 username 列表。"""
    team_path = team_reports_root() / "config" / "team.json"
    if not team_path.exists():
        return []
    data = read_json(team_path)
    return [member["username"] for member in data.get("members", []) if member.get("username")]


def get_role(viewer: str) -> str:
    """
    返回查看者角色：director / team_lead / member。
    """
    org = load_org()
    if viewer in org.get("directors", []):
        return "director"
    if viewer in org.get("team_leads", {}):
        return "team_lead"
    return "member"


def get_visible_usernames(viewer: str) -> list[str]:
    """
    返回查看者有权看到的 username 列表。

    - 总监：全员
    - 小组长：自己 + 组内成员（见 org.json）
    - 普通成员：仅自己
    """
    org = load_org()
    all_members = load_team_members()

    if viewer in org.get("directors", []):
        return all_members

    team_scope = org.get("team_leads", {}).get(viewer)
    if team_scope:
        return team_scope

    return [viewer]


def assert_can_view(viewer: str, target: str) -> None:
    """若 viewer 无权查看 target，抛出 PermissionError。"""
    visible = get_visible_usernames(viewer)
    if target not in visible:
        raise PermissionError(f"{viewer} 无权查看 {target} 的日报")


def describe_scope(viewer: str) -> dict[str, Any]:
    """返回查看者权限说明。"""
    org = load_org()
    role = get_role(viewer)
    visible = get_visible_usernames(viewer)
    labels = org.get("role_labels", {})
    return {
        "viewer": viewer,
        "role": role,
        "role_label": labels.get(role, role),
        "visible_usernames": visible,
        "visible_count": len(visible),
    }
