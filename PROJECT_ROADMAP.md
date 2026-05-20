# AI-Powered Mock Interview Agent - Project Roadmap

## Project Overview
An industrial-grade AI mock interview system that conducts realistic technical interviews for Machine Learning Engineer candidates using their resume as context. The system uses a Socratic questioning approach to deeply evaluate candidates across 5 phases.

---

## Tech Stack

| Component | Technology |
|-----------|------------|
| **LLM** | GPT-4o (reasoning) + GPT-4o-mini (fast responses) |
| **Voice/TTS** | 11Labs (voice ID: ZthnDvLLxYzM9qeFVSJe) |
| **Speech-to-Text** | OpenAI Whisper API |
| **Database** | Supabase (PostgreSQL + Vector) |
| **PDF Parsing** | OpenAI GPT-4o Vision |
| **Embeddings** | OpenAI text-embedding-3-small (384 dim) |
| **Frontend** | React + TypeScript |
| **Backend** | FastAPI (Python) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND (React)                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │ Resume   │  │  Voice    │  │  Chat    │  │  Live Transcript ││
│  │ Upload   │  │  Toggle   │  │  Window  │  │  + Scoring       ││
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘│
└────────────────────────────┬────────────────────────────────────┘
                             │ WebSocket
┌────────────────────────────▼────────────────────────────────────┐
│                     BACKEND (FastAPI)                           │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Interview    │  │  Resume      │  │   Question            │ │
│  │ Orchestrator│  │  Parser      │  │   Retriever (RAG)     │ │
│  │ (State Mach.)│  │  (GPT-4o)   │  │   (Embeddings)        │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ Voice        │  │ Evaluation   │  │   Report              │ │
│  │ Processor    │  │ Engine       │  │   Generator           │ │
│  │ (Whisper)    │  │ (5 Phases)   │  │                       │ │
│  └──────────────┘  └──────────────┘  └────────────────────────┘ │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                     EXTERNAL SERVICES                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐│
│  │ OpenAI   │  │ 11Labs   │  │Supabase  │  │  (Future) AWS   ││
│  │ API      │  │ TTS      │  │ DB+Vec   │  │  Deployment      ││
│  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

---

## Database Schema (Supabase)

### Tables

#### 1. `candidates`
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| email | VARCHAR | Candidate email |
| name | VARCHAR | Full name |
| resume_text | TEXT | Parsed resume content |
| resume_sections | JSONB | Structured resume sections |
| field_specialization | VARCHAR | NLP / Computer Vision / General ML |
| created_at | TIMESTAMP | Creation time |

#### 2. `interviews`
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| candidate_id | UUID | FK to candidates |
| job_description | TEXT | Target job description |
| status | VARCHAR | phase_1/phase_2/phase_3/phase_4/phase_5/completed |
| current_phase | INT | 1-5 |
| conversation_history | JSONB | Full interview transcript |
| created_at | TIMESTAMP | Start time |
| completed_at | TIMESTAMP | End time |

#### 3. `evaluations`
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| interview_id | UUID | FK to interviews |
| phase | INT | 1-5 |
| depth_score | FLOAT | Socrates drill-down score (0-10) |
| accuracy_score | FLOAT | Answer correctness (0-10) |
| overall_score | FLOAT | Weighted phase score |
| details | JSONB | Phase-specific evaluation details |
| created_at | TIMESTAMP | Evaluation time |

#### 4. `ml_questions` (Pre-populated)
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| category | VARCHAR | e.g., "fundamentals", "neural_networks", "nlp", "cv" |
| question | TEXT | The question |
| answer | TEXT | Expected answer |
| embedding | VECTOR(384) | Question embedding |

---

## Phase Breakdown

### Phase 1: Background & Introduction
**Purpose**: Warm-up, establish rapport, understand candidate background

**Questions**:
- "Could you please tell me about yourself?"
- "What motivated you to pursue Machine Learning?"
- "What are your current projects or areas of focus?"

**Evaluation**: No formal scoring (baseline for Phase 5 behavioral assessment)

**State Tracking**: Candidate mentions → topics for follow-up in Phase 2/3

---

### Phase 2: First Project Deep-Dive (Socratic/RAG Doll)
**Purpose**: Evaluate depth of knowledge on primary project using Socrates method

**Algorithm**:
```
1. Identify "most important" project from resume (first in experience or projects)
2. Extract project tech stack and domain
3. Ask: "What did you build in this project?"
4. WHILE candidate keeps answering:
   a. Ask clarifying "how" and "why" questions
   b. Drill down to fundamental concepts
   c. If candidate struggles → back off, praise minimally, move to next topic
   d. If candidate demonstrates mastery → push harder
5. Track "drill depth" reached for each topic
```

**Example Drill-down Chain (RAG Project)**:
```
Q: "What exactly did you build?"
Q: "Could you tell me how this works?"
Q: "What is Retrieval-Augmented Generation?"
Q: "What are different chunking strategies?"
Q: "Why didn't you use fine-tuning instead of RAG?"
Q: "What are the disadvantages of RAG?"
Q: "How do HNSW and IVFFlat indexing work?"
```

