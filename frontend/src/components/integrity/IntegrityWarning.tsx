import { useEffect } from 'react';
import type { IntegrityEventType } from '../../types';

interface IntegrityWarningProps {
  count: number;
  max: number;
  eventType: IntegrityEventType;
  onDismiss: () => void;
}

const REASONS: Record<IntegrityEventType, string> = {
  tab_blur: 'You switched tabs. Please stay on this page until the interview ends.',
  window_blur: 'The window lost focus. Please stay in the interview.',
  visibility_hidden: 'The interview page was hidden. Please keep it visible.',
  camera_lost: 'The camera was disconnected. Please re-enable it.',
  no_face: "We couldn't see your face. Please stay in frame.",
  multi_face: 'Multiple people detected. Only the candidate may be in frame.',
  camera_dark: 'The camera feed is dark. Please check your camera.',
};

export function IntegrityWarning({ count, max, eventType, onDismiss }: IntegrityWarningProps) {
  useEffect(() => {
    const id = window.setTimeout(onDismiss, 6000);
    return () => window.clearTimeout(id);
  }, [onDismiss]);

  return (
    <div className="integrity-warning" role="alert" aria-live="assertive">
      <div className="integrity-warning-icon">!</div>
      <div className="integrity-warning-body">
        <div className="integrity-warning-title">
          Integrity warning {count} of {max}
        </div>
        <div className="integrity-warning-message">{REASONS[eventType] ?? 'Integrity event detected.'}</div>
      </div>
      <button
        type="button"
        className="integrity-warning-close"
        onClick={onDismiss}
        aria-label="Dismiss warning"
      >
        ×
      </button>
    </div>
  );
}
