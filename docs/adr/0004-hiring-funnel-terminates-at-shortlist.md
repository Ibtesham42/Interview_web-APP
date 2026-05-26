# Hiring Funnel terminates at Shortlist; "Hired" is out of scope

Status: accepted

The platform's Hiring Funnel — the sequence a Candidate moves through after
sign-up — has four Stages: **Signed up → Interview Started → Interview
Completed → Shortlisted**. There is no "Hired" Stage and no `hired_at`
timestamp, no `decision='hired'` enum value, and no Candidate-level boolean
that says a hire happened. Funnel analytics report counts and conversion
rates through the four Stages and stop there.

The alternatives were: (a) extend the Recruiter `Decision` enum to include
`'hired'`, terminating the funnel inside the platform; (b) the chosen scope —
funnel stops at Shortlist, hire-and-beyond is observed in the customer's ATS
or HRIS; (c) add a one-way `hired_at` timestamp on the Candidate as a separate
ratchet distinct from the per-Recruiter Decision.

We chose **(b)**. The product is the *AI Mock Interview Platform* (CLAUDE.md,
first line). The platform observes Candidate sign-up, interview execution,
scoring, and the Recruiter's review action. It does NOT observe offer letter
generation, offer acceptance, contract signing, or start date — those events
live in the customer's ATS / HRIS / email systems and the platform receives
no signal about them. Modeling "Hired" here means modeling state we do not
observe; that state decays into a lie the moment a Recruiter forgets to mark
it. The truth of "this Candidate is hired" already exists in another system
— our copy can only diverge.

This is the same scope-honesty principle that kept `.btn-google` out of the
Button primitive's `variant` union (UI polish C1, commit `d7757f6`) and that
deferred orchestrator state-restore until reliability data justified it
(ADR 0002). Build for the data you actually observe; do not pretend to
observe more.

## Consequences

- The Funnel Stages enum (in code, in CONTEXT.md, in the analytics endpoint
  response) is fixed at four values. Adding "Hired" later requires
  re-grilling this ADR and either retrofitting an enum value or introducing
  a new ratchet column.
- The "% of completed interviews that resulted in a hire" metric — a metric
  recruiters often want — is **not produceable from this platform alone**.
  Producing it requires an integration with the customer's ATS that
  back-reports hire events. That integration is a separate product
  decision, not a schema decision.
- The `recruiter_decisions.decision` enum is `'shortlisted' | 'rejected' |
  'undecided'`. Adding `'hired'` is an enum-widening migration that we
  decline at MVP.
- Conversion-rate analytics are clean and honest: signed-up → started,
  started → completed, completed → shortlisted. Each rate measures
  something the platform actually observes. No ratio in the funnel depends
  on a Recruiter remembering to flip a boolean.
- If a future customer integration (Greenhouse webhook, Lever API) brings
  hire signal into the platform, the right shape is probably a separate
  `external_hire_events` table — not a column on the Candidate — because
  the source-of-truth still lives elsewhere; this platform is a *cache*
  of that fact, not the canonical store.
