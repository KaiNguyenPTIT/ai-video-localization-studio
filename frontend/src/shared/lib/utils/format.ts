export function formatDuration(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return '—';
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  return `${m}:${String(r).padStart(2, '0')}`;
}

export function formatBytes(mb: number): string {
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(1)} MB`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString('vi-VN', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'Vừa xong';
  if (mins < 60) return `${mins} phút trước`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs} giờ trước`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days} ngày trước`;
  const months = Math.floor(days / 30);
  if (months < 12) return `${months} tháng trước`;
  return `${Math.floor(months / 12)} năm trước`;
}

export function formatDurationShort(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return '0s';
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}p`;
  if (m > 0) return `${m}p ${r}s`;
  return `${r}s`;
}

export function episodeLabel(filename: string, index: number): string {
  const match = filename.match(/(?:ep|tập|episode)[\s._-]*(\d+)/i);
  if (match) return `Tập ${match[1].padStart(2, '0')}`;
  return `Tập ${String(index + 1).padStart(2, '0')}`;
}

export function projectStats(episodes: { status: string }[]) {
  const total = episodes.length;
  const completed = episodes.filter(e => e.status === 'completed').length;
  const processing = episodes.filter(e => ['running', 'queueing'].includes(e.status)).length;
  const failed = episodes.filter(e => e.status === 'failed').length;
  const pending = episodes.filter(e => e.status === 'pending').length;
  const awaiting = episodes.filter(e => ['awaiting', 'awaiting_result'].includes(e.status)).length;
  const progress = total > 0 ? Math.round((completed / total) * 100) : 0;
  return { total, completed, processing, failed, pending, awaiting, progress };
}

export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ');
}
