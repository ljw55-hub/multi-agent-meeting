from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, Text, create_engine, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine

metadata = MetaData()

meetings = Table(
    "meetings",
    metadata,
    # User-facing meeting id, for example "real-audio-20260710-01".
    Column("meeting_id", String(128), primary_key=True),
    Column("title", String(255), nullable=False, default=""),
    Column("participants", JSON, nullable=False, default=list),
    Column("language", String(16), nullable=False, default="zh"),
    Column("audio_file_name", String(512), nullable=False, default=""),
    Column("extra", JSON, nullable=False, default=dict),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

meeting_statuses = Table(
    "meeting_statuses",
    metadata,
    Column("meeting_id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("stage", String(64), nullable=False),
    Column("progress", Integer, nullable=False, default=0),
    Column("message", Text, nullable=False, default=""),
    Column("errors", JSON, nullable=False, default=list),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

meeting_results = Table(
    "meeting_results",
    metadata,
    Column("meeting_id", String(128), primary_key=True),
    Column("result", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True)
    return _engine


def init_database() -> None:
    metadata.create_all(get_engine())


def upsert_meeting_metadata(meeting_id: str, values: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow()
    existing = get_meeting_metadata(meeting_id) or {}
    payload = {
        "meeting_id": meeting_id,
        "title": values.get("title", existing.get("title", "")) or "",
        "participants": values.get("participants", existing.get("participants", [])) or [],
        "language": values.get("language", existing.get("language", "zh")) or "zh",
        "audio_file_name": values.get("audio_file_name", existing.get("audio_file_name", "")) or "",
        "extra": values.get("extra", existing.get("extra", {})) or {},
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    stmt = insert(meetings).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[meetings.c.meeting_id],
        set_={key: payload[key] for key in payload if key not in {"meeting_id", "created_at"}},
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)
    return get_meeting_metadata(meeting_id) or payload


def get_meeting_metadata(meeting_id: str) -> dict[str, Any] | None:
    with get_engine().begin() as conn:
        row = conn.execute(select(meetings).where(meetings.c.meeting_id == meeting_id)).mappings().first()
    return _row_to_dict(row)


def save_meeting_status(
    meeting_id: str,
    status: str,
    stage: str,
    progress: int,
    message: str,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    payload = {
        "meeting_id": meeting_id,
        "status": status,
        "stage": stage,
        "progress": max(0, min(100, progress)),
        "message": message,
        "errors": errors or [],
        "updated_at": _utcnow(),
    }
    stmt = insert(meeting_statuses).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[meeting_statuses.c.meeting_id],
        set_={key: payload[key] for key in payload if key != "meeting_id"},
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)
    return payload


def get_meeting_status(meeting_id: str) -> dict[str, Any] | None:
    with get_engine().begin() as conn:
        row = conn.execute(
            select(meeting_statuses).where(meeting_statuses.c.meeting_id == meeting_id)
        ).mappings().first()
    return _row_to_dict(row)


def save_meeting_result(meeting_id: str, result: dict[str, Any]) -> dict[str, Any]:
    now = _utcnow()
    existing = get_meeting_result(meeting_id)
    json_result = _json_safe(result)
    payload = {
        "meeting_id": meeting_id,
        "result": json_result,
        "created_at": now if existing is None else existing.get("created_at", now),
        "updated_at": now,
    }
    stmt = insert(meeting_results).values(**payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[meeting_results.c.meeting_id],
        set_={"result": json_result, "updated_at": now},
    )
    with get_engine().begin() as conn:
        conn.execute(stmt)
    return payload


def get_meeting_result(meeting_id: str) -> dict[str, Any] | None:
    with get_engine().begin() as conn:
        row = conn.execute(
            select(meeting_results).where(meeting_results.c.meeting_id == meeting_id)
        ).mappings().first()
    if row is None:
        return None
    data = dict(row)
    result = data.get("result") or {}
    if isinstance(result, dict):
        result.setdefault("created_at", _json_safe(data.get("created_at")))
        result.setdefault("updated_at", _json_safe(data.get("updated_at")))
        return result
    return None


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "password")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "meeting_assistant")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{db}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
