import { useRef, useState, forwardRef, useImperativeHandle } from 'react';
import styles from './VideoPlayer.module.css';

export interface VideoPlayerHandle {
  seekTo: (seconds: number) => void;
}

interface VideoPlayerProps {
  src: string;
  className?: string;
  poster?: string;
  onTimeUpdate?: (time: number) => void;
}

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export const VideoPlayer = forwardRef<VideoPlayerHandle, VideoPlayerProps>(
  function VideoPlayer({ src, className, poster, onTimeUpdate }, ref) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const [speed, setSpeed] = useState(1);

    useImperativeHandle(ref, () => ({
      seekTo(seconds: number) {
        const v = videoRef.current;
        if (!v) return;
        v.currentTime = Math.max(0, seconds);
        v.play().catch(() => {});
      },
    }));

    const changeSpeed = (s: number) => {
      setSpeed(s);
      if (videoRef.current) videoRef.current.playbackRate = s;
    };

    const togglePiP = async () => {
      const v = videoRef.current;
      if (!v || !document.pictureInPictureEnabled) return;
      try {
        if (document.pictureInPictureElement) await document.exitPictureInPicture();
        else await v.requestPictureInPicture();
      } catch { /* ignore */ }
    };

    return (
      <div className={`${styles.player} ${className || ''}`}>
        <video
          ref={videoRef}
          src={src}
          poster={poster}
          controls
          preload="metadata"
          onTimeUpdate={e => onTimeUpdate?.(e.currentTarget.currentTime)}
        />
        <div className={styles.controls}>
          <div className={styles.speedGroup}>
            {SPEEDS.map(s => (
              <button
                key={s}
                type="button"
                className={`${styles.speedBtn} ${speed === s ? styles.speedActive : ''}`}
                onClick={() => changeSpeed(s)}
              >
                {s}x
              </button>
            ))}
          </div>
          {typeof document !== 'undefined' && document.pictureInPictureEnabled && (
            <button type="button" className={styles.pipBtn} onClick={togglePiP} title="Picture in Picture">
              PiP
            </button>
          )}
        </div>
      </div>
    );
  }
);

/** Parse timestamp HH:MM:SS,mmm to seconds */
export function timestampToSeconds(ts: string): number {
  const normalized = ts.trim().replace(',', '.');
  const parts = normalized.split(':');
  if (parts.length < 2) return 0;
  const h = parts.length === 3 ? parseInt(parts[0], 10) : 0;
  const m = parseInt(parts[parts.length - 2], 10);
  const s = parseFloat(parts[parts.length - 1]);
  return h * 3600 + m * 60 + s;
}
