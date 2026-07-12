# Local Development Guide

This guide explains how to run Multi-Agent Meeting Assistant locally and verify the main service flow.

## Prerequisites

- Docker Desktop
- Docker Compose
- An OpenAI-compatible LLM API key if real model output is required

Check the local Docker environment:

```bash
docker --version
docker compose version
```

## Start Services

Run from the project root:

```bash
docker compose up -d --build
```

The compose stack starts:

- `multi-agent-meeting-api`: FastAPI backend
- `multi-agent-meeting-worker`: Redis queue worker for audio processing
- `multi-agent-meeting-postgres`: PostgreSQL database
- `multi-agent-meeting-redis`: Redis service
- `multi-agent-meeting-chromadb`: ChromaDB vector database

Check service status:

```bash
docker compose ps
```

## Open Web Console

```text
http://localhost:8000/ui
```

The web console is the fastest way to verify the full flow. It can create a meeting, upload audio, poll progress, render the final report, record microphone audio through WebSocket, and search ChromaDB meeting memory.

## Open API Docs

Swagger UI:

```text
http://localhost:8000/docs
```

Health check:

```text
http://localhost:8000/health
```

Expected response:

```json
{"status": "ok"}
```

## Run Demo Flow

```bash
curl -X POST http://localhost:8000/api/v1/meeting/demo/demo
```

Read the result:

```bash
curl http://localhost:8000/api/v1/meeting/demo/report
```

## Upload Audio

Use a URL-safe meeting id. Avoid slashes.

```bash
curl -X POST "http://localhost:8000/api/v1/meeting/meeting-001/upload?language=zh" \
  -F "file=@meeting.m4a;type=audio/x-m4a"
```

Check progress:

```bash
curl http://localhost:8000/api/v1/meeting/meeting-001/status
```

Read the final report:

```bash
curl http://localhost:8000/api/v1/meeting/meeting-001/report
```

Export the final report as Markdown:

```bash
curl http://localhost:8000/api/v1/meeting/meeting-001/export.md
```

List recent meetings:

```bash
curl http://localhost:8000/api/v1/meetings
```

List extracted action items:

```bash
curl "http://localhost:8000/api/v1/action-items?status=pending"
```

Update an action item status:

```bash
curl -X PATCH http://localhost:8000/api/v1/action-items/act-12345678 \
  -H "Content-Type: application/json" \
  -d "{\"status\":\"completed\"}"
```

## Stream Audio

The service exposes a chunked WebSocket transcription endpoint:

```text
ws://localhost:8000/ws/transcription/meeting-001
```

Recommended message flow:

```json
{"type":"config","language":"zh","audio_file_name":"meeting.webm","min_flush_bytes":512000}
```

Then send binary audio chunks from the client. The server returns `buffered` events while bytes are being received.

Request a partial transcription snapshot:

```json
{"type":"flush"}
```

Finish the stream and run the complete meeting pipeline:

```json
{"type":"stop"}
```

The server then pushes `transcript`, `summary`, `actions`, `insights`, `followup`, and `completed` events.

## Search Meeting Memory

After a meeting finishes, the service writes meeting memory into ChromaDB.

```bash
curl "http://localhost:8000/api/v1/meeting/search?query=项目上线 张三&limit=5"
```

## Database Checks

List tables:

```bash
docker compose exec -T postgres psql -U postgres -d meeting_assistant -c "\dt"
```

Check processing status:

```bash
docker compose exec -T postgres psql -U postgres -d meeting_assistant -c "select meeting_id, status, stage, progress, message, updated_at from meeting_statuses order by updated_at desc limit 10;"
```

Check stored reports:

```bash
docker compose exec -T postgres psql -U postgres -d meeting_assistant -c "select meeting_id, created_at, updated_at from meeting_results order by updated_at desc limit 10;"
```

## Stop Services

```bash
docker compose down
```

This stops containers but keeps Docker volumes by default.
