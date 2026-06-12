# -*- coding: utf-8 -*-
"""
解析 Cursor agent-transcripts JSONL，按日期筛选并输出结构化会话数据。

用法:
  python parse_transcripts.py --date 2026-06-12
  python parse_transcripts.py --date today --workspace "D:/经销商PDCA"
  python parse_transcripts.py --date 2026-06-12 --output parsed.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from report_io import get_username, team_reports_root, write_json


TIMESTAMP_RE = re.compile(
    r"<timestamp>([^<]+)</timestamp>",
    re.IGNORECASE,
)
USER_QUERY_RE = re.compile(
    r"<user_query>\s*([\s\S]*?)\s*</user_query>",
    re.IGNORECASE,
)
FILE_PATH_KEYS = (
    "path",
    "target_file",
    "target_notebook",
    "file_path",
    "working_directory",
)
VALID_FILE_EXT = re.compile(
    r"\.(py|md|json|ps1|txt|html|csv|xlsx|js|ts|tsx|jsx|yaml|yml|sh|bat|gitignore|example)$",
    re.IGNORECASE,
)


def is_plausible_file_path(value: str) -> bool:
    """判断字符串是否像真实文件路径。"""
    if not value or "\n" in value or len(value) > 200:
        return False
    if value.startswith(("overview:", "编写 ", "创建 ", "不是，", "自动触发", "阿里云", "pip install")):
        return False
    normalized = value.replace("\\", "/").strip()
    if normalized.startswith(("**", "^/", "{", "`")):
        return False
    if "[REDACTED" in normalized:
        return False
    if re.match(r"^[a-zA-Z]:/", normalized):
        return "/" in normalized[3:] or VALID_FILE_EXT.search(normalized) is not None
    if normalized.startswith("d:/") or normalized.startswith("team-reports/"):
        return True
    if "/" in normalized and VALID_FILE_EXT.search(normalized):
        return True
    return False


def normalize_file_paths(paths: list[str]) -> list[str]:
    """清洗并去重文件路径。"""
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in paths:
        candidate = raw.replace("\\", "/").strip()
        if not is_plausible_file_path(candidate):
            continue
        if candidate not in seen:
            seen.add(candidate)
            cleaned.append(candidate)
    return sorted(cleaned)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="解析 Cursor agent transcripts")
    parser.add_argument(
        "--date",
        default="today",
        help="目标日期，格式 YYYY-MM-DD 或 today",
    )
    parser.add_argument(
        "--workspace",
        default="",
        help="工作区根目录，用于定位 agent-transcripts",
    )
    parser.add_argument(
        "--transcripts-dir",
        default="",
        help="直接指定 agent-transcripts 目录",
    )
    parser.add_argument(
        "--username",
        default="",
        help="用户名，默认读取 CURSOR_REPORT_USER",
    )
    parser.add_argument(
        "--timezone",
        default="Asia/Shanghai",
        help="时区，默认 Asia/Shanghai",
    )
    parser.add_argument(
        "--output",
        default="",
        help="输出 JSON 路径；默认打印到 stdout",
    )
    return parser.parse_args()


def resolve_target_date(raw: str, tz_name: str) -> date:
    """解析目标日期。"""
    tz = ZoneInfo(tz_name)
    if raw.lower() == "today":
        return datetime.now(tz).date()
    return datetime.strptime(raw, "%Y-%m-%d").date()


def slugify_workspace(path: Path) -> str:
    """根据工作区路径推断 Cursor projects slug。"""
    normalized = str(path.resolve()).replace("\\", "/")
    drive, _, rest = normalized.partition(":")
    if drive:
        slug = f"{drive.strip('/').lower()}-{rest.strip('/')}"
    else:
        slug = rest.strip("/")
    slug = re.sub(r"[^a-zA-Z0-9\-_/]+", "-", slug)
    slug = slug.replace("/", "-").replace("_", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug


def discover_transcripts_dir(workspace: str) -> Path:
    """自动发现 agent-transcripts 目录。"""
    if workspace:
        workspace_path = Path(workspace).resolve()
    else:
        workspace_path = team_reports_root().parent

    cursor_home = Path(os.path.expanduser("~/.cursor/projects"))
    candidates: list[Path] = []

    if cursor_home.exists():
        slug = slugify_workspace(workspace_path)
        candidates.extend(
            [
                cursor_home / slug / "agent-transcripts",
                cursor_home / workspace_path.name / "agent-transcripts",
            ]
        )
        for child in cursor_home.iterdir():
            if child.is_dir():
                candidates.append(child / "agent-transcripts")

    seen: set[Path] = set()
    unique_candidates: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(resolved)

    for candidate in unique_candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "未找到 agent-transcripts 目录。"
        f"请使用 --transcripts-dir 指定，或确认 Cursor 项目路径：{workspace_path}"
    )


def parse_timestamp(text: str, tz_name: str) -> date | None:
    """从 user 消息文本中提取日期。"""
    match = TIMESTAMP_RE.search(text)
    if not match:
        return None
    raw = match.group(1).strip()
    formats = [
        "%A, %b %d, %Y, %I:%M %p (UTC%z)",
        "%A, %B %d, %Y, %I:%M %p (UTC%z)",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(ZoneInfo(tz_name)).date()
        except ValueError:
            continue
    return None


def extract_user_query(text: str) -> str:
    """提取 user_query 内容。"""
    match = USER_QUERY_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def clean_assistant_text(text: str) -> str:
    """尽量保留面向用户的中文回复，去掉明显的内部推理英文段。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    zh_lines = [line for line in lines if re.search(r"[\u4e00-\u9fff]", line)]
    if zh_lines:
        return "\n".join(zh_lines[:8])
    return "\n".join(lines[:5])


