from __future__ import annotations

import logging

from ..models import MeetingStatus, TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)

class TranscriptionAgent:
    """Pipeline entry node. Real WhisperX can be plugged in later."""

    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        state["status"] = MeetingStatus.TRANSCRIBING.value

        if state.get("audio_data"):
            logger.info("Audio bytes received, using placeholder transcription in v0.")

        transcript = self._demo_transcript(meeting_id)
        state["transcript"] = transcript
        state["transcript_text"] = "\n".join(
            f"[{seg.start:.1f}s-{seg.end:.1f}s] {seg.speaker}: {seg.text}"
            for seg in transcript.segments
        )
        return state

    @staticmethod
    def _demo_transcript(meeting_id: str) -> TranscriptResult:
        segments = [
            TranscriptSegment(
                speaker="张总",
                text="我们开始今天的 Q3 预算评审会，先请李明汇报目前预算执行情况。",
                start=0.0,
                end=7.5,
            ),
            TranscriptSegment(
                speaker="李明",
                text="截至目前 Q2 预算执行率为 87%，研发投入占比最高，达到 42%。",
                start=8.0,
                end=15.2,
            ),
            TranscriptSegment(
                speaker="李明",
                text="Q3 建议将预算上调 15%，主要增加在 AI 基础设施和人才招聘方面。",
                start=15.4,
                end=23.0,
            ),
            TranscriptSegment(
                speaker="王芳",
                text="人才招聘这块，我建议重点招聘 3 名高级算法工程师，预算大概每人年薪 80 万。",
                start=23.2,
                end=31.0,
            ),
            TranscriptSegment(
                speaker="张总",
                text="可以。李明负责整理 Q3 详细预算方案，下周五前提交给我审批。",
                start=31.5,
                end=38.0,
            ),
            TranscriptSegment(
                speaker="张总",
                text="王芳负责拟定招聘 JD，本周三前完成。赵伟跟进服务器采购，下周一给出采购方案。",
                start=38.2,
                end=47.0,
            ),
            TranscriptSegment(
                speaker="赵伟",
                text="收到，我已经在对比几家供应商，预计下周一可以给出采购方案。",
                start=47.3,
                end=54.0,
            ),
        ]
        return TranscriptResult(
            meeting_id=meeting_id,
            segments=segments,
            duration_seconds=54.0,
            full_text="\n".join(f"{s.speaker}: {s.text}" for s in segments),
        )
