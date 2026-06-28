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
    cmd = [resolve_vertu_command(), *args]
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


async def run_vertu_json(
    args: list[str],
    timeout: float = 45.0,
) -> dict | list | None:
    """执行 vertu 并解析 JSON 输出。"""
    code, stdout, stderr = await run_vertu(args, timeout=timeout)
    if code != 0:
        logger.warning("vertu 非零退出 {}: {}", code, stderr or stdout)
        return None
    text = stdout.strip()
    if not text:
        return None
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
