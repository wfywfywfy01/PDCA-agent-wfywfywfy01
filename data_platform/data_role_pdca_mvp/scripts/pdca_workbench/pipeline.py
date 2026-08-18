# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：PDCA 日流水线调度
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def run_pdca(date_text, push=False, start_date=None):
    if os.name == "nt" and RUN_SCRIPT.is_file():
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(RUN_SCRIPT),
            "-Date",
            date_text,
        ]
        if start_date:
            command.extend(["-StartDate", start_date])
        if push:
            command.append("-Push")
    else:
        # Linux/Docker 不依赖 PowerShell，直接调用同一底层 Python 流水线。
        script = WORKSPACE / "scripts" / "data_role_pdca_daily.py"
        command = [
            sys.executable,
            str(script),
            "--date", date_text,
            "--workspace", str(WORKSPACE),
        ]
        if start_date:
            command.extend(["--start-date", start_date])

        sources = read_json(WORKSPACE / "config" / "data_sources.json")
        sales_json = Path(str(sources.get("sales_json") or ""))
        if sales_json.is_file():
            command.extend(["--sales-json", str(sales_json)])
        else:
            suffix = f"{start_date}_to_{date_text}" if start_date and start_date != date_text else date_text
            cached = WORKSPACE.parents[1] / "data_raw" / f"dealer_sales_month_to_date_{suffix}.json"
            if cached.is_file():
                command.extend(["--sales-json", str(cached)])

        sales_xlsx = Path(str(sources.get("sales_xlsx") or ""))
        if "--sales-json" not in command and sources.get("allow_excel_demo") and sales_xlsx.is_file():
            command.extend(["--sales-xlsx", str(sales_xlsx)])
            if sources.get("sales_sheet"):
                command.extend(["--sales-sheet", str(sources["sales_sheet"])])

        logistics_csv = Path(str(sources.get("logistics_csv") or ""))
        if logistics_csv.is_file():
            command.extend(["--logistics-csv", str(logistics_csv)])
        if push:
            command.append("--push")
    try:
        completed = subprocess.run(
            command,
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, stdout, stderr or "PDCA 生成超过 180 秒，已自动终止。请稍后重试或使用已缓存看板。"
    return completed.returncode, completed.stdout, completed.stderr
