import { formatDuration } from '@/shared/lib/utils/format';
import styles from './DurationStats.module.css';

interface DurationStatsProps {
  targetSec?: number | null;
  estSec?: number | null;
  ttsSec?: number | null;
  outputSec?: number | null;
}

export function DurationStats({ targetSec, estSec, ttsSec, outputSec }: DurationStatsProps) {
  const hasAny = [targetSec, estSec, ttsSec, outputSec].some(v => v != null && v > 0);
  if (!hasAny) return null;

  return (
    <div className={styles.stats}>
      {targetSec != null && targetSec > 0 && (
        <div className={styles.item}>
          <span className={styles.label}>Mục tiêu</span>
          <span className={styles.val}>{formatDuration(targetSec)}</span>
        </div>
      )}
      {estSec != null && estSec > 0 && (
        <div className={styles.item}>
          <span className={styles.label}>Ước tính theo kịch bản</span>
          <span className={styles.est}>~{formatDuration(estSec)}</span>
        </div>
      )}
      {ttsSec != null && ttsSec > 0 && (
        <div className={styles.item}>
          <span className={styles.label}>TTS chuẩn</span>
          <span className={styles.tts}>{formatDuration(ttsSec)}</span>
        </div>
      )}
      {outputSec != null && outputSec > 0 && (
        <div className={styles.item}>
          <span className={styles.label}>Kết quả</span>
          <span className={styles.out}>{formatDuration(outputSec)}</span>
        </div>
      )}
    </div>
  );
}