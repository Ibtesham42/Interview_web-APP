/**
 * Audible + haptic proctoring alerts for the interview room.
 *
 * Tones are synthesized with WebAudio (no audio asset to load — the alert
 * must fire even on a flaky connection). The AudioContext is created
 * lazily on first use; by then the candidate has long since interacted
 * (camera preflight click), so autoplay policy allows it.
 *
 * Two levels:
 * - `playWarningChirp` — short double beep on each integrity warning.
 *   Noticeable but not punishing; the visual overlay carries the detail.
 * - `playTerminationAlarm` — loud, sustained two-tone siren when the
 *   warning threshold is reached and the interview is terminated.
 *
 * Vibration uses `navigator.vibrate` where available (mostly Android
 * Chrome; iOS Safari and desktop ignore it) — strictly best-effort.
 */

let ctx: AudioContext | null = null;

function audioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!ctx) {
    try {
      ctx = new AudioContext();
    } catch {
      return null;
    }
  }
  // A suspended context (created before a gesture) resumes silently.
  if (ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
  return ctx;
}

/** Schedule one tone. `when`/`duration` in seconds relative to now. */
function tone(
  ac: AudioContext,
  frequency: number,
  when: number,
  duration: number,
  volume: number,
  type: OscillatorType = 'sine',
) {
  const osc = ac.createOscillator();
  const gain = ac.createGain();
  osc.type = type;
  osc.frequency.value = frequency;
  const t0 = ac.currentTime + when;
  // Short attack/release ramps avoid hard clicks at tone edges.
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(volume, t0 + 0.02);
  gain.gain.setValueAtTime(volume, t0 + duration - 0.04);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);
  osc.connect(gain).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + duration);
}

export function vibrate(pattern: number | number[]): void {
  try {
    navigator.vibrate?.(pattern);
  } catch {
    // Unsupported / blocked — haptics are best-effort by design.
  }
}

/** Short double beep + a single buzz — one integrity warning. */
export function playWarningChirp(): void {
  const ac = audioContext();
  if (ac) {
    tone(ac, 880, 0, 0.14, 0.18);
    tone(ac, 880, 0.2, 0.14, 0.18);
  }
  vibrate(200);
}

/**
 * Loud two-tone siren (~2.4s) + long vibration pattern — the warning
 * threshold was reached and the interview is being terminated.
 */
export function playTerminationAlarm(): void {
  const ac = audioContext();
  if (ac) {
    for (let i = 0; i < 4; i++) {
      tone(ac, 988, i * 0.6, 0.28, 0.5, 'square');
      tone(ac, 740, i * 0.6 + 0.3, 0.28, 0.5, 'square');
    }
  }
  vibrate([400, 150, 400, 150, 800]);
}
