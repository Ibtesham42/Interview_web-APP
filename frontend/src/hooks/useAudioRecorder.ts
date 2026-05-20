import { useState, useRef, useCallback, useEffect } from 'react';

interface UseAudioRecorderReturn {
  isRecording: boolean;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<{ audioBlob: Blob; duration: number }>;
  audioLevel: number; // 0-100, real-time input level
  isSilence: boolean;
  error: string | null;
}

// Below this level (0-100 RMS scale) the input is treated as silence.
const SILENCE_LEVEL = 12;

// MIME types in order of Whisper compatibility preference.
const MIME_PRIORITY = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
];

export function useAudioRecorder(): UseAudioRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [isSilence, setIsSilence] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);
  const monitoringRef = useRef(false);
  const startTimeRef = useRef(0);

  // Releases the microphone, audio graph and animation loop.
  const cleanup = useCallback(() => {
    monitoringRef.current = false;
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    analyserRef.current = null;
    setAudioLevel(0);
    setIsSilence(true);
  }, []);

  useEffect(() => cleanup, [cleanup]);

  // RMS over the time-domain waveform — captures all speech energy reliably,
  // unlike summing a narrow frequency band.
  const monitorLevel = useCallback(() => {
    const analyser = analyserRef.current;
    if (!analyser || !monitoringRef.current) return;

    const buffer = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buffer);

    let sumSquares = 0;
    for (let i = 0; i < buffer.length; i++) {
      const v = (buffer[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / buffer.length);
    const level = Math.min(100, Math.round(rms * 320));

    setAudioLevel(level);
    setIsSilence(level < SILENCE_LEVEL);

    rafRef.current = requestAnimationFrame(monitorLevel);
  }, []);

  const startRecording = useCallback(async () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') return;

    setError(null);
    chunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000,
        },
      });
      streamRef.current = stream;

      // Live level monitoring via an analyser node.
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioContext = new AudioCtx();
      if (audioContext.state === 'suspended') await audioContext.resume();
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.4;
      source.connect(analyser);
      analyserRef.current = analyser;

      let mimeType = '';
      for (const m of MIME_PRIORITY) {
        if (MediaRecorder.isTypeSupported(m)) {
          mimeType = m;
          break;
        }
      }

      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onerror = () => setError('Recording error — please try again.');

      startTimeRef.current = Date.now();
      // No timeslice: the browser delivers one complete, header-valid blob
      // on stop — exactly what Whisper needs.
      recorder.start();

      monitoringRef.current = true;
      setIsRecording(true);
      setIsSilence(true);
      rafRef.current = requestAnimationFrame(monitorLevel);
    } catch (e) {
      cleanup();
      const denied = e instanceof DOMException && e.name === 'NotAllowedError';
      setError(
        denied
          ? 'Microphone access denied. Enable it in your browser settings and try again.'
          : 'Could not access the microphone. Check your device and try again.',
      );
      throw e;
    }
  }, [monitorLevel, cleanup]);

  const stopRecording = useCallback(() => {
    return new Promise<{ audioBlob: Blob; duration: number }>((resolve, reject) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === 'inactive') {
        reject(new Error('Not recording'));
        return;
      }

      const duration = (Date.now() - startTimeRef.current) / 1000;

      recorder.onstop = () => {
        const type = chunksRef.current[0]?.type || recorder.mimeType || 'audio/webm';
        const audioBlob = new Blob(chunksRef.current, { type });
        chunksRef.current = [];
        mediaRecorderRef.current = null;
        setIsRecording(false);
        cleanup();
        resolve({ audioBlob, duration });
      };

      recorder.stop();
    });
  }, [cleanup]);

  return { isRecording, startRecording, stopRecording, audioLevel, isSilence, error };
}
