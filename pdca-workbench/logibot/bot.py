"""物流跟踪机器人 CLI。"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from db import PUBLIC_COLS, list_all

ROOT = Path(__file__).resolve().parent


def next_half_day(now: datetime | None = None) -> datetime:
    """下次 09:00 或 15:00。
    @param {datetime|None} now
    @returns {datetime}
    """
    now = now or datetime.now()
    today9 = now.replace(hour=9, minute=0, second=0, microsecond=0)
    today15 = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if now < today9:
        return today9
    if now < today15:
        return today15
    return today9 + timedelta(days=1)


ENV_ALIASES = {
    "VPS_IM_APP_ID": "PDCA_VPS_BOT_APP_ID",
    "VPS_IM_APP_SECRET": "PDCA_VPS_BOT_APP_SECRET",
    "VPS_IM_CHANNEL_ID": "PDCA_VPS_BOT_CHANNEL_ID",
}


def load_env(path: Path | None = None) -> None:
    """读 .env，不覆盖已有环境变量。PDCA 容器可复用 PDCA_VPS_BOT_*。
    @param {Path|None} path
    """
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        alt = os.environ.get("LOGIBOT_ENV", "").strip()
        if alt:
            env_path = Path(alt)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    for dest, src in ENV_ALIASES.items():
        if not os.environ.get(dest) and os.environ.get(src):
            os.environ[dest] = os.environ[src]


def _match_sales_quiet() -> list:
    from sales import match_sales

    try:
        return match_sales()
    except Exception as exc:
        print("match_sales", exc)
        return []


def cmd_ingest_forecast(args: argparse.Namespace) -> None:
    from forecast import ingest_forecast

    n = ingest_forecast(args.path)
    matched = _match_sales_quiet()
    print(json.dumps({"ok": True, "shipments": n, "matched": matched}, ensure_ascii=False))


def cmd_ingest_label(args: argparse.Namespace) -> None:
    from label import ingest_label, ingest_label_dir

    target = Path(args.path)
    if target.is_dir():
        rows = ingest_label_dir(target)
    else:
        rows = [ingest_label(target)]
    matched = _match_sales_quiet()
    print(json.dumps({"labels": rows, "matched": matched}, ensure_ascii=False, indent=2))


def cmd_match_sales(_: argparse.Namespace) -> None:
    from sales import match_sales

    print(json.dumps(match_sales(), ensure_ascii=False, indent=2))


def cmd_init_feishu(_: argparse.Namespace) -> None:
    from feishu import ensure_base

    print(json.dumps(ensure_base(), ensure_ascii=False, indent=2))


def cmd_sync(_: argparse.Namespace) -> None:
    from feishu import sync

    print(json.dumps(sync(), ensure_ascii=False))


def cmd_track(_: argparse.Namespace) -> None:
    from track import track_all

    print(json.dumps(track_all(), ensure_ascii=False, indent=2))


def cmd_list(args: argparse.Namespace) -> None:
    from status import needs_review

    rows = []
    for r in list_all():
        if args.need_review and not needs_review(r):
            continue
        rows.append(
            {
                "序号": r.get("序号"),
                "订单号": r.get("订单号"),
                "顺丰单号": r.get("顺丰单号"),
                "国际单号": r.get("国际单号"),
                "快递公司": r.get("快递公司"),
                "销售人员": r.get("销售人员"),
                "境外收货人": r.get("境外收货人"),
                "目的地": r.get("目的地"),
                "产品名称": r.get("产品名称"),
                "签收状态": r.get("签收状态"),
                "生命周期": r.get("生命周期"),
                "异常": r.get("异常"),
                "匹配级别": r.get("匹配级别"),
                "最新轨迹": (r.get("最新轨迹") or "")[:80],
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_schema(_: argparse.Namespace) -> None:
    print("\n".join(PUBLIC_COLS))


def cmd_channels(_: argparse.Namespace) -> None:
    from feishu import _write_env
    from notify import _summarize, list_channels

    rows = [_summarize(c) if isinstance(c, dict) else {"raw": c} for c in list_channels()]
    if len(rows) == 1 and rows[0].get("channel_id"):
        _write_env({"VPS_IM_CHANNEL_ID": rows[0]["channel_id"]})
        rows[0]["saved"] = True
    print(json.dumps({"total": len(rows), "channels": rows}, ensure_ascii=False, indent=2))


def cmd_notify_test(args: argparse.Namespace) -> None:
    from notify import notify, push

    text = args.text or "物流小帮手连通测试"
    if args.channel_id:
        print(json.dumps(push(text, channel_id=args.channel_id), ensure_ascii=False))
        return
    notify(text)
    print(json.dumps({"ok": True}, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    """拉群 → 匹配录单人 → 同步飞书 → 查官网 → 变化推群并私聊录单人。
    @param {argparse.Namespace} args
    """
    from feishu import sync
    from group import pull_group
    from notify import notify
    from track import track_all

    def once() -> None:
        pulled = pull_group(limit=args.limit)
        bits = []
        n = sum(x.get("shipments") or 0 for x in pulled.get("forecast") or [])
        if n:
            bits.append(f"预报 {n} 票")
        labs = pulled.get("labels") or []
        if labs:
            bits.append(f"面单 {len(labs)} 张")
        if bits:
            notify("已收录：" + "，".join(bits))
        matched = _match_sales_quiet()
        try:
            sync()
        except Exception as exc:
            print("sync", exc)
        tracked = track_all()
        print(
            json.dumps(
                {"ok": True, "pulled": pulled, "matched": matched, "tracked": tracked},
                ensure_ascii=False,
            )
        )

    once()
    while args.loop or args.half_day:
        if args.half_day:
            nxt = next_half_day()
            time.sleep(max(1, (nxt - datetime.now()).total_seconds()))
        else:
            time.sleep(args.loop)
        once()


def cmd_pull_group(args: argparse.Namespace) -> None:
    from group import pull_group

    print(json.dumps(pull_group(limit=args.limit), ensure_ascii=False, indent=2))


def cmd_watch_forecast(args: argparse.Namespace) -> None:
    """扫微信文件目录当前月 *预报*.xlsx。
    @param {argparse.Namespace} args
    """
    from forecast import ingest_forecast

    base = Path(args.dir or os.environ.get("WECHAT_FILE_DIR") or "")
    if not base.exists():
        raise SystemExit(f"目录不存在: {base}")
    files = sorted(base.glob("*预报*.xlsx"))
    if not files:
        month = Path(base / __import__("datetime").datetime.now().strftime("%Y-%m"))
        if month.exists():
            files = sorted(month.glob("*预报*.xlsx"))
    if not files:
        files = sorted(base.glob("**/*预报*.xlsx"))
    total = 0
    for f in files:
        n = ingest_forecast(f)
        total += n
        print(json.dumps({"file": str(f), "shipments": n}, ensure_ascii=False))
    matched = _match_sales_quiet()
    print(json.dumps({"ok": True, "files": len(files), "shipments": total, "matched": matched}, ensure_ascii=False))


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="物流跟踪机器人")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest-forecast", help="读预报 xlsx")
    p.add_argument("path")
    p.set_defaults(func=cmd_ingest_forecast)

    p = sub.add_parser("ingest-label", help="读面单图或目录")
    p.add_argument("path")
    p.set_defaults(func=cmd_ingest_label)

    p = sub.add_parser("init-feishu", help="用应用凭证创建多维表")
    p.set_defaults(func=cmd_init_feishu)

    p = sub.add_parser("sync", help="同步飞书多维表")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("track", help="Playwright 查 UPS/DHL 官网")
    p.set_defaults(func=cmd_track)

    p = sub.add_parser("list", help="打印本地台账摘要")
    p.add_argument("--need-review", action="store_true", help="只看 C 级/待人工/未关异常")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("schema", help="打印飞书 41 列名")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("channels", help="列出物流小帮手已加入的群")
    p.set_defaults(func=cmd_channels)

    p = sub.add_parser("notify-test", help="往目标群发一条测试消息")
    p.add_argument("--text", default="")
    p.add_argument("--channel-id", default="")
    p.set_defaults(func=cmd_notify_test)

    p = sub.add_parser("run", help="拉群+匹配录单人+查轨迹，变化推群并私聊")
    p.add_argument("--loop", type=int, default=0, help="秒，>0 则循环")
    p.add_argument("--half-day", action="store_true", help="每次跑完等到下次 09:00/15:00")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("match-sales", help="按订单号补销售人员并绑 IM")
    p.set_defaults(func=cmd_match_sales)

    p = sub.add_parser("pull-group", help="从物流追踪群拉预报和面单")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_pull_group)

    p = sub.add_parser("watch-forecast", help="扫微信目录预报 xlsx")
    p.add_argument("--dir", default="")
    p.set_defaults(func=cmd_watch_forecast)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
