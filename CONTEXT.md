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

## Flagged ambiguities

- "Depth" was overloaded: the evaluation rubric scores a 0–10 **depth dimension**
  of an answer's quality, which is distinct from the 1–5 **Layer** the question
  sits at. Use "depth score" for the former, "Layer" for the latter.

## Example dialogue

> **Dev:** When the candidate nails an L3 question, we go to L4?
> **Domain expert:** Right — a good answer opens the next Layer of the same
> Topic. The doll opens inward.
> **Dev:** And if they freeze at L4?
> **Domain expert:** Step down to L3, don't pivot. A pivot abandons the Topic
> entirely; a step-down keeps them on it at a comfortable Layer. We only pivot
> or end the Phase after repeated struggle.
