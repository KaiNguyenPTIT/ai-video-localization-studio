import type { Segment } from '@/shared/lib/types';
import styles from './ScriptPreview.module.css';

interface ScriptPreviewProps {
  segments: Segment[];
  title?: string;
}

export function ScriptPreview({ segments, title }: ScriptPreviewProps) {
  if (!segments?.length) return null;

  const totalShots = segments.reduce((acc, s) => acc + (s.shot_count || 0), 0);
  return (
    <div className={styles.wrap}>
      <div className={styles.header}>
        <h4>{title || 'Kịch bản AI'}</h4>
        <span className={styles.count}>
          {segments.length} phân cảnh
          {totalShots > 0 && ` · ${totalShots} shot`}
        </span>
      </div>
      <div className={styles.list}>
        {segments.map((seg, i) => (
          <div key={i} className={styles.segment}>
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
          </div>
        ))}
      </div>
    </div>
  );
}