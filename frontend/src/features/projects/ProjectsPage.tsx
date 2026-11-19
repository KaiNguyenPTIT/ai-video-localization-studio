import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { projectService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button, IconButton } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { Badge } from '@/shared/ui/Badge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { Input } from '@/shared/ui/Field';
import { Icon } from '@/shared/ui/Icon';
import { Modal, ConfirmDialog } from '@/shared/ui/Modal';
import { EmptyState, Skeleton } from '@/shared/ui/EmptyState';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { projectStats, formatRelative } from '@/shared/lib/utils/format';
import type { Project } from '@/shared/lib/types';
import styles from './ProjectsPage.module.css';

type Filter = 'all' | 'active' | 'processing' | 'completed' | 'failed';

export function ProjectsPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const addToast = useUIStore(s => s.addToast);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<Filter>('all');
  const [search, setSearch] = useState('');
  const [showNew, setShowNew] = useState(false);
  const [newName, setNewName] = useState('');
  const [creating, setCreating] = useState(false);
  const [deleteProject, setDeleteProject] = useState<Project | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await projectService.list();
      setProjects(list);
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không tải được danh sách dự án' });
    } finally {
      setLoading(false);
    }
  }, [addToast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (searchParams.get('new')) setShowNew(true); }, [searchParams]);

  const hasRunning = useMemo(
    () => projects.some(p => p.episodes?.some(e => ['running', 'queueing', 'awaiting_result'].includes(e.status))),
    [projects],
  );

  useEffect(() => {
    if (!hasRunning) return;
    const timer = setInterval(load, 2500);
    return () => clearInterval(timer);
  }, [hasRunning, load]);

  const counts = useMemo(() => {
    const acc: Record<Filter, number> = { all: projects.length, active: 0, processing: 0, completed: 0, failed: 0 };
    projects.forEach(p => {
      const s = projectStats(p.episodes || []);
      if (s.total > s.completed) acc.active++;
      if (s.processing > 0) acc.processing++;
      if (s.total > 0 && s.completed === s.total) acc.completed++;
      if (s.failed > 0) acc.failed++;
    });
    return acc;
  }, [projects]);

  const filtered = useMemo(() => projects.filter(p => {
    if (search && !p.name.toLowerCase().includes(search.toLowerCase())) return false;
    const s = projectStats(p.episodes || []);
    if (filter === 'completed') return s.total > 0 && s.completed === s.total;
    if (filter === 'processing') return s.processing > 0;
    if (filter === 'failed') return s.failed > 0;
    if (filter === 'active') return s.total > s.completed;
    return true;
  }), [projects, filter, search]);

  const handleCreate = async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const p = await projectService.create(newName.trim());
      addToast({ type: 'success', message: `Đã tạo dự án "${p.name}"` });
      setShowNew(false);
      setNewName('');
      navigate(`/projects/${p.id}`);
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Tạo dự án thất bại' });
    } finally {
      setCreating(false);
    }
  };

  const confirmDeleteProject = async () => {
    if (!deleteProject) return;
    try {
      await projectService.delete(deleteProject.id);
      addToast({ type: 'success', message: `Đã xóa dự án "${deleteProject.name}"` });
      setDeleteProject(null);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Xóa dự án thất bại' });
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        title="Dự án phim / Series"
        subtitle="Quản lý toàn bộ các bộ anime đang thực hiện tóm tắt review"
        actions={<Button icon="plus" onClick={() => setShowNew(true)}>Tạo dự án mới</Button>}
      />

      <div className={styles.toolbar}>
        <div className={styles.searchWrap}>
          <Icon name="search" size={16} className={styles.searchIcon} />
          <Input
            className={styles.search}
            placeholder="Tìm kiếm dự án phim…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <IconButton icon="close" label="Xóa tìm kiếm" size="sm" className={styles.clearBtn} onClick={() => setSearch('')} />
          )}
        </div>
        <SegmentedControl<Filter>
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'Tất cả', count: counts.all },
            { value: 'active', label: 'Đang làm', count: counts.active },
            { value: 'processing', label: 'Đang chạy', count: counts.processing },
            { value: 'completed', label: 'Hoàn thành', count: counts.completed },
            { value: 'failed', label: 'Có lỗi', count: counts.failed },
          ]}
        />
      </div>

      {loading ? (
        <div className={styles.grid}>
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height="182px" />)}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          glyph={search || filter !== 'all' ? 'search' : 'film'}
          title={search || filter !== 'all' ? 'Không tìm thấy dự án phù hợp' : 'Chưa có dự án nào'}
          description={
            search || filter !== 'all'
              ? 'Thử đổi từ khóa tìm kiếm hoặc bộ lọc khác.'
              : 'Hãy tạo dự án anime đầu tiên để bắt đầu thêm tập và tóm tắt.'
          }
          action={search || filter !== 'all'
            ? { label: 'Xóa bộ lọc', onClick: () => { setSearch(''); setFilter('all'); } }
            : { label: 'Tạo dự án mới', onClick: () => setShowNew(true) }}
        />
      ) : (
        <div className={styles.grid}>
          {filtered.map(p => (
            <ProjectCard
              key={p.id}
              project={p}
              onOpen={() => navigate(`/projects/${p.id}`)}
              onDelete={() => setDeleteProject(p)}
            />
          ))}
        </div>
      )}

      <Modal
        open={showNew}
        onClose={() => setShowNew(false)}
        title="Tạo dự án anime mới"
        icon="film"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowNew(false)}>Hủy</Button>
            <Button onClick={handleCreate} loading={creating} icon="plus">Bắt đầu dự án</Button>
          </>
        }
      >
        <label className={styles.label}>Tên bộ phim / Anime</label>
        <Input
          value={newName}
          onChange={e => setNewName(e.target.value)}
          placeholder="VD: Chú Thuật Hồi Chiến (Jujutsu Kaisen)"
          autoFocus
          onKeyDown={e => e.key === 'Enter' && handleCreate()}
        />
        <p className={styles.hint}>Bạn có thể tải nhiều tập lên sau khi tạo dự án.</p>
      </Modal>

      <ConfirmDialog
        open={!!deleteProject}
        onClose={() => setDeleteProject(null)}
        onConfirm={confirmDeleteProject}
        title={`Xóa vĩnh viễn dự án "${deleteProject?.name}"?`}
        message="Hành động này sẽ xóa dự án cùng toàn bộ danh sách tập phim và dữ liệu kịch bản liên quan. Không thể hoàn tác."
      />
    </div>
  );
}

