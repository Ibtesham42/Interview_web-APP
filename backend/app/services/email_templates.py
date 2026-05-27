"""Default email templates for the recruiter Shortlist + Email flow.

Multi-tenant PR 6. Per grill E2, templates are **platform-wide
defaults**, editable per-send in the composer (PR 7). Per-company
templates land as a follow-up (would need a `company_email_templates`
table + a settings UI for editing them).

Each template returns `{subject, body}` — both fields are plain text
(no HTML). Plain text:
- Renders identically across email clients (no Gmail-strips-styles
  surprises).
- Inserts directly into the composer textarea (PR 7) where the
  recruiter can edit before Send.
- Reads correctly in plain-text mail readers (terminal, CLI, etc.).

If we ever need HTML, switch to returning `{subject, text, html}` and
update `services/email.py` to pass both to Resend. Doing it now would
require a richtext editor in the composer UI — out of scope for the
rollout.

Variables substituted into templates use plain string formatting
(`{candidate_name}` etc.) rather than Jinja or similar. Templates are
small, the variable surface is fixed, and a dependency-free format is
preferable for code that the recruiter will read and edit by hand.
"""
from __future__ import annotations

from typing import Any, Dict, TypedDict


class EmailTemplate(TypedDict):
    """Shape returned by every template function. The composer (PR 7)
    pre-fills subject + body into form fields; the recruiter edits
    either freely before Send. The shape is fixed so the composer
    doesn't branch on which template generated the draft."""
    subject: str
    body: str


def _candidate_first_name(candidate: Dict[str, Any]) -> str:
    """Greet by first name when we have one; fall back to a neutral
    address otherwise. `name` on Candidates is the resume-extracted
    full name (services/resume_parser.py); empty strings are common
    when the parser couldn't isolate a name field, so the fallback
    is the load-bearing branch."""
    full = (candidate.get("name") or "").strip()
    if not full:
        return "there"
    # First whitespace-separated token — handles "Alice Smith" → "Alice"
    # and degrades to the entire string when no space (e.g. "Alice").
    return full.split()[0]


def default_shortlist_template(
    candidate: Dict[str, Any],
    company: Dict[str, Any],
) -> EmailTemplate:
    """Subject + body for the shortlist-positive outreach.

    Used as the default when a Recruiter clicks "Shortlist + email"
    (PR 7). Keep the wording neutral — the Recruiter edits before
    Send, so the template doesn't need to commit to specific next
    steps (interview scheduling, take-home, etc.).

    Inputs:
    - `candidate` — at minimum `{name: str, email: str}`. Other fields
      ignored.
    - `company` — at minimum `{name: str}`. Other fields ignored.
    """
    first_name = _candidate_first_name(candidate)
    company_name = (company.get("name") or "our team").strip() or "our team"

    subject = f"Next steps with {company_name}"
    body = (
        f"Hi {first_name},\n\n"
        f"Thank you for completing your interview with {company_name}. "
        f"We were impressed with your responses and would like to move "
        f"forward to the next round.\n\n"
        f"A member of our team will be in touch shortly to coordinate.\n\n"
        f"Best regards,\n"
        f"The {company_name} team"
    )
    return {"subject": subject, "body": body}


def default_rejection_template(
    candidate: Dict[str, Any],
    company: Dict[str, Any],
) -> EmailTemplate:
    """Subject + body for a respectful rejection.

    Not auto-attached to the Reject button (which is a workflow state
    transition, not a notification trigger). Available as a manual
    selection in the composer (PR 7) when a Recruiter wants to send a
    courtesy reply. Kept short, sincere, and free of feedback that
    would invite a back-and-forth — recruiters who want to share
    feedback should edit the body before sending.
    """
    first_name = _candidate_first_name(candidate)
    company_name = (company.get("name") or "our team").strip() or "our team"

    subject = f"Update on your application with {company_name}"
    body = (
        f"Hi {first_name},\n\n"
        f"Thank you for taking the time to interview with {company_name}. "
        f"After careful consideration, we've decided to move forward with "
        f"other candidates whose experience more closely matches what "
        f"we're looking for at this time.\n\n"
        f"We genuinely appreciate the effort you put into the process and "
        f"wish you the best in your search.\n\n"
        f"Best regards,\n"
        f"The {company_name} team"
    )
    return {"subject": subject, "body": body}
