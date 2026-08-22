"""从物流追踪群拉预报 xlsx 和面单附件。走 vertu-cli 读群，不配 Webhook。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urljoin

import requests

from cli import vertu_cli
from db import DATA_DIR, ROOT, mark_message, seen_message
from forecast import ingest_forecast
from label import ingest_label

INBOX = DATA_DIR / "inbox" / "group"
BASE_URL = "https://vps-service.vertu.cn"
FORECAST_EXT = {".xlsx", ".xls"}
LABEL_EXT = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp", ".pdf"}


def _history(channel_id: str, limit: int = 50) -> list[dict]:
    """用当前登录账号拉群历史。
    @param {str} channel_id
    @param {int} limit
    @returns {list}
    """
    data = vertu_cli(
        "im",
        "+history",
        "--channel-id",
        channel_id,
        "--limit",
        str(limit),
        "--no-json",
    )
    return data.get("messages") or []


def _abs_url(url: str) -> str:
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return urljoin(BASE_URL + "/", url.lstrip("/"))


def _download(att: dict, dest_dir: Path) -> Path | None:
    """下载一条附件。
    @param {dict} att
    @param {Path} dest_dir
    @returns {Path|None}
    """
    url = att.get("url") or att.get("signed_url") or att.get("file_url")
    name = att.get("name") or att.get("filename") or "file"
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / Path(name).name
    r = requests.get(_abs_url(url), timeout=60)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def _kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in FORECAST_EXT or "预报" in path.name:
        return "forecast"
    if ext in LABEL_EXT:
        return "label"
    return None


def pull_group(channel_id: str | None = None, limit: int = 50) -> dict:
    """拉群附件：xlsx 进预报，图片/PDF 进面单。
    @param {str|None} channel_id
    @param {int} limit
    @returns {dict}
    """
    cid = channel_id or os.environ.get("VPS_IM_CHANNEL_ID")
    if not cid:
        raise RuntimeError("缺少 VPS_IM_CHANNEL_ID")
    out = {"messages": 0, "forecast": [], "labels": [], "skipped": []}
    for msg in _history(cid, limit=limit):
        mid = msg.get("id")
        if not mid or seen_message(mid):
            continue
        atts = msg.get("attachments") or []
        if not atts:
            mark_message(mid)
            continue
        dest = INBOX / str(mid)
        handled = False
        for att in atts:
            path = _download(att, dest)
            if path is None:
                continue
            kind = _kind(path)
            if kind == "forecast":
                n = ingest_forecast(path)
                out["forecast"].append({"file": str(path), "shipments": n})
                handled = True
            elif kind == "label":
                parsed = ingest_label(path)
                out["labels"].append(
                    {
                        "file": str(path),
                        "status": parsed.get("status"),
                        "invoice": parsed.get("invoice"),
                        "tracking": parsed.get("tracking"),
                    }
                )
                handled = True
            else:
                out["skipped"].append(str(path))
        if handled or atts:
            mark_message(mid)
            out["messages"] += 1
    return out
