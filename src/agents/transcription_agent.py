from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from ..models import MeetingStatus, TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptionAgent:
    """Pipeline entry node.

    If audio bytes are provided, the agent tries to transcribe them with
    Faster-Whisper. Without audio, it returns a deterministic demo transcript so
    the rest of the multi-agent pipeline remains easy to demonstrate.
    """

    _model: Any | None = None
    _model_config: tuple[str, str, str] | None = None

    @staticmethod
    def runtime_status() -> dict[str, Any]:
        provider = os.getenv("ASR_PROVIDER", "faster_whisper").lower()
        whisperx_available = _module_available("whisperx")
        pyannote_available = _module_available("pyannote.audio")
        hf_token_configured = bool(os.getenv("HF_TOKEN", "").strip())
        diarization_enabled = os.getenv("DIARIZATION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        ready = provider == "faster_whisper" or (
            provider == "whisperx"
            and whisperx_available
            and (not diarization_enabled or (pyannote_available and hf_token_configured))
        )
        return {
            "provider": provider,
            "ready": ready,
            "faster_whisper_available": _module_available("faster_whisper"),
            "whisperx_available": whisperx_available,
            "pyannote_available": pyannote_available,
            "diarization_enabled": diarization_enabled,
            "hf_token_configured": hf_token_configured,
            "model": os.getenv("WHISPERX_MODEL" if provider == "whisperx" else "ASR_MODEL_SIZE", "tiny"),
            "device": os.getenv("WHISPERX_DEVICE" if provider == "whisperx" else "ASR_DEVICE", "cpu"),
        }

    async def transcribe_bytes(
        self,
        meeting_id: str,
        audio_data: bytes,
        audio_file_name: str = "",
        language: str = "zh",
    ) -> TranscriptResult:
        """Transcribe an in-memory audio buffer.

        This method is used by the WebSocket streaming endpoint. It intentionally
        keeps the same ASR path as the batch pipeline so streaming and upload
        transcription produce consistent results.
        """
        return await self._transcribe_audio(
            meeting_id=meeting_id,
            audio_data=audio_data,
            audio_file_name=audio_file_name,
            language=language,
        )

    async def process(self, state: dict) -> dict:
        meeting_id = state["meeting_id"]
        state["status"] = MeetingStatus.TRANSCRIBING.value

        audio_data = state.get("audio_data") or b""
        if audio_data:
            try:
                transcript = await self._transcribe_audio(
                    meeting_id=meeting_id,
                    audio_data=audio_data,
                    audio_file_name=state.get("audio_file_name", ""),
                    language=state.get("language", "zh"),
                )
            except Exception as exc:
                logger.warning("Audio transcription failed, using demo transcript: %s", exc)
                state["errors"] = state.get("errors", []) + [f"audio transcription failed: {exc}"]
                transcript = self._demo_transcript(meeting_id)
        else:
            transcript = self._demo_transcript(meeting_id)

        state["transcript"] = transcript
        state["transcript_text"] = "\n".join(
            f"[{seg.start:.1f}s-{seg.end:.1f}s] {seg.speaker}: {seg.text}"
            for seg in transcript.segments
        )
        return state

    async def _transcribe_audio(
        self,
        meeting_id: str,
        audio_data: bytes,
        audio_file_name: str,
        language: str,
    ) -> TranscriptResult:
        provider = os.getenv("ASR_PROVIDER", "faster_whisper").lower()
        if provider not in {"faster_whisper", "whisperx"}:
            raise RuntimeError(f"unsupported ASR_PROVIDER: {provider}")

        suffix = Path(audio_file_name).suffix or ".wav"
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(audio_data)
                temp_path = temp_file.name

            if provider == "whisperx":
                return await asyncio.to_thread(
                    self._transcribe_file_whisperx,
                    meeting_id,
                    temp_path,
                    language,
                )

            return await asyncio.to_thread(
                self._transcribe_file,
                meeting_id,
                temp_path,
                language,
            )
        finally:
            if temp_path:
                try:
                    Path(temp_path).unlink(missing_ok=True)
                except OSError:
                    logger.debug("Failed to remove temporary audio file: %s", temp_path)

    @classmethod
    def _get_model(cls) -> Any:
        model_size = _model_reference()
        device = os.getenv("ASR_DEVICE", "cpu")
        compute_type = os.getenv("ASR_COMPUTE_TYPE", "int8")
        config = (model_size, device, compute_type)
        if cls._model is not None and cls._model_config == config:
            return cls._model

        from faster_whisper import WhisperModel

        cls._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        cls._model_config = config
        return cls._model

    @classmethod
    def _transcribe_file(cls, meeting_id: str, path: str, language: str) -> TranscriptResult:
        model = cls._get_model()
        segments_iter, info = model.transcribe(
            path,
            language=language if language in {"zh", "en"} else None,
            vad_filter=True,
            beam_size=5,
        )

        segments = [
            TranscriptSegment(
                speaker="Speaker 1",
                text=segment.text.strip(),
                start=float(segment.start),
                end=float(segment.end),
                confidence=_segment_confidence(segment),
            )
            for segment in segments_iter
            if segment.text.strip()
        ]

        return TranscriptResult(
            meeting_id=meeting_id,
            segments=segments,
            language=getattr(info, "language", language) or language,
            duration_seconds=float(getattr(info, "duration", 0.0) or 0.0),
            full_text="\n".join(f"{segment.speaker}: {segment.text}" for segment in segments),
        )

    @classmethod
    def _transcribe_file_whisperx(cls, meeting_id: str, path: str, language: str) -> TranscriptResult:
        try:
            import whisperx
        except ImportError as exc:
            raise RuntimeError("whisperx is not installed; install optional WhisperX dependencies first") from exc

        device = os.getenv("WHISPERX_DEVICE", os.getenv("ASR_DEVICE", "cpu"))
        compute_type = os.getenv("WHISPERX_COMPUTE_TYPE", os.getenv("ASR_COMPUTE_TYPE", "int8"))
        model_name = os.getenv("WHISPERX_MODEL", os.getenv("ASR_MODEL_SIZE", "tiny"))
        batch_size = int(os.getenv("WHISPERX_BATCH_SIZE", "8"))
        hf_token = os.getenv("HF_TOKEN", "")
        diarize_enabled = os.getenv("DIARIZATION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

        model = whisperx.load_model(model_name, device=device, compute_type=compute_type, language=language)
        audio = whisperx.load_audio(path)
        result = model.transcribe(audio, batch_size=batch_size, language=language if language in {"zh", "en"} else None)

        detected_language = result.get("language") or language
        align_model, metadata = whisperx.load_align_model(language_code=detected_language, device=device)
        aligned = whisperx.align(
            result.get("segments", []),
            align_model,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )

        final_result = aligned
        if diarize_enabled and hf_token:
            diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
            diarized = diarize_model(audio)
            final_result = whisperx.assign_word_speakers(diarized, aligned)

        segments = []
        for index, raw in enumerate(final_result.get("segments", []), start=1):
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            segments.append(
                TranscriptSegment(
                    speaker=str(raw.get("speaker") or f"Speaker {index}"),
                    text=text,
                    start=float(raw.get("start", 0.0) or 0.0),
                    end=float(raw.get("end", 0.0) or 0.0),
                    confidence=0.95,
                )
            )

        duration = max((segment.end for segment in segments), default=0.0)
        return TranscriptResult(
            meeting_id=meeting_id,
            segments=segments,
            language=detected_language,
            duration_seconds=duration,
            full_text="\n".join(f"{segment.speaker}: {segment.text}" for segment in segments),
        )

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


def _segment_confidence(segment: Any) -> float:
    avg_logprob = getattr(segment, "avg_logprob", None)
    if isinstance(avg_logprob, (int, float)):
        return max(0.0, min(1.0, 1.0 + float(avg_logprob)))
    return 0.95


def _model_reference() -> str:
    model_path = os.getenv("ASR_MODEL_PATH", "").strip()
    if model_path:
        return model_path

    model_size = os.getenv("ASR_MODEL_SIZE", "tiny").strip() or "tiny"
    if os.getenv("ASR_AUTO_DOWNLOAD", "true").lower() in {"1", "true", "yes", "on"}:
        local_dir = Path(os.getenv("ASR_MODEL_DIR", f"/app/models/faster-whisper-{model_size}"))
        if model_size == "tiny":
            _ensure_faster_whisper_tiny(local_dir)
            return str(local_dir)
    return model_size


def _module_available(module_name: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _ensure_faster_whisper_tiny(local_dir: Path) -> None:
    required_files = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
    if all((local_dir / file_name).is_file() and (local_dir / file_name).stat().st_size > 0 for file_name in required_files):
        return

    import httpx

    endpoint = os.getenv("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
    repo = "Systran/faster-whisper-tiny"
    local_dir.mkdir(parents=True, exist_ok=True)
    for file_name in required_files:
        target = local_dir / file_name
        if target.is_file() and target.stat().st_size > 0:
            continue
        url = f"{endpoint}/{repo}/resolve/main/{file_name}"
        temp_target = target.with_suffix(target.suffix + ".download")
        logger.info("Downloading ASR model file: %s", url)
        with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
            response.raise_for_status()
            with temp_target.open("wb") as output:
                for chunk in response.iter_bytes():
                    if chunk:
                        output.write(chunk)
        temp_target.replace(target)
