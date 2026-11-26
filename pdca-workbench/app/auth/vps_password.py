"""Verify user credentials with VPS and retain only the verified identity and expiry."""

from datetime import datetime, timezone

import httpx
from fastapi import HTTPException

VPS_LOGIN_URL = "https://vps-service.vertu.cn/v1/auth/login"
MAX_VPS_USER_ID = (1 << 53) - 1  # JSON IDs must remain exact in the admin UI.


async def verify_vps_password(login: str, password: str) -> tuple[int, datetime]:
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
            response = await client.post(
                VPS_LOGIN_URL,
                headers={"Accept": "application/json", "X-Vertu-Auth-Channel": "pdca"},
                json={"login": login, "password": password},
            )
        if response.status_code in (401, 404):
            raise HTTPException(status_code=401, detail="VPS 账号或密码错误")
        if response.status_code == 429:
            raise HTTPException(status_code=429, detail="VPS 登录请求过多，请稍后重试")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise ValueError("invalid VPS response")
        identity = payload.get("user")
        id_key = "userId"
        if not isinstance(identity, dict):
            identity = payload.get("userinfo")
            id_key = "user_id"
        if not isinstance(identity, dict):
            raise ValueError("missing VPS identity")
        if identity.get("active") is False:
            raise HTTPException(status_code=401, detail="VPS 账号或密码错误")
        user_id = identity.get(id_key)
        if identity.get("active") is not True or type(user_id) is not int or not 1 <= user_id <= MAX_VPS_USER_ID:
            raise ValueError("invalid VPS identity")
        if not isinstance(payload.get("token"), str) or not payload["token"].strip():
            raise ValueError("missing VPS session")
        expiry = datetime.fromisoformat(payload["expires_at"])
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("invalid VPS expiry")
        return user_id, expiry
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        # Error payloads or transport exceptions may include sensitive data.
        raise HTTPException(status_code=503, detail="VPS 登录服务暂不可用，请稍后重试") from None
