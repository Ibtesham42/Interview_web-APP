from typing import Dict, Any, List, Optional
from uuid import UUID
from enum import Enum
from dataclasses import dataclass

from app.config import get_settings, get_groq_client
from app.services.groq_async import acompletion, atranscription
from app.supabase_client import get_supabase

settings = get_settings()


# Field-specific role prompts
FIELD_PROMPTS = {
    "ml": {
        "role": "ML Engineer",
        "topics": "machine learning, deep learning, neural networks, MLOps, model deployment, data pipelines",
        "technical_questions": "gradient descent, regularization, bias-variance, neural networks, transformers, CNNs, RNNs, model optimization, feature engineering"
    },
    "nlp": {
        "role": "NLP Engineer",
        "topics": "natural language processing, LLMs, text analysis, transformers, sentiment analysis, text generation",
        "technical_questions": "tokenization, embeddings, attention mechanism, transformers, BERT, GPT, fine-tuning, text classification, NER"
    },
    "cv": {
        "role": "Computer Vision Engineer",
        "topics": "computer vision, image processing, object detection, segmentation, image classification",
        "technical_questions": "CNNs, object detection, YOLO, image segmentation, feature extraction, image classification, video analysis"
    },
    "data_science": {
        "role": "Data Scientist",
        "topics": "data analysis, statistics, visualization, predictive modeling, business intelligence",
        "technical_questions": "statistical analysis, hypothesis testing, regression, classification, A/B testing, data visualization, feature engineering"
    },
    "web_dev": {
        "role": "Full Stack Developer",
        "topics": "web development, frontend, backend, APIs, databases, REST/GraphQL",
        "technical_questions": "JavaScript, React, Node.js, databases, REST APIs, authentication, performance optimization, web security"
    },
    "mobile": {
        "role": "Mobile Developer",
        "topics": "iOS, Android, React Native, Flutter, mobile app development",
        "technical_questions": "Swift, Kotlin, Flutter, React Native, mobile UI, performance, app store deployment, offline first"
    },
    "devops": {
        "role": "DevOps Engineer",
        "topics": "CI/CD, cloud infrastructure, containers, monitoring, automation",
        "technical_questions": "Docker, Kubernetes, AWS/GCP, CI/CD pipelines, infrastructure as code, monitoring, cloud architecture"
    },
    "backend": {
        "role": "Backend Developer",
        "topics": "server-side development, APIs, databases, microservices, caching",
        "technical_questions": "Python/Node.js, REST/GraphQL, PostgreSQL, Redis, microservices, API design, authentication, scaling"
    },
    "general": {
        "role": "Software Engineer",
        "topics": "software development, programming, system design, problem solving",
        "technical_questions": "data structures, algorithms, system design, coding patterns, software architecture"
    }
}

class InterviewPhase(Enum):
    PHASE_1_BACKGROUND = 1
    PHASE_2_PROJECT_DEEPDIVE = 2
    PHASE_3_SECOND_PROJECT = 3
    PHASE_4_TECHNICAL = 4
    PHASE_5_BEHAVIORAL = 5


PHASE_NAMES = {
    1: "Background Introduction",
    2: "Project Deep-Dive #1",
    3: "Project Deep-Dive #2",
    4: "Technical Assessment",
    5: "Behavioral Questions"
}

PHASE_WEIGHTS = {
    2: 0.30,  # Project Deep-Dive #1
    3: 0.25,  # Project Deep-Dive #2
    4: 0.30,  # Technical Assessment
    5: 0.15   # Behavioral Questions
}


