# Performance Standards

## Frontend Performance

### Bundle Size
- Target: < 250KB gzipped (excluding vendor)
- Vendor: React, React Router (acceptable bulk)
- No animation libraries - CSS only
- Lazy load routes

### Runtime Performance
- 60fps animations (use transform/opacity)
- Virtualize long lists (not needed now)
- Memoize expensive computations
- Debounce rapid events (typing, resize)

### Render Optimization
- Memoize components with React.memo
- useCallback for event handlers
- useMemo for derived data
- Avoid unnecessary re-renders

## Backend Performance

### API Response Times
- REST endpoints: < 200ms (excluding DB)
- WebSocket messages: < 100ms processing
- TTS generation: < 3 seconds
- STT transcription: < 3 seconds

### Database
- Index on candidate_id, interview_id
- Query only needed fields
- No N+1 queries
- Connection pooling via Supabase

### Caching
- Not currently needed
- Future: Redis for active interview state
- Static content: CDN (future)

## Network Performance

### Audio
- Chunked recording (100ms slices)
- WebSocket binary for audio data
- Base64 for small payloads only
- Consider binary WebSocket (future)

### Latency Budget
| Operation | Target | Maximum |
|-----------|--------|---------|
| Page load | < 2s | 5s |
| API call | < 200ms | 500ms |
| Voice record | Real-time | - |
| STT | < 3s | 5s |
| TTS | < 3s | 5s |
| WebSocket | < 100ms | 200ms |

## Monitoring

### Key Metrics
- First Contentful Paint: < 1.5s
- Largest Contentful Paint: < 2.5s
- Time to Interactive: < 3s
- Cumulative Layout Shift: < 0.1

### Errors to Track
- API failure rate
- WebSocket disconnect rate
- Voice recording failure rate
- TTS/STT latency