from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..auth import auth_enabled, require_websocket_api_key
from ..agents import TranscriptionAgent
from ..graph import run_meeting_pipeline
from ..observability import metrics_snapshot
from ..services.queue import enqueue_meeting_job, queue_depth
from ..storage.database import (
    get_meeting_metadata,
    get_meeting_result,
    get_meeting_status,
    list_action_items,
    list_meeting_metadata,
    save_meeting_result,
    save_meeting_status,
    update_action_item,
    upsert_meeting_metadata,
)
from ..storage.vector_store import search_meeting_memories, upsert_meeting_memory

router = APIRouter()
logger = logging.getLogger(__name__)

# Small process-local caches. Postgres is the source of truth.
meeting_results: dict[str, dict[str, Any]] = {}
meeting_metadata: dict[str, dict[str, Any]] = {}
meeting_statuses: dict[str, dict[str, Any]] = {}
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/app/uploads"))


class MeetingStartRequest(BaseModel):
    title: str = ""
    participants: list[str] = []
    language: str = "zh"


class MeetingRetryRequest(BaseModel):
    force: bool = False


class ActionStatusUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None
    task: str | None = None
    deadline: str | None = None
    priority: str | None = None
    context: str | None = None
    jira_issue_key: str | None = None
    feishu_task_id: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_state(state: dict[str, Any]) -> dict[str, Any]:
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


