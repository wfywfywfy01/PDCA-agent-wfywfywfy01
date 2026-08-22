# -*- coding: utf-8 -*-
"""Split demo slides and screenshot each with Chrome headless."""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
ROOT = Path(__file__).resolve().parents[1]
DEMOS = ROOT / "design-demos"
OUT = ROOT / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)

FILES = [
    "01-roulette-neo-swiss.html",
    "02-reference-consulting.html",
    "03-designer-luxury-editorial.html",
]


def split_slides(html: str) -> list[str]:
    parts = re.findall(
        r'(<section class="slide"[^>]*>.*?</section>)',
        html,
        flags=re.S,
    )
    return parts


def wrap(slide: str, head: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="UTF-8"/>
{head}
<style>body{{margin:0;background:#111;overflow:hidden}}.slide{{margin:0!important}}</style>
</head><body>{slide}</body></html>"""


def extract_head(html: str) -> str:
    m = re.search(r"<head>(.*?)</head>", html, flags=re.S)
    if not m:
        return ""
    head = m.group(1)
    # drop title only noise
    return head


def shot(html_path: Path, png_path: Path) -> None:
    uri = html_path.resolve().as_uri()
    cmd = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        "--window-size=1920,1080",
        f"--screenshot={png_path}",
        uri,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    print("wrote", png_path, png_path.stat().st_size)


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="w29_shots_"))
    for name in FILES:
        src = DEMOS / name
        html = src.read_text(encoding="utf-8")
        head = extract_head(html)
        slides = split_slides(html)
        stem = src.stem
        for i, slide in enumerate(slides, 1):
            page = tmp / f"{stem}-p{i}.html"
            page.write_text(wrap(slide, head), encoding="utf-8")
            shot(page, OUT / f"{stem}-p{i}.png")


if __name__ == "__main__":
    main()