def collect_paths_from_input(value: Any, bucket: set[str]) -> None:
    """递归收集工具参数中的文件路径。"""
    if isinstance(value, str):
        normalized = value.replace("\\", "/").strip()
        if not normalized or normalized.startswith("http"):
            return
        if normalized.startswith("**") or normalized.startswith("^/"):
            return
        if "[REDACTED" in normalized or "REDACTED" in normalized:
            return
        if re.search(r"[\\/]", normalized) or re.search(r"\.[a-zA-Z0-9]{1,6}$", normalized):
            if len(normalized) <= 260 and not normalized.startswith("{"):
                bucket.add(normalized)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if key in FILE_PATH_KEYS and isinstance(item, str):
                bucket.add(item.replace("\\", "/"))
            else:
                collect_paths_from_input(item, bucket)
    elif isinstance(value, list):
        for item in value:
            collect_paths_from_input(item, bucket)


def normalize_repo_files(paths: set[str], workspace: Path | None = None) -> list[str]:
    """过滤并规范化仓库相关文件路径。"""
    workspace = workspace or team_reports_root().parent
    workspace_text = str(workspace.resolve()).replace("\\", "/").lower()
    cleaned: set[str] = set()

    for raw in paths:
        if not raw or "\n" in raw or len(raw) > 200:
            continue
        if any(token in raw for token in ("Get-ChildItem", "pip install", "overview:", "创建 ", "编写 ", "不是，")):
            continue
        if raw.startswith(("**", "^/", "`", "*.", "/.")):
            continue

        normalized = raw.replace("\\", "/")
        lower = normalized.lower()
        if lower.startswith(workspace_text):
            rel = normalized[len(workspace_text) :].lstrip("/")
            if rel and ("/" in rel or "." in Path(rel).name):
                cleaned.add(rel)
        elif re.match(r"^[A-Za-z0-9_./-]+\.[A-Za-z0-9]{1,8}$", normalized):
            cleaned.add(normalized)

    return sorted(cleaned)