def _set_meeting_status(
    meeting_id: str,
    status: str,
    stage: str,
    progress: int,
    message: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    payload = save_meeting_status(
        meeting_id=meeting_id,
        status=status,
        stage=stage,
        progress=progress,
        message=message,
        errors=errors or [],
    )
    meeting_statuses[meeting_id] = payload
    return payload


def _progress_callback(meeting_id: str):
    async def callback(stage: str, progress: int, message: str) -> None:
        status = "completed" if stage == "completed" else "processing"
        _set_meeting_status(meeting_id, status, stage, progress, message)

    return callback


def _persist_completed_result(meeting_id: str, result: dict[str, Any]) -> dict[str, Any]:
    data = _serialize_state(result)
    stored_in_vector_db = upsert_meeting_memory(data)
    followup = data.get("followup")
    if isinstance(followup, dict):
        followup["stored_in_vector_db"] = stored_in_vector_db
    meeting_results[meeting_id] = data
    save_meeting_result(meeting_id, data)
    return data


def _load_result(meeting_id: str) -> dict[str, Any] | None:
    return get_meeting_result(meeting_id) or meeting_results.get(meeting_id)


def _load_metadata(meeting_id: str) -> dict[str, Any]:
    return get_meeting_metadata(meeting_id) or meeting_metadata.get(meeting_id, {})


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _transcript_payload(transcript: Any) -> dict[str, Any]:
    if hasattr(transcript, "model_dump"):
        return transcript.model_dump(mode="json")
    if isinstance(transcript, dict):
        return transcript
    return {}


async def _send_pipeline_events(websocket: WebSocket, state: dict[str, Any], processing_time_s: float = 0.0) -> None:
    transcript = state.get("transcript")
    if transcript and hasattr(transcript, "segments"):
        for segment in transcript.segments:
            await websocket.send_json(
                {
                    "type": "transcript",
                    "data": {
                        "speaker": segment.speaker,
                        "text": segment.text,
                        "timestamp": segment.start,
                        "start": segment.start,
                        "end": segment.end,
                        "is_final": True,
                        "confidence": segment.confidence,
                    },
                }
            )

    for event_type, key in (
        ("summary", "summary"),
        ("actions", "actions"),
        ("insights", "insights"),
        ("followup", "followup"),
    ):
        value = state.get(key)
        if hasattr(value, "model_dump"):
            await websocket.send_json({"type": event_type, "data": value.model_dump(mode="json")})
        elif isinstance(value, dict):
            await websocket.send_json({"type": event_type, "data": value})

    await websocket.send_json(
        {
            "type": "completed",
            "meeting_id": state.get("meeting_id"),
            "processing_time_s": round(processing_time_s, 2),
            "errors": state.get("errors", []),
        }
    )


@router.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "Multi-Agent Meeting Assistant",
        "status": "healthy",
        "docs": "/docs",
        "ui": "/ui",
        "demo": "/api/v1/meeting/demo/demo",
        "agents": ["transcription", "summary", "action", "insight", "followup"],
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/api/v1/system/status")
async def system_status() -> dict[str, Any]:
    return {
        "auth_enabled": auth_enabled(),
        "asr": TranscriptionAgent.runtime_status(),
        "metrics": metrics_snapshot(),
    }


@router.get("/api/v1/metrics")
async def get_metrics() -> dict[str, Any]:
    return metrics_snapshot()


@router.get("/api/v1/meetings")
async def list_meetings(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    items = []
    for meta in list_meeting_metadata(limit=limit, offset=offset):
        meeting_id = meta["meeting_id"]
        status = get_meeting_status(meeting_id) or meeting_statuses.get(meeting_id)
        result = _load_result(meeting_id)
        items.append(
            {
                "meeting_id": meeting_id,
                "title": meta.get("title", ""),
                "participants": meta.get("participants", []),
                "language": meta.get("language", "zh"),
                "audio_file_name": meta.get("audio_file_name", ""),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "status": status or {},
                "has_report": bool(result),
            }
        )
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/api/v1/action-items")
async def get_action_items(
    meeting_id: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(200, limit))
    offset = max(0, offset)
    return {
        "items": list_action_items(
            meeting_id=meeting_id,
            status=status,
            assignee=assignee,
            limit=limit,
            offset=offset,
        ),
        "limit": limit,
        "offset": offset,
    }


@router.patch("/api/v1/action-items/{item_id}")
async def patch_action_item(item_id: str, request: ActionStatusUpdate) -> dict[str, Any]:
    payload = request.model_dump(exclude_unset=True)
    if "status" in payload and payload["status"] not in {"pending", "in_progress", "completed", "cancelled"}:
        raise HTTPException(status_code=400, detail="status must be pending/in_progress/completed/cancelled")
    if "priority" in payload and payload["priority"] not in {"low", "medium", "high", "urgent"}:
        raise HTTPException(status_code=400, detail="priority must be low/medium/high/urgent")
    if "task" in payload and not str(payload["task"]).strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")
    item = update_action_item(item_id, payload)
    if not item:
        raise HTTPException(status_code=404, detail=f"action item not found: {item_id}")
    return item


@router.post("/api/v1/meeting/start", status_code=201)
async def start_meeting(request: MeetingStartRequest) -> dict[str, Any]:
    if request.language not in {"zh", "en"}:
        raise HTTPException(status_code=400, detail="language only supports zh/en")
    meeting_id = f"m-{uuid.uuid4().hex[:12]}"
    metadata = upsert_meeting_metadata(meeting_id, request.model_dump())
    meeting_metadata[meeting_id] = metadata
    _set_meeting_status(meeting_id, "created", "created", 0, "Meeting created")
    return {
        "meeting_id": meeting_id,
        "status": "created",
        "websocket_url": f"ws://localhost:8000/ws/meeting/{meeting_id}",
    }


@router.post("/api/v1/meeting/{meeting_id}/demo")
async def run_demo(meeting_id: str) -> dict[str, Any]:
    started = time.time()
    meta = _load_metadata(meeting_id)
    _set_meeting_status(meeting_id, "processing", "queued", 0, "Demo job queued")
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        title=meta.get("title", ""),
        participants=meta.get("participants", []),
        language=meta.get("language", "zh"),
        progress_callback=_progress_callback(meeting_id),
    )
    response = _persist_completed_result(meeting_id, result)
    _set_meeting_status(
        meeting_id,
        "completed",
        "completed",
        100,
        "Meeting processing completed",
        errors=response.get("errors", []),
    )
    response["processing_time_s"] = round(time.time() - started, 2)
    return response


async def _process_upload(meeting_id: str, audio_data: bytes, language: str = "zh") -> None:
    meta = _load_metadata(meeting_id)
    try:
        _set_meeting_status(meeting_id, "processing", "queued", 1, "Background job started")
        result = await run_meeting_pipeline(
            meeting_id=meeting_id,
            audio_data=audio_data,
            audio_file_name=meta.get("audio_file_name", ""),
            title=meta.get("title", ""),
            participants=meta.get("participants", []),
            language=language,
            progress_callback=_progress_callback(meeting_id),
        )
        response = _persist_completed_result(meeting_id, result)
        _set_meeting_status(
            meeting_id,
            "completed",
            "completed",
            100,
            "Meeting processing completed",
            errors=response.get("errors", []),
        )
    except Exception as exc:
        logger.exception("Meeting upload processing failed: meeting_id=%s", meeting_id)
        previous = get_meeting_status(meeting_id) or {}
        _set_meeting_status(
            meeting_id,
            "failed",
            "failed",
            previous.get("progress", 0),
            "Meeting processing failed",
            errors=[str(exc)],
        )


@router.post("/api/v1/meeting/{meeting_id}/upload", status_code=202)
async def upload_audio(
    meeting_id: str,
    file: UploadFile = File(...),
    language: str = "zh",
) -> dict[str, Any]:
    audio_data = await file.read()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "meeting-audio.bin").name
    stored_name = f"{meeting_id}-{uuid.uuid4().hex[:8]}-{safe_name}"
    audio_path = UPLOAD_DIR / stored_name
    audio_path.write_bytes(audio_data)
    metadata = upsert_meeting_metadata(
        meeting_id,
        {
            "audio_file_name": file.filename or "",
            "language": language,
            "extra": {"audio_path": str(audio_path)},
        },
    )
    meeting_metadata[meeting_id] = metadata
    _set_meeting_status(meeting_id, "queued", "queued", 0, "Audio uploaded and queued")
    depth = enqueue_meeting_job(
        {
            "type": "audio_file",
            "meeting_id": meeting_id,
            "audio_path": str(audio_path),
            "language": language,
            "file_name": file.filename or "",
        }
    )
    return {
        "meeting_id": meeting_id,
        "status": "queued",
        "file_name": file.filename,
        "file_size_bytes": len(audio_data),
        "queue_depth": depth,
    }


