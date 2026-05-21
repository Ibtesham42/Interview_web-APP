from pydantic_settings import BaseSettings
from functools import lru_cache

# LLM provider: Groq (OpenAI-compatible API).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = "llama-3.3-70b-versatile"   # chat / reasoning
STT_MODEL = "whisper-large-v3"          # speech-to-text


class Settings(BaseSettings):
    groq_api_key: str
    openai_api_key: str = ""  # optional - only the (unused) embedding seed needs it
    supabase_url: str
    supabase_key: str
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS — production frontend origins.
    # frontend_origins: comma-separated exact origins (e.g. a custom domain).
    # frontend_origin_regex: matches Vercel deployments; tighten to the project
    # slug for safety, e.g. https://my-app-.*\.vercel\.app
    frontend_origins: str = ""
    frontend_origin_regex: str = r"https://.*\.vercel\.app"

    # Piper TTS Configuration (free, open-source)
    use_piper_tts: bool = False  # Set to True to use Piper
    piper_voice_path: str = ""   # Path to .onnx voice file

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def get_groq_client():
    """OpenAI-compatible client pointed at Groq — used for chat and speech-to-text.

    An explicit timeout and retry budget keep a stalled Groq request from
    blocking the (single-worker) event loop indefinitely.
    """
    from openai import OpenAI
    settings = get_settings()
    return OpenAI(
        api_key=settings.groq_api_key,
        base_url=GROQ_BASE_URL,
        timeout=30.0,
        max_retries=2,
    )
