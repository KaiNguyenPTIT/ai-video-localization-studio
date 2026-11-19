import { useEffect, useState, type ReactNode } from 'react';
import { adminService } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './AdminTools.module.css';

/** Cổng kiểm tra quyền admin dùng chung cho các công cụ admin.
 *  Cookie đăng nhập dùng chung nên chỉ cần đăng nhập 1 lần cho mọi tab. */
export function AdminGate({ children }: { children: ReactNode }) {
  const addToast = useUIStore(s => s.addToast);
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    adminService.getSystem().then(() => setAuthed(true)).catch(() => setAuthed(false));
  }, []);

  const login = async () => {
    if (!password) return;
    setBusy(true);
    try {
      await adminService.login(password);
      setPassword('');
      setAuthed(true);
    } catch {
      addToast({ type: 'error', message: 'Sai mật khẩu admin' });
    } finally {
      setBusy(false);
    }
  };

  if (authed === null) return <p className={styles.message}>Đang kiểm tra quyền admin…</p>;
  if (!authed) {
    return (
      <div className={styles.loginBox}>
        <h3>🔒 Khu Vực Admin</h3>
        <p className={styles.desc}>Nhập mật khẩu admin để sử dụng công cụ này.</p>
        <div className={styles.loginRow}>
          <input
            className={styles.text}
            type="password"
            value={password}
            placeholder="Mật khẩu admin (mặc định: admin123)"
            onChange={e => setPassword(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') login(); }}
          />
          <Button onClick={login} loading={busy} disabled={!password}>Đăng nhập</Button>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
