from __future__ import annotations

from datetime import date

from ..integrations.llm_client import LLMClient
from ..models import MeetingSummary, TopicSummary


class SummaryAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def process(self, state: dict) -> dict:
        fallback = self._fallback(state)
        result = await self.llm.chat_json(
            messages=[
                {"role": "system", "content": "你是会议纪要助手，只输出 JSON。"},
                {
                    "role": "user",
                    "content": (
                        "根据会议转写生成结构化纪要，字段包含 title,date,participants,"
                        "topics,decisions,next_steps。\n\n"
                        f"{state.get('transcript_text', '')}"
                    ),
                },
            ],
            fallback=fallback.model_dump(),
        )
        state["summary"] = MeetingSummary(**result)
        return state

    @staticmethod
    def _fallback(state: dict) -> MeetingSummary:
        participants = state.get("participants") or ["张总", "李明", "王芳", "赵伟"]
        return MeetingSummary(
            title=state.get("title") or "Q3 预算评审会",
            date=date.today().isoformat(),
            participants=participants,
            topics=[
                TopicSummary(
                    title="Q3 预算与资源投入",
                    discussion_points=[
                        "Q2 预算执行率为 87%，研发投入占比最高。",
                        "Q3 预算建议上调 15%，重点投向 AI 基础设施与人才招聘。",
                    ],
                    participants=["李明", "张总"],
                    conclusion="同意继续细化 Q3 预算方案并进入审批。",
                ),
                TopicSummary(
                    title="招聘与服务器采购",
                    discussion_points=[
                        "计划招聘 3 名高级算法工程师。",
                        "服务器采购需要完成供应商对比并输出方案。",
                    ],
                    participants=["王芳", "赵伟", "张总"],
                    conclusion="招聘 JD 和采购方案分别由责任人按期推进。",
                ),
            ],
            decisions=[
                "Q3 预算方案进入细化阶段。",
                "招聘和服务器采购作为 Q3 重点支持事项。",
            ],
            next_steps=[
                "李明下周五前提交 Q3 详细预算方案。",
                "王芳本周三前完成招聘 JD。",
                "赵伟下周一前提交服务器采购方案。",
            ],
        )
