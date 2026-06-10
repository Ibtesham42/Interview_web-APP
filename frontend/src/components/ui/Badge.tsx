import type { HTMLAttributes, ReactNode } from 'react';

export type BadgeVariant =
  | 'neutral'
  | 'primary'
  | 'success'
  | 'warning'
  | 'danger'
  | 'info';

// Full literal class strings per variant so Tailwind's content scanner keeps
// them (never build class names by interpolation).
const VARIANTS: Record<BadgeVariant, string> = {
  neutral: 'bg-surface-2 text-ink-muted border-subtle',
  primary: 'bg-primary-subtle text-primary border-subtle',
  success: 'bg-success-surface text-success border-success-border',
  warning: 'bg-warning-surface text-warning border-warning-border',
  danger: 'bg-danger-surface text-danger border-danger-border',
  info: 'bg-info-surface text-info border-info-border',
};

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: ReactNode;
}

/**
 * Compact status / label pill. The single primitive for the app's many
 * status indicators (email delivery, candidate decision, role, integrity).
 * Semantic-token based, so colour meaning is consistent everywhere.
 */
export function Badge({ variant = 'neutral', className = '', children, ...rest }: BadgeProps) {
  const classes = [
    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5',
    'text-xs font-semibold leading-none whitespace-nowrap',
    VARIANTS[variant],
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <span className={classes} {...rest}>
      {children}
    </span>
  );
}
