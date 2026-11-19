import { Link, useNavigate } from 'react-router-dom';
import { useSystemStatus } from '@/shared/hooks/useSystemStatus';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { Icon } from '@/shared/ui/Icon';
import { Badge } from '@/shared/ui/Badge';
import styles from './Topbar.module.css';

export function Topbar() {
  const setPaletteOpen = useUIStore(s => s.setCommandPaletteOpen);
  const navigate = useNavigate();
  const { health, voiceStudioOnline, loading } = useSystemStatus();

  const activeCount = health?.active_tasks ?? 0;

  const keys = health?.gemini_keys ?? 0;
  const keyState = loading ? 'neutral' : keys > 0 ? 'success' : 'error';

  return (
    <header className={styles.topbar}>
      <button className={styles.search} onClick={() => setPaletteOpen(true)}>
        <Icon name="search" size={16} />
        <span className={styles.searchText}>Tìm kiếm dự án, lệnh…</span>
        <kbd className={styles.kbd}>Ctrl K</kbd>
      </button>

      <div className={styles.right}>
        <div className={styles.pills}>
          <Badge tone={voiceStudioOnline ? 'success' : 'warning'} dot>
            <span className={styles.pillText}>VoiceStudio {voiceStudioOnline ? 'sẵn sàng' : 'ngoại tuyến'}</span>
          </Badge>
          <Badge tone={keyState as 'success' | 'error' | 'neutral'} dot>
            <span className={styles.pillText}>{loading ? 'Đang kiểm tra…' : `${keys} Gemini key`}</span>
          </Badge>
          {loading ? null : (
            <Badge tone={health && health.queue_depth > 0 ? 'info' : 'neutral'} dot>
              <span className={styles.pillText}>Hàng chờ {health?.queue_depth ?? 0}</span>
            </Badge>
          )}
        </div>

        <Link to="/tasks" className={styles.tasksBtn} title="Tiến trình đang chạy">
          <Icon name="activity" size={16} />
          <span className={styles.pillText}>Đang chạy</span>
          {activeCount > 0 && <span className={styles.count}>{activeCount}</span>}
        </Link>

        <button className={styles.primaryBtn} onClick={() => navigate('/quick')}>
          <Icon name="bolt" size={16} />
          <span>Tóm tắt nhanh</span>
        </button>
      </div>
    </header>
  );
}
