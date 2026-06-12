import { describe, expect, it } from 'vitest';
import { coldStartDelayMs } from '../wsHost';

describe('coldStartDelayMs', () => {
  it('backs off exponentially for the first attempts', () => {
    expect(coldStartDelayMs(0)).toBe(1000);
    expect(coldStartDelayMs(1)).toBe(2000);
    expect(coldStartDelayMs(2)).toBe(4000);
  });

  it('caps at 8s so the total window rides out a Render wake', () => {
    expect(coldStartDelayMs(3)).toBe(8000);
    expect(coldStartDelayMs(4)).toBe(8000);
    expect(coldStartDelayMs(10)).toBe(8000);
  });

  it('sums to a window long enough for a free-tier cold start', () => {
    const total = [0, 1, 2, 3, 4].reduce((s, a) => s + coldStartDelayMs(a), 0);
    expect(total).toBeGreaterThanOrEqual(20_000); // vs the old ~7s budget
  });
});
