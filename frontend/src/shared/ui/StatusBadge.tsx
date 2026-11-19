import type { EpisodeStatus, TaskStatus } from '@/shared/lib/types';
import styles from './StatusBadge.module.css';
import { Icon, type IconName } from './Icon';
import { cn } from '@/shared/lib/utils/format';

const STATUS_CONFIG: Record<string, { label: string; icon: IconName; className: string }> = {
  pending:         { label: 'Chờ xử lý',        icon: 'clock',        className: 'pending' },
  queueing:        { label: 'Đang xếp hàng',     icon: 'clock',        className: 'queueing' },
  running:         { label: 'Đang chạy',         icon: 'activity',     className: 'running' },
  awaiting:        { label: 'Chờ thao tác',      icon: 'alert',        className: 'awaiting' },
  awaiting_result: { label: 'Chờ dán kịch bản', icon: 'clipboard',    className: 'awaiting' },
  completed:       { label: 'Hoàn thành',        icon: 'check-circle', className: 'completed' },
  failed:          { label: 'Thất bại',          icon: 'alert',        className: 'failed' },
  cancelled:       { label: 'Đã hủy',            icon: 'close',        className: 'cancelled' },
};

interface StatusBadgeProps {
  status: EpisodeStatus | TaskStatus | string;
  showIcon?: boolean;
  size?: 'sm' | 'md';
}

export function StatusBadge({ status, showIcon = true, size = 'sm' }: StatusBadgeProps) {
  const cfg = STATUS_CONFIG[status] || { label: status, icon: 'info' as IconName, className: 'pending' };
  return (
    <span className={cn(styles.badge, styles[cfg.className], size === 'md' && styles.md)}>
      {showIcon && <Icon name={cfg.icon} size={size === 'md' ? 13 : 12} strokeWidth={2.4} />}
      {cfg.label}
    </span>
  );
}
