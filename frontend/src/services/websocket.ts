import type { IntegrityEventType, WebSocketMessage } from '../types';
import { supabase } from '../utils/supabase/client';
import { coldStartDelayMs, resolveWsHost } from './wsHost';

type MessageHandler = (message: WebSocketMessage) => void;

// Explicit VITE_WS_URL, else derive from the REST API origin (VITE_API_URL),
// else local dev. See resolveWsHost — this is the fix for the prod failure
// where a missing VITE_WS_URL fell back to ws://localhost:8000.
const WS_HOST = resolveWsHost(import.meta.env.VITE_WS_URL, import.meta.env.VITE_API_URL);
// Surface the resolved host once so a misconfig (e.g. a localhost fallback in
// production) is visible in the console rather than only as a generic
// "couldn't reach the interview server" panel.
if (typeof console !== 'undefined') {
  console.info('[ws] interview socket host:', WS_HOST);
}
// Cold-start retry budget. Render's free tier spins the backend down when
// the keep-alive misses (and every deploy restarts it); a wake takes 30–60s.
// The old 3-attempt budget (~7s of backoff) gave up long before the server
// was up, so a candidate on a cold backend saw "couldn't reach the interview
// server" even though everything was healthy. Six total attempts with the
// backoff capped at 8s (1+2+4+8+8 ≈ 23s of waiting, plus each attempt's own
// connect time) rides out a wake. Applies ONLY before the socket first opens
// — a drop after open stays terminal (ADR 0002, unchanged).
const MAX_COLD_START_RETRIES = 5;

class InterviewWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private intentionalClose = false;
  private interviewId: string | null = null;

  /**
   * Connect to the interview WebSocket.
   *
   * The retry loop only covers the *cold-start* window — a socket that never
   * opens (e.g. the Render backend is waking up). Once the socket has opened,
   * the interview is running and the in-memory orchestrator cannot be resumed
   * (ADR 0002): a later drop is terminal and surfaces a `disconnected` event
   * rather than silently restarting the interview.
   *
   * Resolves once a socket opens; rejects if every cold-start attempt fails.
   */
  async connect(interviewId: string): Promise<void> {
    this.interviewId = interviewId;
    this.intentionalClose = false;

    for (let attempt = 0; attempt <= MAX_COLD_START_RETRIES; attempt++) {
      if (this.intentionalClose) return;
      try {
        await this.openSocket(interviewId);
        return; // socket opened — interview is now running
      } catch (err) {
        if (attempt >= MAX_COLD_START_RETRIES) {
          throw err instanceof Error
            ? err
            : new Error('Unable to reach the interview server.');
        }
        // Exponential backoff before the next cold-start attempt:
        // 1s, 2s, 4s, 8s, 8s — see coldStartDelayMs.
        await new Promise((r) => setTimeout(r, coldStartDelayMs(attempt)));
      }
    }
  }

  /**
   * Open a single WebSocket. Resolves on `open`; rejects if the socket closes
   * before it ever opens (so {@link connect} can retry). A close *after* the
   * socket has opened is terminal and emits a synthetic `disconnected` event.
   */
  private openSocket(interviewId: string): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      let opened = false;

      // A fresh access token per attempt — getSession() refreshes if needed.
      supabase.auth
        .getSession()
        .then(({ data }) => {
          const token = data.session?.access_token ?? '';
          const ws = new WebSocket(
            `${WS_HOST}/ws/interview/${interviewId}?token=${encodeURIComponent(token)}`,
          );
          this.ws = ws;

          ws.onopen = () => {
            opened = true;
            resolve();
          };

          ws.onmessage = (event) => {
            try {
              const message: WebSocketMessage = JSON.parse(event.data);
              this.emit(message.type, message);
            } catch (e) {
              console.error('Failed to parse WebSocket message:', e);
            }
          };

          ws.onerror = () => {
            // The outcome (retry vs terminal) is decided in onclose.
          };

          ws.onclose = () => {
            if (!opened) {
              // Never opened — cold start or a rejected handshake. Let the
              // connect() retry loop decide whether to try again.
              reject(new Error('WebSocket failed to open'));
              return;
            }
            if (this.intentionalClose || !this.interviewId) return;
            // Opened then dropped: the interview is not resumable (ADR 0002).
            this.emit('disconnected', { type: 'disconnected' });
          };
        })
        .catch(reject);
    });
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.interviewId = null;
    if (this.ws) {
      this.ws.onclose = null; // suppress the terminal event on an intentional close
      this.ws.close();
      this.ws = null;
    }
    this.handlers.clear();
  }

  private send(message: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  sendAnswer(content: string): void {
    this.send({ type: 'answer', content });
  }

  sendVoice(audioBase64: string, duration: number): void {
    this.send({ type: 'voice', audio: audioBase64, duration });
  }

  sendEndInterview(): void {
    this.send({ type: 'end_interview' });
  }

  sendIntegrityEvent(eventType: IntegrityEventType, metadata?: Record<string, unknown>): void {
    this.send({ type: 'integrity_event', event_type: eventType, metadata: metadata ?? {} });
  }

  on(type: string, handler: MessageHandler): void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    this.handlers.get(type)!.add(handler);
  }

  off(type: string, handler: MessageHandler): void {
    this.handlers.get(type)?.delete(handler);
  }

  private emit(type: string, message: WebSocketMessage): void {
    this.handlers.get(type)?.forEach((handler) => handler(message));
  }
}

export const interviewWs = new InterviewWebSocket();
