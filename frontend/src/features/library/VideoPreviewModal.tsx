import React, { useState, useRef, useEffect } from 'react';
import { VideoPlayer, type VideoPlayerHandle } from './VideoPlayer';
import { SubtitlePanel } from './SubtitlePanel';
import { Button, IconButton } from '@/shared/ui/Button';
import { Icon } from '@/shared/ui/Icon';
import styles from './VideoPreviewModal.module.css';

export interface MergeEpisodeRange {
  episode_id?: string;
  filename: string;
  start_time: number;
}

export interface VideoPreviewModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  badge?: string;
  videoUrl?: string | null;
  srtUrl?: string | null;
  merge?: {
    episode_ranges?: MergeEpisodeRange[];
    total_duration?: number;
  } | null;
  metaItems?: Array<{ label: string; value: React.ReactNode }>;
  downloadVideoUrl?: string | null;
  downloadSrtUrl?: string | null;
  onDelete?: () => void;
  deleteLabel?: string;
  extraActions?: React.ReactNode;
}

function formatClock(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '00:00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function episodeShortName(filename: string, index: number): string {
  const m = filename.match(/(?:-\s*)?(0\d+|\d{1,2})\b/);
  return m ? `Tập ${m[1]}` : `Tập ${index + 1}`;
}

export function VideoPreviewModal({
  open,
  onClose,
  title,
  badge,
  videoUrl,
  srtUrl,
  merge,
  metaItems,
  downloadVideoUrl,
  downloadSrtUrl,
  onDelete,
  deleteLabel = 'Xóa file',
  extraActions,
}: VideoPreviewModalProps) {
  const [playbackTime, setPlaybackTime] = useState(0);
  const playerRef = useRef<VideoPlayerHandle>(null);

  useEffect(() => {
    if (!open) return;
    setPlaybackTime(0);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const hasMergeEpisodes = Boolean(merge?.episode_ranges && merge.episode_ranges.length > 0);
  const videoDl = downloadVideoUrl || videoUrl;
  const srtDl = downloadSrtUrl || srtUrl;

  return (
    <div className={styles.previewOverlay} onClick={onClose}>
      <div className={styles.previewPanel} onClick={e => e.stopPropagation()}>
        <IconButton
          icon="close"
          label="Đóng (Esc)"
          size="sm"
          className={styles.previewClose}
          onClick={onClose}
        />

        <div className={styles.previewHeader}>
          <h2 className={styles.previewTitle}>
            {title}
            {badge && <span className={styles.previewBadge}>{badge}</span>}
          </h2>
        </div>

        <div className={styles.previewBody}>
          <div className={styles.previewWorkspace}>
            <div className={styles.previewVideo}>
              {videoUrl ? (
                <VideoPlayer
                  ref={playerRef}
                  src={videoUrl}
                  onTimeUpdate={setPlaybackTime}
                />
              ) : (
                <div className={styles.noVideo}>
                  <Icon name="film" size={32} strokeWidth={1.6} />
                  <span>Chưa có file video hoàn chỉnh</span>
                </div>
              )}
            </div>

            <SubtitlePanel
              src={srtUrl || null}
              currentTime={playbackTime}
              onSeek={seconds => playerRef.current?.seekTo(seconds)}
            />
          </div>

          {hasMergeEpisodes && merge?.episode_ranges && (
            <div className={styles.mergeStrip}>
              <div className={styles.mergeStripHeader}>
                <div>
                  <span className={styles.eyebrow}>Phim gộp liên tục</span>
                  <h3>Danh sách các tập</h3>
                </div>
                <span className={styles.mergeTotal}>
                  {merge.episode_ranges.length} tập · {formatClock(merge.total_duration || 0)}
                </span>
              </div>
              <div className={styles.mergeTiles}>
                {merge.episode_ranges.map((range, i) => {
                  const nextStart = merge.episode_ranges![i + 1]?.start_time ?? Infinity;
                  const isActive = playbackTime >= range.start_time && playbackTime < nextStart;
                  return (
                    <button
                      key={range.episode_id || i}
                      type="button"
                      className={`${styles.mergeTile} ${isActive ? styles.mergeTileActive : ''}`}
                      title={`${range.filename} — ${formatClock(range.start_time)}`}
                      onClick={() => playerRef.current?.seekTo(range.start_time)}
                      aria-current={isActive ? 'true' : undefined}
                    >
                      <span className={styles.mergeTileName}>{episodeShortName(range.filename, i)}</span>
                      <time className={styles.mergeTileTime}>{formatClock(range.start_time)}</time>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {metaItems && metaItems.length > 0 && (
            <div className={styles.previewMeta}>
              {metaItems.map((m, idx) => (
                <div key={idx} className={styles.previewMetaItem}>
                  <span className={styles.previewMetaLabel}>{m.label}:</span>
                  <span className={styles.previewMetaVal}>{m.value}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className={styles.previewActions}>
          {extraActions}
          {videoDl && (
            <a href={videoDl} download target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <Button icon="download">Tải video MP4</Button>
            </a>
          )}
          {srtDl && (
            <a href={srtDl} download target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <Button variant="secondary" icon="download">Tải phụ đề SRT</Button>
            </a>
          )}
          {onDelete && (
            <Button variant="danger" icon="trash" onClick={onDelete}>
              {deleteLabel}
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>
            Đóng
          </Button>
        </div>
      </div>
    </div>
  );
}
