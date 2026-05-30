# Supabase Auth email (signup confirmation) — setup & troubleshooting

> **TL;DR** The "confirm your email" message after company signup is sent
> by **Supabase Auth**, not by this app's Resend integration. If no email
> arrives, it's almost always because the **hosted Supabase project has
> email confirmation ON but no custom SMTP** — the built-in sender is
> rate-limited (~2–4/hour, "for testing only"). Configure SMTP in the
> dashboard (steps below). This is **configuration, not code**.

## Two email systems — don't confuse them

| System | Sends | Configured in | Code |
|---|---|---|---|
| **Supabase Auth** | signup confirmation, password reset, magic links | **Hosted Supabase dashboard** | none of ours — Supabase owns it |
| **Resend** | candidate **invites** (`/api/companies/invite`) + shortlist emails | backend env (`RESEND_API_KEY`) | `backend/app/services/email.py` |

`RESEND_*` has **nothing** to do with the signup confirmation email. Setting
it will not make confirmation mail arrive.

## Diagnosis checklist (in order of likelihood)

1. **No custom SMTP → built-in sender throttled.** Dashboard →
   *Authentication → Emails → SMTP Settings*. If "Enable Custom SMTP" is
   off, you're on Supabase's built-in sender (a few/hour, testing only).
   **Fix:** enable custom SMTP (see below).
2. **Site URL / Redirect allow-list.** Dashboard → *Authentication → URL
   Configuration*. The app's `emailRedirectTo` is
   `window.location.origin + /auth/callback`, so **both** must be listed:
   - `http://localhost:3000/**` (local dev)
   - `https://<your-app>.vercel.app/**` (production + previews)
   If the redirect isn't allow-listed, the confirm link is rejected even
   when the mail is sent.
3. **Confirmation actually ON?** Dashboard → *Authentication → Providers →
   Email → "Confirm email"*. If you're seeing "check your email," it's ON.
   If you'd rather skip verification during early rollout, turning it OFF
   makes `signUp` return an immediate session — the app already handles
   that path and flows straight to company step 2. (Trade-off: unverified
   emails. Re-enable once SMTP is set.)

## Configure custom SMTP (recommended — keeps verification working)

You already have a Resend account (used for invites). Resend exposes an
SMTP endpoint, so reuse it for Supabase Auth mail:

Dashboard → *Authentication → Emails → SMTP Settings* → Enable Custom SMTP:

```
Host:          smtp.resend.com
Port:          465   (SSL)  — or 587 (STARTTLS)
Username:      resend
Password:      <your RESEND_API_KEY>
Sender email:  onboarding@resend.dev   (sandbox, no DNS)
               OR a verified address on your own domain
Sender name:   Interview Platform
```

Then set the rate limit high enough for real signups: *Authentication →
Rate Limits → "Emails per hour"* (the built-in default of ~2–4 is the
throttle most people hit first).

> **Sender domain.** `onboarding@resend.dev` works without DNS but is a
> shared sandbox sender — fine for testing. For production deliverability,
> verify your own domain in Resend (SPF/DKIM) and use a `@yourdomain`
> sender. This mirrors `RESEND_FROM_EMAIL` in `backend/.env.example`.

## localhost vs production — why they differ

- **Local Supabase** (`supabase start`, `supabase/config.toml`):
  `enable_confirmations = false` → signup gets an immediate session, **no
  email at all**. If you DO enable it locally, mail goes to **inbucket**
  (`http://localhost:54324`), a catch-all web inbox — it never reaches a
  real mailbox. So "I didn't get an email on localhost" is expected with
  the local stack.
- **Hosted Supabase from localhost:** mail IS sent by the hosted project,
  but `http://localhost:3000` must be in the redirect allow-list (step 2).
- **Production (Vercel):** same hosted project; the Vercel origin must be
  in the allow-list, and a real SMTP + verified domain is required for
  reliable delivery.

## Where the redirect URL comes from (code reference)

`frontend/src/components/companies/CompanySignup.tsx` builds
`/auth/callback?next=/companies/signup` as the `emailRedirectTo`. After the
user clicks the confirm link, `AuthCallback` lands them back on
`/companies/signup` (now signed in) to finish company step 2. The redirect
target is validated by `safeNext` (same-origin only).
