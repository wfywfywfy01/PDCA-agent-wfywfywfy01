# -*- coding: utf-8 -*-
"""受控文件下载（替代 os.startfile）。"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.auth.deps import require_role
from app.auth.models import User
from app.config import get_settings
from app.legacy import bridge
from app.validation import require_iso_date

router = APIRouter(prefix="/api/files", tags=["files"])


def _allowed_roots() -> list[Path]:
    settings = get_settings()
    return [
        settings.mvp_root / "outputs",
        settings.mvp_root / "inputs",
        settings.repo_root / "data_raw",
        settings.repo_root / "data_reports",
    ]


def _resolve_safe(path_text: str) -> Path:
    target = Path(path_text).resolve()
    for root in _allowed_roots():
        root_resolved = root.resolve()
        # 用 is_relative_to 而不是字符串前缀匹配——字符串前缀会被同名前缀的兄弟目录绕过
        # （比如 root="outputs"，target="outputs_backup/xxx" 也会被字符串前缀判断为"在范围内"）
        if target.is_relative_to(root_resolved) and target.is_file():
            return target
    raise HTTPException(status_code=403, detail="路径不在允许范围内或文件不存在")


@router.get("/download")
async def download_file(
    path: str = Query(...),
    _user: Annotated[User, Depends(require_role("admin"))] = None,
):
    """下载/打开允许目录内的文件。"""
    target = _resolve_safe(path)
    return FileResponse(target, filename=target.name)


@router.get("/output")
async def download_output(
    date: str = Query(...),
    target: str = Query("dashboard"),
    _user: Annotated[User, Depends(require_role("admin"))] = None,
):
    """下载当日 PDCA 输出文件。"""
    date = require_iso_date(date)
    file_path = bridge.latest_output_file(date, target)
    if not file_path or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件还不存在，请先运行 PDCA")
    return FileResponse(file_path, filename=file_path.name)
