// Pure helper extracted from websocket.ts so it can be unit-tested without
// pulling the Supabase client (which throws at import time when env vars are
// missing). Behaviour is identical to the previous in-file definition.

// In production VITE_WS_URL is the wss:// Render backend; unset in local dev.
//
// Normalises three paste-time mistakes that have hit this project's hosting
// env vars before (cf. CHANGE 21/05/2026 18:30 trailing slash, 21:45 trailing
// newline): surrounding whitespace, http(s):// scheme (the WebSocket
// constructor only accepts ws:/wss:), and the value pasted more than once
// (e.g. "wss://host.comwss://host.com", which produces an unresolvable
// hostname and fails silently in the browser).
export function normalizeWsHost(raw: string | undefined): string {
  const fallback = 'ws://localhost:8000';
  if (!raw) return fallback;
  let value = raw.trim().replace(/\/+$/, '');
  if (!value) return fallback;

  value = value
    .replace(/^https:\/\//i, 'wss://')
    .replace(/^http:\/\//i, 'ws://');

  const scheme = value.match(/^wss?:\/\//i);
  if (scheme) {
    const tail = value.slice(scheme[0].length);
    const dupIdx = tail.search(/wss?:?\/\//i);
    if (dupIdx !== -1) {
      value = (scheme[0] + tail.slice(0, dupIdx)).replace(/[^A-Za-z0-9.\-:]+$/, '');
      // Surfaced so the misconfiguration is visible in the console instead of
      // hiding behind a generic "Unable to connect" panel.
      console.warn(
        '[ws] VITE_WS_URL contains a duplicated host; using only the first occurrence. Fix the env var in Vercel.',
      );
    }
  }

  return value;
}
