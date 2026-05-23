import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { interviewWs } from '../services/websocket';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { useIntegrityMonitor } from '../hooks/useIntegrityMonitor';
import { CameraPreflight } from './integrity/CameraPreflight';
import { IntegrityWarning } from './integrity/IntegrityWarning';
import type {
  WebSocketMessage,
  TranscriptMessage,
  Evaluation,
  IntegrityEventType,
} from '../types';

const PHASE_NAMES = ['', 'Background', 'Project #1', 'Project #2', 'Technical', 'Behavioral'];
const MIN_BLOB_BYTES = 1200;
const MIN_DURATION_SEC = 0.5;
const WAVE_FACTORS = [0.45, 0.72, 1, 0.85, 1, 0.7, 0.5];

/**
 * Strict interview turn states. The flow is sequential and one-directional:
 * connecting -> ai_speaking -> ready -> recording -> transcribing -> processing -> ai_speaking ...
 */
type Status =
  | 'connecting'
  | 'ai_speaking'
  | 'ready'
  | 'recording'
  | 'transcribing'
  | 'processing'
  | 'ended';

// --- icons ---
const MicIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);
const StopIcon = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
    <rect x="6" y="6" width="12" height="12" rx="2" />
  </svg>
);
const AiIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
  </svg>
);
const UserIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
    <circle cx="12" cy="7" r="4" />
  </svg>
);

// --- helpers ---
function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const result = reader.result as string;
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.onerror = () => reject(reader.error ?? new Error('Failed to read audio'));
    reader.readAsDataURL(blob);
  });
}

