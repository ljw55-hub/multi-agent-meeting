# Multi-Agent Meeting Assistant

Multi-Agent Meeting Assistant is a backend service for turning meeting audio into structured meeting records, action items, insights, and follow-up artifacts.

The system uses FastAPI as the service layer, Faster-Whisper for speech transcription, LangGraph for multi-agent orchestration, PostgreSQL for persistent storage, and ChromaDB for semantic retrieval over meeting history.

## Features

- Audio upload and asynchronous meeting processing
- Faster-Whisper based speech transcription
- Optional WhisperX alignment and pyannote speaker diarization
- LangGraph pipeline with dedicated agents:
  - Transcription Agent
  - Summary Agent
  - Action Agent
  - Insight Agent
  - Follow-up Agent
- OpenAI-compatible LLM integration, including SiliconFlow
- Configurable timeout, retry, fallback, and Agent parallelism
- PostgreSQL persistence for meeting metadata, status, and reports
- Dedicated action item table with editable assignee, task, deadline, priority, context, and status tracking
- ChromaDB vector storage for meeting memory search
- Redis-backed background worker for audio processing jobs
- REST API, full-result WebSocket, and chunked transcription WebSocket entry points
- Optional Jira, Feishu, and SMTP follow-up integrations
- Docker Compose based local deployment

## Architecture

```text
Client
  -> FastAPI API Gateway
  -> LangGraph Meeting Pipeline
     -> Transcription Agent
     -> Summary Agent
     -> Action Agent
     -> Insight Agent
     -> Follow-up Agent
  -> PostgreSQL / ChromaDB
```

## Quick Start

```bash
docker compose up -d --build
```

Open:

- Web console: http://localhost:8000/ui
- API root: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The web console supports meeting creation, audio upload, progress tracking, report viewing, microphone streaming, and ChromaDB memory search.
The Action Board can be used to review extracted tasks, edit task details, and preserve manual status changes across later report synchronization.

Run a built-in demo meeting:

```bash
curl -X POST http://localhost:8000/api/v1/meeting/demo/demo
```

Upload an audio file:

```bash
curl -X POST "http://localhost:8000/api/v1/meeting/meeting-001/upload?language=zh" \
  -F "file=@meeting.m4a;type=audio/x-m4a"
```

Check processing status:

```bash
curl http://localhost:8000/api/v1/meeting/meeting-001/status
```

Read the final report:

```bash
curl http://localhost:8000/api/v1/meeting/meeting-001/report
```

Stream audio through WebSocket:

```text
ws://localhost:8000/ws/transcription/meeting-001
```

Protocol:

```json
{"type":"config","language":"zh","audio_file_name":"meeting.webm"}
```

Then send binary audio chunks. Send `{"type":"flush"}` to receive a partial transcript snapshot. Send `{"type":"stop"}` to finalize transcription and run the full multi-agent pipeline.

Search historical meeting memory:

```bash
curl "http://localhost:8000/api/v1/meeting/search?query=项目上线 张三&limit=5"
```

## Configuration

Copy `.env.example` to `.env` and update values as needed.

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_MODEL_NAME=deepseek-ai/DeepSeek-V4-Flash
OPENAI_API_KEY=your-api-key
```

Stable development settings:

```env
LLM_TIMEOUT_SECONDS=180
LLM_MAX_RETRIES=2
LLM_PARALLEL_AGENTS=false
```

ASR settings:

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

WhisperX speaker diarization can be enabled when the optional dependencies and HuggingFace token are available:

```env
ASR_PROVIDER=whisperx
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
DIARIZATION_ENABLED=true
HF_TOKEN=your-huggingface-token
```

External follow-up integrations are disabled unless configured:

```env
JIRA_SERVER=
JIRA_EMAIL=
JIRA_API_TOKEN=
JIRA_PROJECT_KEY=MEET

FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_WEBHOOK_URL=

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

## Persistence

PostgreSQL stores:

- `meetings`: meeting metadata
- `meeting_statuses`: asynchronous processing state
- `meeting_results`: structured meeting reports
- `action_items`: extracted tasks with owners, priority, deadline, and status

ChromaDB stores vectorized meeting memory for semantic search.

Docker volumes are used for local persistence:

- `postgres_data`
- `chroma_data`
- `asr_models`

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Local Development Guide](docs/TUTORIAL.md)
- [Roadmap](docs/ROADMAP.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
