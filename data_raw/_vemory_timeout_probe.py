# -*- coding: utf-8 -*-
"""Probe Vemory / vertu latency to diagnose timeouts."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


def run(label: str, cmd: list[str], timeout: int = 60) -> None:
    """Run command and print duration / result."""
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=True,
            timeout=timeout,
        )
        dt = time.time() - t0
        out_len = len(proc.stdout or "")
        err = (proc.stderr or "").replace("\n", " ")[:180]
        head = (proc.stdout or "").replace("\n", " ")[:120]
        print(f"[{label}] rc={proc.returncode} {dt:.1f}s out_len={out_len}")
        if err:
            print(f"  stderr={err}")
        if "RATE_LIMIT" in (proc.stdout or "") or "timeout" in (proc.stdout or "").lower():
            print(f"  head={head}")
        if proc.returncode != 0:
            print(f"  head={head}")
    except subprocess.TimeoutExpired:
        print(f"[{label}] TIMEOUT after {timeout}s")


def main() -> None:
    vertu = (
        shutil.which("vertu-cli.cmd")
        or shutil.which("vertu-cli")
        or str(Path.home() / "AppData" / "Roaming" / "npm" / "vertu-cli.cmd")
    )
    print("vertu=", vertu)
    run("whoami", [vertu, "whoami"], 30)
    run(
        "vemory_3d",
        [
            vertu,
            "vemory",
            "+meetings",
            "--endpoint",
            "im",
            "--scope",
            "mine",
            "--start-date",
            "2026-07-13",
            "--end-date",
            "2026-07-15",
        ],
        45,
    )
    run(
        "vemory_week",
        [
            vertu,
            "vemory",
            "+meetings",
            "--endpoint",
            "im",
            "--scope",
            "mine",
            "--start-date",
            "2026-07-07",
            "--end-date",
            "2026-07-15",
        ],
        60,
    )


if __name__ == "__main__":
    main()
