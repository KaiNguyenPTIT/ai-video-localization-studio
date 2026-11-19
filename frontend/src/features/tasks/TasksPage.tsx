import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { taskService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { Button, IconButton } from '@/shared/ui/Button';
import { Drawer } from '@/shared/ui/Drawer';
import { Icon } from '@/shared/ui/Icon';
import { Input } from '@/shared/ui/Field';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { ConfirmDialog } from '@/shared/ui/Modal';
import { EmptyState, Skeleton } from '@/shared/ui/EmptyState';
import { friendlyError } from '@/shared/lib/services/apiClient';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { PIPELINE_STAGES, getStageIndex } from '@/shared/lib/utils/pipeline';
import { formatDate } from '@/shared/lib/utils/format';
import type { Task } from '@/shared/lib/types';
import styles from './TasksPage.module.css';

type TabId = 'all' | 'queueing' | 'running' | 'awaiting' | 'completed' | 'failed' | 'cancelled';

const TABS: { id: TabId; label: string }[] = [
  { id: 'all', label: 'Tất cả' },
  { id: 'queueing', label: 'Hàng đợi' },
  { id: 'running', label: 'Đang chạy' },
  { id: 'awaiting', label: 'Chờ kịch bản' },
  { id: 'completed', label: 'Đã xong' },
  { id: 'failed', label: 'Thất bại' },
  { id: 'cancelled', label: 'Đã hủy' },
];

const FINISHED: TabId[] = ['completed', 'failed', 'cancelled'];

export function TasksPage() {
  const navigate = useNavigate();
  const addToast = useUIStore(s => s.addToast);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<TabId>('all');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<Task | null>(null);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await taskService.list();
      setTasks(list);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const timer = setInterval(load, 3000);
    return () => clearInterval(timer);
  }, [load]);

  const counts = useMemo(() => {
    const acc = { all: tasks.length, queueing: 0, running: 0, awaiting: 0, completed: 0, failed: 0, cancelled: 0 } as Record<TabId, number>;
    tasks.forEach(t => { if (t.status in acc) acc[t.status as TabId]++; });
    return acc;
  }, [tasks]);

  const filtered = useMemo(() => tasks.filter(t => {
    if (tab !== 'all' && t.status !== tab) return false;
    if (search) {
      const q = search.toLowerCase();
      const name = (t.video_name || t.id).toLowerCase();
      return name.includes(q) || (t.message || '').toLowerCase().includes(q);
    }
    return true;
  }), [tasks, tab, search]);

  const finishedCount = counts.completed + counts.failed + counts.cancelled;

  const handleCancel = async (id: string) => {
    try {
      await taskService.cancel(id);
      addToast({ type: 'info', message: 'Đã hủy tác vụ' });
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Hủy tác vụ thất bại' });
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await taskService.delete(id);
      addToast({ type: 'success', message: 'Đã xóa tác vụ khỏi lịch sử' });
      setSelected(null);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Xóa tác vụ thất bại' });
    }
  };

  const handleClearFinished = async () => {
    setClearing(true);
    try {
      const res = await taskService.clearFinished();
      addToast({ type: 'success', message: `Đã dọn dẹp ${res.count} tác vụ đã kết thúc` });
      setShowClearConfirm(false);
      setSelected(null);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Dọn dẹp lịch sử thất bại' });
    } finally {
      setClearing(false);
    }
  };

  const isFiltering = search !== '' || tab !== 'all';

  return (
    <div className={styles.page}>
      <PageHeader
        title="Tiến trình chạy"
        subtitle="Theo dõi và quản lý lịch sử tiến trình xử lý video"
        actions={
          finishedCount > 0 ? (
            <Button
              variant="secondary"
              size="sm"
              icon="trash"
              onClick={() => setShowClearConfirm(true)}
              title="Xóa các tác vụ đã hoàn thành hoặc thất bại khỏi danh sách"
            >
              Dọn lịch sử đã xong ({finishedCount})
            </Button>
          ) : undefined
        }
      />

      <div className={styles.toolbar}>
        <div className={styles.searchWrap}>
          <Icon name="search" size={16} className={styles.searchIcon} />
          <Input
            className={styles.search}
            placeholder="Tìm theo tên video hoặc nội dung…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <IconButton icon="close" label="Xóa tìm kiếm" size="sm" className={styles.clearBtn} onClick={() => setSearch('')} />
          )}
        </div>
        <SegmentedControl<TabId>
          value={tab}
          onChange={setTab}
          size="sm"
          options={TABS.map(t => ({ value: t.id, label: t.label, count: counts[t.id] }))}
        />
      </div>

      {loading && !tasks.length ? (
        <div className={styles.list}>{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} height="66px" />)}</div>
      ) : filtered.length === 0 ? (
        <EmptyState
          glyph={isFiltering ? 'search' : 'activity'}
          title={isFiltering ? 'Không có tác vụ phù hợp' : 'Chưa có tác vụ nào'}
          description={
            isFiltering
              ? 'Thử đổi từ khóa tìm kiếm hoặc chọn bộ lọc khác.'
              : 'Các tác vụ xử lý video sẽ hiển thị tại đây khi bạn bắt đầu tạo video.'
          }
          action={isFiltering
            ? { label: 'Xóa bộ lọc', onClick: () => { setSearch(''); setTab('all'); } }
            : { label: 'Tạo video mới', onClick: () => navigate('/quick') }}
        />
      ) : (
        <div className={styles.list}>
          {filtered.map(task => (
            <div
              key={task.id}
              className={`${styles.row} ${['running', 'queueing'].includes(task.status) ? styles.rowActive : ''}`}
              onClick={() => setSelected(task)}
            >
              <div className={styles.rowMain}>
                <div className={styles.rowTitle} title={task.video_name || task.id}>
                  {task.video_name || `Tác vụ #${task.id.slice(0, 8)}`}
                </div>
                <div className={styles.rowMsg}>{task.message}</div>
              </div>
              <StatusBadge status={task.status} />
              <div className={styles.rowProgress}>
                {['running', 'queueing', 'completed'].includes(task.status) ? (
                  <>
                    <div className={styles.progressTrack}>
                      <ProgressBar value={task.progress} animated={task.status === 'running'} />
                    </div>
                    <span>{task.progress}%</span>
                  </>
                ) : <span className={styles.dash}>—</span>}
              </div>
              <div className={styles.rowDate}><Icon name="clock" size={12} /> {formatDate(task.created_at)}</div>
              <div className={styles.rowActions} onClick={e => e.stopPropagation()}>
                {['running', 'queueing'].includes(task.status) && (
                  <Button size="sm" variant="ghost" onClick={() => handleCancel(task.id)}>Hủy</Button>
                )}
                {FINISHED.includes(task.status as TabId) && (
                  <IconButton icon="trash" label="Xóa khỏi lịch sử" variant="danger" size="sm" onClick={() => handleDelete(task.id)} />
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <TaskDetailDrawer task={selected} onClose={() => setSelected(null)} onCancel={handleCancel} onDelete={handleDelete} />

      <ConfirmDialog
        open={showClearConfirm}
        onClose={() => setShowClearConfirm(false)}
        onConfirm={handleClearFinished}
        title="Dọn dẹp lịch sử tác vụ?"
        message="Hành động này sẽ xóa tất cả các tác vụ đã hoàn tất, thất bại hoặc bị hủy khỏi danh sách tiến trình. Video thành phẩm của các tập phim trong dự án vẫn được giữ nguyên an toàn."
        confirmLabel={clearing ? 'Đang dọn…' : 'Xóa lịch sử'}
        loading={clearing}
      />
    </div>
  );
}

function TaskDetailDrawer({ task, onClose, onCancel, onDelete }: {
  task: Task | null; onClose: () => void;
  onCancel: (id: string) => void; onDelete: (id: string) => void;
}) {
  if (!task) return null;
  const err = task.error ? friendlyError(new Error(task.error)) : null;
  const stageIdx = getStageIndex(task.progress, task.message, task.status);

  return (
    <Drawer open={!!task} onClose={onClose} title={`Chi tiết tác vụ #${task.id.slice(0, 8)}`} width={520}>
      <div className={styles.detail}>
        <div className={styles.detailTop}>
          <StatusBadge status={task.status} size="md" />
          <span className={styles.detailProgress}>{task.progress}%</span>
        </div>
        <div className={styles.detailMsg}>{task.message}</div>
        <ProgressBar value={task.progress} animated size="md" />

        <div className={styles.pipeline}>
          {PIPELINE_STAGES.map((s, i) => (
            <div key={s} className={`${styles.stage} ${i <= stageIdx ? styles.stageDone : ''} ${i === stageIdx ? styles.stageCurrent : ''}`}>
              <div className={styles.stageDot} />
              <span>{s}</span>
              {i < PIPELINE_STAGES.length - 1 && <div className={styles.stageLine} />}
            </div>
          ))}
        </div>

        {task.video_name && (
          <div className={styles.detailField}>
            <label>Video đầu vào</label>
            <span title={task.video_name}>{task.video_name}</span>
          </div>
        )}
        {task.result?.video_url && (
          <div className={styles.detailField}>
            <label>Video thành phẩm</label>
            <a href={task.result.video_url} target="_blank" rel="noreferrer">
              <Icon name="external" size={14} /> Xem video
            </a>
          </div>
        )}
        {err && (
          <div className={styles.errorBox}>
            <h4>{err.title}</h4>
            <p>{err.message}</p>
          </div>
        )}

        <div className={styles.detailActions}>
          {['running', 'queueing'].includes(task.status) && (
            <Button variant="danger" size="sm" icon="close" onClick={() => onCancel(task.id)}>Hủy tác vụ</Button>
          )}
          {FINISHED.includes(task.status as TabId) && (
            <Button variant="ghost" size="sm" icon="trash" onClick={() => onDelete(task.id)}>Xóa khỏi lịch sử</Button>
          )}
        </div>
      </div>
    </Drawer>
  );
}
