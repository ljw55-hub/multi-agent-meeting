from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..graph import run_meeting_pipeline
from ..storage.database import (
    get_meeting_metadata,
    get_meeting_status,
    save_meeting_result,
    save_meeting_status,
)
from ..storage.vector_store import upsert_meeting_memory

logger = logging.getLogger(__name__)


def serialize_state(state: dict[str, Any]) -> dict[str, Any]:
    data = {
        "meeting_id": state.get("meeting_id"),
        "status": state.get("status"),
        "errors": state.get("errors", []),
    }
    for key in ("transcript", "summary", "actions", "insights", "followup"):
        value = state.get(key)
        if hasattr(value, "model_dump"):
            data[key] = value.model_dump(mode="json")
        elif isinstance(value, dict):
            data[key] = value
    return data


def set_meeting_status(
    meeting_id: str,
    status: str,
    stage: str,
    progress: int,
    message: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    return save_meeting_status(
        meeting_id=meeting_id,
        status=status,
        stage=stage,
        progress=progress,
        message=message,
        errors=errors or [],
    )


def progress_callback(meeting_id: str):
    async def callback(stage: str, progress: int, message: str) -> None:
        status = "completed" if stage == "completed" else "processing"
        set_meeting_status(meeting_id, status, stage, progress, message)

    return callback


def persist_completed_result(meeting_id: str, result: dict[str, Any]) -> dict[str, Any]:
    data = serialize_state(result)
    stored_in_vector_db = upsert_meeting_memory(data)
    followup = data.get("followup")
    if isinstance(followup, dict):
        followup["stored_in_vector_db"] = stored_in_vector_db
    save_meeting_result(meeting_id, data)
    return data


async def process_audio_file(meeting_id: str, audio_path: str, language: str = "zh") -> dict[str, Any]:
    path = Path(audio_path)
    audio_data = path.read_bytes()
    meta = get_meeting_metadata(meeting_id) or {}
    return await process_audio_bytes(
        meeting_id=meeting_id,
        audio_data=audio_data,
        audio_file_name=meta.get("audio_file_name", path.name),
        language=language or meta.get("language", "zh"),
    )


async def process_audio_bytes(
    meeting_id: str,
    audio_data: bytes,
    audio_file_name: str = "",
    language: str = "zh",
) -> dict[str, Any]:
    meta = get_meeting_metadata(meeting_id) or {}
    try:
        set_meeting_status(meeting_id, "processing", "queued", 1, "Worker job started")
        result = await run_meeting_pipeline(
            meeting_id=meeting_id,
            audio_data=audio_data,
            audio_file_name=audio_file_name,
            title=meta.get("title", ""),
            participants=meta.get("participants", []),
            language=language or meta.get("language", "zh"),
            progress_callback=progress_callback(meeting_id),
        )
        response = persist_completed_result(meeting_id, result)
        set_meeting_status(
            meeting_id,
            "completed",
            "completed",
            100,
            "Meeting processing completed",
            errors=response.get("errors", []),
        )
        return response
    except Exception as exc:
        logger.exception("Meeting processing failed: meeting_id=%s", meeting_id)
        previous = get_meeting_status(meeting_id) or {}
        set_meeting_status(
            meeting_id,
            "failed",
            "failed",
            previous.get("progress", 0),
            "Meeting processing failed",
            errors=[str(exc)],
        )
        raise
