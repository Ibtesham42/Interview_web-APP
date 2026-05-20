import type { WebSocketMessage } from '../types';

type MessageHandler = (message: WebSocketMessage) => void;

const WS_HOST = 'ws://localhost:8000';
const MAX_RECONNECT_ATTEMPTS = 3;

class InterviewWebSocket {
  private ws: WebSocket | null = null;
  private handlers: Map<string, Set<MessageHandler>> = new Map();
  private reconnectAttempts = 0;
  private intentionalClose = false;
  private interviewId: string | null = null;

  connect(interviewId: string): Promise<void> {
    this.interviewId = interviewId;
    this.intentionalClose = false;

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(`${WS_HOST}/ws/interview/${interviewId}`);
      this.ws = ws;

      ws.onopen = () => {
        this.reconnectAttempts = 0;
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

      ws.onerror = (error) => {
        if (ws.readyState !== WebSocket.OPEN) reject(error);
      };

      ws.onclose = () => {
        if (this.intentionalClose || !this.interviewId) return;
        if (this.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
          // Exponential backoff: 1s -> 2s -> 4s.
          const delay = 1000 * Math.pow(2, this.reconnectAttempts);
          this.reconnectAttempts++;
          setTimeout(() => {
            if (!this.intentionalClose && this.interviewId) {
              this.connect(this.interviewId).catch(() => {});
            }
          }, delay);
        }
      };
    });
  }

  disconnect(): void {
    this.intentionalClose = true;
    this.interviewId = null;
    if (this.ws) {
      this.ws.onclose = null; // suppress reconnect on an intentional close
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
