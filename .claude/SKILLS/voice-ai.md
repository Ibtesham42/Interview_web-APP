# Voice AI Engineering Standards

## Speech Recognition (STT)

### Frontend Recording
- **Sample rate**: 16000 Hz (optimal for Whisper)
- **Channels**: Mono (channelCount: 1)
- **Codec**: webm/opus (best Whisper compatibility)
- **Audio processing**:
  - Enable echoCancellation, noiseSuppression, autoGainControl
  - Focus on speech frequencies (85-255Hz) for level detection
  - Silence threshold: < 8 audio units = silence

### Recording States
```typescript
interface RecordingState {
  isRecording: boolean;
  audioLevel: number;      // 0-100, for visualization
  isSilence: boolean;       // true if below threshold
  error: string | null;
}
```

### MediaRecorder Configuration
- Timeslice: 100ms intervals for responsive capture
- MIME type priority: webm/opus → webm → mp4 → ogg
- Cleanup: Stop all tracks, close AudioContext on stop/unmount

### User Feedback
- Show audio level in real-time
- Visual indicator: "Listening..." / "Speech detected" / "Processing..."
- Handle permission denial gracefully
- No auto-stop - user controls recording duration

## Speech Synthesis (TTS)

### Edge TTS (Primary)
- Voice: en-US-JennyNeural (professional female)
- Alternative: en-US-GuyNeural (professional male)
- Format: MP3 via edge-tts library
- Latency target: < 3 seconds

### Audio Playback
- Use HTMLAudioElement for playback
- Handle multiple rapid requests (queue or cancel)
- Report completion to update UI state
- Base64 encoding for WebSocket transmission

## Transcript Handling

### Backend (Whisper)
- Model: whisper-1
- Language hint: "en" for faster, more accurate transcription
- Temperature: 0.0 for deterministic output
- Format: text (not verbose_json for simple use case)

### Frontend Display
- Show live transcript while recording
- Display "Processing..." during API call
- Handle empty transcriptions gracefully
- No partial results - wait for final Whisper output

## Real-Time Requirements

### Latency Budget
- Recording start: < 200ms
- Audio capture to WebSocket: real-time chunking
- Whisper transcription: 1-3 seconds
- TTS generation: 1-3 seconds
- Audio playback: < 500ms after generation

### Error Handling
- Network failure: Retry once, then show error
- Microphone denied: Clear message with instructions
- Whisper failure: Allow text fallback input
- TTS failure: Show question text without audio

## Quality Standards

- No choppy audio - ensure clean capture
- Handle background noise - visual indicator when detected
- Responsive feedback - no dead air feel
- Conversational pacing - appropriate pauses between Q&A