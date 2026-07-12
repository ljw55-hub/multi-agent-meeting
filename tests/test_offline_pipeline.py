from __future__ import annotations

import pytest

from src.graph import run_meeting_pipeline
from src.graph.meeting_graph import _run_with_langgraph
from src.models import create_initial_state
from src.agents.transcription_agent import TranscriptionAgent


@pytest.mark.asyncio
async def test_offline_pipeline_generates_structured_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "offline")

    state = await run_meeting_pipeline("test-meeting")

    assert state["status"] == "completed"
    assert state["errors"] == []
    assert state["summary"].title == "Q3 预算评审会"
    assert len(state["actions"].action_items) == 3
    assert state["insights"].keywords
    assert state["followup"].report_url == "/reports/test-meeting.md"
    assert (tmp_path / "reports" / "test-meeting.md").exists()


@pytest.mark.asyncio
async def test_langgraph_pipeline_generates_structured_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "offline")

    state = await _run_with_langgraph(create_initial_state("graph-meeting"))

    assert state["status"] == "completed"
    assert state["errors"] == []
    assert state["summary"].title == "Q3 预算评审会"
    assert len(state["actions"].action_items) == 3
    assert state["followup"].report_url == "/reports/graph-meeting.md"
    assert (tmp_path / "reports" / "graph-meeting.md").exists()


@pytest.mark.asyncio
async def test_transcription_agent_uses_faster_whisper_when_audio_is_uploaded(tmp_path, monkeypatch):
    class FakeSegment:
        start = 0.0
        end = 1.2
        text = "  这是一段真实上传音频的转写结果  "
        avg_logprob = -0.1

    class FakeInfo:
        language = "zh"
        duration = 1.2

    class FakeModel:
        def transcribe(self, path, language=None, vad_filter=True, beam_size=5):
            assert language == "zh"
            assert vad_filter is True
            assert beam_size == 5
            return iter([FakeSegment()]), FakeInfo()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ASR_PROVIDER", "faster_whisper")
    monkeypatch.setattr(TranscriptionAgent, "_get_model", classmethod(lambda cls: FakeModel()))

    state = create_initial_state(
        meeting_id="audio-meeting",
        audio_data=b"fake wav bytes",
        audio_file_name="sample.wav",
        language="zh",
    )
    result = await TranscriptionAgent().process(state)

    transcript = result["transcript"]
    assert transcript.meeting_id == "audio-meeting"
    assert transcript.language == "zh"
    assert transcript.duration_seconds == 1.2
    assert transcript.segments[0].speaker == "Speaker 1"
    assert transcript.segments[0].text == "这是一段真实上传音频的转写结果"
    assert "真实上传音频" in result["transcript_text"]
