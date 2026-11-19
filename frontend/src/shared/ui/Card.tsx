import styles from './Card.module.css';
import { Icon, isIconName, type IconName } from './Icon';
import { cn } from '@/shared/lib/utils/format';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  padding?: boolean;
  onClick?: () => void;
  interactive?: boolean;
}

export function Card({ children, className, padding = true, onClick, interactive }: CardProps) {
  const clickable = interactive ?? !!onClick;
  return (
    <div
      className={cn(styles.card, padding && styles.padded, clickable && styles.clickable, className)}
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={onClick ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } } : undefined}
    >
      {children}
    </div>
  );
}

interface StatCardProps {
  label: string;
  value: string | number;
  sub?: string;
  icon?: IconName | string;
  accent?: 'default' | 'primary' | 'success' | 'warning' | 'error' | 'info';
  onClick?: () => void;
}

export function StatCard({ label, value, sub, icon, accent = 'default', onClick }: StatCardProps) {
  return (
    <Card className={cn(styles.statCard, onClick && styles.clickable)} onClick={onClick ?? undefined} interactive={!!onClick}>
      <div className={styles.statHeader}>
        <span className={styles.statLabel}>{label}</span>
        {icon && (
          <span className={cn(styles.statIcon, styles[`accent_${accent}`])}>
            {isIconName(icon) ? <Icon name={icon} size={16} /> : <span aria-hidden="true">{icon}</span>}
          </span>
        )}
      </div>
      <div className={styles.statValue}>{value}</div>
      {sub && <div className={styles.statSub}>{sub}</div>}
    </Card>
  );
}

interface CardHeaderProps {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: IconName;
  actions?: React.ReactNode;
  className?: string;
}

export function CardHeader({ title, subtitle, icon, actions, className }: CardHeaderProps) {
  return (
    <div className={cn(styles.header, className)}>
      {icon && <span className={styles.headerIcon}><Icon name={icon} size={16} /></span>}
      <div className={styles.headerText}>
        <h3 className={styles.headerTitle}>{title}</h3>
        {subtitle && <p className={styles.headerSubtitle}>{subtitle}</p>}
      </div>
      {actions && <div className={styles.headerActions}>{actions}</div>}
    </div>
  );
}
