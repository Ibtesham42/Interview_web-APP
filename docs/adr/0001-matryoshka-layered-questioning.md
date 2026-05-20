# Matryoshka layered questioning

The interview engine drills each topic through five fixed layers — L1 broad
intro, L2 deeper, L3 decisions/reasoning, L4 edge cases/architecture, L5
real-world/scaling/failure — like nested Russian dolls: each good answer opens
the next layer. The layer pointer is a **deterministic state machine in
Python**, not the LLM's self-report: the orchestrator owns `current_layer` and
`current_topic` in `PhaseState`, climbs a layer on a strong answer and steps
down on a weak one, then tells a single generation LLM call exactly which
layer and topic to ask. This applies in full to the Project Deep-Dive phases
(2–3) and as a light 2-layer mini-drill to phases 4–5.

We also reversed the previous deliberate "STRICT RULES" cold-interrogator
prompt in favour of a warm, conversational register, because the layered
de-escalation (step-down → pivot → end phase) only reads as supportive rather
than as failure if the interviewer has a warm voice to deliver it in.

## Considered options

- **LLM-driven layering** — trust the evaluation's self-reported `drill_level`
  to pick the next layer. Rejected: the layer is a state-machine contract
  (drives generation, de-escalation, scoring); LLM turn-to-turn noise made it
  unpredictable and undebuggable.
- **A dedicated planning LLM call** each turn. Rejected: a third LLM call per
  turn harms voice turnaround, and the evaluation call already emits every
  signal the deterministic plan needs.
- **Keeping the cold prompt.** Rejected: it directly contradicts the goal of a
  human-led, non-interrogative interview.

## Consequences

- Phase 2/3 `overall` gains a layer-depth term
  (`min(max_layer,5)/5 * 0.2`). To keep dashboard/admin trend lines truthful,
  this is **forward-only**: `compute_phase_scores` applies the layer-aware
  formula only when an evaluation row carries `details.layer`; historical
  interviews keep their original formula and their displayed scores never move.
- `_extract_topic_from_question` (a hardcoded ML-keyword matcher) is retired in
  favour of orchestrator-owned `current_topic`, which is what makes the engine
  work for non-software domains.
- Domains outside the 9 curated `FIELD_PROMPTS` entries are LLM-derived at
  orchestrator init (in-memory cached) so any field — business, design,
  marketing, research, management — works without a hardcoded table.
