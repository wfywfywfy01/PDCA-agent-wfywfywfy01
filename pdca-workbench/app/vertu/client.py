# -*- coding: utf-8 -*-
"""vertu-cli 异步子进程封装与运行时健康检查。"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

from app.config import get_settings


def resolve_vertu_command() -> str:
    """解析 vertu-cli 可执行路径。"""
    settings = get_settings()
    if settings.vertu_command and Path(settings.vertu_command).exists():
        return settings.vertu_command
    discovered = shutil.which(settings.vertu_command)
    if discovered:
        return discovered
    npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu-cli.cmd"
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
    logger.debug("vertu-cli exec: {}", " ".join(cmd))
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
        logger.warning("vertu-cli 超时: {}", " ".join(cmd))
        return -1, "", f"timeout after {timeout}s"
    except OSError as exc:
        logger.error("vertu-cli 执行失败: {}", exc)
        return -1, "", str(exc)


def run_vertu_sync_json(args: list[str], timeout: float = 60.0) -> dict | list | None:
    """同步调用 vertu-cli，供调度线程和遗留同步函数复用。"""
    command = resolve_vertu_command()
    cmd = [command, *args]
    if sys.platform == "win32" and command.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", command, *args]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("vertu-cli 同步调用失败: {}", exc)
        return None
    if completed.returncode != 0 or not completed.stdout.strip():
        logger.warning(
            "vertu-cli 同步调用无有效输出 code={} stderr={}",
            completed.returncode,
            (completed.stderr or "")[:200],
        )
        return None
    try:
        return json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        logger.warning("vertu-cli 同步输出不是 JSON: {}", completed.stdout[:200])
        return None


async def run_vertu_sandbox(
    code: str,
    params: dict | None = None,
    timeout: float = 45.0,
) -> dict | list | None:
    """旧 sandbox 兼容入口；vertu-cli 2.x 不再提供任意 Odoo sandbox。"""
    del code, params, timeout
    raise RuntimeError("vertu-cli 2.x 不支持 odoo data sandbox，请改用业务快捷命令")


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
        logger.warning("vertu-cli 输出非 JSON: {}", text[:200])
        return None
    if code != 0:
        logger.warning("vertu-cli 非零退出 {} (无 stdout): {}", code, stderr)
    return None


_HEALTH_CACHE: dict = {"ts": 0.0, "value": None}


async def vertu_health(force: bool = False) -> dict:
    """返回脱敏的 vertu-cli 安装与认证状态，结果缓存 60 秒。"""
    now = time.monotonic()
    cached = _HEALTH_CACHE.get("value")
    if not force and cached and now - float(_HEALTH_CACHE.get("ts") or 0) < 60:
        return dict(cached)

    command = resolve_vertu_command()
    resolved = Path(command).is_file() or bool(shutil.which(command))
    if not resolved:
        value = {"ok": False, "installed": False, "auth_mode": None, "detail": "vertu-cli 未安装"}
    else:
        code, stdout, stderr = await run_vertu(["auth", "status", "--json"], timeout=12.0)
        try:
            payload = json.loads(stdout.strip()) if stdout.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        logged_in = bool(payload.get("logged_in") and payload.get("server_authorized"))
        value = {
            "ok": code == 0 and logged_in,
            "installed": True,
            "auth_mode": payload.get("auth_mode"),
            "never_expires": bool(payload.get("never_expires")),
            "detail": None if code == 0 and logged_in else "vertu-cli 凭据不可用",
        }
        if code != 0:
            logger.warning("vertu-cli auth status 失败: {}", (stderr or "")[:200])
    _HEALTH_CACHE.update({"ts": now, "value": value})
    return dict(value)
