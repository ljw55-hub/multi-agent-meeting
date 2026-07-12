# Troubleshooting

This document records common runtime issues and their fixes.

## Docker Desktop or WSL Cannot Start

### Symptom

Docker Desktop reports virtualization or WSL startup errors.

### Cause

Docker Desktop on Windows depends on WSL2 and hardware virtualization.

### Fix

Check:

```powershell
wsl --status
docker version
docker compose version
```

Make sure virtualization is enabled and Docker Desktop is running before starting the project.

## Meeting ID With Slashes Returns 404

### Symptom

Uploading with a meeting id like `2026/7/10` returns:

```json
{"detail": "Not Found"}
```

### Cause

The slash `/` is a URL path separator.

### Fix

Use URL-safe meeting ids:

```text
20260710
meeting-20260710-001
20260711-full-01
```

## LLM ReadTimeout

### Symptom

The service stays in an Agent stage for a long time. Logs show:

```text
LLM call failed, retrying: provider=openai model=... error=ReadTimeout
```

### Cause

External LLM services can be slow, rate-limited, or temporarily unavailable.

### Fix

Use stable development settings:

```env
LLM_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=2
LLM_PARALLEL_AGENTS=false
```

The system keeps Agent parallelism configurable because Summary, Action, and Insight can run independently after transcription, but external provider stability may vary.

## ASR Model Download Failed

### Symptom

The upload enters the transcription stage but does not move forward. Logs may show:

```text
Audio transcription failed, using demo transcript
```

### Cause

Faster-Whisper needs model files before transcribing audio. Default HuggingFace downloads can be unstable in some network environments.

### Fix

The project downloads the required `faster-whisper-tiny` files directly from the configured mirror and stores them in a persistent Docker volume.

Required files:

```text
config.json
model.bin
tokenizer.json
vocabulary.txt
```

Recommended ASR settings:

```env
ASR_PROVIDER=faster_whisper
ASR_MODEL_SIZE=tiny
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_AUTO_DOWNLOAD=true
ASR_MODEL_DIR=/app/models/faster-whisper-tiny
HF_ENDPOINT=https://hf-mirror.com
HF_HUB_DISABLE_XET=1
```

The Docker Compose service mounts:

```yaml
asr_models:/app/models
```

## ASR Works But Text Is Imperfect

### Symptom

The real audio is transcribed successfully, but a tiny model may output:

```text
請張三旅測
今晚完成項目上線
```

The intended sentence may be closer to:

```text
请张三测试，今晚完成项目上线
```

### Cause

`faster-whisper-tiny` is small and fast, but Chinese recognition quality is limited.

### Fix

Use a larger model when machine resources allow:

```env
ASR_MODEL_SIZE=base
```

or:

```env
ASR_MODEL_SIZE=small
```

Tradeoff:

```text
larger model -> better transcription -> slower and more memory
```

## Results Disappeared After API Restart

### Symptom

`/report` returns 404 after restarting the API container.

### Cause

In-memory Python dictionaries are cleared when the API process restarts.

### Fix

The project persists data in PostgreSQL:

```text
meetings
meeting_statuses
meeting_results
```

PostgreSQL data is stored in a Docker volume:

```text
postgres_data
```

## Vector Search Returns Nothing

### Symptom

The meeting completes, but search cannot find anything.

### Cause

The meeting result must be written to ChromaDB after processing completes.

### Fix

The service calls `upsert_meeting_memory()` after a meeting finishes.

Test retrieval:

```powershell
curl.exe -s "http://localhost:8000/api/v1/meeting/search?query=项目上线 张三&limit=5"
```

ChromaDB data is stored in:

```text
chroma_data
```

## Docker Volume Location

### Explanation

Database files are not stored as normal project files. Docker stores PostgreSQL, ChromaDB, Redis, and ASR model data in Docker volumes.

Useful commands:

```powershell
docker volume ls
docker volume inspect multi-agent-meeting_postgres_data
docker compose exec -T postgres psql -U postgres -d meeting_assistant -c "\dt"
```

Do not manually edit Docker volume files. Use SQL or API endpoints.

## Project Naming

The project uses:

```text
multi-agent-meeting
Multi-Agent Meeting Assistant
```

Container names:

```text
multi-agent-meeting-api
multi-agent-meeting-postgres
multi-agent-meeting-redis
multi-agent-meeting-chromadb
```
