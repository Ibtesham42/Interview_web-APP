# Backend Engineering Standards

## Architecture

### Framework
- **FastAPI** with Pydantic v2 for validation
- Async-first: all I/O operations are async
- Dependency injection via FastAPI's Depends

### Project Structure
```
app/
├── main.py           # App entry, router registration
├── config.py         # Settings (EnvironmentVariables)
├── supabase_client.py # DB client
├── routers/          # Route handlers (endpoints)
├── services/        # Business logic
├── models/          # Pydantic schemas
└── utils/           # Helpers
```

## API Design

### REST Endpoints
- Follow HTTP conventions: GET (read), POST (create), PUT (update), DELETE (remove)
- Return JSON with consistent structure
- Use status codes appropriately: 200, 201, 400, 401, 404, 500
- No nested routes beyond 2 levels: /api/resource/{id}/subresource

### WebSocket
- Namespace: /ws/interview/{interview_id}
- Message format: JSON with type/content/data fields
- Connection lifecycle: connect → auth → session → disconnect
- Reconnection: client handles reconnection on disconnect

## Database (Supabase)

### Schema
- candidates: Candidate profiles with parsed documents
- interviews: Interview sessions and state
- evaluations: Phase scores and feedback
- ml_questions: Vector-enabled question bank

### Queries
- Use Supabase client for all DB operations
- Prefer RPC functions for complex queries
- Always filter by relevant context (candidate_id, interview_id)

## Services

### Interview Orchestrator
- 5-phase state machine: background → project1 → project2 → technical → behavioral
- Phase transitions: automatic on answer submission
- State persistence: Supabase after each phase

### Resume Parser
- GPT-4o Vision for document extraction
- Extract: education, experience, projects, skills
- Store parsed sections for question generation

### Question Retriever
- Vector similarity for domain-specific questions
- Fallback: curated questions by domain
- No external embedding service - use Supabase vectors

### Voice Service
- Edge TTS for speech generation
- Whisper API for transcription
- No 11Labs - removed dependency

## Error Handling

- Use FastAPI's HTTPException for HTTP errors
- Custom exception handlers for consistent error format
- Log errors with appropriate level (info, warning, error)
- Never expose internal errors to client

## Performance

- Connection pooling via Supabase
- Async database operations
- Cached responses where appropriate
- No blocking calls in async context