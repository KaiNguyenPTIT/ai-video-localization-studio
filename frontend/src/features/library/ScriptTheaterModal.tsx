import { useEffect, useRef, useState } from 'react';
import { VideoPlayer, type VideoPlayerHandle } from './VideoPlayer';
import { Button } from '@/shared/ui/Button';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { friendlyError } from '@/shared/lib/services/apiClient';
import type { Episode, Segment } from '@/shared/lib/types';
import styles from './ScriptTheaterModal.module.css';

export interface ScriptTheaterModalProps {
  open: boolean;
  onClose: () => void;
  episode: Episode;
  title: string;
  badge?: string;
  live?: boolean;
  onEditConfig?: () => void;
}

function formatClock(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '00:00:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

/** Timeline của video TÓM TẮT = cộng dồn TTS từng phân cảnh.
 *  start_time gốc là giờ của video NGUỒN (dùng khớp shot) — tua video tóm tắt
 *  bằng giờ nguồn sẽ SAI, nên seek/highlight phải dùng mốc cộng dồn này. */
function resultOffsets(segments: Segment[]): number[] {
  const offs: number[] = [];
  let acc = 0;
  for (const s of segments) {
    offs.push(acc);
    const d = s.tts_duration ?? 0;
    acc += d > 0 ? d : 0;
  }
  return offs;
}

function fmtSec(v: number | null | undefined): string | null {
  if (v === null || v === undefined || v <= 0) return null;
  return `${Math.round(v)}s`;
}

export function ScriptTheaterModal({
  open,
  onClose,
  episode,
  title,
  badge,
  live,
  onEditConfig,
}: ScriptTheaterModalProps) {
  const [playbackTime, setPlaybackTime] = useState(0);
  const playerRef = useRef<VideoPlayerHandle>(null);
  const lineRefs = useRef(new Map<number, HTMLButtonElement>());

  useEffect(() => {
    if (!open) return;
    setPlaybackTime(0);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open, onClose]);

  const segments = episode.segments || [];
  const videoUrl = episode.result_url || null;
  const offs = resultOffsets(segments);
  const totalTts = segments.reduce((a, s) => a + ((s.tts_duration ?? 0) > 0 ? (s.tts_duration as number) : 0), 0);
  const totalShots = segments.reduce((a, s) => a + (s.shot_count || 0), 0);
  const hasResultTime = Boolean(videoUrl) && totalTts > 0;
  const isRunning = ['running', 'queueing'].includes(episode.status);

  let activeIdx: number | null = null;
  if (hasResultTime) {
    for (let i = 0; i < segments.length; i++) {
      if (offs[i] <= playbackTime + 0.05) activeIdx = i;
      else break;
    }
  }

  // Auto-scroll tới dòng đang phát (giống SubtitlePanel).
  useEffect(() => {
    if (activeIdx === null) return;
    lineRefs.current.get(activeIdx)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activeIdx]);

  if (!open) return null;

  const err = episode.error ? friendlyError(new Error(episode.error)) : null;
  const durMeta = [episode.target_sec != null && `🎯 ${fmtSec(episode.target_sec)}`, episode.est_sec != null && `📝 ${fmtSec(episode.est_sec)}`, episode.tts_sec != null && `🎙 ${fmtSec(episode.tts_sec)}`]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className={styles.previewOverlay} onClick={onClose}>
      <div className={styles.previewPanel} onClick={e => e.stopPropagation()}>
        <button className={styles.previewClose} onClick={onClose} title="Đóng (Esc)">
          ✕
        </button>

        <div className={styles.previewHeader}>
          <h2 className={styles.previewTitle}>
            {title}
            {badge && <span className={styles.previewBadge}>{badge}</span>}
            {live && (
              <span className={styles.liveTag}>
                <span className={styles.liveDot} /> LIVE
              </span>
            )}
          </h2>
        </div>

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
                <span style={{ fontSize: 32 }}>🎬</span>
                <span>
                  {isRunning
                    ? 'Video đang dựng — kịch bản cập nhật live bên phải'
                    : episode.status === 'failed'
                      ? 'Dựng thất bại — xem chi tiết lỗi bên dưới'
                      : 'Chưa có file video hoàn chỉnh'}
                </span>
              </div>
            )}
          </div>

          <aside className={styles.scriptPanel} aria-label="Kịch bản">
            <div className={styles.scriptHeader}>
              <div>
                <span className={styles.eyebrow}>{live ? 'Kịch bản live' : 'Kịch bản AI'}</span>
                <h3>{segments.length} phân cảnh</h3>
              </div>
              {(totalShots > 0 || totalTts > 0) && (
                <span className={styles.scriptTotal}>
                  {totalShots > 0 && `${totalShots} shot`}
                  {totalShots > 0 && totalTts > 0 && ' · '}
                  {totalTts > 0 && `${Math.round(totalTts)}s lời bình`}
                </span>
              )}
            </div>
            <div className={styles.scriptList}>
              {segments.length ? (
                segments.map((seg, i) => {
                  const isActive = i === activeIdx;
                  return (
                    <button
                      key={i}
                      type="button"
                      className={`${styles.scriptLine} ${isActive ? styles.scriptLineActive : ''}`}
                      onClick={() => hasResultTime && playerRef.current?.seekTo(offs[i])}
                      disabled={!hasResultTime}
                      title={hasResultTime ? `Nguồn ${seg.start_time}${seg.end_time && seg.end_time !== seg.start_time ? ` → ${seg.end_time}` : ''} · Nhảy tới ${formatClock(offs[i])} trong video tóm tắt` : seg.start_time}
                      aria-current={isActive ? 'true' : undefined}
                      ref={element => {
                        if (element) lineRefs.current.set(i, element);
                        else lineRefs.current.delete(i);
                      }}
                    >
                      <time>{hasResultTime ? formatClock(offs[i]) : seg.start_time}</time>
                      <span className={styles.scriptBody}>
                        <span className={styles.scriptText}>{seg.narration}</span>
                        <span className={styles.scriptBadges}>
                          {hasResultTime && seg.start_time && (
                            <span className={styles.scriptBadge} title="Mốc của cảnh trong video gốc">
                              🎬 nguồn {seg.start_time}
                              {seg.end_time && seg.end_time !== seg.start_time ? ` → ${seg.end_time}` : ''}
                            </span>
                          )}
                          {(seg.tts_duration ?? 0) > 0 && (
                            <span className={styles.scriptBadge}>🎙 {(seg.tts_duration as number).toFixed(1)}s</span>
                          )}
                          {(seg.shot_count ?? 0) > 0 && (
                            <span className={styles.scriptBadge}>🎞 {seg.shot_count} shot</span>
                          )}
                        </span>
                      </span>
                    </button>
                  );
                })
              ) : (
                <p className={styles.scriptEmpty}>
                  {isRunning ? 'AI đang viết kịch bản — các phân cảnh sẽ hiện dần tại đây…' : 'Tập này chưa có kịch bản.'}
                </p>
              )}
            </div>
          </aside>
        </div>

        {err && (
          <div className={styles.errorBox}>
            <h4>{err.title}</h4>
            <p>{err.message}</p>
          </div>
        )}

        <div className={styles.previewMeta}>
          <div className={styles.previewMetaItem}>
            <span className={styles.previewMetaLabel}>Trạng thái:</span>
            <StatusBadge status={episode.status} />
          </div>
          <div className={styles.previewMetaItem}>
            <span className={styles.previewMetaLabel}>Chế độ:</span>
            <span className={styles.previewMetaVal}>{episode.options?.mode === 'manual' ? 'Thủ công' : 'API Tự động'}</span>
          </div>
          {isRunning && (
            <div className={styles.previewMetaItem}>
              <span className={styles.previewMetaLabel}>Tiến độ:</span>
              <span className={styles.previewMetaVal}>{episode.progress}%{episode.message ? ` — ${episode.message}` : ''}</span>
            </div>
          )}
          {durMeta && (
            <div className={styles.previewMetaItem}>
              <span className={styles.previewMetaLabel}>Thời lượng:</span>
              <span className={styles.previewMetaVal}>{durMeta}</span>
            </div>
          )}
        </div>

        <div className={styles.previewActions}>
          {onEditConfig && (
            <Button variant="ghost" onClick={onEditConfig}>
              ⚙ Đổi Cấu Hình
            </Button>
          )}
          {episode.status === 'completed' && episode.result_url && (
            <a href={episode.result_url} download target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <Button>📥 Tải Video MP4</Button>
            </a>
          )}
          {episode.status === 'completed' && episode.srt_url && (
            <a href={episode.srt_url} download target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
              <Button variant="secondary">📥 Tải Phụ Đề SRT</Button>
            </a>
          )}
          <Button variant="ghost" onClick={onClose}>
            Đóng
          </Button>
        </div>
      </div>
    </div>
  );
}
