from supabase import create_client, Client
from functools import lru_cache

_client = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        from app.config import get_settings
        settings = get_settings()
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client
