# Architecture Standards

## System Overview

### Technology Choices
| Component | Technology | Rationale |
|-----------|------------|-----------|
| Frontend | React + TypeScript + Vite | Fast dev, type safety |
| Backend | FastAPI (Python) | Async, modern, easy AI integration |
| Database | Supabase | PostgreSQL + Vector, auth included |
| LLM | OpenAI GPT-4o | Best reasoning, cost-effective |
| TTS | Edge TTS | Free, high quality |
| STT | Whisper API | Best accuracy |
| Real-time | WebSocket | Low latency |

## Architecture Layers

### Presentation Layer (Frontend)
- React components (dumb UI)
- Custom hooks (stateful logic)
- Services (API communication)

### Application Layer (Backend)
- FastAPI routers (HTTP + WebSocket)
- Services (business logic)
- Orchestrator (interview state machine)

### Data Layer
- Supabase (persistent storage)
- Redis (not used - no caching needed yet)

## Design Decisions

### Separations
- **API vs WebSocket**: REST for CRUD, WebSocket for interview session
- **Frontend state**: Local for UI, server-driven for data
- **Voice handling**: Frontend records, backend transcribes

### Trade-offs
- **Edge TTS vs 11Labs**: Free/paid trade-off, quality acceptable
- **Whisper API vs Browser STT**: Accuracy over privacy for MVP
- **Supabase vs Custom DB**: Speed of setup over flexibility

## Scalability Considerations

### Current Limits
- Single candidate per interview session
- No concurrent interviews (future: queue system)
- In-memory state for active interviews

### Future Scaling
- Interview state in database, not memory
- Background job queue for TTS generation
- CDN for static assets
- Multiple WebSocket servers with Redis pub/sub

## Security

### API Keys
- OpenAI: environment variable only
- Supabase: environment variable only
- No keys in frontend code

### WebSocket
- Interview ID as session key
- Validate ownership for access control (future)

## Deployment

### Frontend
- Vite build to static files
- Any static host (Vercel, Netlify, S3)

### Backend
- Python/uvicorn
- ASGI server (gunicorn for production)
- Supabase as managed service

### Environment
- Development: local .env
- Production: environment variables only