def compute_phase_scores(evaluations: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Aggregate raw evaluation rows into per-phase score summaries.

    Pure function over already-fetched evaluation rows — shared by the detailed
    report and the dashboard/admin aggregations so an interview always yields
    the same scores everywhere, with no per-interview database round-trips.
    """
    phase_evaluations: Dict[int, List[Dict]] = {1: [], 2: [], 3: [], 4: [], 5: []}
    for eval_row in evaluations:
        phase = eval_row.get("phase")
        if phase in phase_evaluations:
            phase_evaluations[phase].append(eval_row)

    # Layer-aware (post-Matryoshka) interviews carry `layer` in details. The
    # layer-aware deep-dive formula applies ONLY to these; historical
    # interviews keep their original formula so past scores never move
    # (ADR 0001 — forward-only scoring).
    layer_aware = any(
        isinstance(e.get("details"), dict) and e["details"].get("layer") is not None
        for e in evaluations
    )

    phase_scores: Dict[int, Dict[str, Any]] = {}
    for phase, evals in phase_evaluations.items():
        if not evals:
            continue

        if phase == 1:
            relevances = [e.get("details", {}).get("relevance", 0) for e in evals if e.get("details")]
            specificities = [e.get("details", {}).get("specificity", 0) for e in evals if e.get("details")]
            clarities = [e.get("details", {}).get("clarity", 0) for e in evals if e.get("details")]
            depths = [e.get("details", {}).get("depth", 0) for e in evals if e.get("details")]
            avg_relevance = sum(relevances) / len(relevances) if relevances else 0
            avg_specificity = sum(specificities) / len(specificities) if specificities else 0
            avg_clarity = sum(clarities) / len(clarities) if clarities else 0
            avg_depth = sum(depths) / len(depths) if depths else 0
            phase_scores[phase] = {
                "relevance_score": round(avg_relevance, 2),
                "specificity_score": round(avg_specificity, 2),
                "clarity_score": round(avg_clarity, 2),
                "depth_score": round(avg_depth, 2),
                "overall": round((avg_relevance * 0.25 + avg_specificity * 0.25
                                  + avg_clarity * 0.2 + avg_depth * 0.3), 2),
            }
        elif phase in [2, 3]:
            depths = [e.get("depth_score", 0) for e in evals if e.get("depth_score") is not None]
            accuracies = [e.get("accuracy_score", 0) for e in evals if e.get("accuracy_score") is not None]
            clarities = [e.get("details", {}).get("clarity", 0) for e in evals if e.get("details")]
            avg_depth = sum(depths) / len(depths) if depths else 0
            avg_accuracy = sum(accuracies) / len(accuracies) if accuracies else 0
            avg_clarity = sum(clarities) / len(clarities) if clarities else 0
            if layer_aware:
                # Layer-aware deep-dive score: depth/accuracy/clarity plus a
                # term for the deepest Matryoshka layer reached. The layer term
                # is on the same 0-10 scale as the others
                # (min(max_layer,5)/5*10) — clamped so historical drill_level
                # data cannot overshoot; weights sum to 1.0.
                layers = [
                    (e.get("details") or {}).get("layer", 0) or 0
                    for e in evals if isinstance(e.get("details"), dict)
                ]
                max_layer = max(layers) if layers else 0
                layer_score = min(max_layer, 5) / 5 * 10
                overall = round(avg_depth * 0.4 + avg_accuracy * 0.25
                                + avg_clarity * 0.15 + layer_score * 0.2, 2)
                phase_scores[phase] = {
                    "depth_score": round(avg_depth, 2),
                    "accuracy_score": round(avg_accuracy, 2),
                    "clarity_score": round(avg_clarity, 2),
                    "max_layer": max_layer,
                    "overall": overall,
                }
            else:
                # Original formula — unchanged for historical interviews.
                phase_scores[phase] = {
                    "depth_score": round(avg_depth, 2),
                    "accuracy_score": round(avg_accuracy, 2),
                    "clarity_score": round(avg_clarity, 2),
                    "overall": round((avg_depth * 0.5 + avg_accuracy * 0.3 + avg_clarity * 0.2), 2)
                    if (depths or clarities) else round((avg_depth * 0.7 + avg_accuracy * 0.3), 2),
                }
        elif phase == 4:
            accuracies = [e.get("accuracy_score", 0) for e in evals if e.get("accuracy_score")]
            overall = sum(accuracies) / len(accuracies) if accuracies else 0
            phase_scores[phase] = {
                "correct_answers": sum(1 for a in accuracies if a >= 7),
                "total_questions": len(accuracies),
                "overall": round(overall, 2),
            }
        elif phase == 5:
            scores = {"vision": [], "team": [], "self_awareness": [], "proactivity": [], "communication": []}
            for e in evals:
                details = e.get("details", {})
                for k in scores:
                    if k in details:
                        scores[k].append(details[k])
            phase_scores[phase] = {
                k: round(sum(v) / len(v), 2) if v else 0 for k, v in scores.items()
            }
            all_vals = [v for vals in scores.values() for v in vals]
            phase_scores[phase]["overall"] = round(sum(all_vals) / len(all_vals), 2) if all_vals else 0

    return phase_scores


def compute_final_score(phase_scores: Dict[int, Dict[str, Any]]) -> float:
    """Final weighted score across the assessed phases (2-5)."""
    total_weighted = 0
    total_weight = 0
    for phase, weight in PHASE_WEIGHTS.items():
        if phase in phase_scores:
            total_weighted += phase_scores[phase].get("overall", 0) * weight
            total_weight += weight
    return round(total_weighted / total_weight, 2) if total_weight > 0 else 0


def recommendation_for(final_score: float) -> str:
    """Map a final score to a hiring recommendation."""
    if final_score >= 8.5:
        return "Strong Hire"
    if final_score >= 7.0:
        return "Hire"
    if final_score >= 5.5:
        return "Hold"
    return "No Hire"


def score_interviews_bulk(supabase, interview_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Score many interviews from a SINGLE evaluations query.

    Used by the dashboard and admin aggregations instead of generating a full
    report per interview. Returns {interview_id: {"score", "questions"}}.
    """
    if not interview_ids:
        return {}
    evals = (
        supabase.table("evaluations")
        .select("interview_id,phase,depth_score,accuracy_score,details")
        .in_("interview_id", interview_ids)
        .execute()
        .data
        or []
    )
    by_interview: Dict[str, List[Dict]] = {}
    for row in evals:
        by_interview.setdefault(row["interview_id"], []).append(row)

    result: Dict[str, Dict[str, Any]] = {}
    for iv_id in interview_ids:
        rows = by_interview.get(iv_id, [])
        result[iv_id] = {
            "score": compute_final_score(compute_phase_scores(rows)),
            "questions": len(rows),
        }
    return result


# Matryoshka layer model — one canonical 5-layer scale (see ADR 0001). Each
# entry describes, in plain language, the question to ask at that depth. The
# deterministic layer engine picks the layer; the single generation LLM call
# only phrases it.
LAYER_GUIDE: Dict[int, str] = {
    1: "a broad, open question that lets the candidate introduce the topic in "
       "their own words",
    2: "a deeper question about how it actually works and what the candidate "
       "specifically did",
    3: "a question that probes their decisions and reasoning — why this "
       "approach, what alternatives they weighed, what the tradeoffs were",
    4: "a question about edge cases and architecture — failure modes, "
       "limitations, and how the pieces fit together",
    5: "a question about real-world complexity — scaling, optimization, "
       "production failures, and what they would change with hindsight",
}


@dataclass
class PhaseState:
    """Track state for the current interview phase.

    The Matryoshka layer engine (`InterviewOrchestrator._apply_layer_engine`)
    is a deterministic state machine over these fields: it advances
    `current_layer` on strong answers, steps it down on weak ones, records the
    deepest layer reached for scoring, and runs the 3-strike de-escalation
    cascade. `pending_action` is the single instruction `generate_question`
    reads to phrase the next question.
    """
    phase: int
    questions_asked: int = 0
    # --- Matryoshka layer engine -------------------------------------------
    current_layer: int = 1            # layer (L1-L5) of the NEXT question
    current_topic: Optional[str] = None   # topic being drilled (deep-dive phases)
    max_layer_reached: int = 0        # deepest layer answered well — feeds scoring
    struggle_streak: int = 0          # consecutive weak answers — 3-strike cascade
    topic_count: int = 0              # topics opened in this phase
    topic_complete: bool = False      # current topic drilled to L5 with a strong answer
    pending_action: str = "deepen"    # deepen | hold | step_down | pivot | new_topic
                                      # | complete_topic | next_area | end_phase
    # --- legacy adaptive signals (still written by the evaluators) ----------
    phase_complete: bool = False
    last_answer_depth: int = 0
    consecutive_struggles: int = 0
    consecutive_superficial: int = 0


# Explicit, unambiguous commands that end the interview. Every phrase contains
# the word "interview" on purpose — generic phrases like "that's all" or
# "I'm done" occur naturally inside real answers and must NOT end the session.
END_INTERVIEW_KEYWORDS = ["end interview", "end the interview", "end this interview",
                          "stop interview", "stop the interview", "stop this interview",
                          "quit interview", "quit the interview",
                          "finish interview", "finish the interview"]

# Weak/insufficient response patterns
WEAK_RESPONSE_PATTERNS = ["no", "nope", "nothing", "none", "idk", "i don't know",
                          "i have no idea", "not sure", "maybe", "i'm not sure",
                          "i don't remember", "can't remember", "skip", "pass", "next"]

# Non-answer patterns - immediate low score
NON_ANSWER_PATTERNS = [
    "any", "anything", "none", "no", "nope", "idk", "idk",
    "repeat", "what", "huh", "what's that", "say again",
    "skipped", "passed", "pass", "next question",
    "i don't have", "i don't know", "no experience",
    "not applicable", "n/a", "na", "zero", "0"
]

# Question repetition - user is confused or mocking
QUESTION_REPETITION_PATTERNS = ["?", "why", "what do you mean", "explain", "clarify"]


class InterviewOrchestrator:
    """Orchestrates the 5-phase interview conversation with Socratic method."""

    def __init__(self, interview_id: UUID, candidate_data: Optional[Dict] = None):
        self.interview_id = interview_id
        self.client = get_groq_client()
        self._supabase = None
        self.current_phase = 1
        self.conversation_history: List[Dict[str, str]] = []
        self.phase_state = PhaseState(phase=1)
        self.candidate_data = candidate_data or {}

        # Interview control state
        self._questions_asked: List[str] = []  # Track all questions to avoid repetition
        self._final_question_asked: bool = False  # Track if final question was asked
        self._total_responses: int = 0  # Count of candidate responses

        # Matryoshka support: domain info resolved once (hybrid: curated table
        # or LLM-derived), and a cursor over the candidate's resume projects so
        # each deep-dive phase drills a different one.
        self._field_info: Optional[Dict[str, str]] = None
        self._project_cursor: int = 0

        # Load interview from DB if ID is valid
        if interview_id:
            self._load_interview()

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase()
        return self._supabase

    def _load_interview(self):
        try:
            result = self.supabase.table("interviews").select("*").eq("id", str(self.interview_id)).execute()
            if result.data:
                interview = result.data[0]
                self.current_phase = interview.get("current_phase", 1)
                self.conversation_history = interview.get("conversation_history", [])
        except Exception:
            pass

    def _save_conversation(self):
        try:
            self.supabase.table("interviews").update({
                "conversation_history": self.conversation_history,
                "current_phase": self.current_phase,
                "status": f"phase_{self.current_phase}"
            }).eq("id", str(self.interview_id)).execute()
        except Exception:
            pass

    def should_end_interview(self, answer: str) -> bool:
        """Detect an explicit request to end the interview.

        This is deliberately conservative. A genuine end command is short and
        explicit; a real interview answer is not. Gating on length prevents a
        long answer that merely mentions "the interview" from ending the
        session. The UI also exposes an explicit End button.
        """
        answer_lower = answer.lower().strip().rstrip(".!?")
        if len(answer_lower.split()) > 7:
            return False
        for keyword in END_INTERVIEW_KEYWORDS:
            if keyword in answer_lower:
                return True
        return False

    def is_weak_response(self, answer: str) -> bool:
        """Check if the answer is too weak/insufficient."""
        answer_lower = answer.lower().strip()

        # Check for non-answer patterns
        for pattern in NON_ANSWER_PATTERNS:
            if answer_lower == pattern or answer_lower.startswith(pattern + " "):
                return True

        # Check for weak patterns
        for pattern in WEAK_RESPONSE_PATTERNS:
            if answer_lower == pattern or answer_lower.startswith(pattern + " "):
                return True

        # Check if answer is just repeating the question (user confused)
        if self.conversation_history and len(self.conversation_history) > 0:
            last_question = None
            for msg in reversed(self.conversation_history):
                if msg.get("role") == "assistant":
                    last_question = msg.get("content", "").lower()
                    break
            if last_question and (answer_lower in last_question or answer_lower == last_question.rstrip('?.')):
                return True

        # Also consider very short answers (< 5 words) as potentially weak
        if len(answer.split()) < 5 and len(answer) < 20:
            return True
        return False

    def evaluate_weak_response(self, answer: str) -> Dict[str, Any]:
        """Return evaluation scores for weak/non-answers with low scores."""
        answer_lower = answer.lower().strip()

        # Check what type of weak response
        if any(answer_lower == p or answer_lower.startswith(p + " ") for p in NON_ANSWER_PATTERNS):
            return {"depth": 1, "correctness": 1, "clarity": 1, "relevance": 1, "specificity": 1, "reason": "non_answer"}
        elif any(answer_lower == p or answer_lower.startswith(p + " ") for p in WEAK_RESPONSE_PATTERNS):
            return {"depth": 2, "correctness": 2, "clarity": 3, "relevance": 2, "specificity": 1, "reason": "weak_answer"}
        elif len(answer.split()) < 5:
            return {"depth": 3, "correctness": 3, "clarity": 4, "relevance": 3, "specificity": 2, "reason": "too_short"}
        else:
            return {"depth": 4, "correctness": 4, "clarity": 4, "relevance": 4, "specificity": 3, "reason": "shallow"}

    def is_question_duplicate(self, question: str) -> bool:
        """Check if this question has already been asked (avoid repetition)."""
        # Normalize question for comparison
        normalized = question.lower().strip()
        # Remove trailing punctuation
        normalized = normalized.rstrip('?.')

        for asked_q in self._questions_asked:
            asked_normalized = asked_q.lower().strip().rstrip('?.')
            # Check for high similarity (first 50 chars should match)
            if len(normalized) > 30 and len(asked_normalized) > 30:
                if normalized[:50] == asked_normalized[:50]:
                    return True
            # Exact match after normalization
            elif normalized == asked_normalized:
                return True
        return False

    def mark_final_question_asked(self):
        """Mark that the final question has been asked."""
        self._final_question_asked = True

    def get_question_stats(self) -> Dict[str, int]:
        """Get statistics about questions and responses."""
        return {
            "total_questions": len(self._questions_asked),
            "total_responses": self._total_responses,
            "current_phase": self.current_phase,
            "final_question_asked": self._final_question_asked
        }

    def add_message(self, role: str, content: str):
        self.conversation_history.append({"role": role, "content": content})
        self._save_conversation()

    def get_resume_context(self) -> str:
        """Get resume context for personalized questions.

        Skills are included so the interviewer prompt can steer to what the
        candidate actually claims experience in (React / SEO / Figma / etc.)
        — without them, the prompt knows only the broad domain label and can
        drift into generic-domain questions that ignore the resume.
        """
        if not self.candidate_data:
            return ""

        context = []
        resume_sections = self.candidate_data.get("resume_sections") or {}

        skills = resume_sections.get("skills") or []
        if isinstance(skills, list) and skills:
            labels: List[str] = []
            for s in skills[:20]:
                if isinstance(s, dict):
                    label = (s.get("name") or s.get("skill") or s.get("category")
                             or str(next(iter(s.values()), "")))
                else:
                    label = str(s)
                label = " ".join(str(label).split()).strip()
                if label:
                    labels.append(label[:60])
            if labels:
                context.append(f"Candidate's skills: {', '.join(labels)}")

        if resume_sections.get("projects"):
            projects = resume_sections["projects"]
            if isinstance(projects, list) and len(projects) > 0:
                context.append(f"Candidate's projects: {projects[:2]}")

        if resume_sections.get("experience"):
            exp = resume_sections["experience"]
            if isinstance(exp, list) and len(exp) > 0:
                context.append(f"Candidate's experience: {exp[0]}")

        field_spec = self.candidate_data.get("field_specialization") or "general"
        context.append(f"Field specialization: {field_spec}")

        return "\n".join(context)

    async def _resolve_field_info(self) -> Dict[str, str]:
        """Resolve the candidate's domain to {role, topics, technical_questions}.

        Hybrid (ADR 0001): the 9 curated FIELD_PROMPTS entries are a zero-risk
        fast path; any other domain is LLM-derived once and cached in-memory on
        this orchestrator, so business / design / marketing / research /
        management — any field — works without a hardcoded table.

        Async since PR 7 — the LLM-derive branch awaits a Groq call.
        """
        if self._field_info is not None:
            return self._field_info
        field_spec = (self.candidate_data.get("field_specialization") or "general").lower()
        if field_spec in FIELD_PROMPTS:
            self._field_info = FIELD_PROMPTS[field_spec]
        else:
            self._field_info = await self._derive_field_info(field_spec)
        return self._field_info

    async def _derive_field_info(self, field_spec: str) -> Dict[str, str]:
        """LLM-derive role/topics for a domain not in the curated table."""
        pretty = field_spec.replace("_", " ").replace("-", " ").strip().title() or "General"
        try:
            prompt = (
                f'A candidate is interviewing for a role in the domain "{field_spec}". '
                "Respond with JSON only, no prose, using exactly these keys: "
                '"role" (the job title an interviewer for this domain would hold), '
                '"topics" (a comma-separated list of subject areas to explore), '
                '"technical_questions" (a comma-separated list of specific '
                "concepts or skills to probe). Keep each value concise."
            )
            response = await acompletion(
                self.client,
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
            )
            import json, re
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            data = json.loads(content)
            return {
                "role": str(data.get("role") or f"{pretty} Professional").strip(),
                "topics": str(data.get("topics") or f"{pretty} fundamentals").strip(),
                "technical_questions": str(
                    data.get("technical_questions") or f"core {pretty} concepts"
                ).strip(),
            }
        except Exception as e:
            print(f"[Orchestrator] field-info derivation failed for '{field_spec}': {e}")
            return {
                "role": f"{pretty} Professional",
                "topics": f"{pretty} fundamentals, practical experience, problem solving",
                "technical_questions": (
                    f"core {pretty} concepts, real-world application, decision-making"
                ),
            }

    def _resume_project_labels(self) -> List[str]:
        """Short, human labels for the candidate's resume projects."""
        sections = self.candidate_data.get("resume_sections") or {}
        projects = sections.get("projects") or []
        labels: List[str] = []
        if isinstance(projects, list):
            for proj in projects:
                if isinstance(proj, dict):
                    label = (proj.get("name") or proj.get("title")
                             or proj.get("project") or "")
                    if not label:
                        label = str(next(iter(proj.values()), ""))
                else:
                    label = str(proj)
                label = " ".join(str(label).split()).strip()
                if label:
                    labels.append(label[:80])
        return labels

    async def get_interviewer_prompt(self, phase: int) -> str:
        """Return the system prompt for the interviewer for the given phase.

        Warm-professional register (ADR 0001): supportive and conversational,
        never a cold interrogation. The per-turn layer/topic directive is built
        separately by `_build_question_directive`.

        Async since PR 7 — _resolve_field_info may await a Groq call.
        """
        resume_context = self.get_resume_context()
        field_info = await self._resolve_field_info()
        role = field_info["role"]
        topics = field_info["topics"]
        technical_questions = field_info["technical_questions"]
        field_spec = self.candidate_data.get("field_specialization") or "general"

        base_prompt = f"""You are a senior {role} conducting a friendly, professional mock interview. You are warm, genuinely curious, and encouraging — you put the candidate at ease while still probing for real depth.

CONVERSATIONAL STYLE:
- Acknowledge the candidate's previous answer naturally before the next question — reference something specific they said (e.g. "Right, so the indexing was the bottleneck — ...").
- Sound human and conversational, never robotic. Avoid clipped replies like "Next." or "Understood."
- Be supportive, but do NOT inflate with empty hype ("amazing", "brilliant") and NEVER reveal scores or evaluations.
- Ask exactly ONE question per message. Never stack two questions.
- Keep each question concise (under 35 words) and specific.
- Build every question on what the candidate just said — the interview should feel like one evolving conversation, not a checklist.

MATRYOSHKA DEPTH MODEL:
Topics are explored in nested layers, L1 (broad) to L5 (real-world depth). You will be told which layer to ask at on each turn — follow that guidance precisely and let each question grow from the candidate's last answer. If the candidate struggles, you will be told to ease off; do so gracefully, so it never feels like a failure.

INTERVIEW FOCUS — {topics}
RELEVANT TECHNICAL GROUND — {technical_questions}
"""

        phase_prompts = {
            1: base_prompt + f"""
PHASE 1 — Background & warm-up.
Resume context: {resume_context}

A short, friendly warm-up to settle the candidate in. Ask about their background, what they enjoy working on, and the tools they use day to day. Keep it light and brief — this phase is just a few questions before the interview goes deeper.
""",
            2: base_prompt + f"""
PHASE 2 — Project Deep-Dive.
Resume context: {resume_context}

Explore ONE substantial project from the candidate's background in layered depth — starting broad, then progressively deeper into how it works, the decisions behind it, its edge cases, and its real-world behaviour. Stay on the same project as you drill; you will be told which layer to ask at and when to move on.
""",
            3: base_prompt + f"""
PHASE 3 — Second Project Deep-Dive.
Resume context: {resume_context}

Explore a DIFFERENT project or research experience than Phase 2, using the same layered deep-dive approach. If it is research, layer through the question, the methodology, the decisions, the limitations, and the findings.
""",
            4: base_prompt + f"""
PHASE 4 — Technical assessment.
Candidate domain: {field_spec}

Cover several technical areas relevant to {topics}. For each area, run a short two-question mini-drill: one concept-level question, then one deeper follow-up that probes reasoning or practical application — then move to a new area. You will be told whether to open a new area or follow up.
""",
            5: base_prompt + """
PHASE 5 — Behavioral.

Explore the candidate's growth, collaboration, how they handle challenges, and their curiosity about the role. For each theme, ask one question and then one natural follow-up. Keep it warm and conversational. Evaluate vision, teamwork, self-awareness, and communication.
""",
        }
        return phase_prompts.get(phase, base_prompt)

    # ------------------------------------------------------------------
    # Matryoshka layer engine — deterministic, runs in pure Python. No LLM
    # call is made here; it only updates PhaseState (see ADR 0001).
    # ------------------------------------------------------------------

    def _start_new_topic(self) -> None:
        """Open a fresh topic at L1 for a deep-dive phase.

        Picks the next resume project (so Phase 3 drills a different one than
        Phase 2, and pivots advance again); falls back to None, in which case
        the prompt invites the candidate to name a project themselves.

        `struggle_streak` is deliberately NOT reset here: when a pivot opens a
        new topic, the 3-strike cascade must keep counting across the topic
        boundary (it resets only on a good/hold answer).
        """
        ps = self.phase_state
        ps.current_layer = 1
        ps.topic_complete = False
        ps.topic_count += 1
        labels = self._resume_project_labels()
        ps.current_topic = labels[self._project_cursor] if self._project_cursor < len(labels) else None
        self._project_cursor += 1
        ps.pending_action = "new_topic"

    def _apply_layer_engine(self, phase: int, evaluation: Dict[str, Any]) -> None:
        """Advance the deterministic layer state machine after an evaluation.

        Stamps `layer` (the layer the answered question sat at) into the
        evaluation so it persists in `details` — both the live report and the
        bulk dashboard/admin scoring read it from there. Then runs the phase's
        transition logic so the next question is fully planned.
        """
        answered_layer = self.phase_state.current_layer
        evaluation["layer"] = answered_layer

        if phase == 1:
            return  # flat warm-up — no layering

        quality = self._classify_answer(phase, evaluation)
        if phase in (2, 3):
            self._deep_dive_transition(answered_layer, quality)
        else:
            self._mini_drill_transition(quality)

    def _classify_answer(self, phase: int, evaluation: Dict[str, Any]) -> str:
        """Reduce an evaluation to 'good' | 'hold' | 'struggle'."""
        if phase in (2, 3):
            depth = evaluation.get("depth", 5) or 0
            if (evaluation.get("struggling") or evaluation.get("is_superficial")
                    or depth <= 4):
                return "struggle"
            return "good" if depth >= 7 else "hold"
        if phase == 4:
            score = evaluation.get("correctness", 5) or 0
            if score <= 4:
                return "struggle"
            return "good" if score >= 7 else "hold"
        if phase == 5:
            keys = ("vision", "team", "self_awareness", "proactivity", "communication")
            vals = [evaluation[k] for k in keys if isinstance(evaluation.get(k), (int, float))]
            avg = sum(vals) / len(vals) if vals else 5
            if avg <= 4:
                return "struggle"
            return "good" if avg >= 7 else "hold"
        return "hold"

    def _deep_dive_transition(self, answered_layer: int, quality: str) -> None:
        """Full L1-L5 Matryoshka transition for the deep-dive phases (2-3).

        A strong answer climbs a layer; a fully-drilled topic (L5 + strong) is
        marked complete. A weak answer runs the 3-strike de-escalation cascade
        (step-down -> pivot -> end phase), resetting on any good answer.
        """
        ps = self.phase_state

        if quality == "good":
            ps.struggle_streak = 0
            ps.max_layer_reached = max(ps.max_layer_reached, answered_layer)
            if answered_layer >= 5:
                ps.topic_complete = True
                ps.pending_action = "complete_topic"
            else:
                ps.current_layer = min(5, answered_layer + 1)
                ps.pending_action = "deepen"
            return

        if quality == "hold":
            ps.struggle_streak = 0
            ps.max_layer_reached = max(ps.max_layer_reached, answered_layer)
            ps.current_layer = answered_layer  # re-ask the same layer for specifics
            ps.pending_action = "hold"
            return

        # quality == "struggle" — 3-strike de-escalation cascade.
        ps.struggle_streak += 1
        if ps.struggle_streak >= 3:
            ps.pending_action = "end_phase"
        elif ps.struggle_streak == 2:
            ps.pending_action = "pivot"          # generate_question opens a new topic
            ps.current_layer = 1
            ps.current_topic = None
        elif answered_layer <= 1:
            ps.pending_action = "pivot"          # already shallow — pivot straight away
            ps.current_layer = 1
            ps.current_topic = None
        else:
            ps.current_layer = max(1, answered_layer - 1)
            ps.pending_action = "step_down"

    def _mini_drill_transition(self, quality: str) -> None:
        """Light 2-layer mini-drill transition for phases 4 and 5."""
        ps = self.phase_state
        if quality == "struggle":
            ps.struggle_streak += 1
            ps.current_layer = 1
            ps.pending_action = "next_area"
            return
        ps.struggle_streak = 0
        ps.max_layer_reached = max(ps.max_layer_reached, ps.current_layer)
        if ps.current_layer >= 2:
            ps.current_layer = 1
            ps.pending_action = "next_area"
        else:
            ps.current_layer = 2
            ps.pending_action = "deepen"

    # ------------------------------------------------------------------
    # Per-turn directive — the Python-computed instruction handed to the
    # single generation LLM call. No extra LLM call is made here.
    # ------------------------------------------------------------------

    def _build_question_directive(self) -> str:
        """Build the deterministic instruction for the next question."""
        phase = self.current_phase
        ps = self.phase_state

        if phase == 5 and ps.questions_asked >= 5:
            self._final_question_asked = True
            return ("This is the FINAL question of the interview. Ask one closing "
                    "behavioral question, then warmly thank the candidate for "
                    "their time.")

        if phase == 1:
            return ("Ask the next brief background question. Keep it light, warm "
                    "and welcoming.")
        if phase in (2, 3):
            return self._deep_dive_directive()
        if phase in (4, 5):
            return self._mini_drill_directive(phase)
        return "Ask the next most appropriate question."

    def _deep_dive_directive(self) -> str:
        """Layer/topic instruction for the deep-dive phases (2-3)."""
        ps = self.phase_state
        layer_desc = LAYER_GUIDE.get(ps.current_layer, LAYER_GUIDE[2])
        if ps.current_topic:
            topic_clause = f'the topic: "{ps.current_topic}"'
        else:
            topic_clause = ("a substantial project from the candidate's "
                            "background (let them name it if it is unclear)")

        action = ps.pending_action
        if action == "new_topic":
            return (f"Open a new topic with the candidate. Focus on {topic_clause}. "
                    f"Ask {layer_desc}. Keep it natural and welcoming.")
        if action == "step_down":
            return (f"The candidate found the last question difficult. Stay on "
                    f"{topic_clause}, but ease off and re-frame more simply. "
                    f"Ask {layer_desc}. Make it feel like a natural rephrasing, "
                    f"not a setback.")
        if action == "hold":
            return (f"The candidate's last answer was serviceable but light on "
                    f"specifics. Stay on {topic_clause} at the same depth and "
                    f"ask for a concrete, detailed example. Ask {layer_desc}.")
        # "deepen" (default)
        return (f"The candidate answered well. Stay on {topic_clause} and go one "
                f"layer deeper. Ask {layer_desc}. Let the question build "
                f"naturally on what they just said.")

    def _mini_drill_directive(self, phase: int) -> str:
        """Light 2-layer mini-drill instruction for phases 4 and 5."""
        ps = self.phase_state
        deeper = ps.current_layer >= 2 and ps.pending_action == "deepen"
        if phase == 4:
            if deeper:
                return ("Stay on the SAME technical area and ask one deeper "
                        "follow-up that probes reasoning, tradeoffs, or practical "
                        "application.")
            return ("Move to a NEW technical area relevant to the role and ask "
                    "one focused, concept-level question to open it.")
        # phase 5
        if deeper:
            return ("Ask one natural follow-up to the candidate's last answer — "
                    "dig into the specifics of what they did, felt, or learned.")
        return ("Ask one behavioral question on a fresh theme — growth, "
                "collaboration, handling a challenge, or curiosity about the role.")

    async def generate_question(self, candidate_response: Optional[str] = None) -> str:
        """Generate the next interview question based on phase and context."""
        # Check if final question was already asked - do not ask again
        if self._final_question_asked:
            return "[Interview Complete]"

        messages = [
            {"role": "system", "content": await self.get_interviewer_prompt(self.current_phase)}
        ]

        # Add recent conversation history for context
        recent_history = self.conversation_history[-10:] if self.conversation_history else []
        for msg in recent_history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Add candidate's last response if provided
        if candidate_response:
            messages.append({"role": "user", "content": candidate_response})

        # Ensure a topic is active for the layered deep-dive phases. The layer
        # engine clears `current_topic` when it wants a fresh topic (a pivot or
        # a fully-drilled topic); a None topic on a freshly-advanced phase has
        # the same need.
        if self.current_phase in (2, 3):
            if (self.phase_state.current_topic is None
                    or self.phase_state.pending_action in ("pivot", "complete_topic")):
                self._start_new_topic()

        # The next question is fully planned in Python (layer + topic + action);
        # the single LLM call below only phrases it.
        if not self.conversation_history:
            prompt = "Begin the interview. Welcome the candidate by name and ask your first question."
        else:
            prompt = self._build_question_directive()

        messages.append({"role": "user", "content": prompt})

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=messages,
        )

        question = response.choices[0].message.content.strip()

        # Extract ONLY the first question if multiple are present
        # Split on "?" followed by a new sentence starting with capital letter
        import re
        question_parts = re.split(r'\?\s+(?=[A-Z])', question)
        if len(question_parts) > 1:
            question = question_parts[0].strip()
            if not question.endswith('?'):
                question += '?'

        # Prevent same question being asked twice in a row
        if self._questions_asked and question.lower() == self._questions_asked[-1].lower():
            # Regenerate with different prompt
            alt_prompt = "Ask a DIFFERENT question about a new topic. Do NOT repeat the previous question."
            messages[-1] = {"role": "user", "content": alt_prompt}
            response = await acompletion(
                self.client,
                model="llama-3.3-70b-versatile",
                messages=messages,
            )
            question = response.choices[0].message.content.strip()
            # Also extract first question if multiple
            question_parts = re.split(r'\?\s+(?=[A-Z])', question)
            if len(question_parts) > 1:
                question = question_parts[0].strip()
                if not question.endswith('?'):
                    question += '?'

        # Avoid duplicate questions
        if self.is_question_duplicate(question):
            # Ask a different question about a new aspect
            alt_prompt = prompt + " IMPORTANT: Do not repeat the previous question. Ask about a different aspect or topic."
            messages[-1] = {"role": "user", "content": alt_prompt}
            response = await acompletion(
                self.client,
                model="llama-3.3-70b-versatile",
                messages=messages,
            )
            question = response.choices[0].message.content.strip()

        # Track the question asked
        self._questions_asked.append(question)
        self.add_message("assistant", question)
        self.phase_state.questions_asked += 1
        return question

    async def evaluate_answer(self, question: str, answer: str, phase: int) -> Dict[str, Any]:
        """Evaluate the candidate's answer, then advance the Matryoshka engine.

        The phase evaluator produces answer-quality scores; `_apply_layer_engine`
        then runs the deterministic layer transition — stamping the layer the
        answer sat at into the result (so it persists in `details`) and planning
        the next question — so `generate_question` has a fully-resolved target.
        """
        if phase == 1:
            # Phase 1 is background - evaluate communication quality and relevance
            evaluation = await self._evaluate_background(question, answer)
        elif phase in [2, 3]:
            evaluation = await self._evaluate_socratic_depth(question, answer)
        elif phase == 4:
            evaluation = await self._evaluate_technical(question, answer)
        elif phase == 5:
            evaluation = await self._evaluate_behavioral(question, answer)
        else:
            return {"score": None, "feedback": "No evaluation for this phase"}

        self._apply_layer_engine(phase, evaluation)
        return evaluation

    async def _evaluate_background(self, question: str, answer: str) -> Dict[str, Any]:
        """Evaluate Phase 1 background introduction responses."""
        # First check if it's a weak/non-answer - skip AI evaluation for obvious non-answers
        if self.is_weak_response(answer):
            result = self.evaluate_weak_response(answer)
            self.phase_state.consecutive_struggles += 1
            self.phase_state.last_answer_depth = result.get("depth", 1)

            # If multiple consecutive struggles in Phase 1, move to next phase faster
            if self.phase_state.consecutive_struggles >= 2:
                self.phase_state.phase_complete = True

            return result

        # Reset counter for good answers
        self.phase_state.consecutive_struggles = 0
        self.phase_state.last_answer_depth = 5

        prompt = f"""Evaluate this background introduction response.

Question: {question}
Candidate's answer: {answer}

Evaluate each dimension 0-10:
1. RELEVANCE (0-10): How relevant is the response?
2. SPECIFICITY (0-10): Did they give specific examples?
3. CLARITY (0-10): Is their communication clear?
4. DEPTH (0-10): How much experience do they demonstrate?

Return JSON: {{"relevance": X, "specificity": X, "clarity": X, "depth": X}}
"""
        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        import json, re
        try:
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            result = json.loads(content)
            # Update last_answer_depth for adaptive difficulty
            self.phase_state.last_answer_depth = result.get("depth", 5)
            return result
        except Exception as e:
            print(f"[DEBUG] Phase 1 eval parse error: {e}")
            return {"relevance": 5, "specificity": 5, "clarity": 5, "depth": 5}

    async def _evaluate_socratic_depth(self, question: str, answer: str) -> Dict[str, Any]:
        """Evaluate depth of Socratic drilling response with enhanced detection."""
        # First check if it's a weak/non-answer
        if self.is_weak_response(answer):
            result = self.evaluate_weak_response(answer)
            self.phase_state.consecutive_struggles += 1
            self.phase_state.consecutive_superficial += 1
            self.phase_state.last_answer_depth = result.get("depth", 1)

            # If struggling, move to next topic faster
            if self.phase_state.consecutive_struggles >= 2:
                self.phase_state.phase_complete = True

            return {
                "correctness": result.get("correctness", 1),
                "depth": result.get("depth", 1),
                "specificity": result.get("specificity", 1),
                "clarity": result.get("clarity", 1),
                "is_superficial": True,
                "struggling": True,
            }

        # Reset counters for good answers
        self.phase_state.consecutive_struggles = max(0, self.phase_state.consecutive_struggles - 1)
        self.phase_state.last_answer_depth = 5

        # Detect if answer is superficial/generic
        superficial_indicators = [
            "i'm not sure", "i don't know", "it depends", "generally", "basically",
            "we used", "it can", "it does", "something like", "etc", "and so on"
        ]
        is_superficial = any(phrase in answer.lower() for phrase in superficial_indicators) or len(answer.split()) < 30

        prompt = f"""Evaluate this candidate response for DEPTH and TECHNICAL ACCURACY.

Question asked: {question}
Candidate's answer: {answer}

Evaluate each dimension 0-10:

1. TECHNICAL CORRECTNESS: Is the answer factually accurate?
   - 8-10: Completely correct
   - 5-7: Partially correct, some inaccuracies
   - 0-4: Mostly wrong

2. DEPTH OF UNDERSTANDING: Does the candidate show deep knowledge vs surface familiarity?
   - 8-10: Explains WHY and HOW, not just WHAT. Mentions tradeoffs, alternatives.
   - 5-7: Basic understanding, can describe what but not why
   - 0-4: Surface-level, vague, or "I'm not sure"

3. SPECIFICITY: Did they give concrete examples/details?
   - 8-10: Mentions specific algorithms, libraries, parameters, numbers, code
   - 5-7: Some specifics but vague on implementation
   - 0-4: Generic responses without specifics

4. CLARITY: Is the answer well-structured and clearly communicated?
   - 8-10: Clear, organised, easy to follow
   - 5-7: Understandable but somewhat rambling or unstructured
   - 0-4: Confusing or hard to follow

5. IS SUPERFICIAL: Is the answer generic, vague, or lacking specifics?
   - true: Answer is too general, lacks implementation details
   - false: Answer shows real project experience

6. STRUGGLING: Is the candidate clearly unable to engage with the question at this depth?
   - true: cannot answer the question meaningfully
   - false: engaging with the question, even if imperfectly

Return JSON ONLY: {{"correctness": X, "depth": X, "specificity": X, "clarity": X, "is_superficial": true/false, "struggling": true/false}}
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        import json, re
        try:
            content = response.choices[0].message.content.strip()
            # Handle JSON wrapped in code blocks
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            result = json.loads(content)

            # Legacy adaptive signals (kept for continuity; the deterministic
            # layer engine in _apply_layer_engine is the authoritative driver).
            self.phase_state.last_answer_depth = result.get("depth", 5)
            if result.get("struggling", False):
                self.phase_state.consecutive_struggles += 1
            else:
                self.phase_state.consecutive_struggles = 0
            if result.get("is_superficial", False):
                self.phase_state.consecutive_superficial += 1
            else:
                self.phase_state.consecutive_superficial = 0

            return result
        except Exception as e:
            print(f"[DEBUG] Phase 2/3 eval parse error: {e}")
            return {"correctness": 5, "depth": 5, "specificity": 5, "clarity": 5, "is_superficial": False, "struggling": False}

    async def _evaluate_technical(self, question: str, answer: str) -> Dict[str, Any]:
        """Evaluate a Phase 4 technical answer in the candidate's domain.

        The rubric is generic across domains; the role/topic from the resolved
        field info are injected so the LLM scores against the right ground
        (a marketing answer is not judged on ML terminology).
        """
        field_info = await self._resolve_field_info()
        role = field_info["role"]
        topics = field_info["topics"]
        prompt = f"""Evaluate this {role} technical interview response rigorously.

