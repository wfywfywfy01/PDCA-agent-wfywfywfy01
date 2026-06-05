# -*- coding: utf-8 -*-
"""
同步工作台参考数据：优先 vertu VPS，其次桌面两份 Excel 固化，再生成 walkin JSON。
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
SCRIPTS = WORKSPACE / "scripts"
DEFAULT_VN = Path(r"c:\Users\frank\Desktop\越南门店数据.xlsx")
DEFAULT_COLLECT = Path(r"c:\Users\frank\Desktop\Data collecet(5).xlsx")
PULL_PS1 = SCRIPTS / "pull_vps_sales_data.ps1"


def run_py(script: Path, *args: str) -> bool:
    if not script.is_file():
        print("skip missing", script)
        return False
    cmd = [sys.executable, str(script), *args]
    print(">", " ".join(cmd))
    try:
        subprocess.run(cmd, cwd=str(WORKSPACE), check=True)
        return True
    except subprocess.CalledProcessError as exc:
        print("failed", exc)
        return False


def run_pull_vps(date_text: str) -> bool:
    if not PULL_PS1.is_file():
        return False
    print(">", "powershell", PULL_PS1, date_text)
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(PULL_PS1),
                "-Date",
                date_text,
            ],
            cwd=str(WORKSPACE),
            check=True,
        )
        return True
    except (subprocess.CalledProcessError, OSError) as exc:
        print("VPS pull skipped:", exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--skip-vps", action="store_true")
    parser.add_argument("--vn-xlsx", type=Path, default=DEFAULT_VN)
    parser.add_argument("--collect-xlsx", type=Path, default=DEFAULT_COLLECT)
    args = parser.parse_args()
    month = args.date[:7]

    if args.collect_xlsx.is_file():
        run_py(SCRIPTS / "import_vn_data_collect_reference_once.py", "--xlsx", str(args.collect_xlsx))
    else:
        print("no collect xlsx:", args.collect_xlsx)

    if args.vn_xlsx.is_file():
        run_py(SCRIPTS / "_import_vietnam_from_xlsx_once.py", "--xlsx", str(args.vn_xlsx))
    else:
        print("no vietnam xlsx:", args.vn_xlsx)
        vn_default = Path(r"c:\Users\frank\Desktop\越南门店数据.xlsx")
        if vn_default.is_file():
            run_py(SCRIPTS / "_import_vietnam_from_xlsx_once.py", "--xlsx", str(vn_default))

    if not args.skip_vps:
        run_pull_vps(args.date)

    run_py(SCRIPTS / "build_walkin_bundle.py", "--month", month)
    run_py(SCRIPTS / "build_online_channel_from_vps.py", "--date", args.date)
    print("done. refresh http://127.0.0.1:8767/walkin-cockpit/?date=" + args.date)


if __name__ == "__main__":
    main()
