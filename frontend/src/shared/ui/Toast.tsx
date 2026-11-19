export interface Toast {
  id: string;
  type: 'success' | 'error' | 'info' | 'warning';
  message: string;
  duration?: number;
}

import { useUIStore } from '@/shared/lib/state/uiStore';
import { Icon, type IconName } from './Icon';
import styles from './Toast.module.css';

const TOAST_ICON: Record<Toast['type'], IconName> = {
  success: 'check-circle',
  error: 'alert',
  warning: 'alert',
  info: 'info',
};

export function ToastContainer() {
  const toasts = useUIStore(s => s.toasts);
  const remove = useUIStore(s => s.removeToast);

  if (!toasts.length) return null;
  return (
    <div className={styles.container} role="region" aria-live="polite" aria-label="Thông báo">
      {toasts.map(t => (
        <div key={t.id} className={`${styles.toast} ${styles[t.type]}`} role="status">
          <span className={styles.icon}>
            <Icon name={TOAST_ICON[t.type]} size={16} strokeWidth={2.2} />
          </span>
          <span className={styles.message}>{t.message}</span>
          <button className={styles.close} onClick={() => remove(t.id)} aria-label="Đóng thông báo">
            <Icon name="close" size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
