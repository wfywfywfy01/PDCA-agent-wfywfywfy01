# -*- coding: utf-8 -*-
"""通过 Docker Engine API 调用数据库容器自带的 pg_dump 做原生备份。

为什么这样做：
  远端生产库是 PostgreSQL 18，本机 pg_dump 只有 16/12，应用内置的 pg_dump 备份
  因此长期报 "server version mismatch"。本脚本直接让**数据库容器自己**执行
  pg_dump（版本必然匹配），再把 dump 文件通过 Docker archive API 取回本机，
  不需要在任何机器上安装额外客户端。

用法：
    python scripts/pg_native_backup.py [--workbench-root <dir>] [--docker-host tcp://10.100.0.176:2375]
                                       [--container data-postgres-1] [--keep 14] [--format custom|plain]

产物：<workbench>/data/backups/native_<时间戳>.dump（custom 格式，pg_restore 可直接恢复）
退出码：0 成功；1 失败
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ROOT = Path(r"D:\经销商PDCA\pdca-workbench")
DEFAULT_DOCKER = "http://10.100.0.176:2375"


def api(base: str, path: str, method: str = "GET", body: dict | None = None, timeout: int = 600) -> bytes:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def demux(payload: bytes) -> tuple[bytes, bytes]:
    """解析 Docker 多路复用流：8 字节头 + 负载。返回 (stdout, stderr)。"""
    out, err, i = [], [], 0
    while i + 8 <= len(payload):
        stream = payload[i]
        size = int.from_bytes(payload[i + 4:i + 8], "big")
        chunk = payload[i + 8:i + 8 + size]
        (out if stream == 1 else err).append(chunk)
        i += 8 + size
    return b"".join(out), b"".join(err)


def run_in_container(base: str, container: str, cmd: list[str], user: str = "postgres") -> tuple[int, str, str]:
    exec_id = json.loads(api(base, f"/containers/{container}/exec", "POST", {
        "AttachStdout": True, "AttachStderr": True, "Cmd": cmd, "User": user,
    }))["Id"]
    payload = api(base, f"/exec/{exec_id}/start", "POST", {"Detach": False, "Tty": False})
    out, err = demux(payload)
    code = json.loads(api(base, f"/exec/{exec_id}/json"))["ExitCode"]
    return code, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def parse_db_url(url: str) -> dict:
    m = re.match(r"postgresql(?:\+psycopg2)?://(?P<user>[^:]+):(?P<pass>[^@]+)@(?P<host>[^:/]+):?(?P<port>\d*)/(?P<db>[^?]+)", url)
    if not m:
        raise SystemExit("无法解析 PDCA_DATABASE_URL")
    return {"user": m.group("user"), "password": m.group("pass"), "database": m.group("db")}


def read_database_url(workbench_root: Path) -> str:
    import os
    url = os.environ.get("PDCA_DATABASE_URL", "").strip()
    if url:
        return url
    env_file = workbench_root / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().startswith("PDCA_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("未找到 PDCA_DATABASE_URL")


def find_postgres_container(base: str, hint: str) -> str:
    containers = json.loads(api(base, "/containers/json?all=1"))
    for c in containers:
        name = (c.get("Names") or [""])[0].lstrip("/")
        if name == hint:
            return name
    for c in containers:
        image = (c.get("Image") or "")
        if "postgres" in image and c.get("State") == "running":
            return (c.get("Names") or [""])[0].lstrip("/")
    raise SystemExit("未找到运行中的 PostgreSQL 容器")


def main() -> int:
    parser = argparse.ArgumentParser(description="通过 Docker 调用容器内 pg_dump 的原生备份")
    parser.add_argument("--workbench-root", default=str(DEFAULT_ROOT))
    parser.add_argument("--docker-host", default=DEFAULT_DOCKER)
    parser.add_argument("--container", default="data-postgres-1")
    parser.add_argument("--keep", type=int, default=14)
    parser.add_argument("--format", default="custom", choices=["custom", "plain"])
    args = parser.parse_args()

    workbench_root = Path(args.workbench_root)
    base = args.docker_host.rstrip("/")
    conn = parse_db_url(read_database_url(workbench_root))
    backup_dir = workbench_root / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    try:
        container = find_postgres_container(base, args.container)
    except (SystemExit, urllib.error.URLError) as exc:
        print("[native-backup] 无法连接 Docker 主机: " + str(exc)[:160], file=sys.stderr)
        return 1

    stamp = time.strftime("%Y%m%d_%H%M%S")
    ext = "dump" if args.format == "custom" else "sql"
    remote = f"/tmp/pdca_{stamp}.{ext}"
    local = backup_dir / f"native_{stamp}.{ext}"

    dump_args = ["pg_dump", "-U", conn["user"], "-d", conn["database"], "-f", remote, "--no-owner", "--no-acl"]
    if args.format == "custom":
        dump_args.insert(1, "-Fc")

    try:
        code, out, err = run_in_container(base, container, dump_args)
    except Exception as exc:  # noqa: BLE001
        print("[native-backup] 执行 pg_dump 失败: " + type(exc).__name__ + ": " + str(exc)[:160], file=sys.stderr)
        return 1

    if code != 0:
        print("[native-backup] pg_dump 退出码 " + str(code) + ": " + (err or out).strip()[:300], file=sys.stderr)
        return 1

    try:
        archive = api(base, f"/containers/{container}/archive?path={remote}")
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            member = tar.getmembers()[0]
            extracted = tar.extractfile(member)
            data = extracted.read() if extracted else b""
        if not data:
            print("[native-backup] 取回的备份文件为空", file=sys.stderr)
            return 1
        local.write_bytes(data)
    except Exception as exc:  # noqa: BLE001
        print("[native-backup] 取回备份文件失败: " + type(exc).__name__ + ": " + str(exc)[:160], file=sys.stderr)
        return 1
    finally:
        try:
            run_in_container(base, container, ["rm", "-f", remote], user="root")
        except Exception:  # noqa: BLE001
            pass

    size_kb = round(local.stat().st_size / 1024, 1)
    print("[native-backup] 完成 " + local.name + " 容器=" + container + " 格式=" + args.format + " 大小=" + str(size_kb) + "KB")

    backups = sorted(backup_dir.glob("native_*"))
    for stale in backups[: max(0, len(backups) - args.keep)]:
        stale.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
