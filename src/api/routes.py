from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..graph import run_meeting_pipeline


router = APIRouter()

meeting_results: dict[str, dict[str, Any]] = {}
meeting_metadata: dict[str, dict[str, Any]] = {}


class MeetingStartRequest(BaseModel):
    title: str = ""
    participants: list[str] = []
    language: str = "zh"


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
            data[key] = value.model_dump()
    return data


@router.get("/")
async def root() -> dict[str, Any]:
    return {
        "name": "Multi-Agent HY Meeting Assistant",
        "status": "healthy",
        "docs": "/docs",
        "demo": "/api/v1/meeting/demo/demo",
        "agents": ["transcription", "summary", "action", "insight", "followup"],
    }


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/v1/meeting/start", status_code=201)
async def start_meeting(request: MeetingStartRequest) -> dict[str, Any]:
    if request.language not in {"zh", "en"}:
        raise HTTPException(status_code=400, detail="language only supports zh/en")
    meeting_id = f"m-{uuid.uuid4().hex[:12]}"
    meeting_metadata[meeting_id] = request.model_dump() | {"created_at": _now()}
    return {
        "meeting_id": meeting_id,
        "status": "created",
        "websocket_url": f"ws://localhost:8000/ws/meeting/{meeting_id}",
    }


@router.post("/api/v1/meeting/{meeting_id}/demo")
async def run_demo(meeting_id: str) -> dict[str, Any]:
    started = time.time()
    meta = meeting_metadata.get(meeting_id, {})
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        title=meta.get("title", ""),
        participants=meta.get("participants", []),
        language=meta.get("language", "zh"),
    )
    meeting_results[meeting_id] = result
    response = _serialize_state(result)
    response["processing_time_s"] = round(time.time() - started, 2)
    return response


async def _process_upload(meeting_id: str, audio_data: bytes, language: str = "zh") -> None:
    meta = meeting_metadata.get(meeting_id, {})
    result = await run_meeting_pipeline(
        meeting_id=meeting_id,
        audio_data=audio_data,
        title=meta.get("title", ""),
        participants=meta.get("participants", []),
        language=language,
    )
    meeting_results[meeting_id] = result


@router.post("/api/v1/meeting/{meeting_id}/upload", status_code=202)
async def upload_audio(
    meeting_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: str = "zh",
) -> dict[str, Any]:
    audio_data = await file.read()
    background_tasks.add_task(_process_upload, meeting_id, audio_data, language)
    return {
        "meeting_id": meeting_id,
        "status": "processing",
        "file_name": file.filename,
        "file_size_bytes": len(audio_data),
    }


@router.get("/api/v1/meeting/{meeting_id}/report")
async def get_report(meeting_id: str) -> dict[str, Any]:
    result = meeting_results.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")
    return _serialize_state(result)


@router.get("/api/v1/meeting/{meeting_id}/{section}")
async def get_section(meeting_id: str, section: str) -> Any:
    if section not in {"transcript", "summary", "actions", "insights", "followup"}:
        raise HTTPException(status_code=404, detail="unknown section")
    result = meeting_results.get(meeting_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"meeting not found: {meeting_id}")
    value = result.get(section)
    return value.model_dump() if hasattr(value, "model_dump") else value


@router.websocket("/ws/meeting/{meeting_id}")
async def websocket_meeting(websocket: WebSocket, meeting_id: str) -> None:
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
                    await websocket.send_json({"type": "processing", "stage": "pipeline"})
                    result = await run_meeting_pipeline(meeting_id, bytes(audio_buffer))
                    meeting_results[meeting_id] = result
                    await websocket.send_json({"type": "completed", "data": _serialize_state(result)})
                elif payload.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        return
