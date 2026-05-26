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
Platform operator. Reads platform-wide analytics (user counts, completion rates,
average scores per field). Does NOT operate on candidates as a recruiter would
— their lens is the system, not the hiring funnel. Role string: `'admin'`.
_Avoid_: Owner, superuser.

**Recruiter**:
Workflow operator who reviews completed interviews and decides which candidates
to advance. Acts ON candidates via the recruiter workflow (Shortlist, Reject,
Bookmark, recruiter Notes). Distinct from Admin because the *job* is different
— Admin sees the platform; Recruiter sees the candidate pool. Admins MAY
inherit Recruiter capabilities via additive role-gating, but every workflow
action carries the actor's identity so accountability survives the overlap.
Role string: `'recruiter'`.
_Avoid_: Reviewer (overloaded with the AI evaluator's review of an answer),
Hiring manager (a downstream role we don't model).

**Decision**:
A Recruiter's stance on a Candidate: one of `Shortlisted`, `Rejected`, or
`Undecided` (default). Mutually exclusive. Per-Recruiter, per-Candidate — two
Recruiters can hold opposite Decisions on the same Candidate simultaneously.
_Avoid_: Verdict, Status (Status is already overloaded with interview status).

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

## Flagged ambiguities

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
