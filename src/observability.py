from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("meeting_id", "stage", "agent", "event", "duration_ms", "status", "path"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


_stage_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "total_ms": 0, "max_ms": 0})
_recent_events: deque[dict[str, Any]] = deque(maxlen=200)


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    formatter: logging.Formatter
    if os.getenv("LOG_FORMAT", "json").lower() == "text":
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    else:
        formatter = JsonLogFormatter()

    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers or [logging.StreamHandler()]:
        handler.setFormatter(formatter)
        handler.setLevel(level)
        if handler not in root.handlers:
            root.addHandler(handler)


def log_event(
    logger: logging.Logger,
    event: str,
    message: str,
    *,
    meeting_id: str = "",
    stage: str = "",
    agent: str = "",
    status: str = "",
    duration_ms: float | None = None,
    level: int = logging.INFO,
) -> None:
    extra = {
        "event": event,
        "meeting_id": meeting_id,
        "stage": stage,
        "agent": agent,
        "status": status,
    }
    if duration_ms is not None:
        extra["duration_ms"] = round(duration_ms, 2)
    logger.log(level, message, extra=extra)
    _recent_events.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "meeting_id": meeting_id,
            "stage": stage,
            "agent": agent,
            "status": status,
            "duration_ms": round(duration_ms, 2) if duration_ms is not None else None,
            "message": message,
        }
    )


@contextmanager
def stage_timer(meeting_id: str, stage: str, agent: str = "") -> Iterator[None]:
    started = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        record_stage_duration(stage, duration_ms)
        log_event(
            logging.getLogger("meeting.pipeline"),
            "stage_completed",
            "pipeline stage completed",
            meeting_id=meeting_id,
            stage=stage,
            agent=agent,
            status="completed",
            duration_ms=duration_ms,
        )


def record_stage_duration(stage: str, duration_ms: float) -> None:
    stats = _stage_stats[stage]
    stats["count"] += 1
    stats["total_ms"] += duration_ms
    stats["max_ms"] = max(stats["max_ms"], duration_ms)


def metrics_snapshot() -> dict[str, Any]:
    stages = {}
    for stage, stats in _stage_stats.items():
        count = int(stats["count"])
        stages[stage] = {
            "count": count,
            "avg_ms": round(stats["total_ms"] / count, 2) if count else 0,
            "max_ms": round(stats["max_ms"], 2),
        }
    return {
        "stages": stages,
        "recent_events": list(_recent_events),
    }
