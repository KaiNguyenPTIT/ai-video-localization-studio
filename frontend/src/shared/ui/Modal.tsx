import { useRef } from 'react';
import styles from './Modal.module.css';
import { Button, IconButton } from './Button';
import { Icon, type IconName } from './Icon';
import { useDialogBehavior } from './useDialogBehavior';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  icon?: IconName;
  children: React.ReactNode;
  footer?: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  closeOnOverlay?: boolean;
}

export function Modal({ open, onClose, title, icon, children, footer, size = 'md', closeOnOverlay = true }: ModalProps) {
  const ref = useRef<HTMLDivElement>(null);
  useDialogBehavior(open, onClose, ref);
  if (!open) return null;

  return (
    <div className={styles.overlay} onClick={closeOnOverlay ? onClose : undefined}>
      <div
        className={`${styles.modal} ${styles[size]}`}
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
      >
        <div className={styles.header}>
          {icon && <span className={styles.headerIcon}><Icon name={icon} size={18} /></span>}
          <h2>{title}</h2>
          <IconButton icon="close" label="Đóng" size="sm" onClick={onClose} />
        </div>
        <div className={styles.body}>{children}</div>
        {footer && <div className={styles.footer}>{footer}</div>}
      </div>
    </div>
  );
}

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  loading?: boolean;
}

export function ConfirmDialog({
  open, onClose, onConfirm, title, message,
  confirmLabel = 'Xóa', cancelLabel = 'Hủy', danger = true, loading,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={loading ? () => {} : onClose}
      title={title}
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={loading}>{cancelLabel}</Button>
          <Button variant={danger ? 'dangerSolid' : 'primary'} onClick={onConfirm} loading={loading}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className={styles.message}>{message}</p>
    </Modal>
  );
}