@router.post("/api/v1/meeting/{meeting_id}/retry", status_code=202)
async def retry_meeting(meeting_id: str, request: MeetingRetryRequest | None = None) -> dict[str, Any]:
    meta = _load_metadata(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")

    status = get_meeting_status(meeting_id) or {}
    current_status = status.get("status", "")
    force = bool(request.force) if request else False
    if current_status in {"queued", "processing"} and not force:
        raise HTTPException(status_code=409, detail="meeting is already queued or processing")

    extra = meta.get("extra") or {}
    audio_path = str(extra.get("audio_path") or "")
    if not audio_path:
        raise HTTPException(status_code=400, detail="retry requires an uploaded audio file")
    if not Path(audio_path).is_file():
        raise HTTPException(status_code=404, detail=f"uploaded audio file is missing: {audio_path}")

    retry_count = int(extra.get("retry_count") or 0) + 1
    extra = extra | {"retry_count": retry_count, "last_retry_at": _now()}
    metadata = upsert_meeting_metadata(
        meeting_id,
        {
            "language": meta.get("language", "zh"),
            "audio_file_name": meta.get("audio_file_name", ""),
            "extra": extra,
        },
    )
    meeting_metadata[meeting_id] = metadata
    _set_meeting_status(meeting_id, "queued", "retry_queued", 0, f"Retry queued, attempt {retry_count}")
    depth = enqueue_meeting_job(
        {
            "type": "audio_file_retry",
            "meeting_id": meeting_id,
            "audio_path": audio_path,
            "language": meta.get("language", "zh"),
            "file_name": meta.get("audio_file_name", ""),
            "retry_count": retry_count,
        }
    )
    return {
        "meeting_id": meeting_id,
        "status": "queued",
        "stage": "retry_queued",
        "retry_count": retry_count,
        "queue_depth": depth,
    }


@router.get("/api/v1/meeting/search")
async def search_meetings(query: str, limit: int = 5) -> dict[str, Any]:
    return {
        "query": query,
        "results": search_meeting_memories(query, limit=limit),
    }


@router.get("/api/v1/meeting/{meeting_id}/report")
async def get_report(meeting_id: str) -> dict[str, Any]:
    result = _load_result(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")
    return result


@router.get("/api/v1/meeting/{meeting_id}/export.md", response_class=PlainTextResponse)
async def export_report_markdown(meeting_id: str) -> str:
    result = _load_result(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")
    return _report_markdown(result)


@router.get("/api/v1/meeting/{meeting_id}/status")
async def get_status(meeting_id: str) -> dict[str, Any]:
    status = get_meeting_status(meeting_id) or meeting_statuses.get(meeting_id)
    if status:
        return status

    result = _load_result(meeting_id)
    if result:
        return {
            "meeting_id": meeting_id,
            "status": "completed",
            "stage": "completed",
            "progress": 100,
            "message": "Meeting processing completed",
            "errors": result.get("errors", []),
            "updated_at": _now(),
        }

    meta = _load_metadata(meeting_id)
    if meta:
        return {
            "meeting_id": meeting_id,
            "status": "created",
            "stage": "created",
            "progress": 0,
            "message": "Meeting created",
            "errors": [],
            "updated_at": meta.get("created_at", _now()),
        }
    raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")


@router.get("/api/v1/meeting/{meeting_id}/{section}")
async def get_section(meeting_id: str, section: str) -> Any:
    if section not in {"transcript", "summary", "actions", "insights", "followup"}:
        raise HTTPException(status_code=404, detail="unknown section")
    result = _load_result(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")
    return result.get(section)


@router.websocket("/ws/meeting/{meeting_id}")
async def websocket_meeting(websocket: WebSocket, meeting_id: str) -> None:
    if not await require_websocket_api_key(websocket):
        return
    await websocket.accept()
    audio_buffer = bytearray()
    await websocket.send_json({"type": "connected", "meeting_id": meeting_id})
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                audio_buffer.extend(message["bytes"])
                await websocket.send_json({"type": "recording", "buffer_size": len(audio_buffer)})
            elif message.get("text"):
                payload = json.loads(message["text"])
                if payload.get("type") in {"demo", "stop"}:
                    started = time.time()
                    await websocket.send_json({"type": "processing", "stage": "pipeline"})
                    _set_meeting_status(meeting_id, "processing", "queued", 1, "WebSocket job started")
                    result = await run_meeting_pipeline(
                        meeting_id,
                        bytes(audio_buffer),
                        progress_callback=_progress_callback(meeting_id),
                    )
                    data = _persist_completed_result(meeting_id, result)
                    _set_meeting_status(
                        meeting_id,
                        "completed",
                        "completed",
                        100,
                        "Meeting processing completed",
                        errors=data.get("errors", []),
                    )
                    await _send_pipeline_events(websocket, result, time.time() - started)
                elif payload.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        return


@router.websocket("/ws/transcription/{meeting_id}")
async def websocket_transcription(websocket: WebSocket, meeting_id: str) -> None:
    """Receive audio chunks and return rolling transcription snapshots.

    Faster-Whisper works on audio files rather than native token streams. This
    endpoint therefore buffers incoming chunks and transcribes the current audio
    window when the client sends `flush`, when the buffer reaches the configured
    threshold, or when the client sends `stop`.
    """
    if not await require_websocket_api_key(websocket):
        return
    await websocket.accept()

    agent = TranscriptionAgent()
    audio_buffer = bytearray()
    language = "zh"
    audio_file_name = "stream.webm"
    min_flush_bytes = 512_000
    last_flush_size = 0
    last_flush_time = 0.0
    flush_interval_s = 8.0

    metadata = upsert_meeting_metadata(
        meeting_id,
        {
            "language": language,
            "audio_file_name": audio_file_name,
            "streaming": True,
        },
    )
    meeting_metadata[meeting_id] = metadata
    _set_meeting_status(meeting_id, "processing", "streaming", 0, "Streaming transcription connected")

    await websocket.send_json(
        {
            "type": "connected",
            "meeting_id": meeting_id,
            "mode": "chunked_transcription",
            "message": "Send binary audio chunks, then send {'type':'flush'} for partial text or {'type':'stop'} to finish.",
        }
    )

    async def flush_transcript(event_type: str) -> None:
        nonlocal last_flush_size, last_flush_time
        if not audio_buffer:
            await websocket.send_json({"type": event_type, "meeting_id": meeting_id, "buffer_size": 0, "transcript": None})
            return

        _set_meeting_status(
            meeting_id,
            "processing",
            "streaming_transcription",
            15,
            f"Transcribing streaming buffer ({len(audio_buffer)} bytes)",
        )
        transcript = await agent.transcribe_bytes(
            meeting_id=meeting_id,
            audio_data=bytes(audio_buffer),
            audio_file_name=audio_file_name,
            language=language,
        )
        last_flush_size = len(audio_buffer)
        last_flush_time = time.time()
        await websocket.send_json(
            {
                "type": event_type,
                "meeting_id": meeting_id,
                "buffer_size": len(audio_buffer),
                "transcript": _transcript_payload(transcript),
            }
        )

    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                audio_buffer.extend(message["bytes"])
                await websocket.send_json(
                    {
                        "type": "buffered",
                        "meeting_id": meeting_id,
                        "buffer_size": len(audio_buffer),
                    }
                )
                enough_new_audio = len(audio_buffer) - last_flush_size >= min_flush_bytes
                enough_time = time.time() - last_flush_time >= flush_interval_s
                if enough_new_audio and enough_time:
                    await flush_transcript("partial_transcript")
                continue

            if not message.get("text"):
                continue

            payload = _safe_json_loads(message["text"])
            event_type = payload.get("type")

            if event_type == "config":
                language = payload.get("language", language)
                audio_file_name = payload.get("audio_file_name", audio_file_name)
                min_flush_bytes = int(payload.get("min_flush_bytes", min_flush_bytes))
                flush_interval_s = float(payload.get("flush_interval_s", flush_interval_s))
                metadata = upsert_meeting_metadata(
                    meeting_id,
                    {
                        "language": language,
                        "audio_file_name": audio_file_name,
                        "streaming": True,
                    },
                )
                meeting_metadata[meeting_id] = metadata
                await websocket.send_json(
                    {
                        "type": "configured",
                        "meeting_id": meeting_id,
                        "language": language,
                        "audio_file_name": audio_file_name,
                        "min_flush_bytes": min_flush_bytes,
                        "flush_interval_s": flush_interval_s,
                    }
                )
            elif event_type == "flush":
                await flush_transcript("partial_transcript")
            elif event_type == "stop":
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                stored_name = f"{meeting_id}-{uuid.uuid4().hex[:8]}-{Path(audio_file_name).name}"
                audio_path = UPLOAD_DIR / stored_name
                audio_path.write_bytes(bytes(audio_buffer))
                metadata = upsert_meeting_metadata(
                    meeting_id,
                    {
                        "audio_file_name": audio_file_name,
                        "language": language,
                        "streaming": True,
                        "extra": {"audio_path": str(audio_path)},
                    },
                )
                meeting_metadata[meeting_id] = metadata
                _set_meeting_status(meeting_id, "queued", "queued", 20, "Streaming audio finalized and queued")
                depth = enqueue_meeting_job(
                    {
                        "type": "audio_file",
                        "meeting_id": meeting_id,
                        "audio_path": str(audio_path),
                        "language": language,
                        "file_name": audio_file_name,
                    }
                )
                await websocket.send_json(
                    {
                        "type": "queued",
                        "meeting_id": meeting_id,
                        "stage": "queued",
                        "queue_depth": depth,
                        "message": "Streaming audio queued for background analysis.",
                    }
                )
                break
            elif event_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "error", "message": f"Unsupported event type: {event_type}"})
    except WebSocketDisconnect:
        return
    except Exception as exc:
        logger.exception("Streaming transcription failed: meeting_id=%s", meeting_id)
        _set_meeting_status(meeting_id, "failed", "streaming_failed", 0, "Streaming transcription failed", [str(exc)])
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except RuntimeError:
            logger.debug("WebSocket already closed while sending streaming error: meeting_id=%s", meeting_id)


def _report_markdown(result: dict[str, Any]) -> str:
    meeting_id = result.get("meeting_id", "")
    summary = result.get("summary") or {}
    transcript = result.get("transcript") or {}
    actions = result.get("actions") or {}
    insights = result.get("insights") or {}
    followup = result.get("followup") or {}

    lines = [
        f"# Meeting Report - {meeting_id}",
        "",
        f"Status: {result.get('status', 'completed')}",
        "",
        "## Summary",
        "",
        f"### {summary.get('title', 'Meeting Summary')}",
        "",
    ]
    for topic in summary.get("topics", []):
        lines.extend([f"#### {topic.get('title', 'Topic')}", ""])
        lines.extend(f"- {point}" for point in topic.get("discussion_points", []))
        if topic.get("conclusion"):
            lines.append(f"- Conclusion: {topic['conclusion']}")
        lines.append("")
    if summary.get("decisions"):
        lines.extend(["## Decisions", ""])
        lines.extend(f"- {item}" for item in summary["decisions"])
        lines.append("")

    lines.extend(["## Action Items", ""])
    for item in actions.get("action_items", []):
        lines.append(
            f"- [{item.get('priority', 'medium')}] {item.get('assignee', 'Unassigned')}: "
            f"{item.get('task', '')} | deadline: {item.get('deadline', 'N/A')}"
        )
    lines.append("")

    lines.extend(["## Insights", ""])
    lines.append(f"- Sentiment: {insights.get('overall_sentiment', 'neutral')} ({insights.get('sentiment_score', 0.5)})")
    lines.append(f"- Efficiency score: {insights.get('efficiency_score', 0)}/10")
    if insights.get("keywords"):
        lines.append(f"- Keywords: {', '.join(insights['keywords'])}")
    for stat in insights.get("speaker_stats", []):
        lines.append(f"- {stat.get('speaker')}: {stat.get('percentage', 0)}%")
    lines.append("")

    lines.extend(["## Transcript", ""])
    for segment in transcript.get("segments", []):
        lines.append(
            f"- {segment.get('start', 0):.1f}s-{segment.get('end', 0):.1f}s "
            f"{segment.get('speaker', 'Speaker')}: {segment.get('text', '')}"
        )
    lines.append("")

    lines.extend(["## Follow-up", ""])
    lines.append(f"- Report URL: {followup.get('report_url', '')}")
    lines.append(f"- Stored in vector DB: {followup.get('stored_in_vector_db', False)}")
    return "\n".join(lines)