**Evaluation Matrix**:
| Criterion | Weight | Description |
|-----------|--------|-------------|
| Technical Depth | 40% | How deep could drill before candidate couldn't answer |
| Correctness | 30% | Were explanations accurate |
| Clarity | 20% | Could articulate complex concepts simply |
| Follow-up Engagement | 10% | Did they proactively explain vs被动 answering |

**Scoring**: 0-10 scale per criterion, weighted average

---

### Phase 3: Second Project Deep-Dive
**Purpose**: Evaluate breadth across different project type

**Same Socratic method as Phase 2, but**:
- Different project (research internship, different domain)
- May pivot to domain-specific questions (NLP/CV)

**Evaluation Matrix**: Same as Phase 2

---

### Phase 4: Technical ML Questions (RAG-Based Retrieval)
**Purpose**: Assess factual ML knowledge

**Question Selection**:
1. Detect candidate field: NLP / Computer Vision / General ML
2. Retrieve 8-10 questions from `ml_questions` table based on field + embeddings
3. Mix of difficulty levels

**Question Categories Retrieved**:
- Fundamentals (bias-variance, gradient descent, regularization)
- Neural Networks (ReLU vs sigmoid, CNNs, LSTM)
- Computer Vision (for CV specialization)
- NLP (for NLP specialization)
- Evaluation Metrics (precision, recall, F1, ROC)
- Model Types & Ensembles

**Evaluation Matrix**:
| Criterion | Weight | Description |
|-----------|--------|-------------|
| Correctness | 70% | Exact/partial match to expected answer |
| Completeness | 20% | Full vs partial answer |
| Precision | 10% | Use of correct terminology |

**Scoring**: Binary correct/incorrect with partial credit

---

### Phase 5: Behavioral Questions
**Purpose**: Assess soft skills, culture fit, career trajectory

**Questions**:
1. "Where do you see yourself in 5 years?"
2. "What is the most significant challenge you've faced in a team?"
3. "How do you handle disagreements with team members?"
4. "Do you have any questions for me about the role/company?"
5. "Describe a time you had to learn something quickly."

**Interviewer Tone Guidance**:
- Professional, measured
- Never overly enthusiastic ("Great answer!")
- Brief acknowledgment, then next question
- Example: "Thank you for sharing. Let's move on."

**Anti-Cheating Nudges** (future):
- Random clarifying questions if answer seems scripted

**Evaluation Matrix**:
| Criterion | Weight | Description |
|-----------|--------|-------------|
| Vision/Ambition | 25% | Realistic yet aspirational 5-year plan |
| Team Orientation | 25% | Collaborative, not self-centered |
| Self-Awareness | 20% | Acknowledges weaknesses, learns from challenges |
| Proactivity | 20% | Asks thoughtful questions about role |
| Communication | 10% | Clear, structured responses |

**Negative Scoring**:
- -2 points if NO questions asked at the end
- -1 point for generic/non-thoughtful questions

---

## Voice & Empathy Features

### Voice Input (v1)
- Use OpenAI Whisper API for speech-to-text
- Real-time transcription during interview

### Voice Output (v1)
- 11Labs TTS with voice ID: `ZthnDvLLxYzM9qeFVSJe`
- Queue responses, play when complete

### Empathy/Tone Detection (Future v2)
- **Voice Pacing Detection**:
  - If speaking pace > threshold (e.g., >180 words/min) → "Let's take a moment. Please feel free to collect your thoughts."
  - If prolonged fast pace → "Would you like a short break before we continue?"
- **Sentiment Analysis** (future): Video-based frustration/confusion detection

### Interviewer Personality Prompt
```
You are a professional technical interviewer conducting a mock interview.
- Be courteous and professional
- Ask one question at a time
- Listen carefully and ask follow-up questions
- Do not over-praise or show excessive enthusiasm
- Keep responses brief: acknowledge, then ask next question
- Use the candidate's name occasionally
- If candidate seems nervous: "Take your time, there's no rush."
```

---

## Evaluation Report Structure

### Final Report for Candidate

```
===========================================
   MOCK INTERVIEW EVALUATION REPORT
===========================================

Candidate: [Name]
Position: Machine Learning Engineer
Interview Date: [Date]
Duration: [X] minutes

-------------------------------------------
PHASE 1: Background Introduction
-------------------------------------------
Status: Completed
Notes: [Brief observations]

-------------------------------------------
PHASE 2: Project Deep-Dive (Project Name)
-------------------------------------------
Socratic Depth Score: X.X/10
Correctness Score: X.X/10
Clarity Score: X.X/10
Follow-up Engagement: X.X/10
PHASE 2 OVERALL: X.X/10

Drill-Down Analysis:
- Topic 1 (RAG): Reached depth level 4/6
- Topic 2 (Vector DB): Reached depth level 3/6

-------------------------------------------
PHASE 3: Second Project Deep-Dive
-------------------------------------------
[Same structure as Phase 2]

-------------------------------------------
PHASE 4: Technical Assessment
-------------------------------------------
Field: NLP
Questions Attempted: 8/10
Correct Answers: 6/10
Partial Credit: 1/10
PHASE 4 OVERALL: 8.5/10

-------------------------------------------
PHASE 5: Behavioral Assessment
-------------------------------------------
Vision Score: X.X/10
Team Orientation: X.X/10
Self-Awareness: X.X/10
Proactivity: X.X/10 (NEGATIVE: -2 for no questions)
PHASE 5 OVERALL: X.X/10

-------------------------------------------
FINAL SCORE: X.X/10
===========================================

RECOMMENDATION: [Strong Hire / Hire / Hold / No Hire]
```

