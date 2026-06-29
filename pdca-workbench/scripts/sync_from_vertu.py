# -*- coding: utf-8 -*-
"""
每日从 vertu CLI 拉取经销商业绩 + 会议数据，写入云端 PostgreSQL。

用法：
    python scripts/sync_from_vertu.py
    python scripts/sync_from_vertu.py --date 2026-06-28
    python scripts/sync_from_vertu.py --start-date 2026-06-01 --date 2026-06-28
    python scripts/sync_from_vertu.py --only sellin
    python scripts/sync_from_vertu.py --only meetings

计划任务（Windows Task Scheduler）：
    程序：C:\\Python312\\python.exe
    参数：D:\\经销商PDCA\\pdca-workbench\\scripts\\sync_from_vertu.py
    起始目录：D:\\经销商PDCA\\pdca-workbench
    触发器：每天 06:30

Linux cron：
    30 6 * * * cd /opt/pdca-workbench && python scripts/sync_from_vertu.py >> /var/log/pdca_sync.log 2>&1
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, date
from pathlib import Path

# ── 路径设置 ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
WORKBENCH_ROOT = SCRIPT_DIR.parent           # pdca-workbench/
REPO_ROOT = WORKBENCH_ROOT.parent            # 经销商PDCA/
QUERY_FILE = REPO_ROOT / "data_platform" / "data_role_pdca_mvp" / "system_queries" / "pull_dealer_sales_odoo_sale.py"

# 加入 pdca-workbench 到 sys.path，以便 import app.*
if str(WORKBENCH_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKBENCH_ROOT))

# ── 加载 .env ──────────────────────────────────────────────────────────────────
_env_file = WORKBENCH_ROOT / ".env"
if _env_file.is_file():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file, override=False)
    except ImportError:
        for line in _env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

# ── DB 导入（需要 .env 已加载）────────────────────────────────────────────────
from app.database import bootstrap_database, get_engine     # noqa: E402
from app.models.dealer_sales import DealerSales             # noqa: E402
from app.models.meeting import MeetingRecord                # noqa: E402
from sqlmodel import Session, select                        # noqa: E402


# ── vertu CLI 工具 ─────────────────────────────────────────────────────────────

def _find_vertu() -> str:
    cmd = os.environ.get("VERTU_COMMAND", "")
    if cmd:
        if Path(cmd).exists():
            return cmd
        found = shutil.which(cmd)
        if found:
            return found
    found = shutil.which("vertu")
    if found:
        return found
    npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu.cmd"
    if npm_cmd.exists():
        return str(npm_cmd)
    return "vertu"


def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except OSError as exc:
        return -1, "", str(exc)


def _extract_json(text: str):
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch not in "[{":
            continue
        try:
            obj, _ = decoder.raw_decode(text[i:])
            return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"非 JSON 输出: {text[:200]}")


# ── 经销商 Sell-In 同步 ────────────────────────────────────────────────────────

def sync_sellin(vertu: str, run_date: str, start_date: str) -> dict:
    """拉经销商 Sell-In 并写入 dealer_sales 表。"""
    print(f"[sellin] 拉取 {start_date} ~ {run_date} 数据…")

    if not QUERY_FILE.is_file():
        return {"ok": False, "error": f"查询文件不存在: {QUERY_FILE}", "count": 0}

    params_dict = {"run_date": run_date, "start_date": start_date}
    params_json = json.dumps(params_dict, ensure_ascii=False)

    # vertu 在 Windows 上需要 --params-file（内联 JSON 在 cmd.exe 下引号被吃掉）
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                     delete=False, encoding="utf-8") as pf:
        pf.write(params_json)
        params_path = pf.name

    cmd = [vertu, "odoo", "data", "sandbox",
           "--code-file", str(QUERY_FILE),
           "--params-file", params_path]
    print(f"  > vertu odoo data sandbox --code-file <query> --params-file <{params_json}>")
    try:
        rc, stdout, stderr = _run(cmd, timeout=180)
    finally:
        Path(params_path).unlink(missing_ok=True)
    if rc != 0:
        msg = (stderr or stdout).strip()[:400]
        print(f"  [错误] vertu 退出码 {rc}: {msg}")
        return {"ok": False, "error": msg, "count": 0}

    try:
        payload = _extract_json(stdout)
    except ValueError as exc:
        print(f"  [错误] {exc}")
        return {"ok": False, "error": str(exc), "count": 0}

    result = payload.get("execution", {}).get("result") or payload
    if isinstance(result, dict) and result.get("error"):
        err = result["error"]
        if isinstance(err, dict):
            err = err.get("message") or json.dumps(err, ensure_ascii=False)
        print(f"  [错误] Odoo sandbox: {err}")
        return {"ok": False, "error": str(err), "count": 0}

    rows: list[dict] = []
    if isinstance(result, dict):
        rows = (result.get("customer_summary") or
                result.get("salesperson_summary") or
                result.get("rows") or [])
    elif isinstance(result, list):
        rows = result

    if not rows:
        print("  [warn] 本次返回 0 条经销商业绩")
        return {"ok": True, "count": 0}

    count = 0
    with Session(get_engine()) as session:
        for item in rows:
            name = (item.get("partner_name") or item.get("salesperson") or
                    item.get("dealer") or item.get("name") or "").strip()
            if not name:
                continue
            sell_in_yuan = float(item.get("performance") or 0)
            sell_in_wan = round(sell_in_yuan / 10000, 4)
            units = int(item.get("quantity") or 0)

            existing = session.exec(
                select(DealerSales).where(
                    DealerSales.check_date == run_date,
                    DealerSales.dealer_name == name,
                )
            ).first()

            if existing:
                existing.sell_in_wan = sell_in_wan
                existing.units = units
                existing.source_file = "sync_from_vertu"
                existing.synced_at = datetime.utcnow()
                session.add(existing)
            else:
                session.add(DealerSales(
                    check_date=run_date,
                    dealer_name=name,
                    sell_in_wan=sell_in_wan,
                    units=units,
                    source_file="sync_from_vertu",
                ))
            count += 1
        session.commit()

    print(f"  [ok] 写入/更新 {count} 条经销商业绩 (check_date={run_date})")
    return {"ok": True, "count": count}


# ── 会议同步 ──────────────────────────────────────────────────────────────────

_TEAM = [
    {"name": "杨晶晶", "phone": "[PHONE-REDACTED]"},
    {"name": "何海文", "phone": "[PHONE-REDACTED]"},
    {"name": "王宇彤", "phone": "[PHONE-REDACTED]"},
    {"name": "于冰", "phone": "[PHONE-REDACTED]"},
    {"name": "吴黎", "phone": "[PHONE-REDACTED]"},
    {"name": "尤文静", "phone": "[PHONE-REDACTED]1"},
]


def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def _resolve_vemory_user_id(vertu: str, phone: str) -> int | None:
    phone_key = _normalize_phone(phone)
    if not phone_key:
        return None
    domain = f'["|","|",["login","ilike","{phone_key}"],["mobile","ilike","{phone_key}"],["phone","ilike","{phone_key}"]]'
    cmd = [vertu, "odoo", "data", "search",
           "--endpoint", "im",
           "--model-name", "res.users",
           "--domain", domain,
           "--fields", "id,name,login,phone,mobile",
           "--limit", "5"]
    rc, stdout, _ = _run(cmd, timeout=30)
    if rc != 0:
        return None
    try:
        raw = _extract_json(stdout)
        records = raw if isinstance(raw, list) else (raw.get("records") or raw.get("data") or [])
        if isinstance(records, dict):
            records = records.get("records") or records.get("data") or []
        if records:
            return int(records[0]["id"])
    except (ValueError, KeyError, TypeError):
        pass
    return None


def _pull_vemory_meetings(vertu: str, meeting_date: str, person: dict) -> list[dict]:
    name = person["name"]
    phone = person["phone"]
    user_id = _resolve_vemory_user_id(vertu, phone)
    user_args = ["--user-id", str(user_id)] if user_id else []
    if not user_id:
        print(f"    [{name}] 未能解析 Vemory user_id，跳过")
        return []

    cmd = [vertu, "odoo", "vemory", "meetings",
           "--start-date", meeting_date,
           "--end-date", meeting_date,
           "--max-meetings", "50",
           *user_args]
    rc, stdout, stderr = _run(cmd, timeout=60)
    if rc != 0:
        print(f"    [{name}] 会议拉取失败: {(stderr or stdout).strip()[:120]}")
        return []
    try:
        raw = _extract_json(stdout)
    except ValueError:
        return []
    records = raw if isinstance(raw, list) else (
        raw.get("meetings") or raw.get("records") or raw.get("data") or [])
    return [r for r in records if isinstance(r, dict)]


def _infer_bucket(meeting: dict) -> str:
    title = f"{meeting.get('title') or ''} {meeting.get('brief') or ''}".lower()
    if meeting.get("meeting_type") == "external" or any(
            k in title for k in ("客户", "经销商", "customer", "dealer", "拜访")):
        return "customer"
    if any(k in title for k in ("面试", "interview", "招聘")):
        return "interview"
    return "report"


def sync_meetings(vertu: str, meeting_date: str) -> dict:
    """为团队每人拉 Vemory 会议并写入 meeting_records 表。"""
    print(f"[meetings] 拉取 {meeting_date} 会议…")
    total = 0
    with Session(get_engine()) as session:
        for person in _TEAM:
            print(f"  拉取 {person['name']} 的会议…")
            records = _pull_vemory_meetings(vertu, meeting_date, person)
            for raw in records:
                ext_id = str(raw.get("id") or raw.get("uuid") or raw.get("meeting_id") or "")
                if not ext_id:
                    continue
                title = str(raw.get("title") or raw.get("name") or "未命名会议")
                mtype = "external" if any(k in title.lower() for k in ("dealer", "customer", "经销商")) else "internal"
                seconds = raw.get("duration_seconds")
                minutes = (round(seconds / 60) if isinstance(seconds, (int, float))
                           else int(raw.get("duration_minutes") or 0))
                brief = str(raw.get("brief") or raw.get("summary") or "")
                todos_json = json.dumps(raw.get("todos") or [], ensure_ascii=False)
                participants_json = json.dumps(raw.get("participants") or raw.get("attendees") or [], ensure_ascii=False)
                bucket = _infer_bucket({"title": title, "brief": brief, "meeting_type": mtype})

                existing = session.exec(
                    select(MeetingRecord).where(
                        MeetingRecord.meeting_date == meeting_date,
                        MeetingRecord.external_id == ext_id,
                    )
                ).first()
                if existing:
                    existing.title = title
                    existing.brief = brief
                    existing.todos_json = todos_json
                    existing.synced_at = datetime.utcnow()
                    session.add(existing)
                else:
                    session.add(MeetingRecord(
                        meeting_date=meeting_date,
                        external_id=ext_id,
                        title=title,
                        meeting_type=mtype,
                        bucket=bucket,
                        duration_minutes=minutes,
                        brief=brief,
                        todos_json=todos_json,
                        participants_json=participants_json,
                    ))
                total += 1
        session.commit()
    print(f"  [ok] 写入/更新 {total} 场会议")
    return {"ok": True, "count": total}


# ── 主入口 ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="每日从 vertu CLI 同步到云端 PostgreSQL")
    parser.add_argument("--date", default=date.today().strftime("%Y-%m-%d"),
                        help="同步截止日期 (YYYY-MM-DD)，默认今天")
    parser.add_argument("--start-date", default="",
                        help="同步起始日期 (YYYY-MM-DD)，默认为当月第一天")
    parser.add_argument("--only", choices=["sellin", "meetings", "all"], default="all",
                        help="只同步指定数据类型")
    args = parser.parse_args()

    run_date = args.date
    start_date = args.start_date or (run_date[:8] + "01")

    print(f"{'='*60}")
    print(f"pdca sync_from_vertu  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  run_date={run_date}  start_date={start_date}  only={args.only}")
    print(f"{'='*60}")

    bootstrap_database()
    vertu = _find_vertu()
    print(f"vertu 命令: {vertu}\n")

    results: dict[str, dict] = {}
    errors = 0

    if args.only in ("sellin", "all"):
        r = sync_sellin(vertu, run_date, start_date)
        results["sellin"] = r
        if not r["ok"]:
            errors += 1

    if args.only in ("meetings", "all"):
        r = sync_meetings(vertu, run_date)
        results["meetings"] = r
        if not r["ok"]:
            errors += 1

    print(f"\n{'='*60}")
    print(f"同步完成  错误数={errors}")
    for k, v in results.items():
        status = "ok" if v.get("ok") else "FAIL"
        detail = f"count={v.get('count', '?')}" if v.get("ok") else f"error={v.get('error', '')[:80]}"
        print(f"  {k:12s}: {status}  {detail}")
    print(f"{'='*60}")

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
