# Backend — Claude Instructions

Always read these skill files before any backend task:
- .claude/Skills/backend.md
- .claude/Skills/architecture.md
- .claude/Skills/realtime.md
- .claude/Skills/voice-ai.md
- .claude/Skills/performance.md
- .claude/Skills/product-thinking.md

## Stack
FastAPI + Python + Pydantic v2 + Supabase + OpenAI GPT-4o + Whisper + Edge TTS

## Project Structure
app/
├── main.py              # App entry, router registration
├── config.py            # Settings via environment variables
├── supabase_client.py   # DB client
├── routers/             # Route handlers (HTTP + WebSocket)
├── services/            # Business logic
├── models/              # Pydantic schemas
└── utils/               # Helpers

## API Standards
- Async-first: all I/O must be async
- FastAPI Depends for dependency injection
- Pydantic v2 for all input/output validation
- Router → Service → Data flow strictly
- REST: GET/POST/PUT/DELETE with proper status codes
- No nested routes beyond 2 levels

## WebSocket (from realtime.md)
- Namespace: /ws/interview/{interview_id}
- Message format: JSON with type / content / data fields
- Lifecycle: connect → validate → init → exchange → disconnect
- Single client per interview session
- Graceful disconnect handling

## Services
- InterviewOrchestrator: 5-phase state machine (background → project1 → project2 → technical → behavioral)
- ResumeParser: GPT-4o Vision for document extraction
- QuestionRetriever: Vector similarity via Supabase
- VoiceService: Whisper for STT, Edge TTS for speech

## Database (Supabase)
- Tables: candidates, interviews, evaluations, ml_questions
- Always filter by candidate_id or interview_id
- Use RPC for complex queries
- Index on candidate_id, interview_id

## Voice (from voice-ai.md)
- STT: Whisper API, model whisper-1, language "en", temperature 0.0
- TTS: Edge TTS, voice en-US-JennyNeural, output MP3
- Transmit audio as base64 over WebSocket

## Error Handling
- HTTPException for all HTTP errors
- Consistent error response format
- Log with appropriate level (info / warning / error)
- Never expose internal errors to client

## Performance (from performance.md)
- REST endpoints: < 200ms (excluding DB)
- WebSocket messages: < 100ms processing
- TTS: < 3 seconds
- STT: < 3 seconds
- No blocking calls in async context

## Security
- All API keys via environment variables only
- No keys in code or frontend
- Validate interview ownership before access
