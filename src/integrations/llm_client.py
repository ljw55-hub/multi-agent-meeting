from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LLMClient:
    """Small OpenAI-compatible/MiniMax-compatible client with a safe offline mode."""

    _openai_key_index = 0

    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "offline").lower()
        self.model = os.getenv("OPENAI_MODEL_NAME") or os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_api_keys = _split_keys(os.getenv("OPENAI_API_KEYS", "")) or (
            [self.openai_api_key] if self.openai_api_key else []
        )
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY", "")
        self.minimax_group_id = os.getenv("MINIMAX_GROUP_ID", "")
        self.timeout_s = float(os.getenv("LLM_TIMEOUT_SECONDS", "180"))
        self.max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))

    @property
    def enabled(self) -> bool:
        if self.provider == "openai":
            return bool(self.openai_api_keys)
        if self.provider == "minimax":
            return bool(self.minimax_api_key)
        return False

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        fallback: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        if not self.enabled:
            return fallback

        for attempt in range(1, self.max_retries + 2):
            try:
                if self.provider == "openai":
                    return await self._openai_json(messages, temperature, max_tokens)
                if self.provider == "minimax":
                    return await self._minimax_json(messages, temperature, max_tokens)
            except Exception as exc:
                if attempt > self.max_retries:
                    logger.warning(
                        "LLM call failed, using fallback: provider=%s model=%s attempts=%s error=%s",
                        self.provider,
                        self.model,
                        attempt,
                        _format_exception(exc),
                    )
                    break
                delay_s = min(2 ** (attempt - 1), 8)
                logger.warning(
                    "LLM call failed, retrying: provider=%s model=%s attempt=%s/%s delay_s=%s error=%s",
                    self.provider,
                    self.model,
                    attempt,
                    self.max_retries + 1,
                    delay_s,
                    _format_exception(exc),
                )
                await asyncio.sleep(delay_s)
        return fallback

    async def _openai_json(
        self, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        import httpx

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._next_openai_api_key()}"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(
                f"{self.openai_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_object(text)

    def _next_openai_api_key(self) -> str:
        if not self.openai_api_keys:
            return ""
        key = self.openai_api_keys[LLMClient._openai_key_index % len(self.openai_api_keys)]
        LLMClient._openai_key_index += 1
        return key

    async def _minimax_json(
        self, messages: list[dict[str, str]], temperature: float, max_tokens: int
    ) -> dict[str, Any]:
        import httpx

        url = "https://api.minimax.chat/v1/text/chatcompletion_v2"
        if self.minimax_group_id:
            url = f"{url}?GroupId={self.minimax_group_id}"
        payload = {
            "model": os.getenv("MINIMAX_MODEL", "abab6.5s-chat"),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.minimax_api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_object(text)


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise


def _format_exception(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        body = getattr(response, "text", "")
        return f"{type(exc).__name__}(status={response.status_code}, body={body[:500]!r})"
    return f"{type(exc).__name__}: {exc!r}"


def _split_keys(value: str) -> list[str]:
    return [key.strip() for key in value.split(",") if key.strip()]
