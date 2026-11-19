import { useRef } from 'react';
import styles from './Drawer.module.css';
import { IconButton } from './Button';
import { useDialogBehavior } from './useDialogBehavior';

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}

export function Drawer({ open, onClose, title, subtitle, children, footer, width = 480 }: DrawerProps) {
  const ref = useRef<HTMLDivElement>(null);
  useDialogBehavior(open, onClose, ref);
  if (!open) return null;

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        className={styles.drawer}
        style={{ width }}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
      >
        <div className={styles.header}>
          <div className={styles.headerText}>
            <h2>{title}</h2>
            {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
          </div>
          <IconButton icon="close" label="Đóng" size="sm" onClick={onClose} />
        </div>
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>
  );
}
