# Architecture

## Overview

```text
Client
  -> Web Console / REST API / WebSocket Gateway
  -> LangGraph Meeting Pipeline
     -> Transcription Agent
     -> Summary Agent
     -> Action Agent
     -> Insight Agent
     -> Follow-up Agent
  -> PostgreSQL / Redis / ChromaDB
```

## Layers

### 1. Access Layer

FastAPI provides three entry points:

- Web console at `/ui` for browser-based operation.
- REST API for meeting creation, audio upload, status polling, report reading, and memory search.
- WebSocket endpoints for audio streaming and staged result push.
- Redis queue producer for uploaded audio processing jobs.

Core files:

```text
src/main.py
src/api/routes.py
web/
```

### 2. Orchestration Layer

The meeting workflow is orchestrated with LangGraph. The graph keeps a shared state object and passes it through Agent nodes.

The execution pattern is:

```text
Transcription
  -> [Summary, Action, Insight]
  -> Follow-up
```

Core file:

```text
src/graph/meeting_graph.py
```

### 3. Agent Layer

The project implements five Agents:

- `TranscriptionAgent`: converts audio into timestamped transcript segments.
- `SummaryAgent`: generates structured topics, decisions, and next steps.
- `ActionAgent`: extracts owners, tasks, deadlines, and priorities.
- `InsightAgent`: computes speaker statistics, sentiment, highlights, and efficiency signals.
- `FollowUpAgent`: creates the final report and optionally pushes follow-up artifacts.

Core directory:

```text
src/agents/
```

### 4. Model Layer

Pydantic models define the structured contract between Agents and API responses:

- `TranscriptResult`
- `MeetingSummary`
- `ActionResult`
- `MeetingInsight`
- `FollowUpResult`

Core file:

```text
src/models/schemas.py
```

### 5. Integration Layer

Integration modules adapt external capabilities:

- OpenAI-compatible LLM calls.
- Optional Jira task creation.
- Optional Feishu task and message push.
- Optional SMTP report delivery.

Core directory:

```text
src/integrations/
```

### 6. Storage Layer

Persistent storage is split by responsibility:

- PostgreSQL stores meeting metadata, processing status, and final reports.
- PostgreSQL stores extracted action items in a dedicated task table for filtering and status updates.
- ChromaDB stores vectorized meeting memories for semantic search.
- Redis stores background meeting jobs consumed by the worker service.

Core directory:

```text
src/storage/
```

## Runtime Flow

1. A user creates a meeting from the web console or REST API.
2. For uploaded audio, the API stores the file and enqueues a Redis job.
3. The worker consumes the job and runs the meeting pipeline.
4. For WebSocket audio, the API can still run the stream pipeline directly.
5. Transcription Agent converts audio into structured transcript segments.
6. Summary, Action, and Insight Agents process the transcript.
7. Follow-up Agent creates the report and optional external follow-up artifacts.
8. The final report is stored in PostgreSQL and meeting memory is stored in ChromaDB.
9. Extracted action items are synchronized into the dedicated action item table.
10. The user reads the report and manages action status through the web console or API.

## Fault Tolerance

The service includes several fallbacks:

- LLM calls have timeout, retry, and deterministic fallback behavior.
- The graph has a manual async pipeline fallback if LangGraph execution fails.
- External Jira, Feishu, and SMTP integrations are disabled unless configured.
- Faster-Whisper is the default CPU-friendly ASR path, while WhisperX remains an optional advanced mode.
