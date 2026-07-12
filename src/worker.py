from __future__ import annotations

import asyncio
import json
import logging

from .services.meeting_processor import process_audio_file, set_meeting_status
from .services.queue import QUEUE_NAME, get_redis_client
from .storage.database import init_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_job(raw: str) -> None:
    job = json.loads(raw)
    meeting_id = job["meeting_id"]
    set_meeting_status(meeting_id, "processing", "dequeued", 1, "Worker picked up job")
    await process_audio_file(
        meeting_id=meeting_id,
        audio_path=job["audio_path"],
        language=job.get("language", "zh"),
    )


async def worker_loop() -> None:
    init_database()
    client = get_redis_client()
    logger.info("Meeting worker started. queue=%s", QUEUE_NAME)
    while True:
        item = await asyncio.to_thread(client.blpop, QUEUE_NAME, 5)
        if item is None:
            continue
        _, raw = item
        try:
            await handle_job(raw)
        except Exception:
            logger.exception("Failed to process queued meeting job")


def main() -> None:
    asyncio.run(worker_loop())


if __name__ == "__main__":
    main()