def infer_topics(*texts: str) -> list[str]:
    """从文本中推断简单主题词。"""
    joined = " ".join(texts)
    keywords = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}|[\u4e00-\u9fff]{2,8}", joined)
    stopwords = {
        "今天",
        "帮我",
        "一下",
        "怎么",
        "这个",
        "我们",
        "可以",
        "已经",
        "需要",
        "subagent",
        "completed",
        "REDACTED",
        "the",
        "and",
        "for",
        "with",
        "user",
        "query",
        "Explore",
    }
    counter: Counter[str] = Counter()
    for word in keywords:
        key = word.strip()
        if len(key) < 2 or key.lower() in stopwords:
            continue
        counter[key] += 1
    return [word for word, _ in counter.most_common(5)]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 JSONL 文件。"""
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def session_id_from_path(path: Path) -> str:
    """从 transcript 路径推断 session id。"""
    return path.stem


def parse_session_file(path: Path, target_date: date, tz_name: str) -> dict[str, Any] | None:
    """解析单个 session transcript 文件。"""
    rows = load_jsonl(path)
    if not rows:
        return None

    user_queries: list[str] = []
    assistant_snippets: list[str] = []
    tools_used: set[str] = set()
    files_touched: set[str] = set()
    timestamps: list[date] = []
    turn_count = 0
    outcome = "unknown"
    error_message = ""

    for row in rows:
        if row.get("type") == "turn_ended":
            outcome = row.get("status", "unknown")
            error_message = row.get("error", "")
            continue

        role = row.get("role")
        message = row.get("message", {})
        contents = message.get("content", [])
        if role == "user":
            turn_count += 1
        for block in contents:
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text", "")
                ts = parse_timestamp(text, tz_name)
                if ts:
                    timestamps.append(ts)
                if role == "user":
                    query = extract_user_query(text)
                    if query:
                        user_queries.append(query)
                elif role == "assistant":
                    snippet = clean_assistant_text(text)
                    if snippet:
                        assistant_snippets.append(snippet)
            elif block_type == "tool_use":
                tool_name = block.get("name", "")
                if tool_name:
                    tools_used.add(tool_name)
                collect_paths_from_input(block.get("input", {}), files_touched)

    file_mtime_date = datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo(tz_name)).date()
    session_dates = set(timestamps)
    session_dates.add(file_mtime_date)

    if target_date not in session_dates:
        return None

    first_query = user_queries[0] if user_queries else "未命名会话"
    summary = first_query.splitlines()[0][:120]
    topics = infer_topics(*user_queries, *assistant_snippets)

    return {
        "id": session_id_from_path(path),
        "summary": summary,
        "topics": topics,
        "turns": turn_count,
        "tools_used": sorted(tools_used),
        "files_touched": sorted(files_touched),
        "user_queries": user_queries[:20],
        "assistant_snippets": assistant_snippets[:10],
        "outcome": outcome,
        "error_message": error_message,
        "source_file": str(path),
    }


def collect_session_files(transcripts_dir: Path) -> list[tuple[Path, list[Path]]]:
    """收集主会话及对应 subagent 文件。"""
    grouped: list[tuple[Path, list[Path]]] = []
    for jsonl in sorted(transcripts_dir.glob("*/*.jsonl")):
        if jsonl.parent.name == "subagents":
            continue
        subagent_dir = jsonl.parent / "subagents"
        subagents = sorted(subagent_dir.glob("*.jsonl")) if subagent_dir.exists() else []
        grouped.append((jsonl, subagents))
    return grouped


def merge_session_parts(
    main: dict[str, Any] | None,
    extras: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """将 subagent 解析结果合并进主会话。"""
    parts = [part for part in [main, *extras] if part]
    if not parts:
        return None

    merged = dict(parts[0])
    for part in parts[1:]:
        merged["turns"] = merged.get("turns", 0) + part.get("turns", 0)
        merged["tools_used"] = sorted(set(merged.get("tools_used", [])) | set(part.get("tools_used", [])))
        merged["files_touched"] = sorted(set(merged.get("files_touched", [])) | set(part.get("files_touched", [])))
        merged["user_queries"].extend(part.get("user_queries", []))
        merged["assistant_snippets"].extend(part.get("assistant_snippets", []))
        merged["topics"] = infer_topics(
            *merged.get("user_queries", []),
            *merged.get("assistant_snippets", []),
        )
        if part.get("outcome") == "error":
            merged["outcome"] = "error"
            merged["error_message"] = part.get("error_message", "")

    first_query = merged.get("user_queries", [])
    if first_query:
        merged["summary"] = first_query[0].splitlines()[0][:120]
    elif not merged.get("summary"):
        merged["summary"] = "未命名会话"
    return merged


def build_daily_report(
    sessions: list[dict[str, Any]],
    target_date: date,
    username: str,
    tz_name: str,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """构建日报 JSON 结构。"""
    total_turns = sum(session.get("turns", 0) for session in sessions)
    all_files: set[str] = set()
    topic_counter: Counter[str] = Counter()
    for session in sessions:
        session["files_touched"] = normalize_repo_files(
            set(session.get("files_touched", [])),
            workspace,
        )
        all_files.update(session.get("files_touched", []))
        for topic in session.get("topics", []):
            topic_counter[topic] += 1

    if sessions:
        summaries = [f"- {item['summary']}" for item in sessions[:8]]
        daily_summary = "今日 Cursor 工作概览：\n" + "\n".join(summaries)
    else:
        daily_summary = "今日未检测到 Cursor 会话记录。"

    generated_at = datetime.now(ZoneInfo(tz_name)).isoformat()
    return {
        "date": target_date.isoformat(),
        "user": username,
        "generated_at": generated_at,
        "total_sessions": len(sessions),
        "total_turns": total_turns,
        "sessions": [
            {
                "id": session["id"],
                "summary": session["summary"],
                "topics": session["topics"],
                "turns": session["turns"],
                "tools_used": session["tools_used"],
                "files_touched": session["files_touched"],
                "outcome": session["outcome"],
            }
            for session in sessions
        ],
        "daily_summary": daily_summary,
        "key_topics": [topic for topic, _ in topic_counter.most_common(8)],
        "all_files_modified": sorted(all_files),
        "_raw_sessions": sessions,
    }


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    target_date = resolve_target_date(args.date, args.timezone)
    username = args.username.strip() or get_username()

    if args.transcripts_dir:
        transcripts_dir = Path(args.transcripts_dir).resolve()
    else:
        transcripts_dir = discover_transcripts_dir(args.workspace)

    session_files = collect_session_files(transcripts_dir)
    parsed_sessions: list[dict[str, Any]] = []
    for main_file, subagent_files in session_files:
        main_parsed = parse_session_file(main_file, target_date, args.timezone)
        extra_parsed = [
            parse_session_file(path, target_date, args.timezone)
            for path in subagent_files
        ]
        extra_parsed = [item for item in extra_parsed if item]
        merged = merge_session_parts(main_parsed, extra_parsed)
        if merged:
            parsed_sessions.append(merged)

    parsed_sessions.sort(key=lambda item: item.get("summary", ""))
    workspace_path = Path(args.workspace).resolve() if args.workspace else team_reports_root().parent
    report = build_daily_report(
        parsed_sessions,
        target_date,
        username,
        args.timezone,
        workspace_path,
    )

    if args.output:
        write_json(Path(args.output), report)
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
