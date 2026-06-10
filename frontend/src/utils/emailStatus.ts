import type { EmailStatus } from '../types';

/**
 * Presentation helpers for the Resend delivery lifecycle (ADR 0012).
 *
 * Shared by the composer modal, the invite form, and the candidate-detail
 * "Emails sent" panel so the widened status set (migration 010) is rendered
 * consistently — and so a `delivered`/`suppressed` row is never mislabelled
 * as "Failed" (the bug from when the UI only knew 'sent' | 'failed').
 */
export const EMAIL_STATUS_LABEL: Record<EmailStatus, string> = {
  queued: 'Queued',
  sent: 'Sent',
  delivered: 'Delivered',
  bounced: 'Bounced',
  complained: 'Complained',
  failed: 'Failed',
  suppressed: 'Suppressed',
};

// Outcomes a recipient actually (or provably) received. Everything else is a
// non-delivery the recruiter should see explained.
const POSITIVE: ReadonlySet<EmailStatus> = new Set<EmailStatus>(['sent', 'delivered']);

/** True for 'sent' / 'delivered' — the recipient got (or will get) the mail. */
export function emailStatusIsPositive(status: EmailStatus): boolean {
  return POSITIVE.has(status);
}

/** Human label for a status, falling back to the raw value defensively. */
export function emailStatusLabel(status: EmailStatus): string {
  return EMAIL_STATUS_LABEL[status] ?? status;
}
