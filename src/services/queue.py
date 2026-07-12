from __future__ import annotations

import json
import os
from typing import Any

import redis

QUEUE_NAME = os.getenv("MEETING_JOB_QUEUE", "meeting_jobs")


def get_redis_client() -> redis.Redis:
    host = os.getenv("REDIS_HOST", "redis")
    port = int(os.getenv("REDIS_PORT", "6379"))
    return redis.Redis(host=host, port=port, decode_responses=True)


def enqueue_meeting_job(job: dict[str, Any]) -> int:
    return get_redis_client().rpush(QUEUE_NAME, json.dumps(job, ensure_ascii=False))


def queue_depth() -> int:
    return int(get_redis_client().llen(QUEUE_NAME))
