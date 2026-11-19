import { cn } from '@/shared/lib/utils/format';
import styles from './Badge.module.css';

type Tone = 'neutral' | 'primary' | 'success' | 'warning' | 'error' | 'info';

interface BadgeProps {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
  dot?: boolean;
}

export function Badge({ children, tone = 'neutral', className, dot }: BadgeProps) {
  return (
    <span className={cn(styles.badge, styles[tone], className)}>
      {dot && <span className={styles.dot} />}
      {children}
    </span>
  );
}
