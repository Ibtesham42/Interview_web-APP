import { useEffect, useRef } from 'react';
import type { IntegrityEventType } from '../types';

interface UseCameraPresenceMonitorOptions {
  /** The camera MediaStream from the preflight gate. */
  stream: MediaStream | null;
  /** Disable during preflight, between turns, or after the interview ends. */
  enabled: boolean;
  /** Forwarded to the WS via the caller. */
  onEvent: (event: IntegrityEventType, metadata?: Record<string, unknown>) => void;
}

// Tuning constants. Defaults err on the side of "obvious tampering only"
// (palm covering lens, lens cap, candidate in pitch-dark room). Surfaced
// here so a future calibration pass can adjust without touching the loop.
const SAMPLE_INTERVAL_MS = 1000;        // 1 Hz brightness sample
const SAMPLE_WIDTH = 32;                // downscale target — average is what matters
const SAMPLE_HEIGHT = 24;
const DARK_LUMA_THRESHOLD = 12;         // 0-255; below this = dark
const DARK_WINDOW_SIZE = 5;             // need this many consecutive dark samples
const COOLDOWN_MS = 8000;               // don't refire while still dark

/**
 * Phase B integrity monitor — camera-frame brightness check, browser-only.
 *
 * Once per second, downscale a frame from the live video to a tiny canvas,
 * compute the mean RGB luminance, and slide a 5-sample window. If the whole
 * window stays below the dark threshold, fire `camera_dark` once. Recovery
 * resets the window; a cooldown prevents refiring while the candidate is
 * still adjusting their camera. Zero ML, zero dependencies.
 *
 * The candidate's frames never leave the browser — only the resulting event
 * type plus a small `lum` number reach the backend.
 */
export function useCameraPresenceMonitor({
  stream,
  enabled,
  onEvent,
}: UseCameraPresenceMonitorOptions) {
  const lastFiredAt = useRef(0);
  const darkWindow = useRef<number[]>([]);

  useEffect(() => {
    if (!enabled || !stream) {
      darkWindow.current = [];
      return;
    }

    // Hidden <video> bound to the stream so we can grab frames into a canvas.
    // (Reusing the visible CameraThumbnail video would couple the components.)
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    video.play().catch(() => {
      // Autoplay can fail on some browsers if the page hasn't seen a user
      // gesture yet — the candidate has already clicked through the preflight
      // gate so this is a non-issue in practice. Failure leaves the loop
      // running against a paused video; samples will be black and treated as
      // dark, which is acceptable on the safe side.
    });

    const canvas = document.createElement('canvas');
    canvas.width = SAMPLE_WIDTH;
    canvas.height = SAMPLE_HEIGHT;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return;

    const sampleOnce = () => {
      if (video.readyState < 2 || video.videoWidth === 0) return;
      try {
        ctx.drawImage(video, 0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
        const { data } = ctx.getImageData(0, 0, SAMPLE_WIDTH, SAMPLE_HEIGHT);
        // ITU-R BT.601 luma — cheap and good enough for "is this dark".
        let sum = 0;
        const pixelCount = data.length / 4;
        for (let i = 0; i < data.length; i += 4) {
          sum += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
        }
        const lum = sum / pixelCount;

        const win = darkWindow.current;
        if (lum < DARK_LUMA_THRESHOLD) {
          win.push(lum);
          if (win.length > DARK_WINDOW_SIZE) win.shift();
          if (win.length >= DARK_WINDOW_SIZE) {
            const now = Date.now();
            if (now - lastFiredAt.current >= COOLDOWN_MS) {
              lastFiredAt.current = now;
              onEvent('camera_dark', { lum: Math.round(lum) });
            }
          }
        } else {
          darkWindow.current = [];
        }
      } catch {
        // ImageData / drawImage can throw on tainted streams; the stream is
        // local so this should never fire, but swallow to keep the loop alive.
      }
    };

    const id = window.setInterval(sampleOnce, SAMPLE_INTERVAL_MS);
    return () => {
      window.clearInterval(id);
      video.pause();
      video.srcObject = null;
    };
  }, [enabled, stream, onEvent]);
}
