import { useCallback, useEffect, useState } from 'react';
import { adminService } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './AdminTools.module.css';

/** Xem log server — port từ trang /admin cũ. */
export function LogsViewer() {
  const addToast = useUIStore(s => s.addToast);
  const [lines, setLines] = useState(200);
  const [log, setLog] = useState('');
  const [loading, setLoading] = useState(false);

  const load = useCallback(async (n: number) => {
    setLoading(true);
    try {
      const d = await adminService.getLogs(n);
      setLog(d.log || '');
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không tải được log' });
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { load(lines); }, [load, lines]);

  return (
    <div>
      <div className={styles.toolbar}>
        <label className={styles.toolbarLabel}>
          Số dòng:
          <select className={styles.select} value={lines} onChange={e => setLines(Number(e.target.value))}>
            {[100, 200, 500, 1000].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <Button size="sm" variant="secondary" onClick={() => load(lines)} loading={loading}>🔄 Tải lại</Button>
      </div>
      <pre className={styles.logBox}>{log || 'Trống.'}</pre>
    </div>
  );
}
