"""Vemory 会议拉取与规范化（VPS CLI + 本地 JSON 缓存）。"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

WORKSPACE = Path(__file__).resolve().parents[1]
CACHE_DIR = WORKSPACE / "outputs" / "_vemory_cache"
CUSTOMER_MGMT_PORT = 8787

VEMORY_PEOPLE = [
    {"name": "杨晶晶", "phone": "[PHONE-REDACTED]"},
    {"name": "何海文", "phone": "[PHONE-REDACTED]"},
    {"name": "王宇彤", "phone": "[PHONE-REDACTED]"},
    {"name": "于冰", "phone": "[PHONE-REDACTED]"},
    {"name": "吴黎", "phone": "[PHONE-REDACTED]"},
    {"name": "尤文静", "phone": "[PHONE-REDACTED]1"},
]

DEALER_ROSTER = [
    {"region": "南亚", "country": "印度", "name": "GURU ELECTRONICS SINGAPORE PTE LTD", "owner": "杨晶晶"},
    {"region": "南亚", "country": "印度", "name": "Sidd Senthil", "owner": "何海文"},
    {"region": "中亚", "country": "俄罗斯", "name": "LLC TC Azimut", "owner": "杨晶晶"},
    {"region": "中亚", "country": "土库曼斯坦", "name": "Altyn Zaman H.J.", "owner": "杨晶晶"},
    {"region": "东南亚", "country": "越南", "name": "VMG Communication and Technology Joint Stock Company", "owner": "于冰"},
]

REGION_OWNER_RULES = [
    {"keys": ["中东", "欧洲", "伊拉克", "阿联酋", "英国", "德国"], "owner": "Lina"},
    {"keys": ["东南亚", "柬埔寨", "越南", "泰国", "新加坡"], "owner": "于冰"},
    {"keys": ["南亚", "中亚", "印度", "俄罗斯", "哈萨克斯坦"], "owner": "杨晶晶"},
]


def normalize_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def vemory_people():
    return [{**person, "phone_key": normalize_phone(person["phone"])} for person in VEMORY_PEOPLE]


def normalize_minutes(value) -> int:
    text = str(value or "").strip()
    if not text:
        return 0
    if ":" in text:
        parts = [int(p or 0) for p in text.split(":")]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
        if len(parts) == 3:
            return parts[0] * 60 + parts[1] + round(parts[2] / 60)
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def infer_meeting_type(raw: dict) -> str:
    value = str(raw.get("meeting_type") or raw.get("type") or raw.get("category") or "").lower()
    if any(k in value for k in ("external", "customer", "client", "dealer", "外部", "客户", "经销商")):
        return "external"
    if any(k in value for k in ("internal", "team", "内部", "团队")):
        return "internal"
    participants = raw.get("participants") or raw.get("attendees") or []
    joined = json.dumps(participants, ensure_ascii=False).lower() if not isinstance(participants, str) else participants.lower()
    return "external" if any(k in joined for k in ("@gmail.", "@outlook.", "customer", "dealer", "客户")) else "internal"


def normalize_todos(raw) -> list[dict]:
    if not raw:
        return []
    if isinstance(raw, str):
        return [{"text": line.strip("- •\t "), "owner": "", "due": "", "done": False} for line in raw.splitlines() if line.strip()]
    todos = raw if isinstance(raw, list) else [raw]
    normalized = []
    for item in todos:
        if isinstance(item, str):
            normalized.append({"text": item, "owner": "", "due": "", "done": False})
        elif isinstance(item, dict):
            normalized.append({
                "text": item.get("text") or item.get("content") or item.get("todo") or item.get("title") or "",
                "owner": item.get("owner") or item.get("assignee") or "",
                "due": item.get("due") or item.get("due_date") or "",
                "done": bool(item.get("done") or item.get("is_done") or False),
            })
    return [item for item in normalized if item["text"]]


def normalize_chapters(raw) -> list[dict]:
    if not raw:
        return []
    chapters = raw if isinstance(raw, list) else [raw]
    result = []
    for item in chapters:
        if isinstance(item, str):
            result.append({"title": "章节", "start_time": "", "content": item})
        elif isinstance(item, dict):
            result.append({
                "title": item.get("title") or item.get("name") or "章节",
                "start_time": item.get("start_time") or item.get("start") or "",
                "content": item.get("content") or item.get("summary") or item.get("text") or "",
            })
    return [item for item in result if item.get("title") or item.get("content")]


def normalize_vemory_payload(payload: dict | list, meeting_date: str) -> dict:
    if isinstance(payload, list):
        records = payload
    else:
        records = payload.get("meetings") or payload.get("records") or payload.get("data") or payload.get("items") or []
    meetings = []
    for raw in records:
        if not isinstance(raw, dict):
            continue
        meeting_type = infer_meeting_type(raw)
        seconds = raw.get("duration_seconds")
        minutes = round(seconds / 60) if isinstance(seconds, (int, float)) else normalize_minutes(
            raw.get("duration_minutes") or raw.get("duration") or raw.get("minutes")
        )
        meetings.append({
            "id": str(raw.get("id") or raw.get("uuid") or raw.get("meeting_id") or len(meetings) + 1),
            "title": raw.get("title") or raw.get("name") or raw.get("subject") or "未命名会议",
            "meeting_type": meeting_type,
            "started_at": raw.get("started_at") or raw.get("start") or raw.get("start_time") or "",
            "ended_at": raw.get("ended_at") or raw.get("end") or raw.get("end_time") or "",
            "duration_minutes": minutes,
            "participants": raw.get("participants") or raw.get("attendees") or [],
            "brief": raw.get("brief") or raw.get("summary") or raw.get("report") or raw.get("minutes") or "",
            "chapters": normalize_chapters(raw.get("chapters") or raw.get("sections")),
            "todos": normalize_todos(raw.get("todos") or raw.get("todo") or raw.get("tasks") or raw.get("action_items")),
        })
    return {
        "ok": True,
        "date": meeting_date,
        "source": "vemory",
        "summary": {
            "total": len(meetings),
            "internal": sum(1 for m in meetings if m["meeting_type"] == "internal"),
            "external": sum(1 for m in meetings if m["meeting_type"] == "external"),
            "duration_minutes": sum(m["duration_minutes"] for m in meetings),
            "todo_count": sum(len(m["todos"]) for m in meetings),
        },
        "meetings": meetings,
    }


def classify_meeting_bucket(meeting: dict) -> str:
    """首页会议中心四类：total / interview / report / customer。"""
    title = f"{meeting.get('title') or ''} {meeting.get('brief') or ''}".lower()
    if meeting.get("meeting_type") == "external" or any(k in title for k in ("客户", "经销商", "代理", "customer", "dealer", "拜访")):
        return "customer"
    if any(k in title for k in ("面试", "interview", "招聘", "hr ")):
        return "interview"
    if any(k in title for k in ("汇报", "复盘", "周会", "月会", "日报", "review", "report", "对齐")):
        return "report"
    if meeting.get("meeting_type") == "internal":
        return "report"
    return "report"


def meeting_center_counts(meetings: list[dict]) -> dict:
    buckets = {"total": len(meetings), "interview": 0, "report": 0, "customer": 0}
    for meeting in meetings:
        key = classify_meeting_bucket(meeting)
        buckets[key] = buckets.get(key, 0) + 1
    return buckets


def cache_path(meeting_date: str, person_phone: str = "", end_date: str = "") -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = normalize_phone(person_phone) or "self"
    range_suffix = f"_{end_date}" if end_date and end_date != meeting_date else ""
    return CACHE_DIR / f"{meeting_date}{range_suffix}_{suffix}.json"


def load_cache(meeting_date: str, person_phone: str = "", end_date: str = "") -> dict | None:
    path = cache_path(meeting_date, person_phone, end_date)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["from_cache"] = True
        payload["cache_updated_at"] = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
        return payload
    except (json.JSONDecodeError, OSError):
        return None


def save_cache(meeting_date: str, payload: dict, person_phone: str = "", end_date: str = "") -> None:
    cache_path(meeting_date, person_phone, end_date).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_json_payload(text: str):
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
            return payload
        except json.JSONDecodeError:
            continue
    raise ValueError("VPS 返回内容不是 JSON")


def proxy_customer_vemory(meeting_date: str, person_phone: str = "", person_name: str = "", end_date: str = "") -> dict | None:
    import socket

    # 客户管理服务（8787）目前只按单日聚合，跨天区间一律不走代理，直接落到 call_vemory_cli 走真实区间查询
    if end_date and end_date != meeting_date:
        return None

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", CUSTOMER_MGMT_PORT)) != 0:
            return None
    query = urlencode({"date": meeting_date, "phone": person_phone, "name": person_name})
    try:
        with urlopen(f"http://127.0.0.1:{CUSTOMER_MGMT_PORT}/api/vemory/meetings?{query}", timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if payload.get("meetings") is not None:
            for meeting in payload.get("meetings") or []:
                if "chapters" not in meeting:
                    meeting["chapters"] = []
            save_cache(meeting_date, payload, person_phone)
        return payload
    except (URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def region_fallback_owner(text: str) -> str:
    for rule in REGION_OWNER_RULES:
        if any(key in text for key in rule["keys"]):
            return rule["owner"]
    return ""


def infer_todo_assignment(todo: dict, meeting: dict) -> dict:
    todo_text = " ".join(filter(None, [todo.get("text"), todo.get("owner"), todo.get("due")]))
    meeting_text = " ".join(filter(None, [meeting.get("title"), meeting.get("brief")]))
    combined = f"{todo_text} {meeting_text}".lower()
    for dealer in DEALER_ROSTER:
        name = str(dealer.get("name") or "")
        if name and name.lower() in combined:
            return {"assignee": dealer.get("owner") or "", "customer": name, "reason": f"识别代理：{name}"}
    owner = region_fallback_owner(todo_text) or region_fallback_owner(meeting_text)
    if owner:
        return {"assignee": owner, "customer": "", "reason": f"按区域建议分配给 {owner}"}
    if todo.get("owner"):
        return {"assignee": str(todo["owner"]), "customer": "", "reason": "会议 Todo 自带负责人"}
    return {"assignee": "", "customer": "", "reason": "未识别代理/区域，待人工分配"}


def todo_assignments(meeting: dict) -> list[dict]:
    rows = []
    for index, todo in enumerate(meeting.get("todos") or []):
        assignment = infer_todo_assignment(todo, meeting)
        rows.append({"index": index, "todo": todo, **assignment})
    return rows


def call_vemory_cli(meeting_date: str, person_phone: str = "", person_name: str = "", vertu_cmd: str = "vertu-cli", end_date: str = "", timeout: int = 45) -> dict:
    end = end_date or meeting_date
    vertu = shutil.which(vertu_cmd) or vertu_cmd
    if not shutil.which(vertu_cmd) and not Path(vertu_cmd).exists():
        cached = load_cache(meeting_date, person_phone, end)
        if cached:
            cached["warning"] = "vertu-cli 未安装，当前展示缓存。"
            return cached
        return {
            "ok": False,
            "error": "vertu-cli 未安装，未找到命令。",
            "date": meeting_date,
            "summary": {"total": 0, "internal": 0, "external": 0, "duration_minutes": 0, "todo_count": 0},
            "meetings": [],
        }

    candidates = [[
        vertu,
        "vemory",
        "+meetings",
        "--scope",
        "team",
        "--start-date",
        meeting_date,
        "--end-date",
        end,
    ]]
    errors = []
    for cmd in candidates:
        proc = subprocess.run(cmd, cwd=str(WORKSPACE), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or proc.stdout.strip())
            continue
        try:
            raw = extract_json_payload(proc.stdout)
        except ValueError:
            errors.append("Vemory 返回不是 JSON。")
            continue
        if person_name and isinstance(raw, dict):
            requested = person_name.casefold()
            raw = dict(raw)
            raw["meetings"] = [
                item for item in raw.get("meetings") or []
                if requested in str(item.get("owner_name") or "").casefold()
            ]
        normalized = normalize_vemory_payload(raw, meeting_date)
        normalized["date_end"] = end
        normalized["person"] = {"name": person_name, "phone": person_phone}
        save_cache(meeting_date, normalized, person_phone, end)
        return normalized

    cached = load_cache(meeting_date, person_phone, end)
    if cached:
        cached["warning"] = "VPS 调用失败，当前展示缓存。"
        cached["cli_errors"] = errors[-2:]
        return cached
    return {
        "ok": False,
        "error": "Vemory 调用失败。",
        "cli_errors": errors[-3:],
        "date": meeting_date,
        "person": {"name": person_name, "phone": person_phone},
        "summary": {"total": 0, "internal": 0, "external": 0, "duration_minutes": 0, "todo_count": 0},
        "meetings": [],
    }


def resolve_vemory_user_id(vertu: str, phone: str, person_name: str = "", timeout: int = 45) -> tuple[int | None, str | None]:
    phone_key = normalize_phone(phone)
    if not phone_key:
        return None, "手机号为空"
    domains = [
        f'["|","|",["login","ilike","{phone_key}"],["mobile","ilike","{phone_key}"],["phone","ilike","{phone_key}"]]',
        f'[["login","ilike","{phone_key}"]]',
    ]
    if person_name:
        domains.append(json.dumps([["name", "ilike", person_name]], ensure_ascii=False))
    errors = []
    for domain in domains:
        cmd = [
            vertu,
            "odoo",
            "data",
            "search",
            "--endpoint",
            "im",
            "--model-name",
            "res.users",
            "--domain",
            domain,
            "--fields",
            "id,name,login,phone,mobile",
            "--limit",
            "5",
        ]
        proc = subprocess.run(cmd, cwd=str(WORKSPACE), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if proc.returncode != 0:
            errors.append(proc.stderr.strip() or proc.stdout.strip())
            continue
        try:
            raw = extract_json_payload(proc.stdout)
        except ValueError:
            errors.append("用户搜索返回不是 JSON")
            continue
        records = raw if isinstance(raw, list) else (raw.get("records") or raw.get("data") or raw.get("items") or raw)
        if isinstance(records, dict):
            records = records.get("records") or records.get("data") or []
        if records:
            return int(records[0]["id"]), None
    return None, "未能通过手机号解析 Vemory user_id；" + "；".join(errors[-2:])


def fetch_vemory_meetings(meeting_date: str, person_phone: str = "", person_name: str = "", vertu_cmd: str = "vertu-cli", end_date: str = "") -> dict:
    proxied = proxy_customer_vemory(meeting_date, person_phone, person_name, end_date)
    if proxied:
        return proxied
    return call_vemory_cli(meeting_date, person_phone, person_name, vertu_cmd=vertu_cmd, end_date=end_date)
