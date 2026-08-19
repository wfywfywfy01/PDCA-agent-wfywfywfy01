# -*- coding: utf-8 -*-
"""进程内指标（P5）：Prometheus 文本格式，零外部依赖。

- 请求计数（按路径分组，剔除 /metrics 自身防自指）
- HTTP 状态分布与错误计数
- 同步任务结果与最后成功时刻（由 scheduler 钩子写入）
- 备份新鲜度（导出时读 backup_status）
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

_LOCK = threading.Lock()
_START_MONOTONIC = time.monotonic()

_requests_total = 0
_requests_by_path: dict[str, int] = defaultdict(int)
_status_counts: dict[str, int] = defaultdict(int)
_errors_total = 0
_sync_ok = 1.0  # 0 失败 / 1 成功 / -1 从未运行
_sync_last_success = 0.0  # epoch 秒


def record_request(method: str, path: str, status: int) -> None:
    """每个 HTTP 请求结束后调用（中间件钩子）。"""
    global _requests_total, _errors_total
    with _LOCK:
        _requests_total += 1
        _requests_by_path[f"{method} {path}"] += 1
        _status_counts[str(status)] += 1
        if status >= 500:
            _errors_total += 1


def mark_sync(success: bool) -> None:
    """每日同步任务结果（scheduler 钩子）。"""
    global _sync_ok, _sync_last_success
    with _LOCK:
        _sync_ok = 1.0 if success else 0.0
        if success:
            _sync_last_success = time.time()


def export_prometheus(backup_status_fn=None) -> str:
    """渲染 Prometheus 文本。backup_status_fn 由调用方注入避免循环导入。"""
    with _LOCK:
        snapshot = (
            _requests_total,
            dict(_requests_by_path),
            dict(_status_counts),
            _errors_total,
            _sync_ok,
            _sync_last_success,
            time.monotonic() - _START_MONOTONIC,
        )
    total, by_path, statuses, errors, sync_ok, sync_last, uptime = snapshot

    lines = [
        "# HELP pdca_uptime_seconds Process uptime in seconds.",
        "# TYPE pdca_uptime_seconds gauge",
        f"pdca_uptime_seconds {uptime:.1f}",
        "# HELP pdca_requests_total Total HTTP requests processed.",
        "# TYPE pdca_requests_total counter",
        f"pdca_requests_total {total}",
        "# HELP pdca_http_status_total HTTP responses by status code.",
        "# TYPE pdca_http_status_total counter",
    ]
    for status, count in sorted(statuses.items()):
        lines.append(f'pdca_http_status_total{{status="{status}"}} {count}')
    lines += [
        "# HELP pdca_errors_total HTTP 5xx responses.",
        "# TYPE pdca_errors_total counter",
        f"pdca_errors_total {errors}",
        "# HELP pdca_requests_by_path_total Requests grouped by method and path.",
        "# TYPE pdca_requests_by_path_total counter",
    ]
    for path, count in sorted(by_path.items(), key=lambda item: -item[1]):
        if path == "GET /metrics":
            continue
        safe = path.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'pdca_requests_by_path_total{{path="{safe}"}} {count}')
    lines += [
        "# HELP pdca_sync_last_success_ok 1=last daily sync succeeded, 0=failed, -1=never ran.",
        "# TYPE pdca_sync_last_success_ok gauge",
        f"pdca_sync_last_success_ok {sync_ok}",
        "# HELP pdca_sync_last_success_timestamp_seconds Unix time of last successful daily sync.",
        "# TYPE pdca_sync_last_success_timestamp_seconds gauge",
        f"pdca_sync_last_success_timestamp_seconds {sync_last:.0f}",
    ]
    if backup_status_fn is not None:
        try:
            backup = backup_status_fn() or {}
            fresh = 1 if backup.get("ok") else 0
            lines += [
                "# HELP pdca_backup_fresh 1=latest DB backup is fresh (<36h).",
                "# TYPE pdca_backup_fresh gauge",
                f"pdca_backup_fresh {fresh}",
            ]
        except Exception:  # noqa: BLE001 — 指标渲染绝不因备份状态异常而失败
            lines.append("pdca_backup_fresh 0")
    return "\n".join(lines) + "\n"
