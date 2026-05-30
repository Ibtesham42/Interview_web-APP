# AI Mock Interview Platform

The shared language of the voice-first AI mock interview engine — the concepts
the interview orchestrator reasons about when it decides what to ask next.

## Language

**Phase**:
One of the five fixed stages of an interview (Background, Project Deep-Dive #1,
Project Deep-Dive #2, Technical Assessment, Behavioral). A phase is a coarse
agenda; it is not a depth.
_Avoid_: Stage, round, section.

**Topic**:
A single subject drilled within a phase — a specific resume project, a research
experience, or a technical area. A phase contains one or more topics.
_Avoid_: Subject, theme, area.

**Layer**:
The depth position of a question on a topic, L1–L5. L1 is a broad intro, L2
goes one level deeper, L3 probes decisions and reasoning, L4 probes edge cases
and architecture, L5 probes real-world failure, scaling and optimization. The
"Matryoshka doll" — each answered layer opens the next.
_Avoid_: Level, depth (as a noun for the layer number), drill stage.

**Matryoshka drilling**:
Asking progressively deeper layered questions on one topic, where each
follow-up emerges from the candidate's previous answer rather than from a
script.
_Avoid_: Socratic drilling, grilling.

**Step-down**:
Deliberately moving to a shallower layer (or an easier framing) when the
candidate cannot answer the current layer — as opposed to abandoning the topic.
The first response to a struggle.
_Avoid_: Pivot (a pivot leaves the topic; a step-down stays on it).

**Pivot**:
Abandoning the current topic and starting a fresh topic at L1. The second
response to sustained struggle, after a step-down has not recovered the
candidate.
_Avoid_: Step-down, switch (too vague).

## Roles &amp; workflow

**Candidate**:
The person who signs up, uploads a resume, and runs interviews. Owns their own
interview history and reports. Role string: `'user'` in `profiles.role` (legacy
name kept for backwards compatibility — the role *means* "candidate" everywhere
new code reasons about it).
_Avoid_: User (ambiguous — `auth.users` is the auth-layer concept; "candidate"
is the domain actor).

**Admin**:
Platform operator. Reads platform-wide analytics across all Companies (user
counts, completion rates, average scores per field). Tenant-agnostic — has
no Company affiliation (NULL `company_id`). Their lens is the system, not the
hiring funnel. Inherits Recruiter capabilities via role-gating but cannot
perform Company-scoped actions (invite a Candidate, manage Company Settings)
without a tenant context — the distinction surfaces in the capability gates
(see ADR 0006). Role string: `'admin'`.
_Avoid_: Owner, Superuser, "Platform admin" (use "Admin"; "platform admin"
is documentation-only when distinguishing from Company Admin).

**Recruiter**:
Workflow operator who reviews completed interviews and decides which Candidates
to advance. Acts ON Candidates via the recruiter workflow (Shortlist, Reject,
Bookmark, Recruiter Notes). Distinct from Admin because the *job* is different
— Admin sees the platform; Recruiter sees the candidate pool **scoped to the
Recruiter's Company** (a Recruiter at Acme cannot see Wayne Enterprises'
Candidates). Admin and Company Admin both inherit Recruiter capabilities via
role-gating; every workflow action carries the actor's identity so
accountability survives the overlap. Role string: `'recruiter'` (kept as-is;
the planned rename to `'company_recruiter'` was deferred — see the
migration 005 header for the deviation note).
_Avoid_: Reviewer (overloaded with the AI evaluator's review of an answer),
Hiring manager (a downstream role we don't model).

**Decision**:
A Recruiter's stance on a Candidate: one of `Shortlisted`, `Rejected`,
`On Hold`, or `Undecided` (default). Mutually exclusive. Per-Recruiter,
per-Candidate — two Recruiters can hold opposite Decisions on the same
Candidate simultaneously. `Shortlisted` and `Rejected` are terminal (they
stamp a decided-at time); `On Hold` is a deliberate but reversible parked
state, `Undecided` is the absence of a decision.
_Avoid_: Verdict, Status (Status is the derived candidate-facing label —
see Candidate Status — not the Decision itself).

**On Hold**:
The non-terminal "parked for later" Decision — the Recruiter has neither
advanced nor declined the Candidate but wants them flagged as actively
deferred (distinct from the never-touched `Undecided` default). Reversible;
sends no email.
_Avoid_: Pending, Waitlist, Maybe.

**Candidate Status**:
The single human-readable label shown when reviewing a Candidate:
`Invited`, `Interview Completed`, `Shortlisted`, `Rejected`, or `On Hold`.
DERIVED, not stored — it is the reviewer's terminal/parked Decision when one
exists, otherwise the Candidate's furthest Funnel Stage (Interview Completed
vs Invited). The Shortlist/Reject/Hold actions on the review screen set the
underlying Decision; Status is the read-side projection of it.
_Avoid_: State, Stage (Stage is the Funnel position; Status folds Decision
over it).

**Shortlist**:
The terminal positive Decision — a Recruiter has marked this Candidate as
worth advancing. Verb: "to shortlist a Candidate." Noun: "the shortlist" =
the set of Candidates in the Shortlisted state for the current Recruiter.
_Avoid_: Approve, Accept, Select.

**Reject**:
The terminal negative Decision — a Recruiter has decided this Candidate will
not advance. Reversible (can be set back to Undecided).
_Avoid_: Decline, Drop, Pass.

**Bookmark**:
An orthogonal flag a Recruiter attaches to a Candidate to track them for
later. Independent of Decision — a Candidate can be Bookmarked AND
Shortlisted, or Bookmarked AND Undecided. Per-Recruiter.
_Avoid_: Favorite, Star, Pin.

**Recruiter Note**:
Free-form text a Recruiter attaches to a Candidate. Per-Recruiter (one
Recruiter's Notes are not visible to another). Overwritable; no version
history at MVP.
_Avoid_: Comment (suggests a thread), Memo.

**Hiring Funnel**:
The platform-observable sequence a Candidate moves through, from sign-up to
Shortlist. Four ordered Funnel Stages: Signed up → Interview Started →
Interview Completed → Shortlisted. The platform deliberately stops at
Shortlist — what happens after (offer, hire, start date) is in the
Recruiter's ATS, not here (see ADR 0004).
_Avoid_: Pipeline (overloaded with the interview engine's processing pipeline),
Workflow (too generic).

**Funnel Stage**:
One of the four positions in the Hiring Funnel. A Candidate is at exactly one
Stage at any time — the *furthest* one they have reached. Movement is
one-way (a Candidate at Shortlisted is also implicitly past Completed,
Started, and Signed up). "Rejected" is NOT a Funnel Stage — it is a Decision
branch off Completed, distinct from forward funnel progression.
_Avoid_: Phase (collides with the interview engine's Phase 1–5),
Step, Status (already overloaded with `interviews.status`).

## Multi-tenant

The platform supports multiple Companies on one deployment. This section
captures the multi-tenant vocabulary added by the 2026-05-27 rollout. See
ADR 0005 for the schema decisions.

**Company** (a.k.a. Tenant):
A hiring organization with its own Candidates, Recruiters, and Apply Link.
Created via `/companies/signup` by a `'user'` who flips to `'company_admin'`
on creation. Identified by an immutable UUID + a human-readable Slug. A
Candidate belongs to exactly one Company (or to no Company if B2C).
_Avoid_: Tenant — use Company in domain conversation; "tenant" survives as
an architecture term (e.g. tenant-scoped query, `TenantContext`) but the
*noun* is a Company. Also avoid: Org, Workspace, Account (ambiguous with
`auth.users`).

**Company Admin**:
The Admin of one specific Company. Operates ONLY within their Company —
sees their Candidates, manages their Settings (Apply Link, contact info),
invites Candidates, and inherits Recruiter capabilities (Shortlist / Reject
/ Bookmark / Notes) within that Company. Distinct from Admin (platform):
the Company Admin's lens is one tenant's hiring funnel, not the system as
a whole. Role string: `'company_admin'`. Created by `/companies/signup`;
never inhabits more than one Company at a time.
_Avoid_: Owner, Tenant admin, Workspace admin.

**Apply Link**:
The public URL `/apply/{slug}` that a Company shares with prospective
Candidates. Visiting the link lands on a no-auth page showing the Company's
name + contact info; clicking Apply routes to `/signup?company={slug}`,
which stamps the new Candidate's profile with the Company's id on signup.
The Slug is chosen at Company creation and is part of the schema contract
— renaming a Slug breaks outstanding links.
_Avoid_: Invite URL (Apply Link is shared broadly; the Invite is a
per-Candidate email — see below), Application page, Job link (we don't
model jobs yet).

**Invite**:
A per-Candidate email sent via `POST /api/companies/invite`, addressed
to one specific email address and carrying the same Apply Link URL the
public landing exposes. Distinct from the Apply Link by *audience*: the
Apply Link is broadcast (a Recruiter posts it on LinkedIn, embeds it in
a careers page), the Invite is targeted (a Recruiter says "I want this
specific person to apply"). Both flows terminate at the same
`/apply/{slug}` page; the Invite simply puts the URL in front of one
named recipient. Audit-logged in `email_outbox` with
`candidate_id IS NULL` (the recipient hasn't signed up yet); the
candidate appears in the tenant's pool only once they complete signup
through the link. Capability: `'invite_candidate'` (HIRING_ROLES with a
tenant — see [[capability_module]] / ADR 0006).
_Avoid_: Invitation (too generic — every email is an "invitation" of
some sort), Invite URL (the URL belongs to the Apply Link; the Invite
is the act of emailing it), Outreach (overloaded — the
shortlist-email is also outreach but a different action against an
existing Candidate).



- "Depth" was overloaded: the evaluation rubric scores a 0–10 **depth dimension**
  of an answer's quality, which is distinct from the 1–5 **Layer** the question
  sits at. Use "depth score" for the former, "Layer" for the latter.
- "User" is overloaded between `auth.users` (the Supabase auth-layer table) and
  the domain notion of "Candidate". When discussing the hiring/workflow domain,
  prefer "Candidate" and reserve "User" for the auth layer.

## Example dialogue

> **Dev:** When the candidate nails an L3 question, we go to L4?
> **Domain expert:** Right — a good answer opens the next Layer of the same
> Topic. The doll opens inward.
> **Dev:** And if they freeze at L4?
> **Domain expert:** Step down to L3, don't pivot. A pivot abandons the Topic
> entirely; a step-down keeps them on it at a comfortable Layer. We only pivot
> or end the Phase after repeated struggle.
