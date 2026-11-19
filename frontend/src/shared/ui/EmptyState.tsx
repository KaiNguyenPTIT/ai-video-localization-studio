import styles from './EmptyState.module.css';
import { Button } from './Button';
import { Icon, type IconName } from './Icon';

interface EmptyStateProps {
  /** @deprecated prefer `glyph` */
  icon?: string;
  glyph?: IconName;
  title: string;
  description?: string;
  action?: { label: string; onClick: () => void };
  compact?: boolean;
}

export function EmptyState({ icon, glyph, title, description, action, compact }: EmptyStateProps) {
  return (
    <div className={compact ? styles.compact : styles.empty} role="status">
      <div className={styles.iconBadge}>
        {glyph ? <Icon name={glyph} size={compact ? 22 : 28} strokeWidth={1.8} />
          : icon ? <span className={styles.emoji}>{icon}</span>
            : <Icon name="folder" size={compact ? 22 : 28} strokeWidth={1.8} />}
      </div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action && <Button onClick={action.onClick}>{action.label}</Button>}
    </div>
  );
}

export function Skeleton({ width, height, className }: { width?: string; height?: string; className?: string }) {
  return <div className={`skeleton ${styles.skeleton} ${className || ''}`} style={{ width, height: height || '16px' }} />;
}
