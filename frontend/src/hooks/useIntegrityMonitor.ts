import { useEffect, useRef } from 'react';
import type { IntegrityEventType } from '../types';

interface UseIntegrityMonitorOptions {
  /** Disable while in preflight, between turns, or after the interview ends. */
  enabled: boolean;
  /** Called once per de-duplicated event; the caller forwards it to the WS. */
  onEvent: (event: IntegrityEventType, metadata?: Record<string, unknown>) => void;
}

const COOLDOWN_MS = 3000;

/**
 * Phase A integrity monitor — browser APIs only, zero dependencies.
 *
 * Watches the candidate for tab/window/visibility loss using the Page
 * Visibility API and window `blur` event, and surfaces each as a single
 * de-duplicated event (3-second per-type cooldown prevents spamming the
 * backend on rapid alt-tabbing). Camera/face checks land in Phase B/C.
 */
export function useIntegrityMonitor({ enabled, onEvent }: UseIntegrityMonitorOptions) {
  const lastFiredAt = useRef<Partial<Record<IntegrityEventType, number>>>({});

  useEffect(() => {
    if (!enabled) return;

    const fire = (eventType: IntegrityEventType, metadata?: Record<string, unknown>) => {
      const now = Date.now();
      const last = lastFiredAt.current[eventType] ?? 0;
      if (now - last < COOLDOWN_MS) return;
      lastFiredAt.current[eventType] = now;
      onEvent(eventType, metadata);
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'hidden') {
        fire('visibility_hidden');
      }
    };

    // window blur fires on alt-tab to another app, on focus moving to a
    // browser chrome element (devtools), and on some OS-level overlays.
    const handleBlur = () => fire('window_blur');

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('blur', handleBlur);

    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('blur', handleBlur);
    };
  }, [enabled, onEvent]);
}
