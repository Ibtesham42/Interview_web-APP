import { useCallback, useRef } from 'react';

/**
 * Subtle cursor-based 3D tilt for premium card hover.
 *
 * Lightweight (transform-only, no re-renders), respects `prefers-reduced-motion`,
 * and stays gentle — `maxDeg` should remain small (2-5deg).
 */
export function useTilt(maxDeg = 4) {
  const ref = useRef<HTMLDivElement>(null);

  const onMouseMove = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const el = ref.current;
      if (!el) return;
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

      const rect = el.getBoundingClientRect();
      const px = (e.clientX - rect.left) / rect.width - 0.5;
      const py = (e.clientY - rect.top) / rect.height - 0.5;
      el.style.transform =
        `perspective(900px) rotateX(${(-py * maxDeg).toFixed(2)}deg) ` +
        `rotateY(${(px * maxDeg).toFixed(2)}deg)`;
    },
    [maxDeg],
  );

  const onMouseLeave = useCallback(() => {
    const el = ref.current;
    if (el) el.style.transform = 'perspective(900px) rotateX(0deg) rotateY(0deg)';
  }, []);

  return { ref, onMouseMove, onMouseLeave };
}
