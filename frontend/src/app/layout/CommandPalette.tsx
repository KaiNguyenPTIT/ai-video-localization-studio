import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { projectService } from '@/shared/lib/services';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { Icon, type IconName } from '@/shared/ui/Icon';
import styles from './CommandPalette.module.css';

const COMMANDS = [
  { label: 'Tạo dự án mới', path: '/projects', action: 'new', keywords: 'create project tao du an moi', icon: 'plus' as IconName },
  { label: 'Tải tập phim lên', path: '/projects', action: 'upload', keywords: 'add episode upload tai tap', icon: 'upload' as IconName },
  { label: 'Tổng quan', path: '/', keywords: 'home dashboard tong quan', icon: 'dashboard' as IconName },
  { label: 'Dự án phim', path: '/projects', keywords: 'series anime du an phim', icon: 'film' as IconName },
  { label: 'Tiến trình chạy', path: '/tasks', keywords: 'queue running tien trinh', icon: 'clock' as IconName },
  { label: 'Kho video đã xuất', path: '/library', keywords: 'output video srt kho', icon: 'library' as IconName },
  { label: 'Cài đặt & API Key', path: '/settings', keywords: 'api keys voice cai dat', icon: 'settings' as IconName },
  { label: 'Tóm tắt nhanh', path: '/quick', keywords: 'fast single video tom tat nhanh', icon: 'bolt' as IconName },
  { label: 'Google AI Studio', path: '/studio', keywords: 'manual prompt script studio', icon: 'sparkles' as IconName },
  { label: 'Dung lượng ổ đĩa', path: '/storage', keywords: 'cleanup disk dung luong', icon: 'storage' as IconName },
  { label: 'Nhật ký hệ thống', path: '/logs', keywords: 'activity history nhat ky', icon: 'logs' as IconName },
];

export function CommandPalette() {
  const open = useUIStore(s => s.commandPaletteOpen);
  const setOpen = useUIStore(s => s.setCommandPaletteOpen);
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [projects, setProjects] = useState<{ id: string; name: string }[]>([]);
  const [highlight, setHighlight] = useState(0);

  useEffect(() => {
    if (!open) {
      setQuery('');
      setHighlight(0);
      return;
    }
    projectService.list().then(list => setProjects(list.map(p => ({ id: p.id, name: p.name })))).catch(() => {});
  }, [open]);

  const items = useMemo(() => {
    const q = query.toLowerCase().trim();
    const cmds = COMMANDS.filter(c =>
      !q || c.label.toLowerCase().includes(q) || c.keywords.includes(q)
    ).map(c => ({ type: 'command' as const, ...c }));

    const projs = projects
      .filter(p => !q || p.name.toLowerCase().includes(q))
      .slice(0, 5)
      .map(p => ({ type: 'project' as const, label: p.name, path: `/projects/${p.id}`, id: p.id, icon: 'folder' as IconName }));

    return [...cmds, ...projs];
  }, [query, projects]);

  useEffect(() => { setHighlight(0); }, [query]);

  if (!open) return null;

  const run = (item: typeof items[0]) => {
    setOpen(false);
    if (item.type === 'project') {
      navigate(item.path);
    } else if ('action' in item && item.action === 'new') {
      navigate('/projects?new=1');
    } else if ('action' in item && item.action === 'upload') {
      navigate('/projects');
    } else {
      navigate(item.path);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHighlight(h => Math.min(h + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHighlight(h => Math.max(h - 1, 0));
    } else if (e.key === 'Enter' && items[highlight]) {
      e.preventDefault();
      run(items[highlight]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  return (
    <div className={styles.overlay} onClick={() => setOpen(false)}>
      <div className={styles.palette} onClick={e => e.stopPropagation()}>
        <input
          className={styles.input}
          placeholder="Tìm lệnh, dự án…"
          autoFocus
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className={styles.list}>
          {items.length === 0 ? (
            <div className={styles.empty}>Không có kết quả</div>
          ) : items.map((item, i) => (
            <button
              key={item.type === 'project' ? item.id : item.label}
              className={`${styles.item} ${i === highlight ? styles.itemActive : ''}`}
              onClick={() => run(item)}
              onMouseEnter={() => setHighlight(i)}
            >
              <span className={styles.itemIcon}><Icon name={item.icon} size={16} /></span>
              <span>{item.label}</span>
              {item.type === 'project' && <span className={styles.itemMeta}>Dự án</span>}
            </button>
          ))}
        </div>
        <div className={styles.hint}>↑↓ di chuyển · Enter chọn · Esc đóng · Ctrl+K</div>
      </div>
    </div>
  );
}
