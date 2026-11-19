import styles from './Button.module.css';
import { Icon, type IconName } from './Icon';
import { cn } from '@/shared/lib/utils/format';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'dangerSolid';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  icon?: IconName;
  iconRight?: IconName;
  block?: boolean;
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading,
  icon,
  iconRight,
  block,
  children,
  className,
  disabled,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(styles.btn, styles[variant], styles[size], block && styles.block, className)}
      disabled={disabled || loading}
      {...props}
    >
      {loading
        ? <span className={styles.spinner} aria-hidden="true" />
        : icon && <Icon name={icon} size={size === 'sm' ? 14 : 16} />}
      {children != null && <span className={styles.label}>{children}</span>}
      {iconRight && !loading && <Icon name={iconRight} size={size === 'sm' ? 14 : 16} />}
    </button>
  );
}

interface IconButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  label: string;
  variant?: 'ghost' | 'secondary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
}

export function IconButton({
  icon,
  label,
  variant = 'ghost',
  size = 'md',
  loading,
  className,
  disabled,
  ...props
}: IconButtonProps) {
  return (
    <button
      className={cn(styles.iconBtn, styles[variant], styles[`icon_${size}`], className)}
      aria-label={label}
      title={label}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <span className={styles.spinner} aria-hidden="true" /> : <Icon name={icon} size={size === 'sm' ? 15 : 17} />}
    </button>
  );
}
