"""Inbound provider webhooks — currently Resend delivery events (ADR 0012).

`POST /api/webhooks/resend` is how the platform learns what happened to an
email AFTER Resend accepted it: delivered, bounced, complained, delayed. It:

  1. Verifies the Svix signature (Resend signs webhooks with Svix) using
     stdlib hmac — no `svix` dependency, same no-new-dep posture as the
     httpx-not-the-SDK choice in services/email.py. FAIL CLOSED: a missing
     secret or a bad signature is rejected; we never trust unsigned input.
  2. De-dupes on the Svix message id (`svix-id`) so Svix's at-least-once
     retries are ingested exactly once.
  3. Correlates the event to its `email_outbox` row via `resend_message_id`
     and advances that row's `status` along a monotonic precedence ladder
     (a late `sent` never clobbers an earlier `delivered`).
  4. On a hard bounce / spam complaint, adds the recipient to the global
     suppression list so future sends to that address are refused.
  5. Appends the raw event to `email_events` for forensics.

The endpoint has NO auth dependency: it is authenticated by the signature,
not by a Supabase JWT (Resend is not a logged-in user). It returns 200 fast
and idempotently — webhooks must not do slow work in the request path.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services import email as email_svc
from app.supabase_client import get_supabase

logger = logging.getLogger("app.webhooks")

router = APIRouter()

# Svix tolerates clock skew; reject timestamps further than this from now.
_SIGNATURE_TOLERANCE_SECONDS = 5 * 60

# Resend event type -> the email_outbox.status it implies. None = the event is
# informational (record it, but don't change the row's status).
_EVENT_STATUS: Dict[str, Optional[str]] = {
    "email.sent": "sent",
    "email.delivered": "delivered",
    "email.delivery_delayed": None,   # transient; a hard bounce comes separately
    "email.bounced": "bounced",
    "email.complained": "complained",
    "email.opened": None,
    "email.clicked": None,
}

# Monotonic precedence — status only advances. Negative terminals
# (bounced/complained/failed/suppressed) outrank the positive lifecycle so a
# reordered/late positive event can never mask a delivery problem.
_STATUS_RANK: Dict[str, int] = {
    "queued": 0,
    "sent": 1,
    "delivered": 2,
    "failed": 3,
    "suppressed": 3,
    "bounced": 4,
    "complained": 4,
}

# Event types that take the recipient out of circulation permanently.
_SUPPRESSING = {"email.bounced": "bounce", "email.complained": "complaint"}


def _verify_svix_signature(secret: str, headers, raw_body: bytes) -> bool:
    """Verify a Svix/Resend webhook signature. Returns True iff valid.

    Signed content is `"{id}.{timestamp}.{body}"`, HMAC-SHA256 with the
    base64-decoded secret (the part after the `whsec_` prefix), compared
    constant-time against each `v1,<sig>` entry in the `svix-signature`
    header. The timestamp must be within the tolerance window.
    """
    svix_id = headers.get("svix-id")
    svix_timestamp = headers.get("svix-timestamp")
    svix_signature = headers.get("svix-signature")
    if not (svix_id and svix_timestamp and svix_signature):
        return False

    # Replay / skew guard.
    try:
        ts = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - ts) > _SIGNATURE_TOLERANCE_SECONDS:
        return False

    secret_key = secret
    if secret_key.startswith("whsec_"):
        secret_key = secret_key[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(secret_key)
    except Exception:  # noqa: BLE001 — malformed secret => cannot verify
        return False

    signed_content = b"%s.%s.%s" % (
        svix_id.encode("utf-8"),
        svix_timestamp.encode("utf-8"),
        raw_body,
    )
    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    ).decode("utf-8")

    # Header is space-delimited "v1,<sig> v1,<sig2> ...". Compare against each.
    for part in svix_signature.split():
        _, _, candidate = part.partition(",")
        if candidate and hmac.compare_digest(candidate, expected):
            return True
    return False


def _already_processed(supabase, svix_id: str) -> bool:
    """True if we've already ingested this Svix message id. Fails OPEN
    (returns False) so a guard error doesn't silently drop a real event —
    the UNIQUE index on email_events.svix_id is the hard dedupe backstop."""
    try:
        rows = (
            supabase.table("email_events")
            .select("id")
            .eq("svix_id", svix_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        if not email_svc._is_missing_table_error(exc):
            logger.warning("event dedupe lookup failed: %s", exc)
        return False
    return bool(rows)


def _correlate_outbox(supabase, resend_message_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Find the email_outbox row this event refers to, by Resend message id."""
    if not resend_message_id:
        return None
    try:
        rows = (
            supabase.table("email_outbox")
            .select("id,company_id,to_email,status")
            .eq("resend_message_id", resend_message_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox correlation failed: %s", exc)
        return None
    return rows[0] if rows else None


def _advance_status(current: Optional[str], proposed: Optional[str]) -> Optional[str]:
    """Return the new status if `proposed` outranks `current`, else None
    (meaning: leave the row unchanged)."""
    if proposed is None:
        return None
    if current is None:
        return proposed
    if _STATUS_RANK.get(proposed, 0) > _STATUS_RANK.get(current, 0):
        return proposed
    return None


@router.post("/resend")
async def resend_webhook(request: Request):
    """Ingest a Resend delivery event. Always returns quickly; 2xx tells Svix
    to stop retrying, 4xx/5xx triggers its backoff retry."""
    settings = get_settings()
    secret = settings.resend_webhook_secret.strip()

    raw_body = await request.body()

    # Fail closed: with no secret we cannot authenticate the sender, so we
    # refuse rather than process forged delivery/suppression events.
    if not secret:
        logger.warning("resend webhook hit but RESEND_WEBHOOK_SECRET is unset")
        return JSONResponse(status_code=503, content={"detail": "Webhook not configured"})

    if not _verify_svix_signature(secret, request.headers, raw_body):
        return JSONResponse(status_code=401, content={"detail": "Invalid signature"})

    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return JSONResponse(status_code=400, content={"detail": "Malformed JSON"})

    svix_id = request.headers.get("svix-id", "")
    event_type = event.get("type", "")
    data = event.get("data") or {}
    resend_message_id = data.get("email_id") or data.get("id")
    occurred_at = event.get("created_at")

    supabase = get_supabase()

    # Idempotent: Svix retries on any non-2xx, so a previously-applied event
    # must be a no-op. The UNIQUE index is the backstop; this avoids re-doing
    # the status/suppression writes.
    if svix_id and _already_processed(supabase, svix_id):
        return JSONResponse(status_code=200, content={"status": "duplicate"})

    outbox = _correlate_outbox(supabase, resend_message_id)
    company_id = outbox.get("company_id") if outbox else None

    # 1. Record the raw event (forensics + dedupe). Insert first so the
    #    suppression row can reference it.
    event_id: Optional[str] = None
    try:
        inserted = (
            supabase.table("email_events")
            .insert({
                "svix_id": svix_id or None,
                "outbox_id": outbox.get("id") if outbox else None,
                "company_id": company_id,
                "resend_message_id": resend_message_id,
                "event_type": event_type,
                "payload": event,
                "occurred_at": occurred_at,
            })
            .execute()
        )
        rows = inserted.data or []
        event_id = rows[0]["id"] if rows else None
    except Exception as exc:  # noqa: BLE001
        # A duplicate svix_id (race against the dedupe check) is benign.
        msg = str(getattr(exc, "message", "") or exc).lower()
        if "duplicate" in msg or "unique" in msg or "23505" in msg:
            return JSONResponse(status_code=200, content={"status": "duplicate"})
        logger.warning("email_events insert failed: %s", exc)
        # Fall through: still try to apply status/suppression effects.

    # 2. Advance the outbox row's status along the precedence ladder.
    if outbox is not None:
        new_status = _advance_status(outbox.get("status"), _EVENT_STATUS.get(event_type))
        if new_status is not None:
            try:
                update: Dict[str, Any] = {"status": new_status}
                if occurred_at:
                    update["last_event_at"] = occurred_at
                supabase.table("email_outbox").update(update).eq(
                    "id", outbox["id"]
                ).execute()
            except Exception as exc:  # noqa: BLE001
                logger.warning("outbox status update failed: %s", exc)

    # 3. Suppress the recipient on hard bounce / complaint.
    reason = _SUPPRESSING.get(event_type)
    if reason:
        recipient = _recipient_of(data, outbox)
        if recipient:
            email_svc.record_suppression(
                supabase,
                email=recipient,
                reason=reason,
                company_id=company_id,
                source_event_id=event_id,
                note=f"auto from {event_type}",
            )

    logger.info(
        "resend webhook: type=%s msg=%s outbox=%s",
        event_type, resend_message_id, outbox.get("id") if outbox else None,
    )
    return JSONResponse(status_code=200, content={"status": "ok"})


def _recipient_of(data: Dict[str, Any], outbox: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best-effort recipient address for suppression. Prefer the event
    payload's `to` (Resend sends a list or a string); fall back to the
    correlated outbox row's to_email."""
    to = data.get("to")
    if isinstance(to, list) and to:
        return to[0]
    if isinstance(to, str) and to:
        return to
    if outbox:
        return outbox.get("to_email")
    return None
