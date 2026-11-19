import { cn } from '@/shared/lib/utils/format';
import styles from './Spinner.module.css';

interface SpinnerProps {
  size?: number;
  className?: string;
  label?: string;
}

export function Spinner({ size = 18, className, label }: SpinnerProps) {
  return (
    <span className={cn(styles.wrap, className)} role="status" aria-label={label || 'Đang tải'}>
      <span className={styles.spinner} style={{ width: size, height: size }} />
    </span>
  );
}
