# -*- coding: utf-8 -*-
"""从 vertu VPS 经销商业绩 JSON 生成 walkin 线上 OKR/渠道参考表。"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from workbench_data import build_online_channel_payload, write_online_channel_reference  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()
    out = write_online_channel_reference(args.date)
    payload = build_online_channel_payload(args.date)
    print(out)
    print("stores", len(payload.get("stores") or []), "month", list((payload.get("okrByMonth") or {}).keys()))


if __name__ == "__main__":
    main()
