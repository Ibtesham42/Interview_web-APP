"""
Seed script to populate the ML Questions database.
Run this after setting up your .env file.

Usage:
    python -m app.seed_db
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.question_retriever import seed_ml_questions
from app.config import get_settings


async def main():
    print("Seeding ML Questions database...")
    settings = get_settings()
    print(f"Supabase URL: {settings.supabase_url[:30]}...")

    try:
        count = await seed_ml_questions()
        print(f"Successfully seeded {count} ML questions!")
    except Exception as e:
        print(f"Error seeding database: {e}")
        print("Make sure your Supabase credentials are correct and the database is running.")


if __name__ == "__main__":
    asyncio.run(main())
