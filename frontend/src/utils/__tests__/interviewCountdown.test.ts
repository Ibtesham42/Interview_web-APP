import { describe, it, expect } from 'vitest';
import {
  ANSWER_COUNTDOWN_SECONDS,
  shouldRunAnswerCountdown,
  nextCountdownValue,
} from '../interviewCountdown';

describe('shouldRunAnswerCountdown', () => {
  it('runs only when it is the user turn and the mic is already granted', () => {
    expect(shouldRunAnswerCountdown('ready', true)).toBe(true);
  });

  it('does NOT run when mic permission is unknown or denied (safety)', () => {
    expect(shouldRunAnswerCountdown('ready', null)).toBe(false);
    expect(shouldRunAnswerCountdown('ready', false)).toBe(false);
  });

  it('does NOT run outside the user turn, even with the mic granted', () => {
    for (const s of [
      'connecting',
      'ai_speaking',
      'recording',
      'transcribing',
      'processing',
      'ended',
    ]) {
      expect(shouldRunAnswerCountdown(s, true)).toBe(false);
    }
  });
});

describe('nextCountdownValue', () => {
  it('counts down one second at a time', () => {
    expect(nextCountdownValue(ANSWER_COUNTDOWN_SECONDS)).toBe(9);
    expect(nextCountdownValue(2)).toBe(1);
  });

  it('reaching 0 signals auto-start and never goes negative', () => {
    expect(nextCountdownValue(1)).toBe(0);
    expect(nextCountdownValue(0)).toBe(0);
  });
});
