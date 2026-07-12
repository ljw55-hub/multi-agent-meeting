from __future__ import annotations

import asyncio
import inspect
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from ..agents import ActionAgent, FollowUpAgent, InsightAgent, SummaryAgent, TranscriptionAgent
from ..models import create_initial_state

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, str], Awaitable[None] | None]


class GraphState(TypedDict, total=False):
    meeting_id: str
    audio_data: bytes
    audio_file_name: str
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
    audio_file_name: str = "",
    title: str = "",
    participants: list[str] | None = None,
    language: str = "zh",
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    state = create_initial_state(
        meeting_id=meeting_id,
        audio_data=audio_data,
        audio_file_name=audio_file_name,
        title=title,
        participants=participants,
        language=language,
    )

    try:
        return await _run_with_langgraph(state, progress_callback=progress_callback)
    except Exception as exc:
        logger.warning("LangGraph execution failed, falling back to manual pipeline: %s", exc)
        return await _run_manually(state, progress_callback=progress_callback)


async def _run_with_langgraph(
    state: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    from langgraph.graph import END, START, StateGraph

    transcription = TranscriptionAgent()
    summary = SummaryAgent()
    action = ActionAgent()
    insight = InsightAgent()
    followup = FollowUpAgent()

    async def transcription_node(current: GraphState) -> dict[str, Any]:
        await _emit_progress(progress_callback, "transcription", 10, "正在进行语音转写")
        result = await transcription.process(dict(current))
        await _emit_progress(progress_callback, "transcription", 30, "语音转写完成")
        return _pick_updates(result, "status", "transcript", "transcript_text", "errors")

    async def summary_node(current: GraphState) -> dict[str, Any]:
        await _emit_progress(progress_callback, "summary", 45, "正在生成会议摘要")
        result = await summary.process(dict(current))
        return _pick_updates(result, "summary")

    async def action_node(current: GraphState) -> dict[str, Any]:
        await _emit_progress(progress_callback, "action", 60, "正在提取待办事项")
        result = await action.process(dict(current))
        return _pick_updates(result, "actions")

    async def insight_node(current: GraphState) -> dict[str, Any]:
        await _emit_progress(progress_callback, "insight", 75, "正在分析会议洞察")
        result = await insight.process(dict(current))
        return _pick_updates(result, "insights")

    async def followup_node(current: GraphState) -> dict[str, Any]:
        await _emit_progress(progress_callback, "followup", 90, "正在生成后续跟进")
        result = await followup.process(dict(current))
        await _emit_progress(progress_callback, "completed", 100, "会议处理完成")
        return _pick_updates(result, "followup", "status", "errors")

    graph = StateGraph(GraphState)
    graph.add_node("transcription", transcription_node)
    graph.add_node("summary", summary_node)
    graph.add_node("action", action_node)
    graph.add_node("insight", insight_node)
    graph.add_node("followup", followup_node)

    graph.add_edge(START, "transcription")
    if _parallel_agents_enabled():
        graph.add_edge("transcription", "summary")
        graph.add_edge("transcription", "action")
        graph.add_edge("transcription", "insight")
        graph.add_edge("summary", "followup")
        graph.add_edge("action", "followup")
        graph.add_edge("insight", "followup")
    else:
        graph.add_edge("transcription", "summary")
        graph.add_edge("summary", "action")
        graph.add_edge("action", "insight")
        graph.add_edge("insight", "followup")
    graph.add_edge("followup", END)

    compiled = graph.compile()
    return await compiled.ainvoke(state)


def _pick_updates(state: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: state[key] for key in keys if key in state}


async def _run_manually(
    state: dict[str, Any],
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    await _emit_progress(progress_callback, "transcription", 10, "正在进行语音转写")
    state = await TranscriptionAgent().process(state)
    await _emit_progress(progress_callback, "transcription", 30, "语音转写完成")

    if _parallel_agents_enabled():
        results = await asyncio.gather(
            _run_agent("summary", 45, "正在生成会议摘要", SummaryAgent(), dict(state), ("summary",), progress_callback),
            _run_agent("action", 60, "正在提取待办事项", ActionAgent(), dict(state), ("actions",), progress_callback),
            _run_agent("insight", 75, "正在分析会议洞察", InsightAgent(), dict(state), ("insights",), progress_callback),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                state["errors"] = state.get("errors", []) + [str(result)]
                continue
            state.update(result)
    else:
        for stage, progress, message, agent, keys in (
            ("summary", 45, "正在生成会议摘要", SummaryAgent(), ("summary",)),
            ("action", 60, "正在提取待办事项", ActionAgent(), ("actions",)),
            ("insight", 75, "正在分析会议洞察", InsightAgent(), ("insights",)),
        ):
            state.update(await _run_agent(stage, progress, message, agent, dict(state), keys, progress_callback))

    await _emit_progress(progress_callback, "followup", 90, "正在生成后续跟进")
    state.update(
        await _run_agent(
            "followup",
            90,
            "正在生成后续跟进",
            FollowUpAgent(),
            dict(state),
            ("followup", "status", "errors"),
            progress_callback,
        )
    )
    await _emit_progress(progress_callback, "completed", 100, "会议处理完成")
    state["status"] = "completed"
    return state


async def _run_agent(
    stage: str,
    progress: int,
    message: str,
    agent: Any,
    state: dict[str, Any],
    keys: tuple[str, ...],
    progress_callback: ProgressCallback | None,
) -> dict[str, Any]:
    await _emit_progress(progress_callback, stage, progress, message)
    result = await agent.process(state)
    return _pick_updates(result, *keys)


async def _emit_progress(
    callback: ProgressCallback | None,
    stage: str,
    progress: int,
    message: str,
) -> None:
    if callback is None:
        return
    result = callback(stage, progress, message)
    if inspect.isawaitable(result):
        await result


def _parallel_agents_enabled() -> bool:
    return os.getenv("LLM_PARALLEL_AGENTS", "false").lower() in {"1", "true", "yes", "on"}