function formatClock(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function InterviewRoom() {
  const { interviewId } = useParams<{ interviewId: string }>();
  const navigate = useNavigate();

  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [status, setStatus] = useState<Status>('connecting');
  const [phase, setPhase] = useState(1);
  const [candidateName, setCandidateName] = useState('Candidate');
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [empathyNudge, setEmpathyNudge] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const [lostConnection, setLostConnection] = useState(false);
  const [interviewTime, setInterviewTime] = useState(0);
  // Integrity / anti-cheating state. cameraStream gates the interview entirely
  // — the WS does not open until the candidate grants camera access.
  const [cameraStream, setCameraStream] = useState<MediaStream | null>(null);
  const [activeWarning, setActiveWarning] = useState<
    { count: number; max: number; eventType: IntegrityEventType } | null
  >(null);
  const [integrityTerminated, setIntegrityTerminated] = useState(false);

  const { startRecording, stopRecording, audioLevel, isSilence, error: micError } =
    useAudioRecorder();

  const audioRef = useRef<HTMLAudioElement>(null);
  const audioUrlRef = useRef<string | null>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  const formatTime = (s: number) =>
    `${Math.floor(s / 60).toString().padStart(2, '0')}:${(s % 60).toString().padStart(2, '0')}`;

  // Interview timer
  useEffect(() => {
    const id = window.setInterval(() => setInterviewTime((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);

  // Smooth auto-scroll as the transcript or turn state changes
  useEffect(() => {
    chatBottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, status]);

  // Releases the turn back to the user once AI playback ends.
  const handleAudioEnded = useCallback(() => {
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    setStatus((s) => (s === 'ai_speaking' ? 'ready' : s));
  }, []);

  // WebSocket connection lifecycle. The socket does NOT open until the
  // candidate has granted camera access in the preflight gate — without it
  // there is no interview, only the gate UI.
  useEffect(() => {
    if (!interviewId || !cameraStream) return;
    let cancelled = false;
    interviewWs.connect(interviewId).catch(() => {
      if (!cancelled) setConnectionError(true);
    });
    return () => {
      cancelled = true;
      interviewWs.disconnect();
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
    };
  }, [interviewId, cameraStream]);

  // Release the camera tracks on unmount so the OS camera indicator turns
  // off the moment the candidate leaves the interview.
  useEffect(() => {
    return () => {
      cameraStream?.getTracks().forEach((t) => t.stop());
    };
  }, [cameraStream]);

  // Surface a camera_lost integrity event if a video track ends unexpectedly
  // (user revokes permission, OS turns the camera off, etc.) while the
  // interview is live.
  useEffect(() => {
    if (!cameraStream) return;
    const track = cameraStream.getVideoTracks()[0];
    if (!track) return;
    const onEnded = () => interviewWs.sendIntegrityEvent('camera_lost');
    track.addEventListener('ended', onEnded);
    return () => track.removeEventListener('ended', onEnded);
  }, [cameraStream]);

  // Phase A integrity monitor — browser APIs only (tab/window/visibility).
  // Disabled while still preflighting, while the WS is connecting, after the
  // interview ends, after an integrity termination, or in any error state.
  const integrityEnabled =
    !!cameraStream &&
    !connectionError &&
    !lostConnection &&
    !integrityTerminated &&
    status !== 'connecting' &&
    status !== 'ended';

  const handleIntegrityEvent = useCallback(
    (eventType: IntegrityEventType, metadata?: Record<string, unknown>) => {
      interviewWs.sendIntegrityEvent(eventType, metadata);
    },
    [],
  );

  useIntegrityMonitor({ enabled: integrityEnabled, onEvent: handleIntegrityEvent });

  // WebSocket handlers — the WebSocket is the single source of truth for state.
  useEffect(() => {
    const onInit = (msg: WebSocketMessage) => {
      if (msg.candidate_name) setCandidateName(msg.candidate_name);
      if (msg.current_phase) setPhase(msg.current_phase);
    };

    const onQuestion = (msg: WebSocketMessage) => {
      const content = (msg.content || '').trim();
      if (!content || content === '[Interview Complete]') return;
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && last.content === content) return prev;
        return [
          ...prev,
          { id: crypto.randomUUID(), role: 'assistant', content, timestamp: Date.now() },
        ];
      });
    };

    const onAudio = (msg: WebSocketMessage) => {
      const el = audioRef.current;
      // Never overlap audio: stop whatever is playing and release its URL.
      if (el && !el.paused) el.pause();
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
        audioUrlRef.current = null;
      }
      const content = msg.content || '';
      if (!content || !el) {
        // No speech to play — hand the turn straight to the user.
        setStatus('ready');
        return;
      }
      const url = URL.createObjectURL(
        new Blob([base64ToArrayBuffer(content)], { type: 'audio/mpeg' }),
      );
      audioUrlRef.current = url;
      el.src = url;
      setStatus('ai_speaking');
      el.play().catch(() => setStatus('ready'));
    };

    const onEvaluation = (msg: WebSocketMessage) => {
      if (msg.data) setEvaluation(msg.data as unknown as Evaluation);
    };

    const onPhaseUpdate = (msg: WebSocketMessage) => {
      if (msg.phase) setPhase(msg.phase);
    };

    const onEmpathyNudge = (msg: WebSocketMessage) => {
      if (msg.content) {
        setEmpathyNudge(msg.content);
        window.setTimeout(() => setEmpathyNudge(null), 6000);
      }
    };

    const onVoiceTranscript = (msg: WebSocketMessage) => {
      const transcript = (msg.transcript || '').trim();
      if (!transcript) {
        setNotice("I didn't catch that — tap the mic and answer again.");
        setStatus('ready');
        return;
      }
      setNotice(null);
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: 'user', content: transcript, timestamp: Date.now() },
      ]);
      setStatus('processing');
      interviewWs.sendAnswer(transcript);
    };

    const onVoiceError = () => {
      setNotice('Transcription failed — tap the mic and try again.');
      setStatus('ready');
    };

    const onBackendError = (msg: WebSocketMessage) => {
      setNotice(msg.message || 'A server error occurred.');
    };

    const onInterviewEnded = (msg: WebSocketMessage) => {
      setStatus('ended');
      audioRef.current?.pause();
      // Integrity-terminated interviews stay on this screen so the candidate
      // sees the reason explicitly; the partial report is still reachable.
      if (msg.reason === 'integrity_terminated') {
        setIntegrityTerminated(true);
        return;
      }
      navigate(`/report/${interviewId}`);
    };

    const onIntegrityWarning = (msg: WebSocketMessage) => {
      if (typeof msg.count !== 'number' || typeof msg.max !== 'number' || !msg.event_type) return;
      // The backend's terminate signal arrives as a normal warning frame
      // followed by an interview_ended frame; the overlay reflects the count.
      setActiveWarning({ count: msg.count, max: msg.max, eventType: msg.event_type });
    };

    // The socket dropped after the interview was already running. The
    // in-memory orchestrator cannot be resumed (ADR 0002) — surface a
    // terminal state instead of silently restarting the interview.
    const onDisconnected = () => {
      audioRef.current?.pause();
      setLostConnection(true);
    };

    interviewWs.on('init', onInit);
    interviewWs.on('question', onQuestion);
    interviewWs.on('audio', onAudio);
    interviewWs.on('evaluation', onEvaluation);
    interviewWs.on('phase_update', onPhaseUpdate);
    interviewWs.on('empathy_nudge', onEmpathyNudge);
    interviewWs.on('voice_transcript', onVoiceTranscript);
    interviewWs.on('voice_error', onVoiceError);
    interviewWs.on('error', onBackendError);
    interviewWs.on('interview_ended', onInterviewEnded);
    interviewWs.on('disconnected', onDisconnected);
    interviewWs.on('integrity_warning', onIntegrityWarning);

    return () => {
      interviewWs.off('init', onInit);
      interviewWs.off('question', onQuestion);
      interviewWs.off('audio', onAudio);
      interviewWs.off('evaluation', onEvaluation);
      interviewWs.off('phase_update', onPhaseUpdate);
      interviewWs.off('empathy_nudge', onEmpathyNudge);
      interviewWs.off('voice_transcript', onVoiceTranscript);
      interviewWs.off('voice_error', onVoiceError);
      interviewWs.off('error', onBackendError);
      interviewWs.off('interview_ended', onInterviewEnded);
      interviewWs.off('disconnected', onDisconnected);
      interviewWs.off('integrity_warning', onIntegrityWarning);
    };
  }, [interviewId, navigate]);

  // Recording is only permitted when it is genuinely the user's turn.
  const handleRecord = useCallback(async () => {
    setNotice(null);

    if (status === 'ready') {
      try {
        await startRecording();
        setStatus('recording');
      } catch {
        setStatus('ready'); // micError surfaces the reason
      }
      return;
    }

    if (status === 'recording') {
      try {
        const { audioBlob, duration } = await stopRecording();
        if (!audioBlob || audioBlob.size < MIN_BLOB_BYTES || duration < MIN_DURATION_SEC) {
          setNotice('That was too short — tap the mic and speak your full answer.');
          setStatus('ready');
          return;
        }
        setStatus('transcribing');
        const base64 = await blobToBase64(audioBlob);
        interviewWs.sendVoice(base64, duration);
      } catch {
        setNotice('Recording failed — tap the mic and try again.');
        setStatus('ready');
      }
    }
  }, [status, startRecording, stopRecording]);

  const handleEnd = useCallback(() => {
    interviewWs.sendEndInterview();
  }, []);

  const lastMessage = messages[messages.length - 1];
  const micEnabled = status === 'ready' || status === 'recording';
  const showConnecting = !connectionError && status === 'connecting' && messages.length === 0;

  return (
    <div className="interview-container">
      {/* Audio element is always mounted so playback never races the DOM. */}
      <audio ref={audioRef} hidden onEnded={handleAudioEnded} onError={handleAudioEnded} />

      {activeWarning && (
        <IntegrityWarning
          count={activeWarning.count}
          max={activeWarning.max}
          eventType={activeWarning.eventType}
          onDismiss={() => setActiveWarning(null)}
        />
      )}

      {!cameraStream ? (
        <CameraPreflight onReady={setCameraStream} />
      ) : integrityTerminated ? (
        <div className="iv-connect-state iv-terminated">
          <div className="iv-connect-icon error">!</div>
          <h3>Interview terminated</h3>
          <p>
            This interview was ended early because the integrity warning limit
            ({activeWarning?.max ?? 3}) was reached. Your progress up to this point
            was saved.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/')}
            style={{ marginTop: 'var(--space-md)' }}
          >
            Back to dashboard
          </button>
        </div>
      ) : connectionError ? (
        <div className="iv-connect-state">
          <div className="iv-connect-icon error">!</div>
          <h3>Unable to connect</h3>
          <p>We couldn't reach the interview server. Check your connection and refresh the page.</p>
        </div>
      ) : lostConnection ? (
        <div className="iv-connect-state">
          <div className="iv-connect-icon error">!</div>
          <h3>Connection lost</h3>
          <p>
            The interview connection dropped and can't be resumed. Your progress up to
            this point was saved.
          </p>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/')}
            style={{ marginTop: 'var(--space-md)' }}
          >
            Back to dashboard
          </button>
        </div>
      ) : showConnecting ? (
        <div className="iv-connect-state">
          <div className="spinner" />
          <div className="loading-text">Preparing your interview…</div>
        </div>
      ) : (
        <>
          {/* Header */}
          <div className="interview-header">
            <div className="interview-info">
              <div className="ai-avatar">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                  <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                  <line x1="12" y1="19" x2="12" y2="23" />
                  <line x1="8" y1="23" x2="16" y2="23" />
                </svg>
              </div>
              <div>
                <h3 style={{ fontSize: '0.9375rem', marginBottom: '2px' }}>
                  Interview with {candidateName}
                </h3>
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)' }}>
                  {PHASE_NAMES[phase]} · Voice Interview
                </p>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexWrap: 'wrap' }}>
              <div className="progress-bar">
                {[1, 2, 3, 4, 5].map((p, i) => (
                  <div key={p} className="progress-step">
                    <div className={`progress-dot ${p === phase ? 'active' : ''} ${p < phase ? 'completed' : ''}`} />
                    {i < 4 && <div className={`progress-line ${p < phase ? 'completed' : ''}`} />}
                  </div>
                ))}
              </div>

              <div className="interview-timer">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <polyline points="12 6 12 12 16 14" />
                </svg>
                <span>{formatTime(interviewTime)}</span>
              </div>

              <button
                className="btn btn-danger"
                onClick={handleEnd}
                style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
              >
                End
              </button>
            </div>
          </div>

          {empathyNudge && <div className="empathy-nudge">{empathyNudge}</div>}

          {/* Transcript */}
          <div className="chat-window" role="log" aria-live="polite" aria-label="Interview transcript">
            {messages.map((m) => {
              const speaking =
                status === 'ai_speaking' && m.id === lastMessage?.id && m.role === 'assistant';
              return (
                <div key={m.id} className={`msg msg-${m.role === 'assistant' ? 'ai' : 'user'}`}>
                  <div className="msg-avatar" aria-hidden="true">
                    {m.role === 'assistant' ? <AiIcon /> : <UserIcon />}
                  </div>
                  <div className="msg-body">
                    <div className="msg-meta">
                      <span className="msg-author">
                        {m.role === 'assistant' ? 'Interviewer' : 'You'}
                      </span>
                      <span className="msg-time">{formatClock(m.timestamp)}</span>
                    </div>
                    <div className={`msg-bubble${speaking ? ' speaking' : ''}`}>{m.content}</div>
                    {speaking && (
                      <div className="msg-status">
                        <span className="eq" aria-hidden="true">
                          <i /><i /><i />
                        </span>
                        Speaking
                      </div>
                    )}
                  </div>
                </div>
              );
            })}

            {status === 'transcribing' && (
              <div className="msg msg-user">
                <div className="msg-avatar" aria-hidden="true"><UserIcon /></div>
                <div className="msg-body">
                  <div className="msg-meta"><span className="msg-author">You</span></div>
                  <div className="msg-bubble pending">
                    <span className="typing" aria-hidden="true"><i /><i /><i /></span>
                  </div>
                </div>
              </div>
            )}

            {status === 'processing' && lastMessage?.role === 'user' && (
              <div className="msg msg-ai">
                <div className="msg-avatar" aria-hidden="true"><AiIcon /></div>
                <div className="msg-body">
                  <div className="msg-meta"><span className="msg-author">Interviewer</span></div>
                  <div className="msg-bubble pending">
                    <span className="typing" aria-hidden="true"><i /><i /><i /></span>
                  </div>
                </div>
              </div>
            )}

            <div ref={chatBottomRef} />
          </div>

          {/* Turn / input area */}
          <div className="input-area">
            <div className="turn-state" aria-live="polite">
              {status === 'connecting' && (
                <>
                  <span className="turn-pill busy">
                    <span className="typing sm" aria-hidden="true"><i /><i /><i /></span>
                    Starting…
                  </span>
                  <div className="turn-hint">Preparing your first question.</div>
                </>
              )}

              {status === 'ai_speaking' && (
                <>
                  <span className="turn-pill speaking">
                    <span className="eq small" aria-hidden="true"><i /><i /><i /></span>
                    Interviewer speaking
                  </span>
                  <div className="turn-hint">Listen to the question — you'll answer next.</div>
                </>
              )}

              {status === 'ready' && (
                <>
                  <span className="turn-pill ready">
                    <span className="turn-dot" style={{ background: 'var(--accent-green)' }} />
                    Your turn
                  </span>
                  <div className="turn-title">Tap the mic to answer</div>
                  <div className="turn-hint">Speak naturally — your answer is transcribed automatically.</div>
                </>
              )}

              {status === 'recording' && (
                <>
                  <span className="turn-pill live">
                    <span
                      className={`turn-dot ${isSilence ? '' : 'pulse'}`}
                      style={{ background: 'var(--accent-rose)' }}
                    />
                    {isSilence ? 'Listening…' : 'Speech detected'}
                  </span>
                  <div className="voice-wave" aria-hidden="true">
                    {WAVE_FACTORS.map((f, i) => (
                      <div
                        key={i}
                        className="voice-wave-bar"
                        style={{
                          height: `${Math.max(6, Math.min(34, 6 + audioLevel * f * 0.32))}px`,
                          opacity: isSilence ? 0.35 : 0.9,
                        }}
                      />
                    ))}
                  </div>
                  <div className="turn-hint">Tap again when you've finished your answer.</div>
                </>
              )}

              {status === 'transcribing' && (
                <>
                  <span className="turn-pill busy">
                    <span className="typing sm" aria-hidden="true"><i /><i /><i /></span>
                    Processing…
                  </span>
                  <div className="turn-hint">Transcribing your answer.</div>
                </>
              )}

              {status === 'processing' && (
                <>
                  <span className="turn-pill busy">
                    <span className="typing sm" aria-hidden="true"><i /><i /><i /></span>
                    Preparing…
                  </span>
                  <div className="turn-hint">Generating the next question.</div>
                </>
              )}

              {micError && <div className="turn-error">{micError}</div>}
              {notice && !micError && <div className="turn-notice">{notice}</div>}
            </div>

            <button
              className={`record-btn ${status === 'recording' ? 'recording' : ''}`}
              onClick={handleRecord}
              disabled={!micEnabled}
              aria-label={status === 'recording' ? 'Stop recording' : 'Start recording'}
            >
              {status === 'recording' ? <StopIcon /> : <MicIcon />}
            </button>
          </div>

          {/* Evaluation Panel */}
          {evaluation && (
            <div className="evaluation-panel">
              <div className="evaluation-grid">
                {Object.entries(evaluation.details || {}).map(([key, value]) => (
                  <div key={key} className="evaluation-item">
                    <div className="evaluation-score">{Number(value).toFixed(1)}</div>
                    <div className="evaluation-label">{key.replace(/_/g, ' ')}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
