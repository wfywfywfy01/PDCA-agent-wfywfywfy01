# -*- coding: utf-8 -*-
"""宿主机 Docker 磁盘治理（服务器常驻容器内运行，P5+）。

经 /var/run/docker.sock 走 Docker HTTP API（httpx UDS），无需 docker CLI。

每日轻清（只动 PDCA 自己的东西，不碰其他项目）：
- 仅回收 PDCA 仓库中 7 天以上未被任何容器引用的镜像，保留最新两份
- 停止超过 24 小时的 pdca-* 历史回滚容器
- 发布前备份保留策略（各保留最新 7 份 .dump）

每周深清（每 7 次运行触发一次，计数持久化）：
- buildkit 构建缓存全清——纯可再生缓存，却是压满磁盘的头号元凶

安全红线：
- 不清理其他项目的镜像/容器/卷；
- 绝不执行 volumes prune：数据库等业务数据在数据卷里，数据本体不碰。

容器启动方式（由部署/运维脚本创建，挂载 docker.sock 与 backups 目录）：
    docker run -d --name pdca-docker-cleanup --restart unless-stopped \
      -v /var/run/docker.sock:/var/run/docker.sock \
      -v /opt/PDCA-agent/pdca-workbench/backups:/backups:rw \
      <app-image> python /app/scripts/server_cleanup.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

SOCK = "/var/run/docker.sock"
BACKUPS = Path(os.environ.get("PDCA_BACKUPS_DIR", "/backups"))
INTERVAL = int(os.environ.get("PDCA_CLEANUP_INTERVAL_SECONDS", "86400"))
KEEP = 7
HEARTBEAT = Path("/tmp/pdca-cleanup-ok")
IMAGE_PREFIXES = ("ghcr.io/wfywfywfy01/pdca-workbench:", "ghcr.io/frankie-foo/pdca-workbench:")
DEEP_EVERY = int(os.environ.get("PDCA_CLEANUP_DEEP_EVERY", "7"))
STATE_FILE = Path(os.environ.get("PDCA_CLEANUP_STATE_FILE", "/tmp/pdca-cleanup-runs"))


def _client() -> httpx.Client:
    transport = httpx.HTTPTransport(uds=SOCK)
    return httpx.Client(transport=transport, base_url="http://docker", timeout=60.0)


def cleanup_images(client: httpx.Client) -> int:
    images = client.get("/images/json", params={"all": "true"}).raise_for_status().json()
    containers = client.get("/containers/json", params={"all": "true"}).raise_for_status().json()
    used = {container["ImageID"] for container in containers}
    # Unknown/dangling and cross-tagged images are not demonstrably ours.
    own = sorted(
        (item for item in images if item.get("RepoTags")
         and all(tag.startswith(IMAGE_PREFIXES) for tag in item["RepoTags"])),
        key=lambda item: item.get("Created", 0), reverse=True,
    )
    protected = used | {item["Id"] for item in own[:2]}
    cutoff = time.time() - 7 * 86400
    deleted = 0
    for item in own:
        if item["Id"] in protected or item.get("Created", 0) >= cutoff:
            continue
        response = client.delete("/images/" + item["Id"], params={"force": "false", "noprune": "true"})
        if response.status_code == 409:  # A deployment may have started using it since the snapshot.
            continue
        response.raise_for_status()
        deleted += 1
    return deleted


def cleanup_stale_containers(client: httpx.Client) -> int:
    """只清停止超过 24h 的 pdca-* 容器（历史回滚容器）；其他项目不碰。"""
    containers = client.get("/containers/json", params={"all": "true"}).raise_for_status().json()
    cutoff = time.time() - 24 * 3600
    removed = 0
    for container in containers:
        name = (container.get("Names") or [""])[0].lstrip("/")
        if not name.startswith("pdca-") or container.get("State") != "exited":
            continue
        if container.get("Created", 0) >= cutoff:
            continue
        try:
            client.delete("/containers/" + container["Id"], params={"force": "true"})
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def cleanup_build_cache(client: httpx.Client) -> int:
    resp = client.post("/build/prune", params={"keep-storage": "0"})
    return int(resp.json().get("SpaceReclaimed", 0) or 0)


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
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        return int(STATE_FILE.read_text().strip() or "0") if STATE_FILE.exists() else 0
    except OSError:
        return getattr(_run_counter, "_mem", 0)


def _bump_counter() -> None:
    try:
        STATE_FILE.write_text(str(_run_counter() + 1))
    except OSError:
        _run_counter._mem = getattr(_run_counter, "_mem", 0) + 1


def run_once(deep: bool = False) -> None:
    with _client() as client:
        removed_images = cleanup_images(client)
        removed_containers = cleanup_stale_containers(client)
        reclaimed_cache = cleanup_build_cache(client) if deep else 0
    removed_files = _cleanup_backups()
    HEARTBEAT.touch()
    print(
        f"[cleanup] pdca_images_removed={removed_images} containers_removed={removed_containers} "
        f"cache_reclaimed_mb={reclaimed_cache / 1e6:.1f} deep={deep} backups_removed={removed_files}",
        flush=True,
    )


def main() -> None:
    print(f"[cleanup] started interval={INTERVAL}s deep_every={DEEP_EVERY}", flush=True)
    while True:
        try:
            count = _run_counter()
            run_once(deep=count % DEEP_EVERY == 0)
            _bump_counter()
        except Exception as exc:  # Keep retrying, but do not refresh the success heartbeat.
            print(f"[cleanup] FAILED: {exc}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    if "--healthcheck" in sys.argv:
        fresh = HEARTBEAT.exists() and 0 <= time.time() - HEARTBEAT.stat().st_mtime < INTERVAL * 2
        sys.exit(0 if fresh else 1)
    else:
        main()