function ProjectCard({ project, onOpen, onDelete }: { project: Project; onOpen: () => void; onDelete: () => void }) {
  const stats = projectStats(project.episodes || []);
  const done = stats.total > 0 && stats.completed === stats.total;
  const tone = stats.failed > 0 ? 'error' : stats.processing > 0 ? 'primary' : done ? 'success' : 'default';

  return (
    <Card onClick={onOpen} className={styles.projectCard}>
      <div className={styles.cardTop}>
        <div className={styles.cardIcon}><Icon name="film" size={18} /></div>
        <h3 className={styles.projectName}>{project.name}</h3>
        <StatusPill tone={tone} processing={stats.processing} failed={stats.failed} done={done} />
      </div>

      <div className={styles.projectMeta}>
        <span><Icon name="layers" size={12} /> {stats.total} tập</span>
        {stats.completed > 0 && <span className={styles.completed}>{stats.completed} xong</span>}
        {stats.processing > 0 && <span className={styles.processing}>{stats.processing} đang chạy</span>}
        {stats.failed > 0 && <span className={styles.failed}>{stats.failed} lỗi</span>}
      </div>

      <ProgressBar value={stats.progress} tone={stats.failed > 0 ? 'error' : done ? 'success' : 'primary'} />

      <div className={styles.projectFooter}>
        <span className={styles.updated}><Icon name="clock" size={12} /> {formatRelative(project.updated_at || project.created_at)}</span>
        <div className={styles.cardActions}>
          <Button size="sm" iconRight="arrow-right" onClick={e => { e.stopPropagation(); onOpen(); }}>Mở</Button>
          <IconButton icon="trash" label="Xóa dự án" variant="danger" size="sm" onClick={e => { e.stopPropagation(); onDelete(); }} />
        </div>
      </div>
    </Card>
  );
}

function StatusPill({ tone, processing, failed, done }: { tone: string; processing: number; failed: number; done: boolean }) {
  if (failed > 0) return <Badge tone="error" dot>Có lỗi</Badge>;
  if (processing > 0) return <Badge tone="primary" dot>Đang chạy</Badge>;
  if (done) return <Badge tone="success" dot>Hoàn thành</Badge>;
  return <Badge tone={tone === 'default' ? 'neutral' : 'info'} dot>Chưa xong</Badge>;
}
