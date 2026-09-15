# -*- coding: utf-8 -*-
"""宿主机 Docker 磁盘治理（服务器常驻容器内运行，P5+）。

经 /var/run/docker.sock 走 Docker HTTP API（httpx UDS），无需 docker CLI。

每日轻清：
- 悬空镜像（纯垃圾层）
- 未引用镜像（仅 7 天以上，保护刚 load 待部署的新镜像）
- 停止超过 24 小时的容器（历史回滚容器）

每周深清（每 7 次运行触发一次）：
- buildkit 构建缓存全清（可再生，构建时自动重建）

安全红线：
- 绝不执行 volumes prune：数据库等业务数据在数据卷里，数据本体不碰；
- 备份 .dump 保留最新 7 份（PDCA_BACKUPS_KEEP 可调）。

容器启动方式（由部署/运维脚本创建，挂载 docker.sock 与 backups 目录）：
    docker run -d --name pdca-docker-cleanup --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /opt/PDCA-agent/pdca-workbench/backups:/backups:rw \
      <app-image> python /app/scripts/server_cleanup.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

SOCK = "/var/run/docker.sock"
BACKUPS = Path(os.environ.get("PDCA_BACKUPS_DIR", "/backups"))
INTERVAL = int(os.environ.get("PDCA_CLEANUP_INTERVAL_SECONDS", "86400"))
KEEP = int(os.environ.get("PDCA_BACKUPS_KEEP", "7"))
DEEP_EVERY = int(os.environ.get("PDCA_CLEANUP_DEEP_EVERY", "7"))
STATE_FILE = Path(os.environ.get("PDCA_CLEANUP_STATE_FILE", "/tmp/pdca-cleanup-runs"))


def _client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=SOCK)
    return httpx.Client(transport=transport, base_url="http://docker", timeout=60.0)


def _post(client: httpx.Client, path: str, filters: str | None = None) -> int:
    """POST 并返回释放字节数；失败打印原因不中断。"""
    params = {"filters": filters} if filters else {}
    try:
        resp = client.post(path, params=params)
        data = resp.json()
        return int(data.get("SpaceReclaimed", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] {path} failed: {exc}", flush=True)
        return 0


def _cleanup_backups() -> int:
    removed = 0
    for pattern in ("pdca-before-*.dump", "pdca-walkin-before-*.dump"):
        files = sorted(BACKUPS.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[KEEP:]:
            try:
                old.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def _run_counter() -> int:
    """持久化运行次数（容器重启不丢；目录只读时退回内存计数）。"""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        count = int(STATE_FILE.read_text().strip() or "0") if STATE_FILE.exists() else 0
    except OSError:
        return getattr(_run_counter, "_mem", 0)
    return count


def _bump_counter() -> None:
    try:
        count = _run_counter() + 1
        STATE_FILE.write_text(str(count))
    except OSError:
        _run_counter._mem = getattr(_run_counter, "_mem", 0) + 1


def run_once(deep: bool = False) -> None:
    client = _client()
    reclaimed = 0
    # 悬空镜像（任何年龄）：纯垃圾层
    reclaimed += _post(client, "/images/prune", json.dumps({"dangling": ["true"]}))
    # 未引用镜像：仅 7 天以上，避免误删刚 load 待部署的新镜像
    reclaimed += _post(
        client,
        "/images/prune",
        json.dumps({"dangling": ["false"], "until": ["168h"]}),
    )
    # 停止超过 24 小时的容器（历史回滚容器；运行中的不受影响）
    _post(client, "/containers/prune", json.dumps({"until": ["24h"]}))
    if deep:
        # buildkit 构建缓存：可再生，每周深清一次
        reclaimed += _post(client, "/build/prune", json.dumps({"all": ["true"]}))
    removed_files = _cleanup_backups()
    print(
        f"[cleanup] reclaimed={reclaimed / 1e6:.1f}MB deep={deep} backups_removed={removed_files}",
        flush=True,
    )


def main() -> None:
    print(f"[cleanup] started interval={INTERVAL}s deep_every={DEEP_EVERY}", flush=True)
    while True:
        count = _run_counter()
        deep = count % DEEP_EVERY == 0
        run_once(deep=deep)
        _bump_counter()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
