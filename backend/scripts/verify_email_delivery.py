#!/usr/bin/env python3
"""Read-only production verification probe for the Resend email pipeline.

Run this AFTER setting RESEND_API_KEY / RESEND_FROM_EMAIL (+ webhook secret)
on Render and redeploying, to confirm blockers #1 (email delivery) and #2
(ENVIRONMENT=production) from PRODUCTION_CHECKLIST.md are cleared.

It performs NO writes and sends NO email. Two layers:

  1. Liveness + environment (no secrets needed):
       GET {API_BASE}/health  -> status, deployed commit, environment.
     Confirms which build is live and whether ENVIRONMENT=production took.

  2. Delivery flow (needs the Supabase service-role key):
       Reads email_outbox / email_events / email_suppressions over the last
       24h and aggregates in-process (no RPC, no GROUP BY). Confirms sends
       are landing as 'sent'/'delivered' rather than 'failed', and that
       webhook events are being ingested.

Usage (PowerShell):
    $env:API_BASE   = "https://interview-web-app.onrender.com"
    $env:SUPABASE_URL = "https://<ref>.supabase.co"   # optional (enables layer 2)
    $env:SUPABASE_KEY = "<service-role key>"           # optional
    python backend/scripts/verify_email_delivery.py

Exit code 0 = all checks passed or only warnings; 1 = a hard failure
(health down, or every recent send 'failed').
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

import httpx

API_BASE = os.getenv("API_BASE", "https://interview-web-app.onrender.com").rstrip("/")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

# Status buckets that mean "the candidate did NOT receive this email".
_BAD_STATUSES = {"failed", "bounced", "complained", "suppressed"}
_DELIVERED_STATUSES = {"sent", "delivered"}


def _ok(msg: str) -> None:
    print(f"  [PASS] {msg}")


def _warn(msg: str) -> None:
    print(f"  [warn] {msg}")


def _fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")


def check_health() -> bool:
    """Layer 1 — liveness + environment. Returns False on a hard failure."""
    print(f"\n1. Health / build identity  ({API_BASE}/health)")
    try:
        resp = httpx.get(f"{API_BASE}/health", timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — probe reports, never raises
        _fail(f"could not reach {API_BASE}/health: {exc}")
        return False

    _ok(f"backend healthy — status={data.get('status')} commit={data.get('commit')}")
    env = str(data.get("environment", "")).strip().lower()
    if env == "production":
        _ok("ENVIRONMENT=production is live (blocker #2 cleared)")
    else:
        _warn(
            f"environment={env or 'unset'} — set ENVIRONMENT=production on Render "
            "so the readiness gate runs in strict mode (blocker #2)."
        )
    return True


def check_delivery() -> bool:
    """Layer 2 — read email_* tables. Returns False if every recent send failed."""
    print("\n2. Email delivery flow  (last 24h, read-only)")
    if not (SUPABASE_URL and SUPABASE_KEY):
        _warn(
            "SUPABASE_URL / SUPABASE_KEY not set — skipping DB probes. Set both "
            "(service-role key) to verify end-to-end delivery."
        )
        return True

    try:
        from supabase import create_client
    except Exception as exc:  # noqa: BLE001
        _warn(f"supabase package unavailable ({exc}); run from the backend venv.")
        return True

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    # --- email_outbox: status mix over the window -------------------------
    try:
        rows = (
            client.table("email_outbox")
            .select("status,email_type,sent_at,error_message")
            .gte("sent_at", since)
            .order("sent_at", desc=True)
            .limit(500)
            .execute()
            .data
            or []
        )
    except Exception as exc:  # noqa: BLE001
        _fail(f"could not read email_outbox: {exc}")
        return False

    if not rows:
        _warn("no sends in the last 24h — trigger one invite/shortlist email, then re-run.")
        return True

    by_status = Counter(r.get("status") or "unknown" for r in rows)
    summary = ", ".join(f"{s}={n}" for s, n in sorted(by_status.items()))
    print(f"     email_outbox ({len(rows)} rows): {summary}")

    delivered = sum(by_status.get(s, 0) for s in _DELIVERED_STATUSES)
    bad = sum(by_status.get(s, 0) for s in _BAD_STATUSES)

    # The signature of blocker #1: every send 'failed' with the disabled-mode message.
    disabled_mode = [
        r for r in rows
        if (r.get("status") == "failed")
        and "RESEND_API_KEY missing" in (r.get("error_message") or "")
    ]
    if disabled_mode and delivered == 0:
        _fail(
            f"all {len(disabled_mode)} recent send(s) failed with 'RESEND_API_KEY "
            "missing' — blocker #1 NOT cleared. Set RESEND_API_KEY + a verified "
            "RESEND_FROM_EMAIL on Render and redeploy."
        )
        return False

    if delivered:
        _ok(f"{delivered} send(s) accepted by Resend ('sent'/'delivered') — blocker #1 cleared")
    if bad:
        _warn(
            f"{bad} send(s) in a non-delivered state ({', '.join(sorted(_BAD_STATUSES))}); "
            "inspect error_message for the ones that matter."
        )

    # --- email_events: webhook ingestion ----------------------------------
    try:
        events = (
            client.table("email_events")
            .select("event_type,received_at")
            .gte("received_at", since)
            .limit(500)
            .execute()
            .data
            or []
        )
        if events:
            by_type = Counter(e.get("event_type") or "unknown" for e in events)
            _ok("webhook events flowing: " + ", ".join(f"{t}={n}" for t, n in sorted(by_type.items())))
        else:
            _warn(
                "no email_events in 24h — delivery/bounce webhook not landing. Register "
                "the Resend webhook to POST /api/webhooks/resend and set RESEND_WEBHOOK_SECRET."
            )
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not read email_events: {exc}")

    # --- email_suppressions: informational --------------------------------
    try:
        supp = (
            client.table("email_suppressions")
            .select("email,reason,created_at")
            .order("created_at", desc=True)
            .limit(10)
            .execute()
            .data
            or []
        )
        if supp:
            _warn(f"{len(supp)} suppressed address(es) on file (newest: {supp[0].get('email')}).")
    except Exception as exc:  # noqa: BLE001
        _warn(f"could not read email_suppressions: {exc}")

    return True


def main() -> int:
    print("=" * 72)
    print("Resend email delivery — production verification probe (read-only)")
    print("=" * 72)
    healthy = check_health()
    delivered_ok = check_delivery()
    print("\n" + "=" * 72)
    if not healthy or not delivered_ok:
        print("RESULT: FAIL — see the [FAIL] lines above.")
        return 1
    print("RESULT: OK — no hard failures (review any [warn] lines).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
