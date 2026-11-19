import { useState, useEffect, useCallback } from 'react';
import { libraryService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button, IconButton } from '@/shared/ui/Button';
import { Card, StatCard } from '@/shared/ui/Card';
import { Icon } from '@/shared/ui/Icon';
import { Input, Select } from '@/shared/ui/Field';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { ConfirmDialog } from '@/shared/ui/Modal';
import { VideoPreviewModal } from '@/features/library/VideoPreviewModal';
import { EmptyState, Skeleton } from '@/shared/ui/EmptyState';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { formatDate, formatBytes } from '@/shared/lib/utils/format';
import type { LibraryItem } from '@/shared/lib/types';
import styles from './LibraryPage.module.css';

type Sort = 'newest' | 'oldest' | 'name' | 'size';
type FilterType = 'all' | 'merged' | 'single';

export function LibraryPage() {
  const addToast = useUIStore(s => s.addToast);
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<Sort>('newest');
  const [filterType, setFilterType] = useState<FilterType>('all');
  const [preview, setPreview] = useState<LibraryItem | null>(null);
  const [deleteItem, setDeleteItem] = useState<LibraryItem | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await libraryService.list();
      setItems(data.items);
    } catch {
      setError('Không thể tải danh sách thành phẩm. Vui lòng thử lại.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleOpenFolder = async () => {
    try {
      const res = await fetch('/api/open-library-folder', { method: 'POST' });
      if (!res.ok) throw new Error();
      addToast({ type: 'success', message: 'Đã mở thư mục data/media/final trên máy tính' });
    } catch {
      addToast({ type: 'error', message: 'Không thể mở thư mục' });
    }
  };

  const mergedCount = items.filter(i => i.merge && i.video).length;
  const singleCount = items.filter(i => !i.merge && i.video).length;
  const videoCount = items.filter(item => item.video).length;
  const subtitleCount = items.filter(item => item.video && item.srt).length;

  let filtered = items.filter(item => {
    if (!item.video) return false;
    if (search && !item.title.toLowerCase().includes(search.toLowerCase())) return false;
    if (filterType === 'merged' && !item.merge) return false;
    if (filterType === 'single' && item.merge) return false;
    return true;
  });

  filtered = [...filtered].sort((a, b) => {
    if (sort === 'newest') return b.modified_at.localeCompare(a.modified_at);
    if (sort === 'oldest') return a.modified_at.localeCompare(b.modified_at);
    if (sort === 'name') return a.title.localeCompare(b.title);
    if (sort === 'size') return (b.video?.size_mb || 0) - (a.video?.size_mb || 0);
    return 0;
  });

  const filteredSizeMb = filtered.reduce((total, item) => total + (item.video?.size_mb || 0), 0);
  const isFiltering = search !== '' || filterType !== 'all';

  const confirmDelete = async () => {
    if (!deleteItem) return;
    try {
      const res = await libraryService.delete(deleteItem.base_name);
      const n = res.deleted?.length ?? 0;
      const failed = res.failed ?? [];
      if (failed.length > 0) {
        addToast({
          type: 'error',
          message: `Còn ${failed.length} file chưa xóa được (đang mở/khóa?): ${failed.map(f => f.file).join(', ')}. Hãy đóng trình phát video rồi thử lại.`,
        });
      } else if (n > 0) {
        addToast({ type: 'success', message: `Đã xóa ${n} file video và phụ đề khỏi ổ đĩa (thư mục data/media/final)` });
      } else {
        addToast({ type: 'success', message: 'Không còn file nào trên đĩa (có thể đã bị xóa trước đó), đã đồng bộ dữ liệu' });
      }
      if (failed.length === 0) {
        setDeleteItem(null);
        setPreview(null);
      }
      load();
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      const locked = detail.includes('409') || detail.toLowerCase().includes('khóa');
      addToast({
        type: 'error',
        message: locked
          ? 'File video đang mở (trình phát/preview chưa nhả). Hãy đóng trình phát video rồi bấm Xóa lại.'
          : 'Không thể xóa file này (file có thể đang mở/khóa)',
      });
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        title="Kho video & thành phẩm"
        subtitle="Xem trước, tải về video tóm tắt MP4 và phụ đề SRT hoàn chỉnh"
        actions={
          <>
            <Button variant="secondary" size="sm" icon="folder" onClick={handleOpenFolder}>
              Mở thư mục máy tính
            </Button>
            <Button variant="secondary" size="sm" icon="refresh" onClick={load} disabled={loading}>
              Làm mới
            </Button>
          </>
        }
      />

      <section className={styles.summary} aria-label="Tổng quan thư viện">
        <StatCard label="Tổng video hoàn thành" value={videoCount} icon="video" accent="primary" />
        <StatCard label="Có phụ đề SRT" value={subtitleCount} icon="clipboard" accent="info" />
        <StatCard label="Trọn bộ / tập lẻ" value={`${mergedCount} / ${singleCount}`} icon="layers" accent="default" />
        <StatCard
          label="Dung lượng đang xem"
          value={filteredSizeMb >= 1024 ? `${(filteredSizeMb / 1024).toFixed(1)} GB` : `${filteredSizeMb.toFixed(1)} MB`}
          icon="storage"
          accent="success"
        />
      </section>

      <section className={styles.toolbar} aria-label="Bộ lọc thư viện">
        <div className={styles.searchWrap}>
          <Icon name="search" size={16} className={styles.searchIcon} />
          <Input
            className={styles.search}
            placeholder="Tìm kiếm theo tên phim/video…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          {search && (
            <IconButton icon="close" label="Xóa tìm kiếm" size="sm" className={styles.clearBtn} onClick={() => setSearch('')} />
          )}
        </div>

        <SegmentedControl<FilterType>
          value={filterType}
          onChange={setFilterType}
          size="sm"
          options={[
            { value: 'all', label: 'Tất cả', count: videoCount },
            { value: 'merged', label: 'Trọn bộ', icon: 'film', count: mergedCount },
            { value: 'single', label: 'Tập lẻ', icon: 'play', count: singleCount },
          ]}
        />

        <label className={styles.sortLabel}>
          <span>Sắp xếp</span>
          <Select className={styles.sort} value={sort} onChange={e => setSort(e.target.value as Sort)}>
            <option value="newest">Mới nhất</option>
            <option value="oldest">Cũ nhất</option>
            <option value="name">Tên A-Z</option>
            <option value="size">Dung lượng lớn nhất</option>
          </Select>
        </label>
      </section>

      {loading ? (
        <div className={styles.grid}>{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} height="208px" />)}</div>
      ) : error ? (
        <EmptyState glyph="alert" title="Không thể tải thư viện" description={error} action={{ label: 'Thử lại', onClick: load }} />
      ) : filtered.length === 0 ? (
        <EmptyState
          glyph={isFiltering ? 'search' : 'video'}
          title={isFiltering ? 'Không có video nào khớp bộ lọc' : 'Chưa có video thành phẩm nào'}
          description={isFiltering ? 'Hãy thử tìm kiếm với từ khóa khác.' : 'Các video tóm tắt sau khi hoàn thành sẽ xuất hiện tại đây.'}
          action={isFiltering ? { label: 'Xóa bộ lọc', onClick: () => { setSearch(''); setFilterType('all'); } } : undefined}
        />
      ) : (
        <div className={styles.grid}>
          {filtered.map(item => (
            <Card key={item.base_name} padding={false} className={styles.card} onClick={() => setPreview(item)}>
              <div className={styles.thumb}>
                <span className={styles.mediaIcon} aria-hidden="true">
                  <Icon name={item.merge ? 'film' : 'play'} size={22} />
                </span>
                <span className={styles.typeLabel}>{item.merge ? 'Trọn bộ' : 'Tập tóm tắt'}</span>
              </div>
              <div className={styles.cardBody}>
                <h3>{item.title}</h3>
                <div className={styles.cardMeta}>
                  <span>{item.video ? formatBytes(item.video.size_mb) : ''}</span>
                  <span>{formatDate(item.modified_at)}</span>
                </div>
                <div className={styles.assets}>
                  <span className={styles.assetReady}><Icon name="check" size={12} strokeWidth={3} /> Sẵn sàng xuất bản</span>
                  {item.srt && <span className={styles.assetSrt}><Icon name="clipboard" size={12} /> Có SRT</span>}
                </div>
              </div>
              <div className={styles.cardFooter}>
                <span title={item.video?.filename || item.srt?.filename}>
                  {item.video?.filename || item.srt?.filename}
                </span>
                <span className={styles.openHint}>Xem &amp; tải <Icon name="arrow-right" size={13} /></span>
              </div>
            </Card>
          ))}
        </div>
      )}

      <VideoPreviewModal
        open={!!preview}
        onClose={() => setPreview(null)}
        title={preview?.title || ''}
        badge={preview?.merge ? 'Phim gộp trọn bộ' : 'Tập tóm tắt'}
        videoUrl={preview?.video?.media_url}
        srtUrl={preview?.srt?.url}
        merge={preview?.merge}
        metaItems={[
          ...(preview?.video ? [{ label: 'Dung lượng', value: formatBytes(preview.video.size_mb) }] : []),
          { label: 'Xuất lúc', value: formatDate(preview?.modified_at) },
          { label: 'Phụ đề SRT', value: preview?.srt ? 'Có sẵn (bấm câu thoại để tua video)' : 'Không có' },
        ]}
        downloadVideoUrl={preview?.video?.url}
        downloadSrtUrl={preview?.srt?.url}
        onDelete={() => {
          const target = preview;
          setPreview(null);
          setDeleteItem(target);
        }}
        deleteLabel="Xóa file"
      />

      <ConfirmDialog
        open={!!deleteItem}
        onClose={() => setDeleteItem(null)}
        onConfirm={confirmDelete}
        title={`Xóa vĩnh viễn "${deleteItem?.title}"?`}
        message="Hành động này sẽ xóa cả file video MP4 và file phụ đề SRT trong thư mục data/media/final khỏi ổ đĩa máy tính. Video gốc trong data/uploads được giữ nguyên."
      />
    </div>
  );
}
