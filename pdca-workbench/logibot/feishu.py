"""飞书多维表同步。无 token 时跳过。"""

from __future__ import annotations

import os

import requests

from pathlib import Path

from db import PUBLIC_COLS, ROOT, connect, list_all

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
BASE = "https://open.feishu.cn/open-apis/bitable/v1/apps"
DRIVE_PERM = "https://open.feishu.cn/open-apis/drive/v1/permissions"
TEXT = 1
ENV_PATH = ROOT / ".env"


def _enabled() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "FEISHU_APP_ID",
            "FEISHU_APP_SECRET",
            "FEISHU_APP_TOKEN",
            "FEISHU_TABLE_ID",
        )
    )


def _tenant_token() -> str:
    r = requests.post(
        TOKEN_URL,
        json={
            "app_id": os.environ["FEISHU_APP_ID"],
            "app_secret": os.environ["FEISHU_APP_SECRET"],
        },
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(data)
    return data["tenant_access_token"]


def _headers() -> dict:
    return {"Authorization": f"Bearer {_tenant_token()}"}


def _write_env(updates: dict) -> None:
    """把 token 写回 .env，不打印 secret。
    @param {dict} updates
    """
    rows = []
    seen = set()
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key = line.split("=", 1)[0].strip()
                if key in updates:
                    rows.append(f"{key}={updates[key]}")
                    seen.add(key)
                    continue
            rows.append(line)
    for key, val in updates.items():
        if key not in seen:
            rows.append(f"{key}={val}")
    ENV_PATH.write_text("\n".join(rows) + "\n", encoding="utf-8")
    for key, val in updates.items():
        os.environ[key] = val


def ensure_base(name: str = "国际物流跟踪表") -> dict:
    """用应用凭证创建多维表+41列，并尽量把你加成管理员。
    @param {str} name
    @returns {dict} app_token/table_id/url
    """
    if not os.environ.get("FEISHU_APP_ID") or not os.environ.get("FEISHU_APP_SECRET"):
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET")
    headers = _headers()
    r = requests.post(BASE, headers=headers, json={"name": name}, timeout=30)
    body = r.json() if r.text else {"http": r.status_code, "text": r.text}
    if body.get("code") != 0:
        raise RuntimeError(body)
    app_token = body["data"]["app"]["app_token"]
    fields = [{"field_name": c, "type": TEXT} for c in PUBLIC_COLS]
    r = requests.post(
        f"{BASE}/{app_token}/tables",
        headers=headers,
        json={"table": {"name": "跟踪表", "default_view_name": "表格", "fields": fields}},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(body)
    table_id = body["data"]["table_id"]
    url = f"https://feishu.cn/base/{app_token}?table={table_id}"
    _write_env({"FEISHU_APP_TOKEN": app_token, "FEISHU_TABLE_ID": table_id})
    share = None
    open_id = os.environ.get("FEISHU_USER_OPEN_ID")
    if open_id:
        r = requests.post(
            f"{DRIVE_PERM}/{app_token}/members",
            headers=headers,
            params={"type": "bitable"},
            json={
                "member_type": "openid",
                "member_id": open_id,
                "perm": "full_access",
            },
            timeout=30,
        )
        try:
            share = r.json()
        except Exception:
            share = {"http": r.status_code, "text": r.text[:300]}
    return {
        "app_token": app_token,
        "table_id": table_id,
        "url": url,
        "share": share,
    }


def _fields(row: dict) -> dict:
    out = {}
    for c in PUBLIC_COLS:
        v = row.get(c)
        if v is None or v == "":
            continue
        out[c] = v
    return out


def sync() -> dict:
    """按顺丰单号 upsert 到飞书。
    @returns {dict} created/updated/skipped
    """
    if not _enabled():
        return {"skipped": True, "reason": "未配置 FEISHU_*"}
    app = os.environ["FEISHU_APP_TOKEN"]
    table = os.environ["FEISHU_TABLE_ID"]
    headers = _headers()
    existing = {}
    page_token = None
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{BASE}/{app}/tables/{table}/records",
            headers=headers,
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise RuntimeError(body)
        for rec in body.get("data", {}).get("items", []):
            fields = rec.get("fields") or {}
            sf = fields.get("顺丰单号")
            if isinstance(sf, dict):
                sf = sf.get("text") or sf.get("value")
            if sf:
                existing[str(sf)] = rec["record_id"]
        if not body.get("data", {}).get("has_more"):
            break
        page_token = body.get("data", {}).get("page_token")
        if not page_token:
            break

    created = 0
    updated = 0
    conn = connect()
    for row in list_all():
        sf = row["顺丰单号"]
        payload = {"fields": _fields(row)}
        rid = row.get("feishu_record_id") or existing.get(sf)
        if rid:
            r = requests.put(
                f"{BASE}/{app}/tables/{table}/records/{rid}",
                headers=headers,
                json=payload,
                timeout=30,
            )
            r.raise_for_status()
            updated += 1
        else:
            r = requests.post(
                f"{BASE}/{app}/tables/{table}/records",
                headers=headers,
                json=payload,
                timeout=30,
            )
            r.raise_for_status()
            body = r.json()
            if body.get("code") != 0:
                raise RuntimeError(body)
            rid = body["data"]["record"]["record_id"]
            created += 1
        conn.execute(
            'UPDATE shipments SET feishu_record_id=? WHERE "顺丰单号"=?',
            (rid, sf),
        )
        conn.commit()
    conn.close()
    return {"skipped": False, "created": created, "updated": updated}
