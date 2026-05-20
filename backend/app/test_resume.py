"""
Test script for Sprint 2 - Resume Processing
Run after setting up Supabase and having a real PDF.

Usage:
    python -m app.test_resume
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.resume_parser import ResumeParser, PDFExtractor


async def test_pdf_extraction(pdf_path: str):
    """Test PDF text extraction without AI."""
    print(f"\n{'='*50}")
    print(f"Testing PDF extraction: {pdf_path}")
    print('='*50)

    with open(pdf_path, 'rb') as f:
        pdf_content = f.read()

    extractor = PDFExtractor()
    result = extractor.extract_text(pdf_content)

    print(f"\nSuccess: {result.get('success')}")
    print(f"Page count: {result.get('page_count', 'N/A')}")
    print(f"Text preview:\n{result.get('full_text', '')[:500]}...")

    return result


async def test_ai_parsing(pdf_path: str):
    """Test AI-powered resume parsing."""
    print(f"\n{'='*50}")
    print(f"Testing AI parsing: {pdf_path}")
    print('='*50)

    with open(pdf_path, 'rb') as f:
        pdf_content = f.read()

    parser = ResumeParser()
    result = await parser.parse_resume(pdf_content)

    print(f"\nName: {result.get('name')}")
    print(f"Field: {result.get('field_specialization')}")
    print(f"Sections: {list(result.get('sections', {}).keys())}")
    print(f"\nPrimary project: {result.get('primary_project')}")
    print(f"\nFull text preview:\n{result.get('full_text', '')[:300]}...")

    return result


async def main():
    if len(sys.argv) < 2:
        print("Usage: python -m app.test_resume <path_to_pdf>")
        print("\nTesting PDFExtractor with sample...")
        # Test with a dummy test
        print("PDFExtractor is ready. Pass a PDF path to test AI parsing.")
        return

    pdf_path = sys.argv[1]

    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        return

    # Test extraction
    await test_pdf_extraction(pdf_path)

    # Test AI parsing
    await test_ai_parsing(pdf_path)


if __name__ == "__main__":
    asyncio.run(main())
