# -*- coding: utf-8 -*-
"""宿主机 Docker 磁盘治理（服务器常驻容器内运行，P5+）。

经 /var/run/docker.sock 走 Docker HTTP API（httpx UDS），无需 docker CLI：
- image prune：仅回收 7 天以上未被引用的镜像（保护新加载待部署的镜像）
- builder prune / container prune
- 发布前备份保留策略（各保留最新 7 份 .dump）

容器启动方式（由部署/运维脚本创建，挂载 docker.sock 与 backups 目录）：
    docker run -d --name pdca-docker-cleanup --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /opt/PDCA-agent/pdca-workbench/backups:/backups:rw \
      <app-image> python /app/scripts/server_cleanup.py
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import httpx

SOCK = "/var/run/docker.sock"
BACKUPS = Path(os.environ.get("PDCA_BACKUPS_DIR", "/backups"))
INTERVAL = int(os.environ.get("PDCA_CLEANUP_INTERVAL_SECONDS", "86400"))
KEEP = 7


def _client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=SOCK)
    return httpx.Client(transport=transport, base_url="http://docker", timeout=60.0)


def _prune(client: httpx.Client, path: str, params: dict) -> str:
    try:
        resp = client.post(path, params=params)
        data = resp.json()
        return data.get("SpaceReclaimed", 0)
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


def run_once() -> None:
    client = _client()
    reclaimed = 0
    # 仅回收 7 天以上未引用镜像，避免误删刚 load 待部署的新镜像
    reclaimed += _prune(client, "/images/prune", {"filters": '{"dangling": {"false": true}, "until": ["168h"]}'})
    reclaimed += _prune(client, "/build/prune", {})
    try:
        client.post("/containers/prune", params={"filters": '{"until": ["168h"]}'})
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] containers/prune failed: {exc}", flush=True)
    removed_files = _cleanup_backups()
    print(
        f"[cleanup] reclaimed={reclaimed / 1e6:.1f}MB backups_removed={removed_files}",
        flush=True,
    )


def main() -> None:
    print(f"[cleanup] started interval={INTERVAL}s", flush=True)
    while True:
        run_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
