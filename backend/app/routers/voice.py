from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from typing import Optional
import io

from app.services.voice_service import VoiceService, SpeechToTextService, VoiceAnalyzer

router = APIRouter()


@router.post("/tts")
async def text_to_speech(text: str = Form(...)):
    """Convert text to speech using Edge TTS (free)."""
    try:
        voice_service = VoiceService()
        audio_content = await voice_service.text_to_speech(text)

        return StreamingResponse(
            io.BytesIO(audio_content),
            media_type="audio/mpeg",
            headers={"Content-Disposition": "inline"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tts/file")
async def text_to_speech_file(text: str = Form(...), filename: str = Form("audio.mp3")):
    """Convert text to speech and return as downloadable file."""
    try:
        voice_service = VoiceService()
        audio_content = await voice_service.text_to_speech(text)

        return StreamingResponse(
            io.BytesIO(audio_content),
            media_type="audio/mpeg",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stt")
async def speech_to_text(file: UploadFile = File(...)):
    """Transcribe audio to text using OpenAI Whisper."""
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="File must be audio")

    try:
        audio_content = await file.read()
        stt_service = SpeechToTextService()
        transcript = await stt_service.transcribe_audio(audio_content, file.filename)

        return {"transcript": transcript}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_speech(
    file: UploadFile = File(...),
    duration_seconds: float = Form(...)
):
    """Analyze speech characteristics for pace and sentiment."""
    if not file.content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="File must be audio")

    try:
        audio_content = await file.read()
        stt_service = SpeechToTextService()
        analyzer = VoiceAnalyzer()

        # Transcribe first
        transcription = await stt_service.transcribe_audio(audio_content, file.filename)

        # Analyze pace
        pace_analysis = await analyzer.analyze_pace(transcription, duration_seconds)

        # Analyze sentiment
        sentiment = await analyzer.analyze_sentiment_hint(transcription)

        return {
            "transcript": transcription,
            "pace": pace_analysis,
            "sentiment": sentiment,
            "empathy_nudge": pace_analysis.get("recommendation", "") if pace_analysis.get("is_too_fast") else None
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))