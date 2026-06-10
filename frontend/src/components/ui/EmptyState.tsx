import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  /** Optional leading icon/illustration (kept small + muted). */
  icon?: ReactNode;
  /** Optional primary action (e.g. a Button or Link). */
  action?: ReactNode;
  className?: string;
}

/**
 * Consistent empty/zero-data state. One primitive so "no candidates", "no
 * emails", "no interviews yet" all read the same — calm, centred, with an
 * optional next-step action rather than a dead end.
 */
export function EmptyState({ title, description, icon, action, className = '' }: EmptyStateProps) {
  const classes = [
    'flex flex-col items-center justify-center text-center gap-3 px-6 py-12',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <div className={classes}>
      {icon && <div className="text-ink-subtle [&>svg]:h-8 [&>svg]:w-8">{icon}</div>}
      <h3 className="text-base font-semibold text-ink">{title}</h3>
      {description && <p className="max-w-sm text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
