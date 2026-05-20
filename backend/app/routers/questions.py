from fastapi import APIRouter, HTTPException
from typing import List
from uuid import UUID

from app.models.schemas import MLQuestionResponse
from app.supabase_client import get_supabase

router = APIRouter()


@router.get("/ml-questions", response_model=List[MLQuestionResponse])
async def get_ml_questions(category: str = None, limit: int = 10):
    supabase = get_supabase()

    query = supabase.table("ml_questions").select("*")
    if category:
        query = query.eq("category", category)
    query = query.limit(limit)

    result = query.execute()
    return result.data


@router.get("/ml-questions/search", response_model=List[MLQuestionResponse])
async def search_ml_questions(query_text: str, field: str = None, limit: int = 5):
    supabase = get_supabase()

    # For now, simple text search
    # In production, use vector similarity search with embeddings
    result = supabase.rpc(
        "match_ml_questions",
        {
            "query_text": query_text,
            "match_count": limit,
            "field_filter": field
        }
    ).execute()

    return result.data if result.data else []