Domain focus: {topics}

Question: {question}
Candidate's answer: {answer}

Evaluate each dimension 0-10:

1. CORRECTNESS: Is the answer technically correct for this domain?
   - 8-10: Completely accurate
   - 5-7: Partially correct, minor inaccuracies
   - 0-4: Significant errors

2. COMPLETENESS: Did they fully answer the question?
   - 8-10: Covers all aspects with details
   - 5-7: Mentions main points but lacks depth
   - 0-4: Incomplete or missing key points

3. PRECISION: Did they use correct terminology for this domain?
   - 8-10: Precise use of {role} domain terms
   - 5-7: Some domain language used
   - 0-4: Vague or incorrect terminology

4. PRACTICAL KNOWLEDGE: Can they connect theory to implementation?
   - 8-10: Mentions actual tools, libraries, or production concerns
   - 5-7: Theoretical understanding shown
   - 0-4: Only high-level conceptual understanding

Return JSON: {{"correctness": X, "completeness": X, "precision": X, "practical": X}}
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        import json, re
        try:
            content = response.choices[0].message.content.strip()
            # Extract JSON from text (handle markdown code blocks or embedded JSON)
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = content
            # Clean up markdown
            json_str = re.sub(r'^```(?:json)?\s*', '', json_str)
            json_str = re.sub(r'\s*```$', '', json_str)
            result = json.loads(json_str)
            # Convert boolean values to numeric scores if needed
            for key in result:
                if isinstance(result[key], bool):
                    result[key] = 8 if result[key] else 3
            return result
        except Exception as e:
            print(f"[DEBUG] Phase 4 eval parse error: {e}")
            return {"correctness": 5, "completeness": 5, "precision": 5, "practical": 5}

    async def _evaluate_behavioral(self, question: str, answer: str) -> Dict[str, Any]:
        """Evaluate behavioral question responses."""
        prompt = f"""Evaluate this behavioral interview response.

Question: {question}
Candidate's answer: {answer}

Evaluate:
1. Vision/Ambition (0-10): Is their 5-year plan realistic yet aspirational?
2. Team Orientation (0-10): Do they show collaborative mindset?
3. Self-Awareness (0-10): Do they acknowledge weaknesses and learn from challenges?
4. Proactivity (0-10): Do they ask thoughtful questions? (-2 if NO questions asked at end)
5. Communication (0-10): Clear and structured response?

Return JSON: {{"vision": X, "team": X, "self_awareness": X, "proactivity": X, "communication": X}}
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        import json, re
        try:
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
            result = json.loads(content)

            # Check for "no questions" penalty in behavioral evaluation
            if "no questions" in answer.lower() or "don't have any questions" in answer.lower():
                result["proactivity"] = max(0, result.get("proactivity", 5) - 2)

            return result
        except Exception as e:
            print(f"[DEBUG] Phase 5 eval parse error: {e}")
            return {"vision": 5, "team": 5, "self_awareness": 5, "proactivity": 5, "communication": 5}

    def advance_phase(self) -> int:
        """Move to the next interview phase."""
        if self.current_phase < 5:
            self.current_phase += 1
            self.phase_state = PhaseState(phase=self.current_phase)
            self._save_conversation()
            return self.current_phase
        return self.current_phase

    def advance_phase_if_ready(self, evaluation: Dict[str, Any]) -> bool:
        """Decide whether to move on to the next phase.

        Driven by the Matryoshka layer engine (see ADR 0001):
        - A deep-dive phase ends once its topic is drilled to L5 with a strong
          answer, or the 3-strike de-escalation cascade has fired, or a hard
          question cap is reached.
        - A sustained run of weak answers ends any phase early — a human
          interviewer stops grinding a topic the candidate cannot handle.
        - Every phase has a hard cap so the interview always progresses.
        """
        ps = self.phase_state
        qs = ps.questions_asked

        # Universal early exit on a sustained run of weak answers.
        if ps.struggle_streak >= 3 and qs >= 2:
            return True

        if self.current_phase == 1:
            return qs >= 3  # warm-up only — keep it short

        if self.current_phase in (2, 3):
            # 3-strike cascade resolved to ending the phase.
            if ps.pending_action == "end_phase":
                return True
            # Topic fully drilled to L5 with a strong answer.
            if ps.topic_complete and qs >= 5:
                return True
            # Hard cap.
            return qs >= 10

        if self.current_phase == 4:
            return qs >= 8

        if self.current_phase == 5:
            return qs >= 5

        return False

    def is_complete(self) -> bool:
        return self.current_phase >= 5 and self.phase_state.questions_asked >= 5


class VoiceEmpathyProcessor:
    """Process voice input for empathy/tone detection."""

    def __init__(self):
        self.client = get_groq_client()

    async def transcribe_audio(self, audio_content: bytes) -> str:
        """Transcribe audio using Whisper."""
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as f:
            f.write(audio_content)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as audio_file:
                transcript = await atranscription(
                    self.client,
                    model="whisper-large-v3",
                    file=audio_file,
                )
            return transcript.text
        finally:
            os.unlink(temp_path)

    async def detect_pace(self, text: str, audio_duration_seconds: float) -> Dict[str, Any]:
        """Detect speaking pace (words per minute)."""
        word_count = len(text.split())
        words_per_minute = (word_count / audio_duration_seconds) * 60 if audio_duration_seconds > 0 else 0

        return {
            "words_per_minute": words_per_minute,
            "is_too_fast": words_per_minute > 180,
            "is_too_slow": words_per_minute < 60,
            "recommendation": self._get_pace_recommendation(words_per_minute)
        }

    def _get_pace_recommendation(self, wpm: float) -> str:
        if wpm > 200:
            return "Take a breath. Please slow down and collect your thoughts."
        elif wpm > 180:
            return "Let's take a moment. Please feel free to pause before answering."
        elif wpm < 60:
            return "That's fine, take your time."
        return ""

    async def generate_empathy_nudge(self, pace_analysis: Dict[str, Any]) -> Optional[str]:
        """Generate an empathy nudge based on voice analysis."""
        if not pace_analysis.get("recommendation"):
            return None

        prompt = f"""A candidate is doing a mock interview. Their speech analysis shows:
