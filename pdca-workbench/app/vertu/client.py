# -*- coding: utf-8 -*-
"""vertu CLI 异步子进程封装。"""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from loguru import logger

from app.config import get_settings


def resolve_vertu_command() -> str:
    """解析 vertu 可执行路径。"""
    settings = get_settings()
    if settings.vertu_command and Path(settings.vertu_command).exists():
        return settings.vertu_command
    discovered = shutil.which(settings.vertu_command)
    if discovered:
        return discovered
    npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu.cmd"
    if npm_cmd.exists():
        return str(npm_cmd)
    return settings.vertu_command


async def run_vertu(
    args: list[str],
    timeout: float = 45.0,
) -> tuple[int, str, str]:
    """
    异步执行 vertu 命令。

    @param args vertu 子命令参数（不含 vertu 本身）
    @param timeout 超时秒数
    @returns (exit_code, stdout, stderr)
    """
    import sys
    bin_path = resolve_vertu_command()
    # Windows .cmd/.bat 文件必须经 cmd /c 执行，否则 asyncio 子进程无法识别
    if sys.platform == "win32" and bin_path.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", bin_path, *args]
    else:
        cmd = [bin_path, *args]
    logger.debug("vertu exec: {}", " ".join(cmd))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        logger.warning("vertu 超时: {}", " ".join(cmd))
        return -1, "", f"timeout after {timeout}s"
    except OSError as exc:
        logger.error("vertu 执行失败: {}", exc)
        return -1, "", str(exc)


async def run_vertu_sandbox(
    code: str,
    params: dict | None = None,
    timeout: float = 45.0,
) -> dict | list | None:
    """执行 vertu odoo data sandbox，用临时文件避免 Windows 命令行引号问题。"""
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", encoding="utf-8", delete=False
    ) as cf:
        cf.write(code)
        code_file = cf.name

    params_file: str | None = None
    if params:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        ) as pf:
            json.dump(params, pf, ensure_ascii=False)
            params_file = pf.name

    try:
        args = ["odoo", "data", "sandbox", "--code-file", code_file]
        if params_file:
            args += ["--params", f"@{params_file}"]
        return await run_vertu_json(args, timeout=timeout)
    finally:
        os.unlink(code_file)
        if params_file:
            os.unlink(params_file)


async def run_vertu_json(
    args: list[str],
    timeout: float = 45.0,
) -> dict | list | None:
    """执行 vertu 并解析 JSON 输出。

    vertu sandbox 命令在有 permission notices 时返回 exit code 255（非错误），
    因此优先尝试解析 stdout JSON，仅在 stdout 为空时才把非零 exit code 视为失败。
    """
    code, stdout, stderr = await run_vertu(args, timeout=timeout)
    text = stdout.strip()
    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
        logger.warning("vertu 输出非 JSON: {}", text[:200])
        return None
    if code != 0:
        logger.warning("vertu 非零退出 {} (无 stdout): {}", code, stderr)
    return None
