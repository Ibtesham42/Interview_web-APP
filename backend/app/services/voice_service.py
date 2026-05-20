import base64
import io
import wave
import os
import tempfile
from typing import Optional, Dict, Any
import httpx
import edge_tts
from app.config import get_settings, get_groq_client

settings = get_settings()


class VoiceService:
    """Free TTS service using Edge TTS (primary) and Piper (optional)."""

    def __init__(self):
        self.use_piper = settings.use_piper_tts
        self.piper_voice_path = settings.piper_voice_path
        self._piper_voice = None

        # Edge TTS voices - professional and natural
        self.edge_voice = "en-US-JennyNeural"  # Professional female voice
        self.edge_voice_male = "en-US-GuyNeural"  # Professional male voice

    def _get_piper_voice(self):
        """Load Piper voice (lazy loading)."""
        if self._piper_voice is not None:
            return self._piper_voice

        if not self.piper_voice_path or not os.path.exists(self.piper_voice_path):
            # Try to find voice in default locations
            default_paths = [
                os.path.join(os.path.dirname(__file__), "..", "voices", "en_US-lessac-medium.onnx"),
                os.path.join(os.getcwd(), "voices", "en_US-lessac-medium.onnx"),
                "en_US-lessac-medium.onnx",
            ]
            for path in default_paths:
                if os.path.exists(path):
                    self.piper_voice_path = path
                    break

        if self.piper_voice_path and os.path.exists(self.piper_voice_path):
            from piper import PiperVoice
            self._piper_voice = PiperVoice.load(self.piper_voice_path)
            return self._piper_voice

        return None

    async def text_to_speech(self, text: str, output_path: Optional[str] = None) -> bytes:
        """Convert text to speech using Edge TTS (free) or Piper (optional)."""
        # Try Edge TTS first (free, no API key needed, high quality)
        try:
            return await self._edge_tts(text, output_path)
        except Exception as e:
            print(f"[VoiceService] Edge TTS failed: {e}")

        # Try Piper if enabled
        if self.use_piper:
            try:
                piper_voice = self._get_piper_voice()
                if piper_voice:
                    return self._piper_synthesize(text, output_path)
            except Exception as e:
                print(f"[VoiceService] Piper failed: {e}")

        # Return empty bytes if all fail
        return b""

    async def _edge_tts(self, text: str, output_path: Optional[str] = None) -> bytes:
        """Convert text to speech using Microsoft Edge TTS (free)."""
        communicate = edge_tts.Communicate(text, self.edge_voice)

        if output_path:
            await communicate.save(output_path)
            with open(output_path, "rb") as f:
                return f.read()
        else:
            # Use temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                temp_path = f.name
            try:
                await communicate.save(temp_path)
                with open(temp_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

    def _piper_synthesize(self, text: str, output_path: Optional[str] = None) -> bytes:
        """Synthesize speech using Piper."""
        piper_voice = self._get_piper_voice()
        if not piper_voice:
            raise Exception("Piper voice not loaded")

        # Create temp file for wave output
        if output_path:
            with wave.open(output_path, "wb") as wav_file:
                piper_voice.synthesize_wav(text, wav_file)
            with open(output_path, "rb") as f:
                return f.read()
        else:
            # Use temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                temp_path = f.name
            try:
                with wave.open(temp_path, "wb") as wav_file:
                    piper_voice.synthesize_wav(text, wav_file)
                with open(temp_path, "rb") as f:
                    return f.read()
            finally:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

    async def _elevenlabs_tts(self, text: str, output_path: Optional[str] = None) -> bytes:
        """Convert text to speech using 11Labs."""
        url = f"{self.base_url}/text-to-speech/{self.voice_id}"

        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": self.api_key
        }

        payload = {
            "text": text,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=30.0)

        if response.status_code != 200:
            raise Exception(f"11Labs API error: {response.status_code} - {response.text}")

        audio_content = response.content

        if output_path:
            with open(output_path, "wb") as f:
                f.write(audio_content)

        return audio_content


