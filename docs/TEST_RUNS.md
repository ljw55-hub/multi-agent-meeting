# Test Runs

This file records local end-to-end test runs, observed bottlenecks, and fixes.

## 2026-07-16 - `m-bfbd493bb46d`

### Input

- Title: 项目同步会议
- Language: zh
- File: `录音 (2).m4a`
- Audio path: `/app/uploads/m-bfbd493bb46d-f62f08a7-录音 (2).m4a`
- ASR provider: WhisperX
- ASR model: `/app/models/faster-whisper-small`
- Diarization model: `/app/models/pyannote/speaker-diarization-community-1`
- Alignment: disabled

### Result

- Final status: failed
- Failed stage: transcription
- Progress at failure: 10%
- Error:

```text
real audio transcription failed: cannot access local variable 'detected_language' where it is not associated with a value
```

### Timeline

All timestamps are UTC from container logs. Add 8 hours for China local time.

| Time | Module | Observation | Approx duration |
| --- | --- | --- | --- |
| 07:28:18 | Upload / queue | Meeting metadata created and worker pipeline started | - |
| 07:28:30 | WhisperX VAD / ASR pipeline | Voice activity detection started | 12s after pipeline start |
| 07:28:56 | Pyannote diarization | Diarization model loading started | 26s after VAD start |
| 07:30:52 | TranscriptionAgent | First transcription attempt failed on `detected_language` | 154s from pipeline start |
| 07:30:52 | Meeting graph | LangGraph path fell back to manual pipeline | - |
| 07:30:56 | WhisperX VAD / ASR pipeline | Manual fallback transcription started | 4s after fallback |
| 07:31:21 | Pyannote diarization | Diarization model loading started again | 25s after fallback ASR start |
| 07:33:19 | TranscriptionAgent | Manual fallback failed on the same variable issue | 143s from fallback start |
| 07:33:19 | Worker | Job marked failed in PostgreSQL | 301s from upload to final failure |

### Module Cost Summary

This run failed before summary, action extraction, insight analysis, follow-up generation, vector-store persistence, or Feishu notification.

| Module | Status | Approx cost |
| --- | --- | --- |
| API upload and queue | completed | < 1s API side, about 12s until worker pipeline activity |
| WhisperX ASR + VAD, first attempt | failed later during result construction | about 26s until diarization began |
| Pyannote diarization, first attempt | completed enough to reach segment construction | about 116s from diarization load to failure |
| LangGraph fallback | triggered | immediate |
| WhisperX ASR + VAD, fallback attempt | failed later during result construction | about 25s until diarization began |
| Pyannote diarization, fallback attempt | completed enough to reach segment construction | about 118s from diarization load to failure |
| Summary Agent | not reached | 0s |
| Action Agent | not reached | 0s |
| Insight Agent | not reached | 0s |
| Follow-up Agent | not reached | 0s |
| Feishu/Jira integrations | not reached | 0s |

### Root Cause

`WHISPERX_ALIGNMENT_ENABLED=false` skips the alignment branch. The code previously assigned `detected_language` only inside the alignment branch, but later used it when building `TranscriptResult`.

### Fix

`detected_language = result.get("language") or language` is now assigned immediately after ASR transcription, before the optional alignment branch.

Additional fine-grained timing logs were added for future runs:

- `transcription.asr_load`
- `transcription.audio_load`
- `transcription.asr`
- `transcription.alignment`
- `transcription.diarization`
- `transcription.segment_build`

## 2026-07-16 - `m-8c4c00bbeca1`

### Result

- Final status: completed
- Main issue: speaker diarization was executed, but all transcript segments were displayed as the first participant.
- Stored speakers in transcript: only `Zhang San`
- Expected speakers: two participants

### Diagnosis

Raw pyannote diarization was tested directly against the uploaded audio and returned two speaker labels:

- `SPEAKER_00`
- `SPEAKER_01`

The raw diarization output contained 46 speaker turns, so the diarization model itself did identify two speakers.

The actual problem was the post-processing step. Since `WHISPERX_ALIGNMENT_ENABLED=false`, the ASR output only had a few long transcript segments. Those long segments can span multiple speakers. Passing long unaligned segments through the default speaker assignment caused each long segment to be assigned to a single dominant speaker, and the participant mapper then displayed all segments as the first participant.

### Fix

When alignment is disabled, the transcription pipeline now uses pyannote speaker turns to split long ASR segments by time before building `TranscriptSegment` objects.

Trade-off:

- This gives visible speaker separation without requiring the large Chinese alignment model.
- Text splitting is approximate because there are no word-level timestamps.
- For production-grade word-level speaker assignment, enable WhisperX alignment with a local Chinese wav2vec2 align model.
