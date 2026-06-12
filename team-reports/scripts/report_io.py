# -*- coding: utf-8 -*-
"""团队 Cursor 日报系统 — 共享工具模块。"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def repo_root() -> Path:
    """返回仓库根目录（team-reports 的上一级）。"""
    return Path(__file__).resolve().parents[2]


def team_reports_root() -> Path:
    """返回 team-reports 目录。"""
    return Path(__file__).resolve().parents[1]


def load_env() -> None:
    """加载 team-reports/.env 环境变量。"""
    env_path = team_reports_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()


def get_username() -> str:
    """从环境变量或 config/user.json 读取用户名。"""
    env_user = os.getenv("CURSOR_REPORT_USER", "").strip()
    if env_user:
        return env_user

    config_path = team_reports_root() / "config" / "user.json"
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        username = str(data.get("username", "")).strip()
        if username:
            return username

    raise ValueError(
        "未配置用户名。请设置 CURSOR_REPORT_USER 或创建 team-reports/config/user.json"
    )


def daily_dir(username: str | None = None) -> Path:
    """返回某用户的 daily 目录。"""
    user = username or get_username()
    return team_reports_root() / "daily" / user


def weekly_dir(username: str | None = None) -> Path:
    """返回某用户的 weekly 目录。"""
    user = username or get_username()
    return team_reports_root() / "weekly" / user


def monthly_dir(username: str | None = None) -> Path:
    """返回某用户的 monthly 目录。"""
    user = username or get_username()
    return team_reports_root() / "monthly" / user


def parse_iso_date(value: str) -> date:
    """解析 YYYY-MM-DD 日期字符串。"""
    return datetime.strptime(value, "%Y-%m-%d").date()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """写入 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    """读取 JSON 文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def write_markdown(path: Path, content: str) -> None:
    """写入 Markdown 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_daily_markdown(report: dict[str, Any]) -> str:
    """将日报 JSON 渲染为 Markdown。"""
    lines = [
        f"# Cursor 日报 — {report.get('user', '')} — {report.get('date', '')}",
        "",
        f"- 生成时间：{report.get('generated_at', '')}",
        f"- 会话数：{report.get('total_sessions', 0)}",
        f"- 对话轮次：{report.get('total_turns', 0)}",
        "",
        "## 今日摘要",
        "",
        str(report.get("daily_summary", "")).strip() or "（无）",
        "",
        "## 关键主题",
        "",
    ]
    for topic in report.get("key_topics", []):
        lines.append(f"- {topic}")
    if not report.get("key_topics"):
        lines.append("- （无）")

    lines.extend(["", "## 涉及文件", ""])
    for file_path in report.get("all_files_modified", []):
        lines.append(f"- {file_path}")
    if not report.get("all_files_modified"):
        lines.append("- （无）")

    lines.extend(["", "## 会话明细", ""])
    for session in report.get("sessions", []):
        lines.extend(
            [
                f"### {session.get('summary', '未命名会话')}",
                "",
                f"- 会话 ID：`{session.get('id', '')}`",
                f"- 轮次：{session.get('turns', 0)}",
                f"- 结果：{session.get('outcome', 'unknown')}",
                f"- 工具：{', '.join(session.get('tools_used', [])) or '（无）'}",
                f"- 主题：{', '.join(session.get('topics', [])) or '（无）'}",
                "",
            ]
        )

    return "\n".join(lines)


def iter_daily_json_files(root: Path | None = None) -> list[Path]:
    """遍历 daily 目录下所有 JSON 文件。"""
    base = root or (team_reports_root() / "daily")
    if not base.exists():
        return []
    return sorted(base.glob("*/*.json"))


def iter_weekly_json_files(root: Path | None = None) -> list[Path]:
    """遍历 weekly 目录下所有 JSON 文件。"""
    base = root or (team_reports_root() / "weekly")
    if not base.exists():
        return []
    return sorted(base.glob("*/*.json"))
