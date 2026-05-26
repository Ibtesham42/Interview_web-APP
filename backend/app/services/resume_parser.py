import base64
import io
from typing import Dict, Any, List, Optional
from app.config import get_settings, get_groq_client
from app.services.groq_async import acompletion

settings = get_settings()


class ResumeParser:
    """Parse resume PDFs using OpenAI GPT-4o Vision."""

    def __init__(self):
        self.client = get_groq_client()

    async def parse_resume(self, pdf_content: bytes) -> Dict[str, Any]:
        """Parse a resume PDF and extract structured information."""
        # First, try to extract text from PDF
        try:
            extracted = PDFExtractor.extract_text(pdf_content)
            if extracted.get("success") and extracted.get("full_text"):
                return await self._parse_text(extracted["full_text"])
        except Exception as e:
            print(f"PDF extraction failed: {e}")

        # Fallback: return empty structure
        return {
            "full_text": "",
            "sections": {"education": [], "experience": [], "projects": [], "skills": []},
            "name": "Unknown",
            "primary_project": {}
        }

    async def _parse_with_file_id(self, file_id: str) -> Dict[str, Any]:
        """Parse resume using uploaded file ID."""
        prompt = """
You are an expert resume parser. Analyze this resume and extract structured information.

For the resume provided, identify and extract:

1. **Personal Info**: Name, email, phone (if present)

2. **Education**: List of education entries with degree, institution, field, year

3. **Experience**: List of work experiences with company, role, duration, responsibilities

4. **Projects**: List of projects with name, description, technologies, outcomes

5. **Skills**: Technical skills, programming languages, frameworks, tools

6. **Full Text**: The complete text content of the resume

Return your response as a JSON object with these exact keys:
- "name": candidate name
- "sections": object with keys "education", "experience", "projects", "skills"
- "full_text": complete text content
- "primary_project": the most impressive/relevant project for ML engineer role

Be thorough and extract ALL information visible in the resume.
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"[Resume file ID: {file_id}]\n\n{prompt}"
                        }
                    ]
                }
            ],
        )

        return self._parse_response(response.choices[0].message.content)

    async def _parse_with_vision_fallback(self, pdf_content: bytes) -> Dict[str, Any]:
        """Fallback: Extract PDF pages as images and use vision."""
        try:
            from PyPDF2 import PdfReader
            pdf_reader = PdfReader(io.BytesIO(pdf_content))
            pages_text = []

            for page in pdf_reader.pages:
                text = page.extract_text()
                if text.strip():
                    pages_text.append(text)

            if pages_text:
                # Use GPT-4o to parse the extracted text
                return await self._parse_text("\n\n---PAGE BREAK---\n\n".join(pages_text))
        except ImportError:
            pass

        # Ultimate fallback: return raw response asking for text input
        return {
            "full_text": "PDF parsing failed. Please ensure the PDF contains selectable text.",
            "sections": {"education": [], "experience": [], "projects": [], "skills": []},
            "name": "Unknown",
            "primary_project": {}
        }

    async def _parse_text(self, text: str) -> Dict[str, Any]:
        """Parse resume text using GPT-4o."""
        prompt = f"""
You are an expert resume parser. Analyze this resume text and extract structured information.

Return a JSON object with these exact keys:
- "name": candidate name (or "Unknown" if not found)
- "sections": object with keys "education", "experience", "projects", "skills"
- "full_text": the complete text content
- "primary_project": the most impressive/relevant project for ML engineer role

Resume text:
{text[:15000]}

Be thorough and extract ALL information.
"""

        response = await acompletion(
            self.client,
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
        )

        return self._parse_response(response.choices[0].message.content)

    def _parse_response(self, result_text: str) -> Dict[str, Any]:
        """Parse the JSON response from GPT."""
        import json
        try:
            if "```json" in result_text:
                start = result_text.find("```json") + 7
                end = result_text.find("```", start)
                result_text = result_text[start:end]
            elif "```" in result_text:
                start = result_text.find("```") + 3
                end = result_text.find("```", start)
                result_text = result_text[start:end]

            parsed_data = json.loads(result_text.strip())

            return {
                "full_text": parsed_data.get("full_text", ""),
                "sections": parsed_data.get("sections", {}),
                "name": parsed_data.get("name", "Unknown"),
                "primary_project": parsed_data.get("primary_project", {})
            }
        except json.JSONDecodeError:
            return {
                "full_text": result_text,
                "sections": {},
                "name": "Unknown",
                "primary_project": {}
            }


class PDFExtractor:
    """Standalone PDF text extraction (fallback when OpenAI parsing unavailable)."""

    @staticmethod
    def extract_text(pdf_content: bytes) -> Dict[str, Any]:
        """Extract text from PDF without AI."""
        try:
            from PyPDF2 import PdfReader
            pdf_reader = PdfReader(io.BytesIO(pdf_content))
            pages = []
            full_text = ""

            for i, page in enumerate(pdf_reader.pages):
                text = page.extract_text()
                pages.append({"page": i + 1, "text": text})
                full_text += text + "\n\n"

            return {
                "success": True,
                "page_count": len(pdf_reader.pages),
                "pages": pages,
                "full_text": full_text.strip()
            }
        except ImportError:
            return {
                "success": False,
                "error": "PyPDF2 not installed. Install with: pip install PyPDF2"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
