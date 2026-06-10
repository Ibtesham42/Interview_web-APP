"""Outbound email service — Resend wrapper + email_outbox audit log.

Multi-tenant PR 6 (migration 006) hardened into a production-grade delivery
pipeline by ADR 0012 (migration 010). Public surface:

- `send(supabase, *, company_id, candidate_id, sender_id, to, subject, body,
        email_type=None, idempotency_key=None, from_name=None, reply_to=None)`
  → outbox row dict. Before hitting Resend it now:
    1. de-dupes on `(company_id, idempotency_key)` (returns the prior row),
    2. refuses + records `status='suppressed'` if the recipient is on the
       suppression list (hard bounce / spam complaint),
    3. enforces a per-tenant hourly rate limit (raises `EmailRateLimited`).
  It then sends with a tenant-branded From + Reply-To and persists a row in
  `email_outbox` regardless of outcome (success → `status='sent'` +
  `resend_message_id`; failure → `status='failed'` + `error_message`).

- `list_for_candidate(supabase, candidate_id, company_id=...)` → ordered list
  of prior outbox rows for the per-candidate "previous messages" list.

- `record_suppression(...)` / `is_suppressed(...)` — suppression-list helpers
  shared with the Resend webhook ingester (routers/webhooks.py).

Why httpx + manual API call, not the official `resend` SDK: we already pin
httpx (a Supabase transitive); Resend's transactional surface is one POST; and
httpx is sync+async in one client, mirroring the Groq wrapper. The same
no-new-dependency posture is why the webhook verifies the Svix signature with
stdlib hmac instead of pulling the `svix` package.

Delivery status beyond `sent` (delivered / bounced / complained) is filled in
asynchronously by Resend webhooks — see routers/webhooks.py. `sent` here means
only that Resend ACCEPTED the message, not that it was delivered.

Disabled mode: when RESEND_API_KEY is empty (local dev, CI), `send()` writes a
`status='failed'` outbox row with a clear "email not configured" message
instead of hitting the network — the audit row provides accountability even
when the send is impossible.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger("app.email")

_RESEND_API = "https://api.resend.com/emails"

# Mirrors the network timeout we use for Groq. Resend's transactional sends
# complete in well under a second; 15s gives headroom without letting a
# degraded upstream block the (single-worker) request indefinitely.
_RESEND_TIMEOUT_SECONDS = 15.0


class EmailServiceError(Exception):
    """Raised by `send()` only when persistence to email_outbox itself
    fails — the platform cannot serve an audit trail. Distinct from
    Resend-side delivery failures (those are recorded in the outbox
    with `status='failed'` and do NOT raise)."""


class EmailRateLimited(Exception):
    """Raised by `send()` when a tenant exceeds EMAIL_RATE_LIMIT_PER_HOUR.
    The router maps this to HTTP 429. No outbox row is written — the send
    was refused before it began, not attempted-and-failed."""

    def __init__(self, company_id: str, limit: int):
        self.company_id = company_id
        self.limit = limit
        super().__init__(
            f"Email rate limit reached ({limit}/hour) for company {company_id}."
        )


class ResendApiError(Exception):
    """Raised by the Resend HTTP wrapper when Resend returns a non-2xx.

    Carries the provider HTTP status + Resend's own human-readable `message`
    (e.g. the 403 "verify a domain…" guidance) so `send()` can translate it
    into a recruiter-friendly `error_message` instead of leaking a raw
    httpx `HTTPStatusError` string to the UI."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.resend_message = (message or "").strip()
        super().__init__(f"Resend {status_code}: {self.resend_message}")


def _friendly_resend_error(status_code: int, resend_message: str) -> str:
    """Map a Resend API failure to a clear, actionable message safe to show a
    recruiter. Resend's own `message` is appended when present because it is
    usually the most useful part (esp. the 403 domain-verification guidance)."""
    msg = (resend_message or "").strip()
    detail = f" Details: {msg}" if msg else ""
    low = msg.lower()

    if status_code == 401 or "api key" in low or "api_key" in low:
        return (
            "The email service rejected the API key. Check RESEND_API_KEY in the "
            "server configuration." + detail
        )
    if status_code == 403:
        return (
            "This email couldn't be sent: the sending address isn't authorised "
            "for this recipient. Verify your domain in Resend and set the sender "
            "(RESEND_FROM_EMAIL) to an address on it — the sandbox sender can only "
            "email your own Resend account address." + detail
        )
    if status_code == 422:
        return "The email was rejected as invalid by the email service." + detail
    if status_code == 429:
        return "The email service is rate-limiting right now. Please try again shortly."
    return f"The email provider could not send this message (error {status_code})." + detail


