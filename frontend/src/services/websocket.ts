import type { WebSocketMessage } from '../types';
import { supabase } from '../utils/supabase/client';

type MessageHandler = (message: WebSocketMessage) => void;

// In production VITE_WS_URL is the wss:// Render backend; unset in local dev.
// A trailing slash is stripped so `${WS_HOST}/ws/...` never doubles up.
const WS_HOST = (import.meta.env.VITE_WS_URL ?? 'ws://localhost:8000').replace(/\/+$/, '');
const MAX_RECONNECT_ATTEMPTS = 3;

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

    for (let attempt = 0; attempt <= MAX_RECONNECT_ATTEMPTS; attempt++) {
      if (this.intentionalClose) return;
      try {
        await this.openSocket(interviewId);
        return; // socket opened — interview is now running
      } catch (err) {
        if (attempt >= MAX_RECONNECT_ATTEMPTS) {
          throw err instanceof Error
            ? err
            : new Error('Unable to reach the interview server.');
        }
        // Exponential backoff before the next cold-start attempt: 1s, 2s, 4s.
        await new Promise((r) => setTimeout(r, 1000 * Math.pow(2, attempt)));
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
