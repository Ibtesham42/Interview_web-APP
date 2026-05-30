import { useEffect, useRef } from 'react';
import type { IntegrityEventType } from '../types';

interface UseFaceMonitorOptions {
  stream: MediaStream | null;
  enabled: boolean;
  onEvent: (event: IntegrityEventType, metadata?: Record<string, unknown>) => void;
}

interface FaceDetectorAdapter {
  /** Returns face count (≥0), or -1 if the source isn't ready yet. */
  detect(video: HTMLVideoElement): Promise<number>;
  dispose?: () => void;
}

// Tuning constants — surfaced here so a future calibration pass can adjust
// without touching the sampling loop. Defaults err toward "obvious" misses
// (candidate stepped out of frame) and away from "glanced at notes" noise.
const SAMPLE_INTERVAL_MS = 500;        // 2 Hz — face detect is heavier than brightness
const NO_FACE_HYSTERESIS_MS = 5000;    // must be missing for ≥5s before firing
const NO_FACE_COOLDOWN_MS = 10000;
const MULTI_FACE_COOLDOWN_MS = 8000;

// MediaPipe Tasks Vision is pinned in package.json (^0.10.14). The WASM
// runtime and the BlazeFace model are self-hosted from our own origin
// (Vercel `dist/`) rather than jsdelivr / GCS — a blocked or down CDN used
// to silently disable the face checks. The WASM runtime is copied out of
// node_modules at build time (scripts/copy-mediapipe-wasm.mjs, run by
// predev/prebuild), keeping it lockstep with the resolved package version;
// the model is committed under public/mediapipe/. Both resolve same-origin.
const MEDIAPIPE_WASM_BASE = '/mediapipe/wasm';
const BLAZEFACE_MODEL_URL = '/mediapipe/blaze_face_short_range.tflite';

// Native FaceDetector API — Chromium / Edge / Opera. Not in TS lib.dom yet,
// so declare the slice we touch.
type NativeFaceDetectorCtor = new (options?: {
  maxDetectedFaces?: number;
  fastMode?: boolean;
}) => { detect(source: HTMLVideoElement): Promise<unknown[]> };

declare global {
  interface Window {
    FaceDetector?: NativeFaceDetectorCtor;
  }
}

/**
 * Pick the cheapest available face detector.
 *
 * 1. Native `FaceDetector` API (~70 % of users on Chromium-family browsers).
 *    Zero bundle weight, zero startup cost.
 * 2. Lazy-imported MediaPipe BlazeFace (~1 MB JS + ~3 MB WASM + ~230 KB
 *    model, all loaded on first use). Only paid for on Firefox / Safari.
 * 3. Returns null on both failures — face monitoring is then silently off
 *    (the Phase A tab/focus monitor and the Phase B brightness check still
 *    run, so integrity coverage degrades gracefully rather than breaks).
 */
async function createAdapter(): Promise<FaceDetectorAdapter | null> {
  if (typeof window.FaceDetector === 'function') {
    try {
      const detector = new window.FaceDetector({ maxDetectedFaces: 4, fastMode: true });
      return {
        detect: async (video) => {
          if (video.readyState < 2 || video.videoWidth === 0) return -1;
          const faces = await detector.detect(video);
          return Array.isArray(faces) ? faces.length : 0;
        },
      };
    } catch {
      // Native init failed — fall through to MediaPipe.
    }
  }

  try {
    const mp = await import('@mediapipe/tasks-vision');
    const vision = await mp.FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_BASE);
    const detector = await mp.FaceDetector.createFromOptions(vision, {
      baseOptions: { modelAssetPath: BLAZEFACE_MODEL_URL },
      runningMode: 'VIDEO',
    });
    return {
      detect: async (video) => {
        if (video.readyState < 2 || video.videoWidth === 0) return -1;
        const result = detector.detectForVideo(video, performance.now());
        return result.detections?.length ?? 0;
      },
      dispose: () => {
        try {
          detector.close();
        } catch {
          /* nothing to do */
        }
      },
    };
  } catch (err) {
    console.warn('[face-monitor] MediaPipe load failed — face checks disabled', err);
    return null;
  }
}

/**
 * Phase C integrity monitor — face presence and multi-person detection.
 *
 * Two events fire over the existing `integrity_event` WS channel:
 * - `multi_face` (severity=critical): fired immediately when >1 face appears,
 *   with an 8 s cooldown so a leaning-over partner doesn't spam events.
 * - `no_face`   (severity=warning):  fired only after the face has been
 *   absent for ≥5 s of continuous samples, with a 10 s post-fire cooldown.
 *   The hysteresis tolerates a candidate glancing at notes / drinking water
 *   without producing a warning.
 *
 * Frames stay in the browser — only the event type and a tiny `count`
 * metadata number reach the backend.
 */
export function useFaceMonitor({ stream, enabled, onEvent }: UseFaceMonitorOptions) {
  const noFaceSinceRef = useRef<number | null>(null);
  const lastNoFaceFiredRef = useRef(0);
  const lastMultiFaceFiredRef = useRef(0);

  useEffect(() => {
    if (!enabled || !stream) {
      noFaceSinceRef.current = null;
      return;
    }

    let cancelled = false;
    let interval: number | null = null;
    let adapter: FaceDetectorAdapter | null = null;

    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    video.play().catch(() => {
      // Autoplay can fail on first paint — the candidate has already
      // gestured (clicked through the preflight gate) so this almost never
      // hits in practice. If it does, detect() returns -1 until ready.
    });

    (async () => {
      adapter = await createAdapter();
      if (cancelled || !adapter) return;

      interval = window.setInterval(async () => {
        if (!adapter) return;
        let faceCount: number;
        try {
          faceCount = await adapter.detect(video);
        } catch {
          return;
        }
        if (faceCount < 0) return; // source not ready

        const now = Date.now();

        if (faceCount > 1) {
          // Immediate fire — second person is the high-signal event.
          noFaceSinceRef.current = null;
          if (now - lastMultiFaceFiredRef.current >= MULTI_FACE_COOLDOWN_MS) {
            lastMultiFaceFiredRef.current = now;
            onEvent('multi_face', { count: faceCount });
          }
          return;
        }

        if (faceCount === 0) {
          if (noFaceSinceRef.current === null) {
            noFaceSinceRef.current = now;
          } else if (
            now - noFaceSinceRef.current >= NO_FACE_HYSTERESIS_MS &&
            now - lastNoFaceFiredRef.current >= NO_FACE_COOLDOWN_MS
          ) {
            lastNoFaceFiredRef.current = now;
            onEvent('no_face');
            // Restart hysteresis after a fire so we don't re-arm in 0 ms.
            noFaceSinceRef.current = now;
          }
          return;
        }

        // faceCount === 1 — happy path.
        noFaceSinceRef.current = null;
      }, SAMPLE_INTERVAL_MS);
    })();

    return () => {
      cancelled = true;
      if (interval !== null) window.clearInterval(interval);
      adapter?.dispose?.();
      video.pause();
      video.srcObject = null;
    };
  }, [enabled, stream, onEvent]);
}
