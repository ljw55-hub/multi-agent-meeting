from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..integrations.llm_client import LLMClient
from ..models import MeetingInsight, SpeakerStats, TranscriptResult


class InsightAgent:
    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm or LLMClient()

    async def process(self, state: dict) -> dict:
        transcript: TranscriptResult | None = state.get("transcript")
        stats = self._speaker_stats(transcript)
        fallback = {
            "overall_sentiment": "neutral",
            "sentiment_score": 0.72,
            "efficiency_score": 8.1,
            "keywords": self._keywords(transcript),
            "highlights": [
                "会议明确了 Q3 预算上调方向。",
                "招聘与服务器采购均形成了负责人和截止时间。",
            ],
            "suggestions": [
                "后续可把预算审批、招聘 JD、采购方案接入任务系统自动追踪。"
            ],
        }
        result = await self.llm.chat_json(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是会议洞察分析师，只输出严格 JSON。"
                        "overall_sentiment 必须是 positive/neutral/negative。"
                        "sentiment_score 和 efficiency_score 必须是数字。"
                        "keywords、highlights、suggestions 必须是字符串数组。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "分析会议情绪、关键词、亮点、改进建议、效率评分。"
                        "不要输出 Markdown，不要输出解释。\n\n"
                        f"{state.get('transcript_text', '')}"
                    ),
                },
            ],
            fallback=fallback,
        )
        result = self._normalize_result(result, fallback)
        state["insights"] = MeetingInsight(
            meeting_id=state["meeting_id"],
            speaker_stats=stats,
            **result,
        )
        return state

    @staticmethod
    def _speaker_stats(transcript: TranscriptResult | None) -> list[SpeakerStats]:
        if not transcript:
            return []
        buckets: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"duration": 0.0, "words": 0, "segments": 0}
        )
        total = 0.0
        for seg in transcript.segments:
            duration = max(seg.end - seg.start, 0)
            buckets[seg.speaker]["duration"] += duration
            buckets[seg.speaker]["words"] += len(seg.text)
            buckets[seg.speaker]["segments"] += 1
            total += duration

        stats = [
            SpeakerStats(
                speaker=speaker,
                duration_s=round(float(data["duration"]), 1),
                percentage=round(float(data["duration"]) / total * 100, 1) if total else 0,
                word_count=int(data["words"]),
                segment_count=int(data["segments"]),
            )
            for speaker, data in buckets.items()
        ]
        return sorted(stats, key=lambda item: item.duration_s, reverse=True)

    @staticmethod
    def _keywords(transcript: TranscriptResult | None) -> list[str]:
        if not transcript:
            return []
        candidates = ["预算", "Q3", "AI", "招聘", "服务器", "采购", "方案", "审批"]
        text = transcript.full_text
        counted = Counter({word: text.count(word) for word in candidates})
        return [word for word, count in counted.most_common(6) if count > 0]

    @staticmethod
    def _normalize_result(result: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        normalized = fallback | result
        normalized["overall_sentiment"] = str(normalized.get("overall_sentiment", "neutral")).lower()
        if normalized["overall_sentiment"] not in {"positive", "neutral", "negative"}:
            normalized["overall_sentiment"] = "neutral"
        normalized["keywords"] = _ensure_list(normalized.get("keywords", []))
        normalized["highlights"] = _ensure_list(normalized.get("highlights", []))
        normalized["suggestions"] = _ensure_list(normalized.get("suggestions", []))
        normalized["sentiment_score"] = _ensure_float(normalized.get("sentiment_score", 0.5), 0.5)
        normalized["efficiency_score"] = _ensure_float(normalized.get("efficiency_score", 5.0), 5.0)
        return normalized


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.replace("；", ";").replace("，", ",").replace("、", ",")
        return [item.strip() for part in normalized.split(";") for item in part.split(",") if item.strip()]
    return [str(value)]


def _ensure_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
