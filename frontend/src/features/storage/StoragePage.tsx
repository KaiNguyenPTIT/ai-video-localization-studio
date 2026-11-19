import { useState, useEffect } from 'react';
import { settingsService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button } from '@/shared/ui/Button';
import { Card, CardHeader, StatCard } from '@/shared/ui/Card';
import { Icon } from '@/shared/ui/Icon';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { ConfirmDialog } from '@/shared/ui/Modal';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { formatBytes } from '@/shared/lib/utils/format';
import type { StorageStats } from '@/shared/lib/types';
import styles from './StoragePage.module.css';

export function StoragePage() {
  const addToast = useUIStore(s => s.addToast);
  const [stats, setStats] = useState<StorageStats | null>(null);
  const [showCleanup, setShowCleanup] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [lastFreed, setLastFreed] = useState<number | null>(null);

  const load = () => settingsService.getStorage().then(setStats);
  useEffect(() => { load(); }, []);

  const cleanableMb = stats?.cleanable ?? ((stats?.temporary ?? 0) + (stats?.audio ?? 0) + (stats?.segments ?? 0) + (stats?.orphan_uploads ?? 0));
  const projectUploadsMb = stats?.project_uploads ?? stats?.uploads ?? 0;

  const cleanup = async () => {
    setCleaning(true);
    try {
      const r = await settingsService.cleanup();
      setLastFreed(r.freed_mb);
      addToast({ type: 'success', message: `Đã giải phóng ${r.freed_mb} MB (${r.deleted_count} tệp tin)` });
      setShowCleanup(false);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Dọn dẹp thất bại' });
    } finally {
      setCleaning(false);
    }
  };

  const rows: { label: string; mb: number; tone?: 'primary' | 'success' | 'warning' | 'error' }[] = stats ? [
    { label: 'Video thành phẩm (Final)', mb: stats.output, tone: 'success' },
    { label: 'Video gốc tập phim (bảo vệ 100%)', mb: projectUploadsMb, tone: 'success' },
    { label: 'Bộ nhớ đệm âm thanh TTS', mb: stats.audio, tone: 'warning' },
    { label: 'Phân đoạn cắt video', mb: stats.segments, tone: 'warning' },
    { label: 'Tệp tin tạm thời', mb: stats.temporary, tone: 'warning' },
    { label: 'Video nén chế độ thủ công', mb: stats.manual, tone: 'primary' },
    { label: 'Tệp tải lên mồ côi (24h+)', mb: stats.orphan_uploads ?? 0, tone: 'error' },
  ] : [];

  return (
    <div className={styles.page}>
      <PageHeader
        title="Quản lý bộ nhớ"
        subtitle="Kiểm tra dung lượng lưu trữ và dọn dẹp tệp tin đệm an toàn"
        actions={<Button variant="secondary" size="sm" icon="refresh" onClick={load}>Làm mới</Button>}
      />

      <div className={styles.statsGrid}>
        <StatCard label="Tổng dung lượng" value={formatBytes(stats?.total ?? 0)} icon="storage" accent="primary" />
        <StatCard label="Video thành phẩm" value={formatBytes(stats?.output ?? 0)} icon="video" accent="success" />
        <StatCard label="Video gốc tập phim" value={formatBytes(projectUploadsMb)} icon="folder" accent="info" />
        <StatCard label="Bộ nhớ tạm có thể dọn" value={formatBytes(cleanableMb)} icon="trash" accent="warning" />
      </div>

      <Card className={styles.breakdown}>
        <CardHeader title="Phân bổ dung lượng lưu trữ" icon="layers" />
        <div className={styles.rows}>
          {rows.map(({ label, mb, tone }) => (
            <div key={label} className={styles.row}>
              <span className={styles.rowLabel}>{label}</span>
              <div className={styles.barWrap}>
                <ProgressBar value={stats?.total ? (mb / stats.total) * 100 : 0} tone={tone ?? 'primary'} />
              </div>
              <span className={styles.size}>{formatBytes(mb)}</span>
            </div>
          ))}
        </div>
      </Card>

      <Card className={styles.cleanupCard}>
        <CardHeader title="Dọn dẹp tệp tin tạm & bộ nhớ đệm" icon="trash" />
        <p className={styles.cleanupDesc}>
          Hệ thống có thể giải phóng an toàn khoảng <strong>{formatBytes(cleanableMb)}</strong>.
          Bao gồm: tệp tạm thời, bộ nhớ đệm âm thanh TTS, phân đoạn video trung gian và các tệp tải lên mồ côi (cũ hơn 24 giờ).
        </p>
        <div className={styles.safeNote}>
          <Icon name="check-circle" size={16} />
          <span>Video gốc của các tập phim và video thành phẩm luôn được bảo vệ an toàn tuyệt đối.</span>
        </div>
        {lastFreed !== null && (
          <p className={styles.freedMsg}><Icon name="check" size={14} strokeWidth={3} /> Lần dọn gần nhất đã giải phóng {formatBytes(lastFreed)}</p>
        )}
        <Button icon="trash" onClick={() => setShowCleanup(true)}>Dọn dẹp tệp tin tạm</Button>
      </Card>

      <ConfirmDialog
        open={showCleanup}
        onClose={() => setShowCleanup(false)}
        onConfirm={cleanup}
        title="Xác nhận dọn dẹp bộ nhớ tạm?"
        message={`Hành động này sẽ giải phóng an toàn ~${formatBytes(cleanableMb)} tệp tin tạm và phân đoạn trung gian. Video gốc và video thành phẩm của các tập phim sẽ không bị ảnh hưởng.`}
        confirmLabel="Tiến hành dọn dẹp"
        danger={false}
        loading={cleaning}
      />
    </div>
  );
}