def _is_disabled() -> bool:
    """True when no Resend API key is configured."""
    return not get_settings().resend_api_key.strip()


def _is_missing_table_error(exc: Exception) -> bool:
    """True when a Supabase/PostgREST error means the table/column doesn't
    exist yet (migration 010 not applied, or the post-deploy schema-cache
    reload we observed after a project resume). Lets the advisory pre-send
    guards (suppression / idempotency / rate-limit) fail OPEN — we'd rather
    send than block all email on a transient schema lag — while the audit
    INSERT, which genuinely needs the new columns, still fails LOUD."""
    code = getattr(exc, "code", "") or ""
    message = str(getattr(exc, "message", "") or exc).lower()
    return (
        code in {"PGRST205", "PGRST204", "42P01", "42703"}
        or "does not exist" in message
        or "schema cache" in message
        or "could not find" in message
    )


# ---------------------------------------------------------------------------
# Suppression list
# ---------------------------------------------------------------------------

def is_suppressed(supabase, email: str) -> Optional[Dict[str, Any]]:
    """Return the suppression row for `email` (case-insensitive) or None.

    Fails OPEN on any read error (missing table / transient outage): a guard
    that breaks must not take the whole send path down with it.
    """
    addr = (email or "").strip().lower()
    if not addr:
        return None
    try:
        rows = (
            supabase.table("email_suppressions")
            .select("id,email,reason,company_id")
            .eq("email", addr)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001 — guard must not break send
        if not _is_missing_table_error(exc):
            logger.warning("suppression lookup failed for %s: %s", addr, exc)
        return None
    return rows[0] if rows else None


def record_suppression(
    supabase,
    *,
    email: str,
    reason: str,
    company_id: Optional[str] = None,
    source_event_id: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    """Add `email` (lowercased) to the global suppression list.

    Idempotent: the UNIQUE index on lower(email) means a repeat bounce for an
    already-suppressed address is a no-op (the duplicate-key error is
    swallowed). Called by the webhook ingester on hard bounce / complaint.
    """
    addr = (email or "").strip().lower()
    if not addr:
        return
    payload = {
        "email": addr,
        "reason": reason,
        "company_id": company_id,
        "source_event_id": source_event_id,
        "note": note,
    }
    try:
        supabase.table("email_suppressions").insert(payload).execute()
        logger.info("suppressed %s (reason=%s)", addr, reason)
    except Exception as exc:  # noqa: BLE001
        # Duplicate (already suppressed) is the expected benign case.
        msg = str(getattr(exc, "message", "") or exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            return
        logger.warning("failed to suppress %s: %s", addr, exc)


# ---------------------------------------------------------------------------
# Idempotency + rate limiting (pre-send guards)
# ---------------------------------------------------------------------------

_OUTBOX_COLUMNS = (
    "id,company_id,candidate_id,sender_id,to_email,subject,body,status,"
    "resend_message_id,error_message,sent_at,sender_id,idempotency_key,"
    "email_type,reply_to,last_event_at"
)


def _find_idempotent_row(
    supabase, company_id: str, idempotency_key: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Return a prior outbox row for this `(company_id, idempotency_key)` if
    one exists (a retry / double-click). Fails OPEN (treats as "no prior
    row") so a guard error never blocks a legitimate first send."""
    if not idempotency_key:
        return None
    try:
        rows = (
            supabase.table("email_outbox")
            .select(_OUTBOX_COLUMNS)
            .eq("company_id", company_id)
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        if not _is_missing_table_error(exc):
            logger.warning("idempotency lookup failed: %s", exc)
        return None
    return rows[0] if rows else None


def _over_rate_limit(supabase, company_id: str) -> bool:
    """True when the tenant has sent >= EMAIL_RATE_LIMIT_PER_HOUR in the past
    rolling hour. Fails OPEN (returns False) on any counting error."""
    limit = get_settings().email_rate_limit_per_hour
    if not limit or limit <= 0:
        return False
    since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    try:
        res = (
            supabase.table("email_outbox")
            .select("id", count="exact")
            .eq("company_id", company_id)
            .gte("sent_at", since)
            .execute()
        )
        count = getattr(res, "count", None)
    except Exception as exc:  # noqa: BLE001
        if not _is_missing_table_error(exc):
            logger.warning("rate-limit count failed: %s", exc)
        return False
    return count is not None and count >= limit


# ---------------------------------------------------------------------------
# Resend transport
# ---------------------------------------------------------------------------

def _build_from(from_name: Optional[str]) -> str:
    """Compose the From header. Single verified sender address, tenant-branded
    display name: `"Acme via Rehearsify <noreply@platform>"`. Gives per-tenant
    identity without per-tenant DNS (ADR 0012 — verified domains deferred)."""
    settings = get_settings()
    addr = settings.resend_from_email
    name = (from_name or "").strip()
    if name:
        platform = settings.platform_from_name.strip()
        label = f"{name} via {platform}" if platform else name
        # Strip characters that would break the display-name quoting.
        label = label.replace('"', "").replace("\n", " ").replace("\r", " ")
        return f'"{label}" <{addr}>'
    return addr


def _post_to_resend_sync(
    api_key: str, payload: Dict[str, Any], idempotency_key: Optional[str]
) -> Dict[str, Any]:
    """Synchronous HTTP call to Resend. Wrapped in `asyncio.to_thread` by the
    async `send()` so the single-worker event loop is not blocked for the
    round-trip — same pattern as the Groq wrapper."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # Resend honours an Idempotency-Key header — a retry with the same key
    # returns the original result instead of sending again.
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    with httpx.Client(timeout=_RESEND_TIMEOUT_SECONDS) as client:
        response = client.post(_RESEND_API, headers=headers, json=payload)
    if response.is_error:
        # Resend returns a JSON body like
        #   {"statusCode":403,"name":"...","message":"You can only send..."}
        # Capture that message — it's what tells the operator how to fix a 403
        # (verify a domain) — and raise a typed error the caller can translate.
        detail = ""
        try:
            data = response.json()
            detail = data.get("message") or data.get("error") or ""
        except Exception:  # noqa: BLE001 — non-JSON error body
            detail = (response.text or "")[:300]
        raise ResendApiError(response.status_code, detail)
    return response.json()


async def _post_to_resend(
    api_key: str, payload: Dict[str, Any], idempotency_key: Optional[str] = None
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _post_to_resend_sync, api_key, payload, idempotency_key
    )


# ---------------------------------------------------------------------------
# Public send
# ---------------------------------------------------------------------------

async def send(
    supabase,
    *,
    company_id: str,
    candidate_id: Optional[str],
    sender_id: Optional[str],
    to: str,
    subject: str,
    body: str,
    email_type: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    from_name: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Send one email through Resend and record the outcome in `email_outbox`.

    Pre-send guards (in order):
      1. Idempotency — if a row already exists for `(company_id,
         idempotency_key)`, return it without sending again.
      2. Suppression — if `to` is on the suppression list, write a
         `status='suppressed'` row and return it (no network call).
      3. Rate limit — if the tenant is over EMAIL_RATE_LIMIT_PER_HOUR, raise
         `EmailRateLimited` (no row written).

    Then send (tenant-branded From + optional Reply-To) and persist the audit
    row. The function ALWAYS writes a row on a genuine send attempt (success OR
    failure); only an outbox INSERT failure raises (`EmailServiceError`).
    """
    to_addr = (to or "").strip()

    # 1. Idempotency — return the prior send verbatim.
    prior = _find_idempotent_row(supabase, company_id, idempotency_key)
    if prior is not None:
        logger.info(
            "idempotent replay: company=%s key=%s -> outbox=%s",
            company_id, idempotency_key, prior.get("id"),
        )
        return prior

    # 2. Suppression — refuse + record, no network.
    suppression = is_suppressed(supabase, to_addr)
    if suppression is not None:
        return _insert_outbox(
            supabase,
            company_id=company_id,
            candidate_id=candidate_id,
            sender_id=sender_id,
            to_email=to_addr,
            subject=subject,
            body=body,
            status="suppressed",
            resend_message_id=None,
            error_message=(
                f"Recipient is suppressed (reason={suppression.get('reason')}); "
                "not sent to protect sender reputation."
            ),
            email_type=email_type,
            idempotency_key=idempotency_key,
            reply_to=reply_to,
        )

    # 3. Rate limit — refuse loudly (router -> 429).
    if _over_rate_limit(supabase, company_id):
        limit = get_settings().email_rate_limit_per_hour
        logger.warning("rate limit hit: company=%s limit=%s", company_id, limit)
        raise EmailRateLimited(company_id, limit)

    settings = get_settings()
    api_key = settings.resend_api_key.strip()
    reply_to_clean = (reply_to or "").strip() or None

    status = "sent"
    resend_message_id: Optional[str] = None
    error_message: Optional[str] = None

    if not api_key:
        status = "failed"
        error_message = "Email service not configured (RESEND_API_KEY missing)"
    else:
        try:
            payload: Dict[str, Any] = {
                "from": _build_from(from_name),
                "to": [to_addr],
                "subject": subject,
                "text": body,
            }
            if reply_to_clean:
                payload["reply_to"] = reply_to_clean
            data = await _post_to_resend(api_key, payload, idempotency_key)
            resend_message_id = data.get("id")
            logger.info(
                "sent: company=%s to=%s type=%s resend_id=%s",
                company_id, to_addr, email_type, resend_message_id,
            )
        except ResendApiError as exc:
            # Resend rejected the send (e.g. 403 unverified domain). Surface a
            # clear, actionable message — never the raw httpx error.
            status = "failed"
            error_message = _friendly_resend_error(exc.status_code, exc.resend_message)
            logger.warning(
                "resend rejected: company=%s to=%s status=%s msg=%s",
                company_id, to_addr, exc.status_code, exc.resend_message,
            )
        except Exception as exc:  # noqa: BLE001 — network/timeout/unexpected
            status = "failed"
            error_message = (
                "The email could not be sent due to a temporary problem reaching "
                "the email service. Please try again."
            )
            logger.warning(
                "send failed: company=%s to=%s err=%s: %s",
                company_id, to_addr, type(exc).__name__, exc,
            )

    return _insert_outbox(
        supabase,
        company_id=company_id,
        candidate_id=candidate_id,
        sender_id=sender_id,
        to_email=to_addr,
        subject=subject,
        body=body,
        status=status,
        resend_message_id=resend_message_id,
        error_message=error_message,
        email_type=email_type,
        idempotency_key=idempotency_key,
        reply_to=reply_to_clean,
    )


def _insert_outbox(supabase, **fields: Any) -> Dict[str, Any]:
    """Persist one email_outbox row. The ONLY failure that raises
    (`EmailServiceError`) — a missing audit row is worse than a failed send."""
    try:
        result = supabase.table("email_outbox").insert(fields).execute()
    except Exception as exc:
        raise EmailServiceError(f"email_outbox insert failed: {exc}") from exc
    rows = result.data or []
    return rows[0] if rows else fields


def list_for_candidate(
    supabase,
    candidate_id: str,
    *,
    company_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return outbox rows for a candidate, newest first.

    `company_id` (tenant scope) follows the rest of the recruiter service:
    non-None filters by it so a recruiter never sees another tenant's emails;
    None skips the filter (platform-admin path / tests).
    """
    q = (
        supabase.table("email_outbox")
        .select(
            "id,company_id,candidate_id,sender_id,to_email,subject,body,status,"
            "resend_message_id,error_message,sent_at,email_type,reply_to,"
            "last_event_at"
        )
        .eq("candidate_id", candidate_id)
        .order("sent_at", desc=True)
    )
    if company_id is not None:
        q = q.eq("company_id", company_id)
    return q.execute().data or []
