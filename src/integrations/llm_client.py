from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class LLMClient:
    """Small OpenAI-compatible/MiniMax-compatible client with a safe offline mode."""

    def __init__(self) -> None:
        self.provider = os.getenv("LLM_PROVIDER", "offline").lower()
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.minimax_api_key = os.getenv("MINIMAX_API_KEY", "")
        self.minimax_group_id = os.getenv("MINIMAX_GROUP_ID", "")

    @property
    def enabled(self) -> bool:
        if self.provider == "openai":
            return bool(self.openai_api_key)
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

        try:
            if self.provider == "openai":
                return await self._openai_json(messages, temperature, max_tokens)
            if self.provider == "minimax":
                return await self._minimax_json(messages, temperature, max_tokens)
        except Exception as exc:
            logger.warning("LLM call failed, using fallback: %s", exc)
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
        headers = {"Authorization": f"Bearer {self.openai_api_key}"}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_object(text)

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
        async with httpx.AsyncClient(timeout=60) as client:
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
