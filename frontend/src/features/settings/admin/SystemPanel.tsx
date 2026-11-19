import { useCallback, useEffect, useState } from 'react';
import { adminService, type SystemInfo } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './AdminTools.module.css';

/** Thông tin hệ thống + nút restart server — port từ trang /admin cũ. */
export function SystemPanel() {
  const addToast = useUIStore(s => s.addToast);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [loading, setLoading] = useState(false);
  const [restarting, setRestarting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setInfo(await adminService.getSystem());
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không tải được thông tin hệ thống' });
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { load(); }, [load]);

  const handleRestart = async () => {
    if (!window.confirm('Khởi động lại server? Các tác vụ đang chạy sẽ bị gián đoạn.')) return;
    setRestarting(true);
    try {
      await adminService.restart();
      addToast({ type: 'info', message: 'Server đang restart — đợi ~15 giây rồi tải lại trang' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Restart thất bại' });
    } finally {
      setRestarting(false);
    }
  };

  const items: [string, string][] = info ? [
    ['Nền tảng', info.platform],
    ['Python', info.python],
    ['FFmpeg', info.ffmpeg],
    ['GPU', info.gpu],
    ['RAM', `${info.ram_avail_gb} / ${info.ram_total_gb} GB trống`],
    ['Ổ đĩa', `${info.disk_free_gb} / ${info.disk_total_gb} GB trống`],
    ['API keys', `${info.api_keys} khóa · ${info.workers} workers`],
    ['Hàng đợi', `${info.queue_depth} tác vụ`],
  ] : [];

  return (
    <div>
      <div className={styles.grid}>
        {items.map(([k, v]) => (
          <div key={k} className={styles.cell}>
            <span className={styles.cellLabel}>{k}</span>
            <span className={styles.cellVal}>{v}</span>
          </div>
        ))}
        {!info && !loading && <p className={styles.message}>Chưa có dữ liệu.</p>}
      </div>
      <div className={styles.actions}>
        <Button size="sm" variant="secondary" onClick={load} loading={loading}>🔄 Cập nhật</Button>
        <Button size="sm" variant="danger" onClick={handleRestart} loading={restarting}>⏻ Restart Server</Button>
      </div>
    </div>
  );
}
