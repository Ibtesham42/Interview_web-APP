import type { HTMLAttributes, ReactNode } from 'react';

type Padding = 'none' | 'sm' | 'md' | 'lg';

const PADDING: Record<Padding, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-5',
  lg: 'p-6',
};

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: Padding;
  /** Adds a subtle hover affordance — use for clickable/linked cards. */
  interactive?: boolean;
  children: ReactNode;
}

/**
 * Surface container — the base panel of the design system. Token-driven, so it
 * renders correctly in both themes. Replaces the legacy `.panel` / `.stat-card`
 * classes as screens migrate (Phase 3+).
 */
export function Card({
  padding = 'md',
  interactive = false,
  className = '',
  children,
  ...rest
}: CardProps) {
  const classes = [
    'rounded-lg border border-subtle bg-surface shadow-sm',
    PADDING[padding],
    interactive ? 'transition-colors hover:border-strong hover:bg-surface-2' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}

interface CardSectionProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

/** Optional header row with a bottom divider — title left, actions right. */
export function CardHeader({ className = '', children, ...rest }: CardSectionProps) {
  const classes = [
    'flex items-center justify-between gap-3 border-b border-subtle pb-3 mb-4',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  );
}

export function CardTitle({ className = '', children, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  const classes = ['text-base font-semibold text-ink', className].filter(Boolean).join(' ');
  return (
    <h3 className={classes} {...rest}>
      {children}
    </h3>
  );
}
