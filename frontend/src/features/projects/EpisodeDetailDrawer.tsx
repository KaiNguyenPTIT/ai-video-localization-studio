import { useState } from 'react';
import { episodeService } from '@/shared/lib/services';
import { Drawer } from '@/shared/ui/Drawer';
import { Button } from '@/shared/ui/Button';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { VideoPlayer } from '@/features/library/VideoPlayer';
import { SegmentViewer } from '@/features/projects/SegmentViewer';
import { ScriptPreview } from '@/features/projects/ScriptPreview';
import { DurationStats } from '@/features/projects/DurationStats';
import { validateScript } from '@/shared/lib/utils/scriptValidation';
import { friendlyError } from '@/shared/lib/services/apiClient';
import { useUIStore } from '@/shared/lib/state/uiStore';
import type { Episode, Voice, Model } from '@/shared/lib/types';
import styles from './EpisodeDetailDrawer.module.css';

interface EpisodeDetailDrawerProps {
  episode: Episode | null;
  projectId: string;
  onClose: () => void;
  voices: Record<string, Voice>;
  models: Model[];
  onEditConfig?: (ep: Episode) => void;
}

export function EpisodeDetailDrawer({ episode, projectId, onClose, onEditConfig }: EpisodeDetailDrawerProps) {
  const addToast = useUIStore(s => s.addToast);
  const [script, setScript] = useState('');
  const [validation, setValidation] = useState<ReturnType<typeof validateScript> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showTechnical, setShowTechnical] = useState(false);

  if (!episode) return null;

  const isManual = episode.options?.mode === 'manual';
  const isAwaiting = episode.status === 'awaiting_result';
  const isCompleted = episode.status === 'completed';
  const err = episode.error ? friendlyError(new Error(episode.error)) : null;

  const handleValidate = () => {
    const result = validateScript(script);
    setValidation(result);
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await episodeService.manualSubmit(projectId, episode.id, script);
      addToast({ type: 'success', message: 'Đã nhận kịch bản — đang bắt đầu dựng video' });
      onClose();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Gửi kịch bản thất bại' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Drawer open={!!episode} onClose={onClose} title={`Chi tiết: ${episode.filename}`} width={580}>
      <div className={styles.content}>
        <div className={styles.meta}>
          <StatusBadge status={episode.status} size="md" />
          <span className={styles.mode}>{isManual ? 'Chế độ Thủ công' : 'Chế độ API Tự động'}</span>
          {onEditConfig && !['running', 'queueing'].includes(episode.status) && (
            <div style={{ marginLeft: 'auto' }}>
              <Button size="sm" variant="ghost" onClick={() => { onClose(); onEditConfig(episode); }}>
                ⚙ Đổi Cấu Hình
              </Button>
            </div>
          )}
        </div>

        {episode.message && <div className={styles.message}>{episode.message}</div>}

        {['running', 'queueing'].includes(episode.status) && (
          <div className={styles.progress}>
            <ProgressBar value={episode.progress} animated size="md" />
            <span>{episode.progress}%</span>
          </div>
        )}

        <DurationStats
          targetSec={episode.target_sec}
          estSec={episode.est_sec}
          ttsSec={episode.tts_sec}
        />

        {['running', 'queueing'].includes(episode.status) && episode.segments && episode.segments.length > 0 && (
          <ScriptPreview segments={episode.segments} title="Kịch bản AI (cập nhật theo tiến trình)" />
        )}

        {err && (
          <div className={styles.errorBox}>
            <h4>{err.title}</h4>
            <p>{err.message}</p>
            <button className={styles.techToggle} onClick={() => setShowTechnical(!showTechnical)}>
              {showTechnical ? 'Ẩn' : 'Xem'} chi tiết kỹ thuật
            </button>
            {showTechnical && <pre className={styles.techDetail}>{err.technical}</pre>}
          </div>
        )}

        {isAwaiting && isManual && (
          <div className={styles.manualSection}>
            {episode.manual_prompt && (
              <div className={styles.promptBox}>
                <div className={styles.promptHeader}>
                  <span>Prompt AI đã tạo</span>
                  <Button size="sm" variant="ghost" onClick={() => {
                    navigator.clipboard.writeText(episode.manual_prompt!);
                    addToast({ type: 'info', message: 'Đã sao chép prompt vào bộ nhớ tạm' });
                  }}>Sao chép</Button>
                </div>
                <textarea className={styles.promptText} readOnly value={episode.manual_prompt} />
                {episode.target_words && (
                  <div className={styles.promptMeta}>
                    Mục tiêu: {episode.target_words} từ · ~{episode.num_segments} phân cảnh
                  </div>
                )}
              </div>
            )}
            <h4>Dán Kết Quả Kịch Bản Từ AI Studio</h4>
            <textarea
              className={styles.scriptInput}
              placeholder="Dán nội dung kịch bản AI trả về tại đây (định dạng: MM:SS\tlời bình)..."
              value={script}
              onChange={e => setScript(e.target.value)}
              rows={12}
            />
            <div className={styles.scriptActions}>
              <Button variant="secondary" size="sm" onClick={handleValidate}>Kiểm tra kịch bản</Button>
              <Button size="sm" onClick={handleSubmit} loading={submitting} disabled={!script.trim()}>
                Gửi & Dựng Video
              </Button>
            </div>
            {validation && (
              <div className={styles.validation}>
                {validation.valid ? <span className={styles.valid}>✓ Hợp lệ ({validation.segments} phân cảnh)</span> : null}
                {validation.errors.map((e, i) => <span key={i} className={styles.invalid}>✕ {e}</span>)}
                {validation.warnings.map((w, i) => <span key={i} className={styles.warn}>⚠ {w}</span>)}
              </div>
            )}
          </div>
        )}

        {isCompleted && episode.result_url && (
          <div className={styles.completed}>
            <DurationStats
              targetSec={episode.target_sec}
              estSec={episode.est_sec}
              ttsSec={episode.tts_sec}
            />
            {episode.segments && episode.segments.length > 0 ? (
              <SegmentViewer videoUrl={episode.result_url} segments={episode.segments} />
            ) : (
              <VideoPlayer src={episode.result_url} />
            )}
            <div className={styles.outputActions}>
              <a href={episode.result_url} download target="_blank" rel="noreferrer">
                <Button>📥 Tải Video MP4</Button>
              </a>
              {episode.srt_url && (
                <a href={episode.srt_url} download target="_blank" rel="noreferrer">
                  <Button variant="secondary">📥 Tải Phụ Đề SRT</Button>
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </Drawer>
  );
}