class SpeechToTextService:
    """OpenAI Whisper-based speech-to-text service."""

    def __init__(self):
        self.client = get_groq_client()

    async def transcribe_audio(self, audio_content: bytes, filename: str = "audio.webm") -> str:
        """Transcribe audio using Whisper with optimized settings."""
        import tempfile
        import os

        # Determine file extension from filename
        ext = os.path.splitext(filename)[1].lower() if filename else ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            f.write(audio_content)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as audio_file:
                # Use Whisper-1 with language hint for better accuracy
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=audio_file,
                    language="en",
                    response_format="text",
                    temperature=0.0  # More deterministic output
                )
            # With response_format="text" the SDK returns a plain string,
            # not an object with a `.text` attribute.
            text = transcript if isinstance(transcript, str) else getattr(transcript, "text", "")
            return text.strip() if text else ""
        finally:
            os.unlink(temp_path)

    async def transcribe_with_timestamps(self, audio_content: bytes, filename: str = "audio.webm") -> Dict[str, Any]:
        """Transcribe with word-level timestamps."""
        import tempfile
        import os

        ext = os.path.splitext(filename)[1].lower() if filename else ".webm"
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
            f.write(audio_content)
            temp_path = f.name

        try:
            with open(temp_path, "rb") as audio_file:
                transcript = self.client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=audio_file,
                    language="en",
                    response_format="verbose_json",
                    timestamp_granularities=["word"],
                    temperature=0.0
                )
            return {
                "text": transcript.text,
                "words": getattr(transcript, 'words', []),
                "duration": getattr(transcript, 'duration', None)
            }
        finally:
            os.unlink(temp_path)


class VoiceAnalyzer:
    """Analyze voice characteristics for empathy features."""

    def __init__(self):
        self.client = get_groq_client()

    async def analyze_pace(self, text: str, duration_seconds: float) -> Dict[str, Any]:
        """Analyze speaking pace (words per minute)."""
        if not text or duration_seconds <= 0:
            return {
                "words_per_minute": 0,
                "is_too_fast": False,
                "is_too_slow": False,
                "recommendation": ""
            }

        word_count = len(text.split())
        words_per_minute = (word_count / duration_seconds) * 60

        recommendation = self._get_pace_recommendation(words_per_minute)

        return {
            "words_per_minute": round(words_per_minute, 1),
            "word_count": word_count,
            "duration_seconds": duration_seconds,
            "is_too_fast": words_per_minute > 180,
            "is_too_slow": words_per_minute < 60,
            "recommendation": recommendation
        }

    def _get_pace_recommendation(self, wpm: float) -> str:
        if wpm > 220:
            return "Take a breath. Please slow down and collect your thoughts."
        elif wpm > 180:
            return "Let's take a moment. Please feel free to pause before answering."
        elif wpm < 50:
            return "That's fine, take your time."
        return ""

    async def generate_empathy_nudge(self, pace_analysis: Dict[str, Any]) -> Optional[str]:
        """Generate an empathy nudge based on voice analysis."""
        if not pace_analysis.get("recommendation"):
            return None

        prompt = f"""A candidate is doing a mock interview. Their speech analysis shows:
- Words per minute: {pace_analysis.get('words_per_minute', 0):.0f}
- Issue: {pace_analysis.get('recommendation', 'None')}

Generate a brief, professional encouragement message to help them relax.
Keep it under 15 words. Be warm but professional. Do not be overly enthusiastic.
"""

        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )

        return response.choices[0].message.content.strip()

    async def analyze_sentiment_hint(self, text: str) -> Dict[str, Any]:
        """Get a hint about sentiment from text (future: video-based)."""
        if not text:
            return {"sentiment": "neutral", "confidence": 0}

        prompt = f"""Analyze this interview response for emotional tone:
"{text[:500]}"

Return JSON with:
- sentiment: one of "nervous", "confident", "uncertain", "frustrated", "neutral"
- confidence: 0.0 to 1.0
- flags: list of issues like ["speaking_too_fast", "hedging", "unclear"]

Return ONLY valid JSON, no markdown.
"""

        response = self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}]
        )

        import json
        try:
            result = json.loads(response.choices[0].message.content.strip())
            return result
        except:
            return {"sentiment": "neutral", "confidence": 0, "flags": []}
