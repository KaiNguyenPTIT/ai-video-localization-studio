import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { usePolling } from '@/shared/hooks/useTaskProgress';
import { settingsService, projectService, taskService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Card, CardHeader, StatCard } from '@/shared/ui/Card';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { Button } from '@/shared/ui/Button';
import { Badge } from '@/shared/ui/Badge';
import { SectionHeader } from '@/shared/ui/SectionHeader';
import { EmptyState, Skeleton } from '@/shared/ui/EmptyState';
import { Icon, type IconName } from '@/shared/ui/Icon';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { formatBytes, formatRelative, projectStats } from '@/shared/lib/utils/format';
import type { Project, Task } from '@/shared/lib/types';
import styles from './DashboardPage.module.css';

const ACTIVE = ['running', 'queueing', 'awaiting'];

export function DashboardPage() {
  const navigate = useNavigate();
  const addToast = useUIStore(s => s.addToast);

  const fetchData = useCallback(async () => {
    const [stats, projects, health, taskList] = await Promise.all([
      settingsService.getStats(),
      projectService.list(),
      settingsService.getHealth().catch(() => null),
      taskService.list(),
    ]);
    return {
      stats,
      projects,
      health,
      runningTasks: taskList.filter(t => ACTIVE.includes(t.status)),
    };
  }, []);

  const { data, loading, refresh } = usePolling(fetchData, 4000);

  const handleCancel = async (taskId: string) => {
    try {
      await taskService.cancel(taskId);
      addToast({ type: 'info', message: 'Đã hủy tác vụ' });
      refresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Hủy thất bại' });
    }
  };

  const stats = data?.stats;
  const running = data?.runningTasks ?? [];
  const projects = data?.projects ?? [];
  const health = data?.health;

  const totalTasks = Object.values(stats?.tasks ?? {}).reduce((a, b) => a + b, 0);
  const completed = stats?.episodes.completed ?? 0;
  const totalEpisodes = stats?.episodes.total ?? 0;
  const hasProjects = projects.length > 0;

  if (loading && !data) {
    return (
      <div className={styles.page}>
        <PageHeader title="Tổng quan" subtitle="Theo dõi hệ thống sản xuất video tóm tắt anime" />
        <div className={styles.statsGrid}>
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height="92px" />)}
        </div>
        <section className={styles.section}>
          <Skeleton height="120px" />
        </section>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <PageHeader
        title="Tổng quan"
        subtitle="Theo dõi toàn diện quy trình sản xuất video tóm tắt anime"
        actions={
          <>
            <Button variant="secondary" icon="bolt" onClick={() => navigate('/quick')}>Tóm tắt nhanh</Button>
            <Button icon="plus" onClick={() => navigate('/projects?new=1')}>Tạo phim mới</Button>
          </>
        }
      />

      {!hasProjects && (
        <section className={styles.section}>
          <Card className={styles.hero}>
            <div className={styles.heroText}>
              <h2>Bắt đầu video tóm tắt đầu tiên</h2>
              <p>Tạo một dự án phim, tải các tập lên và để AI viết kịch bản lời bình — hoặc thử ngay chế độ tóm tắt nhanh cho một video đơn lẻ.</p>
              <div className={styles.heroActions}>
                <Button icon="plus" onClick={() => navigate('/projects?new=1')}>Tạo dự án phim</Button>
                <Button variant="secondary" icon="bolt" onClick={() => navigate('/quick')}>Tóm tắt 1 video</Button>
              </div>
            </div>
            <div className={styles.heroGlyph} aria-hidden="true"><Icon name="film" size={72} strokeWidth={1.2} /></div>
          </Card>
        </section>
      )}

      <div className={styles.statsGrid}>
        <StatCard label="Dự án phim" value={stats?.projects ?? 0} icon="film" accent="primary" onClick={() => navigate('/projects')} />
        <StatCard label="Tổng số tập" value={totalEpisodes} sub={`${completed} đã hoàn thành`} icon="layers" accent="info" />
        <StatCard label="Tỷ lệ hoàn thành" value={totalEpisodes ? `${Math.round((completed / totalEpisodes) * 100)}%` : '—'} icon="check-circle" accent="success" />
        <StatCard label="Tác vụ nền" value={totalTasks} icon="activity" accent="warning" onClick={() => navigate('/tasks')} />
        <StatCard label="Hàng đợi chờ" value={stats?.queue_depth ?? 0} icon="clock" accent={stats?.queue_depth ? 'warning' : 'default'} onClick={() => navigate('/tasks')} />
        <StatCard label="Video thành phẩm" value={stats?.output_files ?? 0} icon="library" onClick={() => navigate('/library')} />
        <StatCard label="Bộ nhớ đã dùng" value={formatBytes(stats?.output_size_mb ?? 0)} icon="storage" onClick={() => navigate('/storage')} />
      </div>

      {running.length > 0 && (
        <section className={styles.section}>
          <SectionHeader
            title={<><Icon name="activity" size={18} /> Đang xử lý</>}
            subtitle={`${running.length} tác vụ đang chạy`}
            actions={<Button variant="ghost" size="sm" onClick={() => navigate('/tasks')}>Xem tất cả</Button>}
          />
          <div className={styles.taskList}>
            {running.map(task => (
              <ActiveTaskCard
                key={task.id}
                task={task}
                projects={projects}
                onOpen={() => navigate('/tasks')}
                onCancel={() => handleCancel(task.id)}
              />
            ))}
          </div>
        </section>
      )}

      <section className={styles.twoCol}>
        <Card className={styles.panel}>
          <CardHeader
            icon="film"
            title="Dự án gần đây"
            subtitle={hasProjects ? `${projects.length} dự án` : undefined}
            actions={hasProjects ? <Button variant="ghost" size="sm" onClick={() => navigate('/projects')}>Tất cả</Button> : undefined}
          />
          {hasProjects ? (
            <div className={styles.projectList}>
              {projects.slice(0, 5).map(p => {
                const s = projectStats(p.episodes ?? []);
                return (
                  <button key={p.id} className={styles.projectRow} onClick={() => navigate(`/projects/${p.id}`)}>
                    <div className={styles.projectInfo}>
                      <div className={styles.projectName}>{p.name}</div>
                      <div className={styles.projectMeta}>
                        {s.total} tập · {s.completed} xong · cập nhật {formatRelative(p.updated_at || p.created_at)}
                      </div>
                    </div>
                    <div className={styles.projectProgress}>
                      <ProgressBar value={s.progress} size="sm" tone={s.progress === 100 ? 'success' : 'primary'} />
                      <span className={styles.projectPct}>{s.progress}%</span>
                    </div>
                  </button>
                );
              })}
            </div>
          ) : (
            <EmptyState
              glyph="film"
              compact
              title="Chưa có dự án nào"
              description="Tạo dự án để bắt đầu sản xuất video tóm tắt."
              action={{ label: 'Tạo dự án', onClick: () => navigate('/projects?new=1') }}
            />
          )}
        </Card>

        <Card className={styles.panel}>
          <CardHeader icon="server" title="Trạng thái hệ thống" />
          <div className={styles.healthList}>
            <HealthRow
              icon="key"
              label="Google Gemini API"
              detail={health ? `${health.gemini_keys} key khả dụng` : 'Không kết nối được'}
              tone={health ? (health.gemini_keys > 0 ? 'success' : 'error') : 'warning'}
            />
            <HealthRow icon="cpu" label="Worker song song" detail={health ? `${health.workers} luồng` : '—'} tone="success" />
            <HealthRow
              icon="clock"
              label="Độ dài hàng đợi"
              detail={health ? `${health.queue_depth} tập` : '—'}
              tone={health && health.queue_depth > 0 ? 'warning' : 'success'}
            />
            <HealthRow icon="sparkles" label="AI model" detail={health?.model ?? '—'} tone="success" />
          </div>
        </Card>
      </section>
    </div>
  );
}

