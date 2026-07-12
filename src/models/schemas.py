from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MeetingStatus(str, Enum):
    PENDING = "pending"
    TRANSCRIBING = "transcribing"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speaker: str
    text: str
    start: float = 0.0
    end: float = 0.0
    confidence: float = 0.95


class TranscriptResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meeting_id: str
    segments: list[TranscriptSegment] = Field(default_factory=list)
    language: str = "zh"
    duration_seconds: float = 0.0
    full_text: str = ""


class TopicSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    discussion_points: list[str] = Field(default_factory=list)
    participants: list[str] = Field(default_factory=list)
    conclusion: str = ""


class MeetingSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "会议纪要"
    date: str = ""
    participants: list[str] = Field(default_factory=list)
    topics: list[TopicSummary] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: f"act-{uuid.uuid4().hex[:8]}")
    assignee: str = "未指定"
    task: str
    deadline: str = ""
    priority: Priority = Priority.MEDIUM
    status: str = "pending"
    context: str = ""
    jira_issue_key: str | None = None
    feishu_task_id: str | None = None


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meeting_id: str
    action_items: list[ActionItem] = Field(default_factory=list)
    sync_status: dict[str, str] = Field(default_factory=dict)


class SpeakerStats(BaseModel):
    speaker: str
    duration_s: float = 0.0
    percentage: float = 0.0
    word_count: int = 0
    segment_count: int = 0


class MeetingInsight(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meeting_id: str
    overall_sentiment: str = "neutral"
    sentiment_score: float = 0.5
    speaker_stats: list[SpeakerStats] = Field(default_factory=list)
    efficiency_score: float = 0.0
    keywords: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class FollowUpResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meeting_id: str
    summary_sent: bool = False
    recipients: list[str] = Field(default_factory=list)
    jira_issues_created: list[str] = Field(default_factory=list)
    feishu_tasks_created: list[str] = Field(default_factory=list)
    reminders_scheduled: int = 0
    report_url: str = ""
    stored_in_vector_db: bool = False


def create_initial_state(
    meeting_id: str,
    audio_data: bytes = b"",
    audio_file_name: str = "",
    title: str = "",
    participants: list[str] | None = None,
    language: str = "zh",
) -> dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "audio_data": audio_data,
        "audio_file_name": audio_file_name,
        "title": title,
        "participants": participants or [],
        "language": language,
        "status": MeetingStatus.PENDING.value,
        "errors": [],
    }
