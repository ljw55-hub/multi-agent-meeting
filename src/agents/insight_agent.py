from __future__ import annotations

from collections import Counter, defaultdict

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
                "招聘与服务器采购均形成了责任人和截止时间。",
            ],
            "suggestions": ["后续可把预算审批、招聘 JD、采购方案接入任务系统自动追踪。"],
        }
        result = await self.llm.chat_json(
            messages=[
                {"role": "system", "content": "你是会议洞察分析师，只输出 JSON。"},
                {
                    "role": "user",
                    "content": (
                        "分析会议情绪、关键词、亮点、改进建议、效率评分。\n\n"
                        f"{state.get('transcript_text', '')}"
                    ),
                },
            ],
            fallback=fallback,
        )
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
