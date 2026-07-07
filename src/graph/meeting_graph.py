from __future__ import annotations

import asyncio
import logging
from typing import Any, TypedDict

from ..agents import ActionAgent, FollowUpAgent, InsightAgent, SummaryAgent, TranscriptionAgent
from ..models import create_initial_state

logger = logging.getLogger(__name__)

class GraphState(TypedDict, total=False):
    meeting_id: str
    audio_data: bytes
    title: str
    participants: list[str]
    language: str
    transcript_text: str
    transcript: Any
    summary: Any
    actions: Any
    insights: Any
    followup: Any
    status: str
    errors: list[str]


async def run_meeting_pipeline(
    meeting_id: str,
    audio_data: bytes = b"",
    title: str = "",
    participants: list[str] | None = None,
    language: str = "zh",
) -> dict[str, Any]:
    state = create_initial_state(
        meeting_id=meeting_id,
        audio_data=audio_data,
        title=title,
        participants=participants,
        language=language,
    )

    try:
        return await _run_with_langgraph(state)
    except Exception as exc:
        logger.warning("LangGraph execution failed, falling back to manual pipeline: %s", exc)
        return await _run_manually(state)


async def _run_with_langgraph(state: dict[str, Any]) -> dict[str, Any]:
    from langgraph.graph import END, START, StateGraph

    transcription = TranscriptionAgent()
    summary = SummaryAgent()
    action = ActionAgent()
    insight = InsightAgent()
    followup = FollowUpAgent()

    graph = StateGraph(GraphState)
    graph.add_node("transcription", transcription.process)
    graph.add_node("summary", summary.process)
    graph.add_node("action", action.process)
    graph.add_node("insight", insight.process)
    graph.add_node("followup", followup.process)

    graph.add_edge(START, "transcription")
    graph.add_edge("transcription", "summary")
    graph.add_edge("transcription", "action")
    graph.add_edge("transcription", "insight")
    graph.add_edge("summary", "followup")
    graph.add_edge("action", "followup")
    graph.add_edge("insight", "followup")
    graph.add_edge("followup", END)

    compiled = graph.compile()
    return await compiled.ainvoke(state)


async def _run_manually(state: dict[str, Any]) -> dict[str, Any]:
    state = await TranscriptionAgent().process(state)

    results = await asyncio.gather(
        SummaryAgent().process(dict(state)),
        ActionAgent().process(dict(state)),
        InsightAgent().process(dict(state)),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, Exception):
            state["errors"] = state.get("errors", []) + [str(result)]
            continue
        for key in ("summary", "actions", "insights"):
            if key in result:
                state[key] = result[key]

    return await FollowUpAgent().process(state)
