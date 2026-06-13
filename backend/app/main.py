import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from postgrest.exceptions import APIError
from app.config import get_settings
from app.readiness import assert_ready
from app.routers import candidates, interviews, questions
from app.routers.reports import router as reports_router
from app.routers.voice import router as voice_router
from app.routers.dashboard import router as dashboard_router
from app.routers.admin import router as admin_router
from app.routers.profile import router as profile_router
from app.routers.recruiter import router as recruiter_router
from app.routers.companies import router as companies_router
from app.routers.jobs import router as jobs_router
from app.routers.apply import router as apply_router
from app.routers.invitations import router as invitations_router
from app.routers.webhooks import router as webhooks_router
from app.routers.interview_session import interview_websocket

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate critical production config before serving the first request.
    # A missing required dependency raises here, so uvicorn aborts the boot
    # with a clear report instead of starting a broken app that only fails
    # at the first interview/signup. Warnings are logged, not fatal.
    assert_ready(get_settings())
    yield


app = FastAPI(
    title="AI Mock Interview Agent",
    description="Industrial-grade AI-powered mock interview system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow local dev plus the configured production origins, and Vercel
# deployments via regex. Auth is Bearer-token (no cookies), so credentials are
# disabled; "*" + credentials is an invalid combination browsers reject.
_cors_origins = ["http://localhost:3000"]
_cors_origins += [o.strip() for o in settings.frontend_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=settings.frontend_origin_regex or None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(candidates.router, prefix="/api/candidates", tags=["candidates"])
app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
app.include_router(questions.router, prefix="/api/questions", tags=["questions"])
app.include_router(reports_router, prefix="/api/reports", tags=["reports"])
app.include_router(voice_router, prefix="/api/voice", tags=["voice"])
app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(profile_router, prefix="/api/auth", tags=["auth"])
app.include_router(recruiter_router, prefix="/api/recruiter", tags=["recruiter"])
app.include_router(companies_router, prefix="/api/companies", tags=["companies"])
# Job requisitions — tenant CRUD (manage_jobs) + public apply lookup (migration 013).
app.include_router(jobs_router, prefix="/api/jobs", tags=["jobs"])
# Candidate-facing invitation ledger (list/accept/decline) — migration 011.
app.include_router(invitations_router, prefix="/api/invitations", tags=["invitations"])
# apply.py has two routes (apply/{slug} public + auth/claim-company authed)
# under one router — mounted with the bare /api prefix.
app.include_router(apply_router, prefix="/api", tags=["apply"])
# Resend delivery webhooks (signature-authenticated, no JWT). See ADR 0012.
app.include_router(webhooks_router, prefix="/api/webhooks", tags=["webhooks"])


@app.exception_handler(APIError)
async def handle_supabase_api_error(request: Request, exc: APIError):
    """Convert raw PostgREST/database errors into clear JSON responses.

    Without this, an unhandled database error returns a plain-text 500 that the
    frontend cannot parse, surfacing to users as a meaningless 'Unknown error'.
    """
    message = getattr(exc, "message", None) or str(exc)
    code = getattr(exc, "code", "") or ""
    if code == "PGRST204" and "user_id" in str(message):
        detail = (
            "Database is not migrated. Run "
            "backend/app/migrations/001_auth_and_ownership.sql in the Supabase "
            "SQL editor, then try again."
        )
    else:
        detail = f"Database error: {message}"
    return JSONResponse(status_code=500, content={"detail": detail})


@app.get("/")
async def root():
    return {"status": "running", "service": "AI Mock Interview Agent"}


@app.get("/health")
async def health():
    """Liveness probe + build identity. `commit` is Render's auto-injected
    deployed commit SHA (RENDER_GIT_COMMIT) so an operator can confirm exactly
    which build is serving — the missing piece for deploy verification. Falls
    back to 'unknown' off-Render (local/dev). Always 200 (UptimeRobot relies on
    it)."""
    return {
        "status": "healthy",
        "commit": os.getenv("RENDER_GIT_COMMIT", "unknown")[:12],
        "environment": settings.environment,
    }


@app.websocket("/ws/interview/{interview_id}")
async def websocket_endpoint(websocket: WebSocket, interview_id: str):
    await interview_websocket(websocket, interview_id)