- Words per minute: {pace_analysis.get('words_per_minute', 0):.0f}
- Issue: {pace_analysis.get('recommendation', 'None')}

Generate a brief, professional encouragement message to help them relax.
Keep it under 15 words. Be warm but professional.
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        return response.choices[0].message.content.strip()


class ReportGenerator:
    """Generate final interview evaluation report."""

    def __init__(self, interview_id: UUID):
        self.interview_id = interview_id
        self._supabase = None

    @property
    def supabase(self):
        if self._supabase is None:
            self._supabase = get_supabase()
        return self._supabase

    def generate_report(self) -> Dict[str, Any]:
        """Generate the final evaluation report."""
        try:
            interview_result = self.supabase.table("interviews").select("*").eq("id", str(self.interview_id)).execute()
            if not interview_result.data:
                return {"error": "Interview not found"}

            interview = interview_result.data[0]
            candidate_result = self.supabase.table("candidates").select("*").eq("id", interview["candidate_id"]).execute()
            candidate = candidate_result.data[0] if candidate_result.data else {}
            eval_result = self.supabase.table("evaluations").select("*").eq("interview_id", str(self.interview_id)).execute()
            evaluations = eval_result.data
            # Integrity events (Phase B). Single bulk query, ordered. If the
            # migration hasn't been applied yet, the SELECT raises an APIError;
            # swallow it so the report still renders without integrity context.
            try:
                integrity_rows = (
                    self.supabase.table("interview_integrity_events")
                    .select("event_type,severity,metadata,created_at")
                    .eq("interview_id", str(self.interview_id))
                    .order("created_at")
                    .execute()
                    .data
                    or []
                )
            except Exception:
                integrity_rows = []
        except Exception as e:
            return {"error": str(e)}

        # Calculate phase + final scores via the shared scoring helpers.
        phase_scores = compute_phase_scores(evaluations)
        final_score = compute_final_score(phase_scores)

        # Generate recommendation
        recommendation = recommendation_for(final_score)

        # Calculate duration
        from datetime import datetime
        duration_minutes = 0
        if interview.get("completed_at") and interview.get("created_at"):
            completed = interview["completed_at"]
            created = interview["created_at"]
            if isinstance(completed, str) and isinstance(created, str):
                try:
                    duration_minutes = (datetime.fromisoformat(completed) - datetime.fromisoformat(created)).total_seconds() / 60
                except:
                    pass

        # Convert phase_scores keys to strings for Pydantic compatibility
        phase_scores_str = {str(k): v for k, v in phase_scores.items()}

        # Derive qualitative feedback from phase performance
        strengths: List[str] = []
        improvements: List[str] = []
        for phase_num, scores in phase_scores.items():
            overall = scores.get("overall", 0) or 0
            label = PHASE_NAMES.get(phase_num, f"Phase {phase_num}")
            if overall >= 7:
                strengths.append(label)
            elif 0 < overall < 5.5:
                improvements.append(label)

        if final_score >= 8.5:
            summary = "Outstanding performance with strong, well-reasoned answers throughout the interview."
        elif final_score >= 7:
            summary = "Solid performance with clear strengths and a few areas to refine."
        elif final_score >= 5.5:
            summary = "A mixed performance - some good moments, but key areas need more depth."
        else:
            summary = "This interview showed gaps in depth and accuracy; focused practice is recommended."
        if improvements:
            summary += " Focus next on: " + ", ".join(improvements) + "."

        report = {
            "interview_id": str(self.interview_id),
            "candidate_name": candidate.get("name", "Unknown"),
            "candidate_field": candidate.get("field_specialization", "ml"),
            "total_duration_minutes": round(duration_minutes, 1),
            "phase_scores": phase_scores_str,
            "final_score": final_score,
            "recommendation": recommendation,
            "total_questions_asked": len(evaluations),
            "generated_at": datetime.utcnow().isoformat(),
            "transcript": interview.get("conversation_history", []) or [],
            "strengths": strengths,
            "improvements": improvements,
            "summary": summary,
            "integrity_events": {
                "count": len(integrity_rows),
                "terminated": interview.get("status") == "terminated_integrity",
                "events": integrity_rows,
            },
        }

        return report

    def generate_markdown_report(self, report: Dict[str, Any]) -> str:
        """Generate a markdown-formatted report."""
        lines = [
            "# Mock Interview Evaluation Report",
            "",
            f"**Candidate:** {report.get('candidate_name', 'Unknown')}",
            f"**Field:** {report.get('candidate_field', 'ML').upper()}",
            f"**Interview Duration:** {report.get('total_duration_minutes', 0):.1f} minutes",
            f"**Total Questions:** {report.get('total_questions_asked', 0)}",
            "",
        ]

        integrity_info = report.get("integrity_events") or {}
        integrity_count = integrity_info.get("count") or 0
        if integrity_info.get("terminated"):
            lines.extend([
                "> **Flagged for integrity review — interview terminated by the integrity monitor.**",
                "",
            ])
        elif integrity_count >= 1:
            noun = "event" if integrity_count == 1 else "events"
            lines.extend([
                f"> **Flagged for integrity review** ({integrity_count} {noun} logged).",
                "",
            ])

        lines.extend(["---", ""])

        phase_scores = report.get("phase_scores", {})

        for phase in [2, 3, 4, 5]:
            if phase not in phase_scores:
                continue

            scores = phase_scores[phase]
            lines.append(f"## Phase {phase}: {PHASE_NAMES.get(phase, '')}")
            lines.append("")

            if phase in [2, 3]:
                lines.append(f"| Criterion | Score |")
                lines.append("|------------|-------|")
                lines.append(f"| Depth Score | {scores.get('depth_score', 0):.1f}/10 |")
                lines.append(f"| Accuracy Score | {scores.get('accuracy_score', 0):.1f}/10 |")
                lines.append(f"| Clarity Score | {scores.get('clarity_score', 0):.1f}/10 |")
                lines.append(f"| **Overall** | **{scores.get('overall', 0):.1f}/10** |")
            elif phase == 4:
                lines.append(f"| Metric | Value |")
                lines.append("|------------|-------|")
                lines.append(f"| Correct Answers | {scores.get('correct_answers', 0)}/{scores.get('total_questions', 0)} |")
                lines.append(f"| **Overall** | **{scores.get('overall', 0):.1f}/10** |")
            elif phase == 5:
                lines.append(f"| Criterion | Score |")
                lines.append("|------------|-------|")
                lines.append(f"| Vision | {scores.get('vision', 0):.1f}/10 |")
                lines.append(f"| Team Orientation | {scores.get('team', 0):.1f}/10 |")
                lines.append(f"| Self-Awareness | {scores.get('self_awareness', 0):.1f}/10 |")
                lines.append(f"| Proactivity | {scores.get('proactivity', 0):.1f}/10 |")
                lines.append(f"| Communication | {scores.get('communication', 0):.1f}/10 |")
                lines.append(f"| **Overall** | **{scores.get('overall', 0):.1f}/10** |")

            lines.append("")

        lines.extend([
            "---",
            "",
            f"## Final Score: {report.get('final_score', 0):.1f}/10",
            f"## Recommendation: **{report.get('recommendation', 'N/A')}**",
            "",
            f"*Report generated at {report.get('generated_at', '')}*"
        ])

        return "\n".join(lines)
