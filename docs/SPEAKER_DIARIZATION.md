# Speaker Diarization

This project supports optional speaker diarization through WhisperX and pyannote.

## What It Does

The default `faster_whisper` path transcribes speech but cannot reliably identify different speakers. It labels all audio as `Speaker 1`.

When `ASR_PROVIDER=whisperx` and diarization is enabled, the pipeline can:

- transcribe the audio with WhisperX
- align transcript timestamps
- run pyannote speaker diarization
- assign each transcript segment to a speaker
- optionally map `SPEAKER_00`, `SPEAKER_01` to meeting participants by first appearance

## External Setup Required

You need a HuggingFace account and token.

1. Create or log in to HuggingFace.
2. Create an access token with model download permission.
3. Accept the required pyannote model terms on HuggingFace:
   - `pyannote/speaker-diarization-3.1`
   - `pyannote/segmentation-3.0`
4. Put the token in local `.env`:

```env
HF_TOKEN=your_huggingface_token
```

Do not commit `.env`.

## Docker Configuration

WhisperX and pyannote are optional because they install large ML dependencies.

Set these values in `.env`:

```env
INSTALL_WHISPERX=true
ASR_PROVIDER=whisperx
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
WHISPERX_BATCH_SIZE=8
DIARIZATION_ENABLED=true
DIARIZATION_USE_PARTICIPANT_COUNT=true
DIARIZATION_MAP_PARTICIPANTS=true
HF_TOKEN=your_huggingface_token
```

Then rebuild:

```powershell
docker compose up -d --build api worker
```

## Speaker Count

If the meeting has participants, the diarization pipeline uses the participant count as the maximum speaker count by default.

You can override it:

```env
DIARIZATION_MIN_SPEAKERS=2
DIARIZATION_MAX_SPEAKERS=2
```

For a two-person test meeting, setting both values to `2` usually gives more stable results.

## Name Mapping

pyannote returns labels like `SPEAKER_00`. If `DIARIZATION_MAP_PARTICIPANTS=true`, the project maps speakers to the meeting participants by first appearance:

```text
SPEAKER_00 -> first participant
SPEAKER_01 -> second participant
```

This is a practical product shortcut, not biometric identity recognition. It assumes the first detected speaker corresponds to the first participant entered in the meeting form.

## Current Limitation

CPU diarization is slow. For production use, run WhisperX/pyannote on a GPU worker or replace local ASR with a managed speech API that supports speaker diarization.
