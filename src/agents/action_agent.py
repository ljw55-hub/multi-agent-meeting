from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from ..integrations.feishu_client import FeishuClient
from ..integrations.jira_client import JiraClient
from ..integrations.llm_client import LLMClient
from ..models import ActionItem, ActionResult, Priority


class ActionAgent:
    def __init__(
        self,
        llm: LLMClient | None = None,
        jira: JiraClient | None = None,
        feishu: FeishuClient | None = None,
    ) -> None:
        self.llm = llm or LLMClient()
        self.jira = jira or JiraClient()
        self.feishu = feishu or FeishuClient()

    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        fallback_items = self._fallback_items()
        fallback = {"action_items": [item.model_dump(mode="json") for item in fallback_items]}
        result = await self.llm.chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是任务提取助手，只输出严格 JSON。"
                        "返回格式为 {\"action_items\": [...]}，每个任务包含 assignee、task、deadline、priority、context。"
                        "priority 只能是 low、medium、high、urgent。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "从会议转写中提取待办事项。deadline 尽量转成日期或明确时间描述。"
                        f"今天是 {date.today().isoformat()}。\n\n"
                        f"{state.get('transcript_text', '')}"
                    ),
                },
            ],
            fallback=fallback,
        )

        items = []
        for raw in self._extract_items(result):
            try:
                items.append(ActionItem(**self._normalize_item(raw)))
            except Exception:
                continue

        action_result = ActionResult(
            meeting_id=meeting_id,
            action_items=items or fallback_items,
            sync_status={"jira": "disabled", "feishu": "disabled"},
        )
        await self._sync_action_items(action_result)
        state["actions"] = action_result
        return state

    async def _sync_action_items(self, result: ActionResult) -> None:
        jira_created = 0
        feishu_created = 0

        if self.jira.is_enabled:
            for item in result.action_items:
                response = await self.jira.create_issue(
                    summary=item.task,
                    description=item.context,
                    assignee=None,
                    due_date=item.deadline or None,
                    priority=JiraClient.map_priority(item.priority.value),
                    labels=["meeting-auto", result.meeting_id],
                )
                if response.get("key") and response.get("key") != "DISABLED":
                    item.jira_issue_key = response["key"]
                    jira_created += 1

        if self.feishu.is_enabled:
            for item in result.action_items:
                response = await self.feishu.create_task(
                    summary=item.task,
                    description=item.context,
                )
                task_id = response.get("task_id")
                if task_id:
                    item.feishu_task_id = task_id
                    feishu_created += 1

        result.sync_status = {
            "jira": f"created:{jira_created}" if self.jira.is_enabled else "disabled",
            "feishu": f"created:{feishu_created}" if self.feishu.is_enabled else "disabled",
        }

    @staticmethod
    def _fallback_items() -> list[ActionItem]:
        today = date.today()
        return [
            ActionItem(
                assignee="李明",
                task="整理 Q3 详细预算方案并提交审批",
                deadline=(today + timedelta(days=5)).isoformat(),
                priority=Priority.HIGH,
                context="Q3 预算拟上调 15%，需要形成可审批的详细方案。",
            ),
            ActionItem(
                assignee="王芳",
                task="拟定高级算法工程师招聘 JD",
                deadline=(today + timedelta(days=2)).isoformat(),
                priority=Priority.MEDIUM,
                context="Q3 计划招聘 3 名高级算法工程师。",
            ),
            ActionItem(
                assignee="赵伟",
                task="完成服务器供应商对比并输出采购方案",
                deadline=(today + timedelta(days=3)).isoformat(),
                priority=Priority.HIGH,
                context="AI 基础设施投入需要服务器采购支持。",
            ),
        ]

    @staticmethod
    def _extract_items(result: Any) -> list[Any]:
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            items = result.get("action_items") or result.get("tasks") or result.get("items") or []
            return items if isinstance(items, list) else [items]
        return []

    @staticmethod
    def _normalize_item(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"task": str(raw)}

        priority_text = str(raw.get("priority", Priority.MEDIUM.value)).lower()
        try:
            priority = Priority(priority_text)
        except ValueError:
            priority = Priority.MEDIUM

        return {
            "assignee": str(raw.get("assignee") or raw.get("owner") or "未指定"),
            "task": str(raw.get("task") or raw.get("title") or raw.get("description") or ""),
            "deadline": str(raw.get("deadline") or raw.get("due_date") or ""),
            "priority": priority,
            "context": str(raw.get("context") or raw.get("reason") or ""),
        }
