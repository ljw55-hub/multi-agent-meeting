from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class FeishuClient:
    """Feishu Open API client for webhook messages and task creation."""

    base_url = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        app_id: str | None = None,
        app_secret: str | None = None,
        webhook_url: str | None = None,
    ) -> None:
        self.app_id = app_id or os.getenv("FEISHU_APP_ID", "")
        self.app_secret = app_secret or os.getenv("FEISHU_APP_SECRET", "")
        self.webhook_url = webhook_url or os.getenv("FEISHU_WEBHOOK_URL", "")
        self._tenant_token = ""
        self._token_expires_at = 0.0

    @property
    def is_enabled(self) -> bool:
        return bool(self.webhook_url or (self.app_id and self.app_secret))

    async def _get_tenant_token(self) -> str:
        if self._tenant_token and time.time() < self._token_expires_at:
            return self._tenant_token
        if not (self.app_id and self.app_secret):
            return ""

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            response.raise_for_status()
            data = response.json()

        self._tenant_token = data.get("tenant_access_token", "")
        self._token_expires_at = time.time() + int(data.get("expire", 7200)) - 300
        return self._tenant_token

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def send_webhook_message(self, title: str, content: str) -> bool:
        if not self.webhook_url:
            return False

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [{"tag": "markdown", "content": content}],
            },
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(self.webhook_url, json=payload)
            response.raise_for_status()
            data = response.json()
        ok = data.get("code", -1) == 0
        if ok:
            logger.info("Feishu webhook message sent: %s", title)
        else:
            logger.warning("Feishu webhook returned non-zero response: %s", data)
        return ok

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def create_task(
        self,
        summary: str,
        description: str = "",
        due_timestamp: int | None = None,
        assignee_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        token = await self._get_tenant_token()
        if not token:
            return {"status": "disabled", "task_id": ""}

        task_body: dict[str, Any] = {
            "summary": summary,
            "description": description or "Created from meeting assistant",
        }
        if due_timestamp:
            task_body["due"] = {"timestamp": str(due_timestamp), "is_all_day": True}
        if assignee_ids:
            task_body["members"] = [{"id": assignee_id, "type": "user"} for assignee_id in assignee_ids]

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.base_url}/task/v2/tasks",
                headers={"Authorization": f"Bearer {token}"},
                json=task_body,
            )
            response.raise_for_status()
            data = response.json()

        task_id = data.get("data", {}).get("task", {}).get("id", "")
        return {"status": "created" if task_id else "unknown", "task_id": task_id, "data": data}

    async def send_meeting_summary(
        self,
        title: str,
        summary_md: str,
        actions_md: str,
        insights_md: str,
    ) -> bool:
        content = (
            f"**Meeting**: {title}\n\n"
            f"---\n\n"
            f"**Summary**\n{summary_md}\n\n"
            f"---\n\n"
            f"**Action Items**\n{actions_md}\n\n"
            f"---\n\n"
            f"**Insights**\n{insights_md}"
        )
        return await self.send_webhook_message(f"Meeting Report | {title}", content)
