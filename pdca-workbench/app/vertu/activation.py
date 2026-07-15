# -*- coding: utf-8 -*-
"""Read-only dealer activation query through the legacy Vertu CLI fallback."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from app.config import get_settings


class ActivationQueryError(RuntimeError):
    """The activation source could not return a valid payload."""


_ACTIVATION_CACHE: dict[str, object] = {
    "ts": 0.0,
    "value": None,
    "retry_after": 0.0,
    "error": None,
}
_ACTIVATION_LOCK = asyncio.Lock()


def resolve_legacy_vertu_command() -> str:
    """Resolve the old ``vertu`` binary without changing the primary CLI."""
    configured = os.environ.get("VERTU_LEGACY_COMMAND", "vertu").strip() or "vertu"
    configured_path = Path(configured)
    if configured_path.exists():
        return str(configured_path.resolve())
    discovered = shutil.which(configured)
    if discovered:
        return discovered
    npm_cmd = Path.home() / "AppData" / "Roaming" / "npm" / "vertu.cmd"
    if npm_cmd.exists():
        return str(npm_cmd)
    return configured


async def run_legacy_vertu_json(
    args: list[str],
    timeout: float = 45.0,
) -> dict | list:
    """Run one legacy CLI read and parse its JSON response."""
    command = resolve_legacy_vertu_command()
    cmd = [command, *args]
    if sys.platform == "win32" and command.lower().endswith((".cmd", ".bat")):
        cmd = ["cmd", "/c", command, *args]
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ActivationQueryError(f"legacy Vertu CLI unavailable: {exc}") from exc

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise ActivationQueryError(f"legacy activation query timed out after {timeout:g}s") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
    stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
    if process.returncode != 0 and not stdout:
        raise ActivationQueryError(
            f"legacy activation query failed (exit {process.returncode}): {stderr[:240]}"
        )
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ActivationQueryError("legacy activation query returned invalid JSON") from exc
    if not isinstance(payload, (dict, list)):
        raise ActivationQueryError("legacy activation query returned an unsupported payload")
    return payload


def _unwrap_sandbox_result(payload: dict | list) -> dict:
    if not isinstance(payload, dict):
        raise ActivationQueryError("legacy activation query did not return an object")
    validation = payload.get("validation")
    if isinstance(validation, dict) and validation.get("ok") is False:
        raise ActivationQueryError("legacy activation query failed static validation")
    execution = payload.get("execution")
    if isinstance(execution, dict):
        if execution.get("error"):
            raise ActivationQueryError(f"legacy activation query failed: {execution['error']}")
        result = execution.get("result")
    else:
        result = payload.get("result", payload)
    if not isinstance(result, dict) or not isinstance(result.get("dealers"), list):
        raise ActivationQueryError("legacy activation query returned an incomplete result")
    return result


async def _query_activation_source() -> dict:
    settings = get_settings()
    script_path = settings.mvp_root / "system_queries" / "dealer_activation_stats.py"
    if not script_path.is_file():
        raise ActivationQueryError(f"activation query script is missing: {script_path}")
    timeout = float(os.environ.get("PDCA_ACTIVATION_QUERY_TIMEOUT_SECONDS", "45"))
    raw = await run_legacy_vertu_json(
        ["odoo", "data", "sandbox", "--code-file", str(script_path)],
        timeout=timeout,
    )
    result = dict(_unwrap_sandbox_result(raw))
    result.update(
        {
            "ok": True,
            "available": True,
            "stale": False,
            "source": "legacy-vertu:mobile.activation.report",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return result


async def fetch_dealer_activation(force: bool = False) -> dict:
    """Return a cached activation payload, falling back to last-known-good data."""
    now = time.monotonic()
    ttl = max(30, int(os.environ.get("PDCA_ACTIVATION_CACHE_TTL_SECONDS", "900")))
    retry_seconds = max(5, int(os.environ.get("PDCA_ACTIVATION_FAILURE_RETRY_SECONDS", "60")))
    cached = _ACTIVATION_CACHE.get("value")
    cached_at = float(_ACTIVATION_CACHE.get("ts") or 0)
    retry_after = float(_ACTIVATION_CACHE.get("retry_after") or 0)
    if not force and now < retry_after:
        if isinstance(cached, dict):
            stale = copy.deepcopy(cached)
            stale.update({"stale": True, "detail": "激活数据刷新失败，当前展示上次成功结果"})
            return stale
        raise ActivationQueryError(str(_ACTIVATION_CACHE.get("error") or "activation source is cooling down"))
    if not force and isinstance(cached, dict) and now - cached_at < ttl:
        return copy.deepcopy(cached)

    async with _ACTIVATION_LOCK:
        now = time.monotonic()
        cached = _ACTIVATION_CACHE.get("value")
        cached_at = float(_ACTIVATION_CACHE.get("ts") or 0)
        retry_after = float(_ACTIVATION_CACHE.get("retry_after") or 0)
        if not force and now < retry_after:
            if isinstance(cached, dict):
                stale = copy.deepcopy(cached)
                stale.update({"stale": True, "detail": "激活数据刷新失败，当前展示上次成功结果"})
                return stale
            raise ActivationQueryError(str(_ACTIVATION_CACHE.get("error") or "activation source is cooling down"))
        if not force and isinstance(cached, dict) and now - cached_at < ttl:
            return copy.deepcopy(cached)
        try:
            value = await _query_activation_source()
        except ActivationQueryError as exc:
            _ACTIVATION_CACHE.update({"retry_after": now + retry_seconds, "error": str(exc)})
            if isinstance(cached, dict):
                stale = copy.deepcopy(cached)
                stale.update({"stale": True, "detail": "激活数据刷新失败，当前展示上次成功结果"})
                logger.warning("Legacy activation refresh failed; serving stale cache: {}", exc)
                return stale
            raise
        _ACTIVATION_CACHE.update({"ts": now, "value": value, "retry_after": 0.0, "error": None})
        return copy.deepcopy(value)
