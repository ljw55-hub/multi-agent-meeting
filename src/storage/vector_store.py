from __future__ import annotations

import hashlib
import logging
import math
import os
from typing import Any

logger = logging.getLogger(__name__)

COLLECTION_NAME = "meeting_memories"
EMBEDDING_DIM = 128


def upsert_meeting_memory(state: dict[str, Any]) -> bool:
    meeting_id = str(state.get("meeting_id") or "")
    if not meeting_id:
        return False

    document = _build_document(state)
    if not document.strip():
        return False

    try:
        collection = _get_collection()
        collection.upsert(
            ids=[meeting_id],
            documents=[document],
            embeddings=[_embed_text(document)],
            metadatas=[
                {
                    "meeting_id": meeting_id,
                    "status": str(state.get("status") or ""),
                    "title": _summary_title(state),
                }
            ],
        )
        return True
    except Exception as exc:
        logger.warning("Failed to upsert meeting memory: meeting_id=%s error=%r", meeting_id, exc)
        return False


def search_meeting_memories(query: str, limit: int = 5) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    try:
        collection = _get_collection()
        result = collection.query(
            query_embeddings=[_embed_text(query)],
            n_results=max(1, min(limit, 20)),
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.warning("Failed to search meeting memories: error=%r", exc)
        return []

    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    items: list[dict[str, Any]] = []
    for document, metadata, distance in zip(documents, metadatas, distances, strict=False):
        items.append(
            {
                "meeting_id": (metadata or {}).get("meeting_id", ""),
                "title": (metadata or {}).get("title", ""),
                "distance": distance,
                "document": document,
            }
        )
    return items


def _get_collection() -> Any:
    import chromadb

    host = os.getenv("CHROMA_HOST", "chromadb")
    port = int(os.getenv("CHROMA_PORT", "8000"))
    client = chromadb.HttpClient(host=host, port=port)
    return client.get_or_create_collection(COLLECTION_NAME)


def _build_document(state: dict[str, Any]) -> str:
    transcript = state.get("transcript") or {}
    if hasattr(transcript, "model_dump"):
        transcript = transcript.model_dump()

    summary = state.get("summary") or {}
    if hasattr(summary, "model_dump"):
        summary = summary.model_dump()

    actions = state.get("actions") or {}
    if hasattr(actions, "model_dump"):
        actions = actions.model_dump()

    insights = state.get("insights") or {}
    if hasattr(insights, "model_dump"):
        insights = insights.model_dump()

    parts = [
        f"Meeting ID: {state.get('meeting_id', '')}",
        f"Transcript:\n{transcript.get('full_text', '') if isinstance(transcript, dict) else ''}",
        f"Summary:\n{_compact(summary)}",
        f"Actions:\n{_compact(actions)}",
        f"Insights:\n{_compact(insights)}",
    ]
    return "\n\n".join(part for part in parts if part.strip())


def _summary_title(state: dict[str, Any]) -> str:
    summary = state.get("summary") or {}
    if hasattr(summary, "model_dump"):
        summary = summary.model_dump()
    if isinstance(summary, dict):
        return str(summary.get("title") or "")
    return ""


def _compact(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    if isinstance(value, dict):
        return " ".join(_flatten(value))
    return str(value or "")


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [part for item in value.values() for part in _flatten(item)]
    if isinstance(value, list):
        return [part for item in value for part in _flatten(item)]
    if value is None:
        return []
    return [str(value)]


def _embed_text(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    tokens = [token for token in text.lower().replace("\n", " ").split(" ") if token]
    if not tokens:
        tokens = [text.lower()]

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        for index, byte in enumerate(digest):
            vector[index % EMBEDDING_DIM] += (byte / 255.0) - 0.5

    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]
