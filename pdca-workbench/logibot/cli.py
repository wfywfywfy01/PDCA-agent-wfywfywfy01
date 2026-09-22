"""本机 vertu-cli 封装。不配 Webhook。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def vertu_exe() -> str:
    """找 vps-work。VERTU_COMMAND 仍写 vertu-cli 时忽略。
    @returns {str}
    """
    from app.config import resolve_cli_command

    exe = resolve_cli_command()
    if not exe or not (shutil.which(exe) or Path(exe).exists()):
        raise RuntimeError("找不到 vps-work")
    return str(exe)


def vertu_cli(*args: str) -> dict:
    """跑 vertu-cli，解析 JSON。
    @returns {dict}
    """
    cmd = [vertu_exe(), *args]
    if "--no-json" not in cmd:
        cmd.append("--no-json")
    raw = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, dict):
        return {"data": data}
    return data
