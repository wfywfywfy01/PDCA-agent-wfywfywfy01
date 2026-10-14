"""Replace only the PDCA site block in the host Caddyfile, then validate and reload.

Run from a temporary Docker container with /etc/caddy mounted read-write,
the host Caddy binary mounted read-only, and host networking.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


SITE = "pdca-workbench-teams.vertu.cn"


def _site_span(text: str) -> tuple[int, int]:
    matches = list(re.finditer(rf"(?m)^{re.escape(SITE)}\s*\{{\s*$", text))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {SITE} block, found {len(matches)}")
    start = matches[0].start()
    depth = 0
    for offset in range(matches[0].end() - 1, len(text)):
        if text[offset] == "{":
            depth += 1
        elif text[offset] == "}":
            depth -= 1
            if depth == 0:
                return start, offset + 1
    raise ValueError("PDCA Caddy site block is not closed")


def replace_site(current: str, candidate: str) -> str:
    old_start, old_end = _site_span(current)
    new_start, new_end = _site_span(candidate)
    if candidate[:new_start].strip().lstrip("#").strip() not in {"", "Replace only the pdca-workbench-teams.vertu.cn site block in /etc/caddy/Caddyfile."}:
        raise ValueError("candidate contains unexpected content before the PDCA site")
    if candidate[new_end:].strip():
        raise ValueError("candidate contains another site or trailing directives")
    return current[:old_start] + candidate[new_start:new_end] + current[old_end:]


def _caddy(command: str, path: Path) -> None:
    result = subprocess.run(
        ["/usr/bin/caddy", command, "--config", str(path), "--adapter", "caddyfile"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"caddy {command} failed with exit {result.returncode}")


def apply(config: Path, site: Path) -> str:
    original = config.read_text(encoding="utf-8")
    replacement = replace_site(original, site.read_text(encoding="utf-8"))
    if replacement == original:
        return "unchanged"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = config.with_name(f"{config.name}.before-pdca-{stamp}")
    temporary = config.with_name(f"{config.name}.pdca-{stamp}.tmp")
    temporary.write_text(replacement, encoding="utf-8")
    os.chmod(temporary, config.stat().st_mode)
    try:
        _caddy("validate", temporary)
        shutil.copy2(config, backup)
        os.replace(temporary, config)
        try:
            _caddy("reload", config)
        except Exception:
            shutil.copy2(backup, temporary)
            os.replace(temporary, config)
            _caddy("reload", config)
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return backup.name


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--site", type=Path, required=True)
    args = parser.parse_args()
    print(apply(args.config, args.site))
