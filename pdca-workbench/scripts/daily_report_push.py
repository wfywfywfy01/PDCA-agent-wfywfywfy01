# -*- coding: utf-8 -*-
"""
每日经营日报推送（P5+）：DB 事实源 → IM 群机器人。

数据全部实时来自生产库：
  - 昨日/本月 Sell-in（与榜单同口径：正向业绩）
  - 今日五件套上报进度 + 缺报门店
  - 近期物流在途与异常
  - 今日会议、今日待办
  - 数据新鲜度（最后同步时刻）

用法：
    python scripts/daily_report_push.py [--date YYYY-MM-DD]
webhook 优先级：PDCA_REPORT_WEBHOOK_URL > PDCA_ALERT_WEBHOOK_URL；
均未配置时仅写 outputs 日志与 outbox（不假装发送）。
平台格式：--platform generic（默认，{"text": ...}，企微自定义/通用兼容）
         / dingtalk（钉钉 {"msgtype":"text",...}）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse as up
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
APP_ROOT = SCRIPT_DIR.parent
load_dotenv(APP_ROOT / ".env")

DB_URL = os.environ.get("PDCA_DATABASE_URL", "").replace(
    "postgresql+psycopg2://", "postgresql://"
)


def connect():
    p = up.urlparse(DB_URL)
    return psycopg2.connect(
        host=p.hostname, port=p.port, user=p.username,
        password=p.password, dbname=p.path[1:], connect_timeout=8,
    )


def q_one(conn, sql, params):
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def fmt_money(wan: float | None) -> str:
    if wan is None:
        return "—"
    return f"{wan:,.2f} 万"


def build_report(day: str) -> str:
    conn = connect()
    try:
        month = day[:7]
        yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()

        # 昨日与本月 Sell-in（榜单口径：正向业绩）
        yesterday_wan = q_one(
            conn,
            "SELECT COALESCE(SUM(sell_in_wan),0) FROM dealer_sales "
            "WHERE check_date=%s AND sell_in_wan>0",
            (yesterday,),
        )
        mtd_wan = q_one(
            conn,
            "SELECT COALESCE(SUM(sell_in_wan),0) FROM dealer_sales "
            "WHERE check_date LIKE %s AND sell_in_wan>0",
            (month + "%",),
        )

        # 五件套上报进度 + 缺报名单
        total_stores = q_one(
            conn, "SELECT COUNT(*) FROM dealer_stores WHERE is_active", ()
        ) or 0
        reported = q_one(
            conn,
            "SELECT COUNT(DISTINCT dealer_id) FROM walkin_daily_reports WHERE report_date=%s",
            (day,),
        ) or 0
        missing_rows = []
        if total_stores > reported:
            cur = conn.cursor()
            cur.execute(
                "SELECT s.name FROM dealer_stores s WHERE s.is_active "
                "AND s.store_id NOT IN (SELECT dealer_id FROM walkin_daily_reports WHERE report_date=%s) "
                "ORDER BY s.region, s.sort_order LIMIT 5",
                (day,),
            )
            missing_rows = [r[0] for r in cur.fetchall()]

        # 物流：近 7 天在途/待核查
        transit = q_one(
            conn,
            "SELECT COUNT(*) FROM logistics_shipments WHERE record_date >= %s "
            "AND COALESCE(current_status,'') NOT ILIKE '%%delivered%%' "
            "AND COALESCE(current_status,'') NOT ILIKE '%%已签收%%'",
            ((date.fromisoformat(day) - timedelta(days=7)).isoformat(),),
        ) or 0
        abnormal = q_one(
            conn,
            "SELECT COUNT(*) FROM logistics_shipments WHERE record_date >= %s "
            "AND (COALESCE(current_status,'') ILIKE '%%异常%%' "
            "OR COALESCE(current_status,'') ILIKE '%%清关失败%%')",
            ((date.fromisoformat(day) - timedelta(days=7)).isoformat(),),
        ) or 0

        # 会议与待办
        meetings = q_one(
            conn, "SELECT COUNT(*) FROM meeting_records WHERE meeting_date=%s", (day,)
        ) or 0
        pending_tasks = q_one(
            conn,
            "SELECT COUNT(*) FROM pdca_tasks WHERE task_date=%s "
            "AND LOWER(COALESCE(status,'')) NOT IN ('done','completed','complete','已完成')",
            (day,),
        ) or 0

        # 数据新鲜度
        synced = q_one(
            conn, "SELECT MAX(synced_at) FROM dealer_sales", ()
        )
    finally:
        conn.close()

    lines = [
        f"📊 PDCA 经营日报 {day}",
        "",
        "【业绩】",
        f"· 昨日 Sell-in：{fmt_money(yesterday_wan)}",
        f"· 本月 Sell-in：{fmt_money(mtd_wan)}",
        "",
        f"【门店五件套】{reported}/{total_stores} 家已上报",
    ]
    if missing_rows:
        lines.append(f"· 缺报：{'、'.join(missing_rows[:5])}"
                     + ("…" if len(missing_rows) > 5 else ""))
        lines.append("· 零客流也要如实上报，不能把 0 当成未上报")
    else:
        lines.append("· 全部上报完成 ✓")
    lines += [
        "",
        f"【物流】近 7 天在途 {transit} 单 · 异常 {abnormal} 单",
        f"【会议】今日 {meetings} 场 · 【待办】{pending_tasks} 项未完成",
        "",
        f"数据截至：{str(synced)[:16] if synced else '尚未同步'}（同步失败请查 /metrics）",
        "入口：https://pdca-workbench-teams.vertu.cn/app/",
    ]
    return "\n".join(lines)


def post_message(webhook: str, message: str, platform: str) -> bool:
    if platform == "dingtalk":
        payload = {"msgtype": "text", "text": {"content": message}}
    elif platform == "wecom":
        payload = {"msgtype": "text", "text": {"content": message}}
    else:
        payload = {"text": message}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            ok = resp.status == 200 and '"errcode":0' in body.replace(" ", "")
            if not ok and '"errcode"' in body:
                print(f"webhook 返回错误: {body[:200]}", file=sys.stderr)
            return resp.status == 200
    except Exception as exc:  # noqa: BLE001 — 推送失败仅记录，不影响主流程
        print(f"webhook 推送失败: {exc}", file=sys.stderr)
        return False


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="每日经营日报推送")
    parser.add_argument("--date", default="", help="YYYY-MM-DD，默认今天")
    parser.add_argument("--platform", default="generic",
                        choices=["generic", "dingtalk", "wecom"])
    args = parser.parse_args()
    day = args.date or date.today().isoformat()
    message = build_report(day)

    webhook = (
        os.environ.get("PDCA_REPORT_WEBHOOK_URL", "").strip()
        or os.environ.get("PDCA_ALERT_WEBHOOK_URL", "").strip()
    )
    outbox = APP_ROOT / "data" / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    out_path = outbox / f"{day}_daily_report_push.txt"
    out_path.write_text(message, encoding="utf-8")

    # 优先 VPS IM 机器人（与告警同通道），其次通用 webhook
    sent = False
    try:
        sys.path.insert(0, str(APP_ROOT))
        from app.vps_im_push import push_vps_message

        sent = push_vps_message(message)
        if sent:
            print(f"[VPS 推送成功] 日报已写入 {out_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"[VPS 推送失败] {exc}")
    if not sent and webhook:
        sent = post_message(webhook, message, args.platform)
        print(f"[{'webhook 推送成功' if sent else 'webhook 推送失败'}] 日报已写入 {out_path}")
    if not sent:
        print(f"[未发送] 日报已写入 {out_path}")
        print(message)
    return 0 if sent else 1


if __name__ == "__main__":
    sys.exit(main())
