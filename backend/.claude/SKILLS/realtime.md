# Real-Time Communication Standards

## WebSocket Architecture

### Connection Flow
1. Client connects to /ws/interview/{interview_id}
2. Server validates interview exists and is active
3. Server sends init message with candidate info
4. Bidirectional message exchange during interview
5. Interview ends → connection closed

### Message Protocol
```typescript
interface WebSocketMessage {
  type: 'init' | 'question' | 'answer' | 'voice' | 'audio' |
        'evaluation' | 'phase_update' | 'empathy_nudge' |
        'voice_transcript' | 'interview_ended' | 'error';
  content?: string;
  phase?: number;
  data?: Record<string, unknown>;
  transcript?: string;
  audio?: string;  // Base64 encoded
}
```

## Server-Side

### Connection Manager
- Track active connections per interview
- Allow single client per interview (interviewer)
- Handle graceful disconnect
- No broadcast - single client per session

### Message Types

#### Outbound (Server → Client)
| Message | Trigger | Payload |
|---------|---------|---------|
| init | Connection | candidate_name, interview_id |
| question | New question | content, phase |
| audio | TTS ready | base64 audio |
| evaluation | Phase complete | scores |
| phase_update | Phase change | phase number |
| empathy_nudge | Pace analysis | message |
| voice_transcript | STT complete | transcript |
| interview_ended | All phases done | - |

#### Inbound (Client → Server)
| Message | Trigger | Payload |
|---------|---------|---------|
| answer | Text submit | content |
| voice | Audio submit | base64, duration |
| end_interview | User request | - |

## Client-Side

### WebSocket Hook
- Single connection per interview
- Auto-reconnect on disconnect (max 3 attempts)
- Message queue during reconnection
- Cleanup on unmount

### State Synchronization
- Use WebSocket messages as source of truth
- Update local state on message receipt
- Optimistic UI for user actions

## Reliability

### Error Handling
- Connection failure: Show error, offer retry
- Message send failure: Queue and retry
- Server disconnect: Attempt reconnection

### Latency Expectations
- Connection: < 500ms
- Message round-trip: < 200ms (local processing)
- Voice round-trip: 3-5 seconds total

### Reconnection Strategy
- Exponential backoff: 1s → 2s → 4s
- Max attempts: 3
- After max: show error, offer manual retry