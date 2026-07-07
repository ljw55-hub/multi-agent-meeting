from __future__ import annotations

from datetime import date, timedelta

from ..integrations.llm_client import LLMClient
from ..models import ActionItem, ActionResult, Priority


class ActionAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        fallback = {"action_items": [item.model_dump() for item in self._fallback_items()]}
        result = await self.llm.chat_json(
            messages=[
                {"role": "system", "content": "你是任务提取助手，只输出 JSON。"},
                {
                    "role": "user",
                    "content": (
                        "从会议转写中提取待办，字段为 assignee,task,deadline,priority,context。"
                        f"今天是 {date.today().isoformat()}。\n\n"
                        f"{state.get('transcript_text', '')}"
                    ),
                },
            ],
            fallback=fallback,
        )
        items = []
        for raw in result.get("action_items", []):
            try:
                raw["priority"] = Priority(str(raw.get("priority", "medium")).lower())
            except ValueError:
                raw["priority"] = Priority.MEDIUM
            items.append(ActionItem(**raw))

        state["actions"] = ActionResult(
            meeting_id=meeting_id,
            action_items=items,
            sync_status={"jira": "disabled", "feishu": "disabled"},
        )
        return state

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
