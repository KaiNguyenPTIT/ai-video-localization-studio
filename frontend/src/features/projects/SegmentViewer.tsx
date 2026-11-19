import { useRef, useState } from 'react';
import { VideoPlayer, timestampToSeconds, type VideoPlayerHandle } from '@/features/library/VideoPlayer';
import type { Segment } from '@/shared/lib/types';
import styles from './SegmentViewer.module.css';

interface SegmentViewerProps {
  videoUrl: string;
  segments: Segment[];
}

export function SegmentViewer({ videoUrl, segments }: SegmentViewerProps) {
  const playerRef = useRef<VideoPlayerHandle>(null);
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  const seekSegment = (seg: Segment, idx: number) => {
    setActiveIdx(idx);
    playerRef.current?.seekTo(timestampToSeconds(seg.start_time));
  };

  return (
    <div className={styles.viewer}>
      <VideoPlayer ref={playerRef} src={videoUrl} />
      <div className={styles.header}>
        <h4>Script Review</h4>
        <span className={styles.count}>
          {segments.length} segments
          {segments.reduce((acc, s) => acc + (s.shot_count || 0), 0) > 0 && ` · ${segments.reduce((acc, s) => acc + (s.shot_count || 0), 0)} shots`}
        </span>
      </div>
      <div className={styles.list}>
        {segments.map((seg, i) => (
          <button
            key={i}
            type="button"
            className={`${styles.segment} ${activeIdx === i ? styles.segmentActive : ''}`}
            onClick={() => seekSegment(seg, i)}
          >
            <span className={styles.ts}>{seg.start_time}</span>
            <span className={styles.narration}>{seg.narration}</span>
            <span className={styles.badges}>
              {(seg.tts_duration ?? 0) > 0 && (
                <span className={styles.badge}>🎙 {(seg.tts_duration as number).toFixed(1)}s</span>
              )}
              {(seg.shot_count ?? 0) > 0 && (
                <span className={styles.badge}>🎞 {seg.shot_count} shot</span>
              )}
            </span>
          </button>
        ))}
      </div>
      <p className={styles.hint}>Click a segment to seek the video. Read-only — editing requires a backend API.</p>
    </div>
  );
}
