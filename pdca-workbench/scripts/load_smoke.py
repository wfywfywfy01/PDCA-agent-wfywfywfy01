# -*- coding: utf-8 -*-
"""
轻量压测冒烟（P5）：并发打关键路径，输出延迟分位数。

用法（工作台已运行时）：
    python scripts/load_smoke.py                      # 默认 http://127.0.0.1:8767，20 并发 × 5 轮
    python scripts/load_smoke.py --base http://127.0.0.1:8767 --concurrency 50 --rounds 10

验证目标（P1 验收口径）：看板/健康检查等读路径 P95 < 1s。
零第三方依赖（标准库 + httpx，requirements 已含）。
"""
from __future__ import annotations

import argparse
import concurrent.futures
import statistics
import sys
import time

import httpx

DEFAULT_PATHS = [
    ("GET", "/health"),
    ("GET", "/login"),
    ("GET", "/app"),
    ("GET", "/api/auth/config"),
    ("GET", "/api/dashboard/overview"),
    ("GET", "/api/workbench/today"),
]


def _hit(base: str, method: str, path: str) -> tuple[str, int, float, str]:
    start = time.perf_counter()
    try:
        resp = httpx.request(
            method,
            base + path,
            timeout=15.0,
            follow_redirects=False,
        )
        return path, resp.status_code, time.perf_counter() - start, ""
    except Exception as exc:  # noqa: BLE001 — 压测报告错误，不中断
        return path, 0, time.perf_counter() - start, str(exc)[:80]


def main() -> int:
    parser = argparse.ArgumentParser(description="PDCA 关键路径压测冒烟")
    parser.add_argument("--base", default="http://127.0.0.1:8767")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    jobs = [
        (method, path)
        for _ in range(args.rounds)
        for method, path in DEFAULT_PATHS
    ]
    print(f"压测目标: {args.base}  并发={args.concurrency}  请求总数={len(jobs)}")

    latencies: list[float] = []
    status_counts: dict[str, int] = {}
    errors = 0
    start = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [pool.submit(_hit, args.base, method, path) for method, path in jobs]
        for future in concurrent.futures.as_completed(futures):
            path, status, elapsed, error = future.result()
            latencies.append(elapsed)
            status_counts[str(status)] = status_counts.get(str(status), 0) + 1
            if status == 0 or status >= 500:
                errors += 1
                if error:
                    print(f"  [ERR] {path}: {error}")
    total = time.perf_counter() - start

    if not latencies:
        print("[FAIL] 无任何响应")
        return 1
    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    print(f"完成: {len(latencies)} 请求 / {total:.1f}s  ({len(latencies)/total:.1f} req/s)")
    print(f"延迟: p50={p50*1000:.0f}ms  p95={p95*1000:.0f}ms  p99={p99*1000:.0f}ms  max={latencies[-1]*1000:.0f}ms")
    print(f"状态分布: {status_counts}")
    print(f"错误(0/5xx): {errors}")

    if p95 > 1.0:
        print(f"[WARN] P95={p95:.2f}s 超过 1s 目标（P1 验收口径）")
    if errors:
        return 1
    print("[PASS] 压测冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
