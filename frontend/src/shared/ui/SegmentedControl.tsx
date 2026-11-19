import { Icon, type IconName } from './Icon';
import { cn } from '@/shared/lib/utils/format';
import styles from './SegmentedControl.module.css';

export interface SegmentedOption<T extends string = string> {
  value: T;
  label: string;
  icon?: IconName;
  count?: number;
}

interface SegmentedControlProps<T extends string = string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  fullWidth?: boolean;
  className?: string;
  'aria-label'?: string;
}

export function SegmentedControl<T extends string = string>({
  options, value, onChange, size = 'md', fullWidth, className, ...rest
}: SegmentedControlProps<T>) {
  return (
    <div
      className={cn(styles.group, size === 'sm' && styles.sm, fullWidth && styles.fullWidth, className)}
      role="tablist"
      aria-label={rest['aria-label']}
    >
      {options.map(opt => (
        <button
          key={opt.value}
          role="tab"
          aria-selected={opt.value === value}
          className={cn(styles.item, opt.value === value && styles.active)}
          onClick={() => onChange(opt.value)}
        >
          {opt.icon && <Icon name={opt.icon} size={size === 'sm' ? 13 : 15} />}
          <span>{opt.label}</span>
          {opt.count != null && <span className={styles.count}>{opt.count}</span>}
        </button>
      ))}
    </div>
  );
}
