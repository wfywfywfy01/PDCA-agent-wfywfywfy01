"""本机 vertu-cli 封装。不配 Webhook。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def vertu_exe() -> str:
    """找 vertu-cli。服务器用 VERTU_COMMAND，Windows 再找 .cmd。
    @returns {str}
    """
    configured = os.environ.get("VERTU_COMMAND", "").strip()
    if configured:
        found = shutil.which(configured) or (configured if Path(configured).exists() else "")
        if found:
            return found
    exe = shutil.which("vertu-cli") or shutil.which("vertu-cli.cmd")
    npm = Path.home() / "AppData" / "Roaming" / "npm" / "vertu-cli.cmd"
    if not exe and npm.exists():
        exe = str(npm)
    if not exe:
        raise RuntimeError("找不到 vertu-cli")
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
