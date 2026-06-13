/**
 * Pure helpers for the interview auto-answer countdown (InterviewRoom).
 *
 * Extracted so the gate + tick logic is unit-testable without React/jsdom —
 * component render tests aren't set up yet (see CURRENT_TASKS). The component
 * owns the timer and side effects; these functions own the decisions.
 */

/** Seconds to wait after the AI finishes speaking before the mic auto-starts. */
export const ANSWER_COUNTDOWN_SECONDS = 10;

/**
 * The auto-answer countdown runs only when it is genuinely the candidate's turn
 * (`status === 'ready'`) AND microphone permission is already granted — so we
 * never auto-trigger a permission prompt (safety). Unknown permission (`null`,
 * not yet queried) or any non-ready status means no countdown (manual tap).
 */
export function shouldRunAnswerCountdown(
  status: string,
  micGranted: boolean | null,
): boolean {
  return status === 'ready' && micGranted === true;
}

/**
 * Next value for a one-second tick, floored at 0. The caller auto-starts
 * recording when this returns 0.
 */
export function nextCountdownValue(current: number): number {
  return current > 0 ? current - 1 : 0;
}