---

## Implementation Tasks

### Sprint 1: Foundation
- [ ] Create Supabase project and database schema
- [ ] Set up FastAPI project structure
- [ ] Implement Supabase client with secrets from environment
- [ ] Create `.gitignore` with all secrets patterns
- [ ] Create `requirements.txt` with all dependencies

### Sprint 2: Resume Processing
- [ ] Implement PDF upload endpoint
- [ ] Implement GPT-4o Vision PDF parsing
- [ ] Implement resume section extraction (experience, education, projects, skills)
- [ ] Detect candidate field specialization (NLP/CV/General)
- [ ] Store parsed resume in Supabase

### Sprint 3: Interview Orchestrator
- [ ] Implement interview state machine (phases 1-5)
- [ ] Create Phase 1 question generator
- [ ] Create Phase 2/3 Socratic drill-down engine
- [ ] Create Phase 4 question retriever (RAG with embeddings)
- [ ] Create Phase 5 behavioral question generator
- [ ] Implement conversation history tracking

### Sprint 4: Voice Integration
- [ ] Integrate 11Labs TTS with voice ID ZthnDvLLxYzM9qeFVSJe
- [ ] Implement Whisper speech-to-text
- [ ] Build audio queue system for TTS responses
- [ ] Add voice pace detection (words per minute)
- [ ] Implement empathy nudge system

### Sprint 5: Evaluation Engine
- [ ] Implement Phase 2/3 Socrates scoring matrix
- [ ] Implement Phase 4 answer evaluation (exact + partial match)
- [ ] Implement Phase 5 behavioral scoring matrix
- [ ] Create weighted final score calculator
- [ ] Generate PDF/JSON report

### Sprint 6: Frontend
- [ ] Create React app with TypeScript
- [ ] Implement resume upload UI
- [ ] Build chat interface with real-time updates
- [ ] Add voice toggle and audio controls
- [ ] Display live evaluation scores
- [ ] Create interview report view

### Sprint 7: Integration & Polish
- [ ] WebSocket integration for real-time interview
- [ ] End-to-end testing
- [ ] Error handling and edge cases
- [ ] Interviewer persona prompt refinement

### Sprint 8 (Future): CI/CD & Deployment
- [ ] GitHub Actions pipeline
- [ ] AWS deployment configuration
- [ ] Anti-cheating system (future)

---

## Milestones

| Milestone | Description | Target |
|-----------|-------------|--------|
| M1 | DB schema + Resume parsing working | Week 1 |
| M2 | Basic interview flow (Phase 1-3) | Week 2 |
| M3 | Voice I/O working | Week 3 |
| M4 | Full interview with evaluation | Week 4 |
| M5 | Frontend + Report generation | Week 5 |
| M6 | Production-ready | Week 6 |

---

## Configuration

### Environment Variables (.env)
```bash
OPENAI_API_KEY=sk-proj-...
ELEVENLABS_API_KEY=sk_1365998877...
ELEVENLABS_VOICE_ID=ZthnDvLLxYzM9qeFVSJe
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=sbp_xxx
```

### Supabase Connection
- Project ID: supabase project at provided URL
- Anon/Service Role Key: <redacted — kept in backend/.env, never committed>

---

## Next Steps

1. **Approve this roadmap**
2. **Provide any additional credentials** (if needed)
3. **I will begin execution** starting with Sprint 1 (Foundation)

---

## Appendix: ML Questions Database (from MLQuestions repo)

### Fundamentals
1. Bias-Variance Tradeoff
2. Gradient Descent
3. Overfitting/Underfitting
4. Curse of Dimensionality
5. Regularization (Ridge/Lasso)
6. PCA
7. Data Normalization
8. Validation vs Test Sets
9. Stratified Cross-Validation
10. Batch vs Stochastic GD

### Neural Networks
1. ReLU vs Sigmoid
2. CNN vs FC Layers
3. CNN Translation Invariance
4. Max-Pooling Purpose
5. Encoder-Decoder Structure
6. Residual Networks
7. Batch Normalization
8. Small vs Large Kernels
9. LSTM/GRU Variants
10. Autoencoders

### Computer Vision
1. Receptive Field Calculation
2. Connected Components
3. Integral Images
4. RANSAC
5. CBIR
6. Image Registration
7. Convolution Operations
8. 3D Reconstruction (SfM/MVS)

### Evaluation Metrics
1. Precision/Recall
2. F1-Score
3. ROC Curve
4. Type I/II Errors

### Ensembles & Models
1. Bagging vs Boosting
2. Imbalanced Data Handling
3. GAN Components
4. Generative vs Discriminative

---

*Document Version: 1.0*
*Created: 2026-04-27*
