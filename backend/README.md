# AI Mock Interview Agent - Backend

## Setup

1. **Install dependencies:**
```bash
cd backend
pip install -r requirements.txt
```

2. **Configure environment:**
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. **Set up Supabase database:**
- Create a Supabase project
- Run the SQL in `app/database.sql` in the Supabase SQL Editor
- Copy your Supabase URL and keys to `.env`

4. **Seed ML Questions:**
```bash
python -m app.seed_db
```

5. **Run the server:**
```bash
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

### Candidates
- `POST /api/candidates/` - Create candidate
- `GET /api/candidates/` - List candidates
- `GET /api/candidates/{id}` - Get candidate
- `POST /api/candidates/upload-resume/{id}` - Upload & parse resume PDF

### Interviews
- `POST /api/interviews/` - Create interview
- `GET /api/interviews/` - List interviews
- `GET /api/interviews/{id}` - Get interview
- `GET /api/interviews/{id}/state` - Get interview state
- `PATCH /api/interviews/{id}/phase` - Update phase
- `PATCH /api/interviews/{id}/complete` - Complete interview
- `GET /api/interviews/{id}/evaluations` - Get evaluations

### Questions
- `GET /api/questions/ml-questions` - Get ML questions
- `GET /api/questions/ml-questions/search` - Search ML questions

### WebSocket
- `WS /ws/interview/{interview_id}` - Real-time interview session

## Architecture

```
backend/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings
│   ├── supabase_client.py   # Supabase connection
│   ├── database.sql         # DB schema
│   ├── seed_db.py           # Seed ML questions
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   ├── routers/
│   │   ├── candidates.py    # Candidate endpoints
│   │   ├── interviews.py    # Interview endpoints
│   │   ├── questions.py     # Question endpoints
│   │   └── interview_session.py  # WebSocket handler
│   └── services/
│       ├── resume_parser.py       # PDF parsing with GPT-4o
│       ├── interview_orchestrator.py  # 5-phase interview logic
│       ├── question_retriever.py  # RAG-based question retrieval
│       └── voice_service.py       # 11Labs TTS
├── requirements.txt
├── .env
└── .gitignore
```
