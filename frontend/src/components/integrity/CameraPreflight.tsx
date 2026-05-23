import { useCallback, useState } from 'react';

interface CameraPreflightProps {
  /** Called once the camera stream has been acquired. */
  onReady: (stream: MediaStream) => void;
}

type Status = 'idle' | 'requesting' | 'denied' | 'unsupported' | 'error';

/**
 * Mandatory pre-interview camera gate.
 *
 * The interview cannot proceed until the candidate explicitly grants camera
 * access. Frames stay on-device — only integrity events (no images) are sent
 * to the backend. The acquired MediaStream is handed up to InterviewRoom,
 * which holds it for the interview's lifetime and stops the tracks on
 * unmount.
 */
export function CameraPreflight({ onReady }: CameraPreflightProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const requestCamera = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus('unsupported');
      return;
    }
    setStatus('requesting');
    setErrorMsg(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, facingMode: 'user' },
        audio: false,
      });
      onReady(stream);
    } catch (err) {
      if (
        err instanceof DOMException &&
        (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')
      ) {
        setStatus('denied');
        return;
      }
      setStatus('error');
      setErrorMsg(err instanceof Error ? err.message : 'Camera access failed.');
    }
  }, [onReady]);

  return (
    <div className="iv-connect-state">
      <CameraIcon />
      <h3>Camera access required</h3>
      {status === 'idle' && (
        <>
          <p>
            This interview is monitored. Your camera must be on for the session to start.
            Video frames stay on your device — only integrity events (not images) are sent.
          </p>
          <button className="btn btn-primary" onClick={requestCamera}>
            Enable camera
          </button>
        </>
      )}
      {status === 'requesting' && (
        <>
          <div className="spinner" />
          <p>Waiting for camera permission…</p>
        </>
      )}
      {status === 'denied' && (
        <>
          <p>
            Camera permission was denied. Allow camera access in your browser settings,
            then click below to try again.
          </p>
          <button className="btn btn-primary" onClick={requestCamera}>
            Try again
          </button>
        </>
      )}
      {status === 'unsupported' && (
        <p>
          Your browser does not expose a camera API. Please switch to a current version of
          Chrome, Edge, Firefox or Safari to start the interview.
        </p>
      )}
      {status === 'error' && (
        <>
          <p>{errorMsg ?? 'Unable to access the camera.'}</p>
          <button className="btn btn-primary" onClick={requestCamera}>
            Try again
          </button>
        </>
      )}
    </div>
  );
}

function CameraIcon() {
  return (
    <div className="iv-connect-icon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M23 7l-7 5 7 5V7z" />
        <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
      </svg>
    </div>
  );
}