function ActiveTaskCard({ task, projects, onOpen, onCancel }: { task: Task; projects: Project[]; onOpen: () => void; onCancel: () => void }) {
  const epName = task.video_name || 'Đang xử lý';
  const project = projects.find(p => p.episodes?.some(e => e.task_id === task.id));
  return (
    <Card className={styles.taskCard}>
      <div className={styles.taskHeader}>
        <div>
          <div className={styles.taskTitle}>{epName}</div>
          {project && <div className={styles.taskProject}><Icon name="film" size={12} /> {project.name}</div>}
        </div>
        <StatusBadge status={task.status} size="md" />
      </div>
      <div className={styles.taskMessage}>{task.message}</div>
      <ProgressBar value={task.progress} animated size="md" />
      <div className={styles.taskFooter}>
        <span className={styles.taskPct}>{task.progress}%</span>
        <div className={styles.taskActions}>
          <Button variant="ghost" size="sm" onClick={onOpen}>Chi tiết</Button>
          <Button variant="ghost" size="sm" icon="close" onClick={onCancel} className={styles.dangerText}>Dừng</Button>
        </div>
      </div>
    </Card>
  );
}

function HealthRow({ icon, label, detail, tone }: { icon: IconName; label: string; detail: string; tone: 'success' | 'warning' | 'error' }) {
  return (
    <div className={styles.healthRow}>
      <span className={styles.healthIcon}><Icon name={icon} size={16} /></span>
      <span className={styles.healthLabel}>{label}</span>
      <Badge tone={tone} dot>{detail}</Badge>
    </div>
  );
}
