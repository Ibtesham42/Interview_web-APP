/**
 * Return the supplied path if it's a safe same-origin relative path
 * to redirect to (starts with '/' and not '//'); otherwise return '/'.
 *
 * Used by the auth flow's `?next=...` plumbing — a user starting the
 * /companies/signup flow while signed out hits Signup or Login first,
 * and the `next` param threads them back through the email-confirm
 * round-trip to the company-setup form afterwards.
 *
 * Open-redirect protection: a `next=//evil.example.com/x` value would
 * navigate the user off-origin via React Router's `navigate(path)`,
 * which `path` interprets as a full URL when it starts with `//`.
 * The `path.startsWith('//')` reject covers this; everything else is
 * a path within our own app and safe to follow.
 *
 * Returns '/' (the role-aware home route) as the default fallback —
 * RoleHome routes each role to its appropriate dashboard.
 */
export function safeNext(value: string | null | undefined): string {
  if (!value) return '/';
  if (!value.startsWith('/')) return '/';
  if (value.startsWith('//')) return '/';
  return value;
}
