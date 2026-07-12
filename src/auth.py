from __future__ import annotations

import os
from typing import Iterable

from fastapi import HTTPException, Request, WebSocket, status


def auth_enabled() -> bool:
    return bool(_configured_keys())


def require_http_api_key(request: Request) -> None:
    if not auth_enabled():
        return
    if _extract_http_key(request) not in _configured_keys():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid API key required",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_websocket_api_key(websocket: WebSocket) -> bool:
    if not auth_enabled():
        return True
    token = websocket.query_params.get("api_key") or _bearer_token(websocket.headers.get("authorization", ""))
    if token in _configured_keys():
        return True
    await websocket.close(code=1008, reason="valid API key required")
    return False


def _extract_http_key(request: Request) -> str:
    return (
        request.headers.get("x-api-key")
        or _bearer_token(request.headers.get("authorization", ""))
        or request.query_params.get("api_key")
        or ""
    )


def _bearer_token(value: str) -> str:
    prefix = "bearer "
    if value.lower().startswith(prefix):
        return value[len(prefix) :].strip()
    return ""


def _configured_keys() -> set[str]:
    raw_values: Iterable[str] = (os.getenv("APP_API_KEY", ""), os.getenv("APP_API_KEYS", ""))
    keys: set[str] = set()
    for raw in raw_values:
        keys.update(item.strip() for item in raw.split(",") if item.strip())
    return keys
