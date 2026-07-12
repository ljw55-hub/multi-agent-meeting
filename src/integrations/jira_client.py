from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class JiraClient:
    """Small Jira Cloud REST client used by the follow-up workflow.

    The client is disabled unless Jira credentials are configured. Disabled
    mode is intentional: local development and automated tests should still run
    without touching a real Jira workspace.
    """

    def __init__(
        self,
        server: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        project_key: str | None = None,
    ) -> None:
        self.server = (server or os.getenv("JIRA_SERVER", "")).rstrip("/")
        self.email = email or os.getenv("JIRA_EMAIL", "")
        self.api_token = api_token or os.getenv("JIRA_API_TOKEN", "")
        self.project_key = project_key or os.getenv("JIRA_PROJECT_KEY", "MEET")
        self.enabled = bool(self.server and self.email and self.api_token and self.project_key)

    @property
    def is_enabled(self) -> bool:
        return self.enabled

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def create_issue(
        self,
        summary: str,
        description: str = "",
        assignee: str | None = None,
        due_date: str | None = None,
        priority: str = "Medium",
        issue_type: str = "Task",
        labels: list[str] | None = None,
    ) -> dict[str, str]:
        if not self.enabled:
            return {"key": "DISABLED", "id": "", "url": "", "status": "disabled"}

        fields: dict[str, Any] = {
            "project": {"key": self.project_key},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": description or summary}],
                    }
                ],
            },
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
            "labels": labels or ["meeting-auto"],
        }
        if due_date:
            fields["duedate"] = due_date
        if assignee:
            fields["assignee"] = {"id": assignee}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self.server}/rest/api/3/issue",
                auth=(self.email, self.api_token),
                json={"fields": fields},
            )
            response.raise_for_status()
            data = response.json()

        issue_key = data.get("key", "")
        logger.info("Created Jira issue: %s", issue_key)
        return {
            "key": issue_key,
            "id": str(data.get("id", "")),
            "url": f"{self.server}/browse/{issue_key}" if issue_key else "",
            "status": "created",
        }

    @staticmethod
    def map_priority(priority: str) -> str:
        mapping = {
            "low": "Low",
            "medium": "Medium",
            "high": "High",
            "urgent": "Highest",
        }
        return mapping.get(priority.lower(), "Medium")
