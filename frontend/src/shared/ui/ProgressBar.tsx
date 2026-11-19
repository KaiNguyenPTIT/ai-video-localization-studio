import styles from './ProgressBar.module.css';
import { cn } from '@/shared/lib/utils/format';

interface ProgressBarProps {
  value: number;
  className?: string;
  size?: 'sm' | 'md' | 'lg';
  animated?: boolean;
  indeterminate?: boolean;
  tone?: 'primary' | 'success' | 'warning' | 'error';
}

export function ProgressBar({ value, className, size = 'sm', animated, indeterminate, tone = 'primary' }: ProgressBarProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div
      className={cn(styles.track, styles[size], className)}
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn(
          styles.fill,
          styles[tone],
          animated && styles.animated,
          indeterminate && styles.indeterminate,
        )}
        style={indeterminate ? undefined : { width: `${pct}%` }}
      />
    </div>
  );
}
