"""Outbound email service — Resend wrapper + email_outbox audit log.

Multi-tenant PR 6 of MULTI_TENANT_ROLLOUT.md. Public surface:

- `send(supabase, *, company_id, candidate_id, sender_id, to, subject, body)`
  → outbox row dict. Hits Resend's HTTP API; persists a row in
  `email_outbox` regardless of send outcome (success → `status='sent'`
  + `resend_message_id`; failure → `status='failed'` + `error_message`).
  Idempotent at the row level only — Resend's API does not de-duplicate,
  so the caller is responsible for not double-clicking Send.

- `list_for_candidate(supabase, candidate_id, company_id=...)` → ordered
  list of prior outbox rows for the per-candidate "previous messages"
  list on the recruiter detail page (PR 7).

Why httpx + manual API call, not the official `resend` SDK:
- We already pin httpx (it's a Supabase transitive). One fewer pinned
  dep and one fewer source of supply-chain risk.
- Resend's surface for transactional sends is one POST endpoint; a
  wrapped SDK doesn't add meaningful ergonomics.
- httpx supports both sync and async in one client, mirroring our
  Groq pattern.

Disabled mode:
- When RESEND_API_KEY is empty (local dev, CI), `send()` writes a
  `status='failed'` outbox row with a clear "email not configured"
  error_message instead of hitting the network. The caller surfaces
  that to the recruiter so they know the message didn't go out. This
  is preferable to raising — the outbox row provides accountability
  even when the send is impossible.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings


_RESEND_API = "https://api.resend.com/emails"

# Mirrors the network timeout we use for Groq (services/interview_orchestrator
# wraps Groq calls at 30s). Resend's transactional sends should complete in
# under a second; 15s gives substantial headroom without letting a degraded
# upstream block the request indefinitely.
_RESEND_TIMEOUT_SECONDS = 15.0


class EmailServiceError(Exception):
    """Raised by `send()` only when persistence to email_outbox itself
    fails — the platform cannot serve an audit trail. Distinct from
    Resend-side delivery failures (those are recorded in the outbox
    with `status='failed'` and do NOT raise)."""


def _is_disabled() -> bool:
    """True when no Resend API key is configured. Send() short-circuits
    to a failed-outbox-row write so the caller sees clear feedback."""
    return not get_settings().resend_api_key.strip()


def _post_to_resend_sync(api_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous HTTP call to Resend. Wrapped in `asyncio.to_thread`
    by the async `send()` so the single-worker event loop is not
    blocked for the duration of the round-trip — same pattern as the
    Groq wrapper (services/groq_async.py)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=_RESEND_TIMEOUT_SECONDS) as client:
        response = client.post(_RESEND_API, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


async def _post_to_resend(api_key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return await asyncio.to_thread(_post_to_resend_sync, api_key, payload)


async def send(
    supabase,
    *,
    company_id: str,
    candidate_id: Optional[str],
    sender_id: Optional[str],
    to: str,
    subject: str,
    body: str,
) -> Dict[str, Any]:
    """Send one email through Resend and record the outcome in
    `email_outbox`.

    Returns the inserted outbox row. The row's `status` reflects what
    happened:
    - `'sent'` — Resend accepted the message. `resend_message_id`
      carries Resend's id (the only thing we can use to correlate with
      their dashboard later).
    - `'failed'` — either the service is disabled (no API key) or the
      Resend call raised. `error_message` carries a short diagnostic
      string the UI can display.

    The function **always** writes an outbox row (success OR failure).
    The audit-log invariant is more important than per-send transport
    reliability — a missing row would leave a recruiter unable to
    confirm whether a candidate was contacted. The only failure mode
    that raises is when the row insert itself fails (persistence
    broken), which surfaces as `EmailServiceError` and is the caller's
    cue to retry the entire send rather than silently drop accountability.
    """
    settings = get_settings()
    from_email = settings.resend_from_email
    api_key = settings.resend_api_key.strip()

    status = "sent"
    resend_message_id: Optional[str] = None
    error_message: Optional[str] = None

    if not api_key:
        # Disabled mode — write a failed-outbox row, no network call.
        status = "failed"
        error_message = "Email service not configured (RESEND_API_KEY missing)"
    else:
        try:
            payload = {
                "from": from_email,
                "to": [to],
                "subject": subject,
                # Resend distinguishes `html` and `text`. We send
                # plain text only (grill E2 — no HTML editor) so the
                # rendered email matches what the recruiter typed in
                # the composer.
                "text": body,
            }
            data = await _post_to_resend(api_key, payload)
            resend_message_id = data.get("id")
        except Exception as exc:  # noqa: BLE001 — record any Resend failure
            status = "failed"
            error_message = f"{type(exc).__name__}: {exc}"

    insert_payload: Dict[str, Any] = {
        "company_id": company_id,
        "candidate_id": candidate_id,
        "sender_id": sender_id,
        "to_email": to,
        "subject": subject,
        "body": body,
        "status": status,
        "resend_message_id": resend_message_id,
        "error_message": error_message,
    }
    try:
        result = supabase.table("email_outbox").insert(insert_payload).execute()
    except Exception as exc:
        raise EmailServiceError(f"email_outbox insert failed: {exc}") from exc

    rows = result.data or []
    return rows[0] if rows else insert_payload


def list_for_candidate(
    supabase,
    candidate_id: str,
    *,
    company_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return outbox rows for a candidate, newest first.

    `company_id` (tenant scope) follows the same pattern as the rest
    of the recruiter service: when non-None, the query filters by it
    so a recruiter never sees a candidate's emails from another
    tenant; `None` skips the filter (platform admin path / tests).
    """
    q = (
        supabase.table("email_outbox")
        .select(
            "id,company_id,candidate_id,sender_id,to_email,subject,body,status,"
            "resend_message_id,error_message,sent_at"
        )
        .eq("candidate_id", candidate_id)
        .order("sent_at", desc=True)
    )
    if company_id is not None:
        q = q.eq("company_id", company_id)
    return q.execute().data or []
