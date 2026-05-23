import { useEffect, useRef } from 'react';

interface CameraThumbnailProps {
  stream: MediaStream;
}

/**
 * Small live preview of the candidate's camera in the interview UI.
 *
 * Mounted only while the interview is live (not on the preflight gate, error
 * screens, or the integrity-terminated screen). The stream is owned by
 * InterviewRoom — this component only attaches it to the video element.
 *
 * Muted + autoPlay + playsInline is the standard combination required to
 * silently play a MediaStream in modern browsers without user interaction.
 */
export function CameraThumbnail({ stream }: CameraThumbnailProps) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;
    return () => {
      // Detach the stream — do NOT stop tracks here; the owner (InterviewRoom)
      // is responsible for the stream's lifetime.
      video.srcObject = null;
    };
  }, [stream]);

  return (
    <div className="camera-thumbnail" aria-hidden="true">
      <video ref={videoRef} autoPlay muted playsInline />
      <div className="camera-thumbnail-badge">
        <span className="camera-thumbnail-dot" />
        Live
      </div>
    </div>
  );
}
