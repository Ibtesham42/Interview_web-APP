import { useCallback, useEffect, useRef } from 'react';

interface UseSnapshotCaptureOptions {
  stream: MediaStream | null;
  /** Capture only while the interview is genuinely live. */
  enabled: boolean;
  /** Receives a base64 JPEG (no data: prefix) + the capture kind. */
  onCapture: (imageBase64: string, kind: 'periodic' | 'integrity') => void;
}

// One frame per minute keeps a 30-minute interview around ~30 frames /
// <1 MB total — enough for a reviewer to verify presence without turning
// the snapshots table into a video store. The first frame lands early
// (5s) so even a one-question interview has visual evidence.
const CAPTURE_INTERVAL_MS = 60_000;
const FIRST_CAPTURE_DELAY_MS = 5_000;
const TARGET_WIDTH = 320;
const JPEG_QUALITY = 0.55;

/**
 * Periodic webcam snapshots for proctoring (migration 012).
 *
 * Draws the camera stream into an offscreen canvas at reduced size and
 * hands the JPEG to the caller, which posts it to the backend. Also
 * exposes `captureNow('integrity')` so the interview room can attach a
 * frame to the exact moment an integrity warning fires.
 *
 * Every failure path is silent by design: a lost frame must never
 * disturb the interview turn flow (same posture as the integrity event
 * log on the backend).
 */
export function useSnapshotCapture({ stream, enabled, onCapture }: UseSnapshotCaptureOptions) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const onCaptureRef = useRef(onCapture);
  onCaptureRef.current = onCapture;

  const grabFrame = useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || video.readyState < 2 || video.videoWidth === 0) return null;
    try {
      const scale = TARGET_WIDTH / video.videoWidth;
      const canvas = document.createElement('canvas');
      canvas.width = TARGET_WIDTH;
      canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
      const ctx2d = canvas.getContext('2d');
      if (!ctx2d) return null;
      ctx2d.drawImage(video, 0, 0, canvas.width, canvas.height);
      const dataUrl = canvas.toDataURL('image/jpeg', JPEG_QUALITY);
      const comma = dataUrl.indexOf(',');
      return comma >= 0 ? dataUrl.slice(comma + 1) : null;
    } catch {
      return null; // tainted canvas / detached track — skip this frame
    }
  }, []);

  const captureNow = useCallback(
    (kind: 'periodic' | 'integrity' = 'integrity') => {
      const frame = grabFrame();
      if (frame) onCaptureRef.current(frame, kind);
    },
    [grabFrame],
  );

  useEffect(() => {
    if (!enabled || !stream) return;

    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    video.play().catch(() => {
      // Autoplay practically never fails here (the candidate already
      // clicked through preflight); grabFrame returns null until ready.
    });
    videoRef.current = video;

    const tick = () => {
      const frame = grabFrame();
      if (frame) onCaptureRef.current(frame, 'periodic');
    };

    const firstTimer = window.setTimeout(tick, FIRST_CAPTURE_DELAY_MS);
    const interval = window.setInterval(tick, CAPTURE_INTERVAL_MS);

    return () => {
      window.clearTimeout(firstTimer);
      window.clearInterval(interval);
      video.pause();
      video.srcObject = null;
      videoRef.current = null;
    };
  }, [enabled, stream, grabFrame]);

  return { captureNow };
}
