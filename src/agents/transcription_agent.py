from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..models import MeetingStatus, TranscriptResult, TranscriptSegment
from ..observability import log_event

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
            "diarization_min_speakers": _optional_int_env("DIARIZATION_MIN_SPEAKERS"),
            "diarization_max_speakers": _optional_int_env("DIARIZATION_MAX_SPEAKERS"),
            "diarization_map_participants": os.getenv("DIARIZATION_MAP_PARTICIPANTS", "true").lower()
            in {"1", "true", "yes", "on"},
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
        participants: list[str] | None = None,
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
            participants=participants,
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
                    participants=state.get("participants", []),
                )
            except Exception as exc:
                logger.exception("Audio transcription failed")
                state["errors"] = state.get("errors", []) + [f"audio transcription failed: {exc}"]
                raise RuntimeError(f"real audio transcription failed: {exc}") from exc
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
        participants: list[str] | None = None,
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
                    participants or [],
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
        beam_size = int(os.getenv("ASR_BEAM_SIZE", "5"))
        best_of = int(os.getenv("ASR_BEST_OF", "5"))
        vad_filter = os.getenv("ASR_VAD_FILTER", "true").lower() in {"1", "true", "yes", "on"}
        initial_prompt = os.getenv("ASR_INITIAL_PROMPT", "").strip() or None
        condition_on_previous_text = os.getenv("ASR_CONDITION_ON_PREVIOUS_TEXT", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        segments_iter, info = model.transcribe(
            path,
            language=language if language in {"zh", "en"} else None,
            vad_filter=vad_filter,
            beam_size=beam_size,
            best_of=best_of,
            initial_prompt=initial_prompt,
            condition_on_previous_text=condition_on_previous_text,
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
    def _transcribe_file_whisperx(
        cls,
        meeting_id: str,
        path: str,
        language: str,
        participants: list[str] | None = None,
    ) -> TranscriptResult:
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
        participants = [item.strip() for item in (participants or []) if item and item.strip()]

        model_started = time.perf_counter()
        model = whisperx.load_model(model_name, device=device, compute_type=compute_type, language=language)
        log_event(
            logger,
            "transcription_substage_completed",
            "WhisperX ASR model loaded",
            meeting_id=meeting_id,
            stage="transcription.asr_load",
            agent="TranscriptionAgent",
            status="completed",
            duration_ms=(time.perf_counter() - model_started) * 1000,
        )

        audio_started = time.perf_counter()
        audio = whisperx.load_audio(path)
        log_event(
            logger,
            "transcription_substage_completed",
            "Audio loaded for WhisperX",
            meeting_id=meeting_id,
            stage="transcription.audio_load",
            agent="TranscriptionAgent",
            status="completed",
            duration_ms=(time.perf_counter() - audio_started) * 1000,
        )

        asr_started = time.perf_counter()
        result = model.transcribe(audio, batch_size=batch_size, language=language if language in {"zh", "en"} else None)
        log_event(
            logger,
            "transcription_substage_completed",
            "WhisperX ASR completed",
            meeting_id=meeting_id,
            stage="transcription.asr",
            agent="TranscriptionAgent",
            status="completed",
            duration_ms=(time.perf_counter() - asr_started) * 1000,
        )

        detected_language = result.get("language") or language
        alignment_enabled = os.getenv("WHISPERX_ALIGNMENT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        aligned = result
        if alignment_enabled:
            align_started = time.perf_counter()
            align_model_name = os.getenv("WHISPERX_ALIGN_MODEL") or None
            align_model_dir = os.getenv("WHISPERX_ALIGN_MODEL_DIR") or None
            align_cache_only = os.getenv("WHISPERX_ALIGN_LOCAL_ONLY", "false").lower() in {"1", "true", "yes", "on"}
            try:
                align_model, metadata = whisperx.load_align_model(
                    language_code=detected_language,
                    device=device,
                    model_name=align_model_name,
                    model_dir=align_model_dir,
                    model_cache_only=align_cache_only,
                )
                aligned = whisperx.align(
                    result.get("segments", []),
                    align_model,
                    metadata,
                    audio,
                    device,
                    return_char_alignments=False,
                )
                log_event(
                    logger,
                    "transcription_substage_completed",
                    "WhisperX alignment completed",
                    meeting_id=meeting_id,
                    stage="transcription.alignment",
                    agent="TranscriptionAgent",
                    status="completed",
                    duration_ms=(time.perf_counter() - align_started) * 1000,
                )
            except Exception as exc:
                if os.getenv("WHISPERX_ALIGNMENT_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}:
                    raise
                logger.warning("WhisperX alignment failed; continuing with raw ASR segments: %s", exc)

        final_result = aligned
        if diarize_enabled:
            if not hf_token:
                raise RuntimeError("HF_TOKEN is required when DIARIZATION_ENABLED=true")
            try:
                diarize_started = time.perf_counter()
                from whisperx.diarize import DiarizationPipeline

                diarize_model = DiarizationPipeline(
                    model_name=os.getenv("DIARIZATION_MODEL_PATH") or None,
                    token=hf_token,
                    device=device,
                )
                diarize_kwargs = _diarization_kwargs(participants)
                diarized = diarize_model(audio, **diarize_kwargs)
                if alignment_enabled:
                    final_result = whisperx.assign_word_speakers(diarized, aligned)
                else:
                    final_result = {
                        **aligned,
                        "segments": _split_segments_by_diarization(
                            aligned.get("segments", []),
                            diarized,
                        ),
                    }
                log_event(
                    logger,
                    "transcription_substage_completed",
                    "Speaker diarization completed",
                    meeting_id=meeting_id,
                    stage="transcription.diarization",
                    agent="TranscriptionAgent",
                    status="completed",
                    duration_ms=(time.perf_counter() - diarize_started) * 1000,
                )
            except Exception as exc:
                if os.getenv("DIARIZATION_REQUIRED", "false").lower() in {"1", "true", "yes", "on"}:
                    raise
                logger.warning("speaker diarization failed; continuing with ASR segments only: %s", exc)

        segments_started = time.perf_counter()
        segments = []
        speaker_names: dict[str, str] = {}
        for index, raw in enumerate(final_result.get("segments", []), start=1):
            text = str(raw.get("text", "")).strip()
            if not text:
                continue
            raw_speaker = str(raw.get("speaker") or f"Speaker {index}")
            speaker = _display_speaker(raw_speaker, speaker_names, participants)
            segments.append(
                TranscriptSegment(
                    speaker=speaker,
                    text=text,
                    start=float(raw.get("start", 0.0) or 0.0),
                    end=float(raw.get("end", 0.0) or 0.0),
                    confidence=0.95,
                )
            )

        log_event(
            logger,
            "transcription_substage_completed",
            "Transcript segments built",
            meeting_id=meeting_id,
            stage="transcription.segment_build",
            agent="TranscriptionAgent",
            status="completed",
            duration_ms=(time.perf_counter() - segments_started) * 1000,
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


def _split_segments_by_diarization(
    asr_segments: list[dict[str, Any]],
    diarization: Any,
) -> list[dict[str, Any]]:
    turns = _diarization_turns(diarization)
    if not turns:
        return list(asr_segments)

    split_segments: list[dict[str, Any]] = []
    for segment in asr_segments:
        text = str(segment.get("text", "")).strip()
        start = float(segment.get("start", 0.0) or 0.0)
        end = float(segment.get("end", start) or start)
        if not text or end <= start:
            split_segments.append(segment)
            continue

        overlaps = _overlapping_turns(start, end, turns)
        if not overlaps:
            split_segments.append(segment)
            continue

        merged = _merge_adjacent_turns(overlaps)
        if len(merged) == 1:
            split_segments.append({**segment, "speaker": merged[0]["speaker"]})
            continue

        chunks = _split_text_by_durations(text, [item["duration"] for item in merged])
        for item, chunk in zip(merged, chunks, strict=False):
            if not chunk.strip():
                continue
            split_segments.append(
                {
                    **segment,
                    "speaker": item["speaker"],
                    "text": chunk.strip(),
                    "start": max(start, item["start"]),
                    "end": min(end, item["end"]),
                }
            )

    return split_segments


def _diarization_turns(diarization: Any) -> list[dict[str, float | str]]:
    try:
        rows = diarization.to_dict("records")
    except AttributeError:
        rows = list(diarization or [])

    turns: list[dict[str, float | str]] = []
    for row in rows:
        try:
            start = float(row.get("start", 0.0) or 0.0)
            end = float(row.get("end", start) or start)
            speaker = str(row.get("speaker") or "").strip()
        except AttributeError:
            continue
        if speaker and end > start:
            turns.append({"start": start, "end": end, "speaker": speaker, "duration": end - start})
    return sorted(turns, key=lambda item: (float(item["start"]), float(item["end"])))


def _overlapping_turns(
    start: float,
    end: float,
    turns: list[dict[str, float | str]],
) -> list[dict[str, float | str]]:
    overlaps: list[dict[str, float | str]] = []
    for turn in turns:
        overlap_start = max(start, float(turn["start"]))
        overlap_end = min(end, float(turn["end"]))
        duration = overlap_end - overlap_start
        if duration >= 0.15:
            overlaps.append(
                {
                    "start": overlap_start,
                    "end": overlap_end,
                    "speaker": str(turn["speaker"]),
                    "duration": duration,
                }
            )
    return overlaps


def _merge_adjacent_turns(
    turns: list[dict[str, float | str]],
    *,
    max_gap_s: float = 0.5,
) -> list[dict[str, float | str]]:
    merged: list[dict[str, float | str]] = []
    for turn in turns:
        if (
            merged
            and merged[-1]["speaker"] == turn["speaker"]
            and float(turn["start"]) - float(merged[-1]["end"]) <= max_gap_s
        ):
            merged[-1]["end"] = turn["end"]
            merged[-1]["duration"] = float(merged[-1]["duration"]) + float(turn["duration"])
        else:
            merged.append(dict(turn))
    return merged


def _split_text_by_durations(text: str, durations: list[float]) -> list[str]:
    if not durations:
        return [text]
    total = sum(max(duration, 0.0) for duration in durations)
    if total <= 0:
        return [text]

    chars = list(text)
    chunks: list[str] = []
    cursor = 0
    for index, duration in enumerate(durations):
        if index == len(durations) - 1:
            chunks.append("".join(chars[cursor:]))
            break
        remaining_chars = len(chars) - cursor
        remaining_ratio = max(duration, 0.0) / total
        take = max(1, min(remaining_chars - 1, round(len(chars) * remaining_ratio)))
        chunks.append("".join(chars[cursor : cursor + take]))
        cursor += take
    return chunks


def _segment_confidence(segment: Any) -> float:
    avg_logprob = getattr(segment, "avg_logprob", None)
    if isinstance(avg_logprob, (int, float)):
        return max(0.0, min(1.0, 1.0 + float(avg_logprob)))
    return 0.95


def _diarization_kwargs(participants: list[str]) -> dict[str, int]:
    kwargs: dict[str, int] = {}
    min_speakers = _optional_int_env("DIARIZATION_MIN_SPEAKERS")
    max_speakers = _optional_int_env("DIARIZATION_MAX_SPEAKERS")
    use_participant_count = os.getenv("DIARIZATION_USE_PARTICIPANT_COUNT", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if use_participant_count and participants:
        min_speakers = min_speakers or 1
        max_speakers = max_speakers or len(participants)
    if min_speakers:
        kwargs["min_speakers"] = min_speakers
    if max_speakers:
        kwargs["max_speakers"] = max_speakers
    return kwargs


def _display_speaker(raw_speaker: str, speaker_names: dict[str, str], participants: list[str]) -> str:
    map_participants = os.getenv("DIARIZATION_MAP_PARTICIPANTS", "true").lower() in {"1", "true", "yes", "on"}
    if not map_participants or not participants:
        return raw_speaker
    if raw_speaker not in speaker_names:
        index = len(speaker_names)
        speaker_names[raw_speaker] = participants[index] if index < len(participants) else raw_speaker
    return speaker_names[raw_speaker]


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


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
