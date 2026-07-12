# Roadmap

This roadmap describes planned product and engineering improvements for Multi-Agent Meeting Assistant.

## Phase 1: Reliable Local Service

Status: completed

- FastAPI service with REST and WebSocket entry points
- Docker Compose environment
- PostgreSQL, Redis, and ChromaDB services
- Faster-Whisper based ASR
- OpenAI-compatible LLM integration
- LangGraph meeting pipeline
- Status and report APIs

## Phase 2: Durable Processing

Status: completed

- Persist meeting metadata in PostgreSQL
- Persist processing status in PostgreSQL
- Persist structured meeting reports in PostgreSQL
- Store meeting memory in ChromaDB
- Add semantic meeting search API
- Add ASR model cache volume

## Phase 3: Frontend Console

Status: planned

Goals:

- Upload audio from a web page
- Show live processing progress
- Display transcript, summary, action items, insights, and follow-up result
- Search historical meetings
- Provide a clean operational UI for repeated use

## Phase 4: Production Task Execution

Status: planned

Goals:

- Move long-running audio processing to a worker process
- Use Redis or a queue service for task dispatch
- Add task cancellation and retry controls
- Add browser microphone UI for the chunked WebSocket transcription endpoint
- Add structured logs and request tracing

## Phase 5: Better ASR and Speaker Support

Status: planned

Goals:

- Support configurable ASR model sizes
- Package WhisperX optional dependencies in a GPU-oriented deployment image
- Add punctuation and text normalization
- Add user-editable transcript correction
- Persist original audio files in object storage

## Phase 6: Integrations

Status: planned

Goals:

- Export reports as Markdown, PDF, and DOCX
- Sync action items to Jira, Linear, or Feishu
- Send meeting summaries through email or webhook
- Add role-based access control for team usage

## Phase 7: Retrieval-Augmented Meeting Memory

Status: planned

Goals:

- Replace deterministic local embeddings with a stronger embedding provider
- Chunk long meetings into semantically meaningful segments
- Support cross-meeting question answering
- Retrieve related decisions, risks, and action items from historical meetings
