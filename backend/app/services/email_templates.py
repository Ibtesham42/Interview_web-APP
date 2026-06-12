"""Default email templates for the recruiter Shortlist + Email flow.

Multi-tenant PR 6. Per grill E2, templates are **platform-wide
defaults**, editable per-send in the composer (PR 7). Per-company
templates land as a follow-up (would need a `company_email_templates`
table + a settings UI for editing them).

Each template returns `{subject, body}` — both fields are plain text.
The body stays plain text because it inserts directly into the composer
textarea where the recruiter edits it by hand; at SEND time
`services/email.py` additionally derives a clean HTML part from the
final body via `render_email_html` below, so every email goes out as
multipart text+HTML without the composer needing a rich-text editor.

Deliverability rules (2026-06-12 — every template and every edit path
must keep these):
- No all-caps subjects, no emojis, no marketing superlatives.
- Subject and body name the company and state the purpose up front.
- A reply line tells the recipient that replying works (Reply-To is the
  company's address — see services/email.py `reply_to`).
- A contact footer carries the company's email/phone/address so the
  message looks like company correspondence, not bulk mail.

Variables substituted into templates use plain string formatting
(`{candidate_name}` etc.) rather than Jinja or similar. Templates are
small, the variable surface is fixed, and a dependency-free format is
preferable for code that the recruiter will read and edit by hand.
"""
from __future__ import annotations

import html as _html
import re
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


def _company_footer(company: Dict[str, Any]) -> str:
    """Reply line + contact footer appended to every template body.

    Part of the *body text* (not bolted on at send time) so the recruiter
    sees and can edit exactly what the candidate will receive, and so the
    footer survives into both the text and HTML parts unchanged.
    Renders only the contact lines the company actually has on file.
    """
    company_name = (company.get("name") or "").strip()
    lines = [
        "If you have any questions, simply reply to this email — it reaches "
        + (f"the {company_name} hiring team" if company_name else "our hiring team")
        + " directly.",
        "",
        "--",
    ]
    if company_name:
        lines.append(company_name)
    contact_bits = []
    if (company.get("email") or "").strip():
        contact_bits.append(company["email"].strip())
    if (company.get("phone") or "").strip():
        contact_bits.append(company["phone"].strip())
    if contact_bits:
        lines.append(" | ".join(contact_bits))
    if (company.get("address") or "").strip():
        lines.append(company["address"].strip())
    return "\n".join(lines)


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

    subject = f"Your application with {company_name}: next steps"
    body = (
        f"Hi {first_name},\n\n"
        f"Thank you for completing your interview with {company_name}. "
        f"We reviewed your responses and would like to move forward with "
        f"your application to the next stage of our hiring process.\n\n"
        f"A member of our team will contact you shortly to coordinate the "
        f"details.\n\n"
        f"Best regards,\n"
        f"The {company_name} hiring team\n\n"
        f"{_company_footer(company)}"
    )
    return {"subject": subject, "body": body}


def default_invite_template(
    company: Dict[str, Any],
    candidate_name: str,
    apply_url: str,
) -> EmailTemplate:
    """Subject + body for a pre-application invitation.

    Sent by the company_admin from /admin/settings before the candidate
    has signed up. The body contains the public `/apply/{slug}` URL
    (constructed by the caller against `FRONTEND_BASE_URL`) so the
    candidate clicks through to the standard signup flow.

    `candidate_name` is whatever the admin typed in the invite form —
    may be empty if they only had an email. The template falls back to
    "Hi there," in that case, matching `default_shortlist_template`'s
    convention.
    """
    name = (candidate_name or "").strip()
    greeting_name = name.split()[0] if name else "there"
    company_name = (company.get("name") or "our team").strip() or "our team"

    subject = f"Interview invitation from {company_name}"
    body = (
        f"Hi {greeting_name},\n\n"
        f"You are invited to complete an interview with {company_name} as "
        f"part of our hiring process. The interview is voice-based, takes "
        f"about 20-30 minutes, and can be completed from any browser with "
        f"a microphone, at a time that suits you.\n\n"
        f"To begin, create your account using this link:\n"
        f"{apply_url}\n\n"
        f"Your responses go directly to the {company_name} hiring team for "
        f"review.\n\n"
        f"Best regards,\n"
        f"The {company_name} hiring team\n\n"
        f"{_company_footer(company)}"
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

    subject = f"An update on your application with {company_name}"
    body = (
        f"Hi {first_name},\n\n"
        f"Thank you for taking the time to interview with {company_name}. "
        f"After careful consideration, we have decided to move forward with "
        f"other candidates whose experience more closely matches our "
        f"current needs.\n\n"
        f"We appreciate the effort you put into the process and would be "
        f"glad to keep your details on file for future openings. We wish "
        f"you every success in your search.\n\n"
        f"Best regards,\n"
        f"The {company_name} hiring team\n\n"
        f"{_company_footer(company)}"
    )
    return {"subject": subject, "body": body}


# ---------------------------------------------------------------------------
# Plain text -> clean HTML (multipart sends, 2026-06-12)
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"(https?://[^\s<>\"]+)")

_HTML_SHELL = (
    '<div style="margin:0;padding:24px;background-color:#f6f7f9;">'
    '<div style="max-width:600px;margin:0 auto;padding:32px;'
    "background-color:#ffffff;border:1px solid #e5e7eb;border-radius:8px;"
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
    'Arial,sans-serif;font-size:15px;line-height:1.6;color:#1f2937;">'
    "{content}"
    "</div></div>"
)


def render_email_html(body: str) -> str:
    """Derive the HTML part of a multipart email from its plain-text body.

    Escape-first (the body may contain recruiter-typed `<`/`&` and, in
    principle, hostile content — it must never become live markup), then:
    - bare http(s) URLs become plain styled links (the apply link must be
      clickable in HTML clients),
    - blank-line-separated blocks become paragraphs, single newlines become
      <br/>,
    - the result sits in a minimal, neutral, inline-styled shell — no
    images, no buttons, no tracking markup: deliberately boring HTML that
    mirrors the text part 1:1, which is what spam filters like to see.
    """
    escaped = _html.escape(body or "", quote=False)
    linked = _URL_RE.sub(
        r'<a href="\1" style="color:#4f46e5;text-decoration:underline;">\1</a>',
        escaped,
    )
    paragraphs = [
        '<p style="margin:0 0 16px;">' + block.replace("\n", "<br/>") + "</p>"
        for block in linked.split("\n\n")
        if block.strip()
    ]
    return _HTML_SHELL.format(content="".join(paragraphs))
