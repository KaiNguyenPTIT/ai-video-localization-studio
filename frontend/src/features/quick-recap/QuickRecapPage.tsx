import { useState, useEffect } from 'react';
import { quickService, taskService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { Icon } from '@/shared/ui/Icon';
import { UploadZone } from '@/features/quick-recap/UploadZone';
import { ConfigPanel } from '@/features/projects/ConfigPanel';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { VideoPlayer } from '@/features/library/VideoPlayer';
import { ScriptPreview } from '@/features/projects/ScriptPreview';
import { DurationStats } from '@/features/projects/DurationStats';
import { useConfig } from '@/shared/hooks/useConfig';
import { useTaskProgress } from '@/shared/hooks/useTaskProgress';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { validateScript } from '@/shared/lib/utils/scriptValidation';
import styles from './QuickRecapPage.module.css';

export function QuickRecapPage() {
  const addToast = useUIStore(s => s.addToast);
  const { voices, models, detailLevels, defaultDetail, loading: configLoading } = useConfig();

  const [file, setFile] = useState<File | null>(null);
  const [config, setConfig] = useState({
    mode: 'api',
    voice_id: '',
    model: '',
    style: 'narrative',
    detail: '',
    custom_minutes: '',
    edit_mode: 'smart_shot',
    character_name_mode: 'romaji',
    free_order: '0',
  });

  useEffect(() => {
    if (defaultDetail && !config.detail) {
      setConfig(prev => ({ ...prev, detail: defaultDetail }));
    }
  }, [defaultDetail, config.detail]);

  const [taskId, setTaskId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [autoRunning, setAutoRunning] = useState(false);
  const [openingFolder, setOpeningFolder] = useState(false);

  const [manualPrompt, setManualPrompt] = useState('');
  const [manualScript, setManualScript] = useState('');
  const [submittingManual, setSubmittingManual] = useState(false);
  const [validation, setValidation] = useState<ReturnType<typeof validateScript> | null>(null);

  const { task } = useTaskProgress(taskId, {
    onComplete: () => addToast({ type: 'success', message: 'Tóm tắt video hoàn tất!' }),
    onFailed: () => addToast({ type: 'error', message: 'Xử lý video thất bại' }),
  });

  const start = async () => {
    if (!file) return;
    setStarting(true);
    try {
      if (config.mode === 'manual') {
        const r = await quickService.manualStart(file, config);
        setTaskId(r.task_id);
        setManualPrompt(r.prompt || '');
        addToast({
          type: 'info',
          message: 'Đã chuẩn bị tác vụ thủ công. Bạn có thể bấm "Tự động AI Studio" hoặc dán kịch bản!',
        });
      } else {
        const r = await quickService.upload(file, config);
        setTaskId(r.task_id);
        addToast({ type: 'info', message: 'Đã đưa video vào hàng đợi xử lý' });
      }
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Khởi động tác vụ thất bại' });
    } finally {
      setStarting(false);
    }
  };

  const handleAutoRun = async () => {
    if (!taskId) return;
    setAutoRunning(true);
    try {
      await quickService.manualAutoRun(taskId);
      addToast({ type: 'info', message: 'Đang mở Google AI Studio và thao tác tự động…' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lỗi khi khởi chạy tự động AI Studio' });
    } finally {
      setAutoRunning(false);
    }
  };

  const handleOpenFolder = async () => {
    if (!taskId) return;
    setOpeningFolder(true);
    try {
      await quickService.manualOpenFolder(taskId);
      addToast({ type: 'success', message: 'Đã mở thư mục chứa video nén trên máy' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không thể mở thư mục' });
    } finally {
      setOpeningFolder(false);
    }
  };

  const submitManual = async () => {
    if (!taskId || !manualScript.trim()) return;
    setSubmittingManual(true);
    try {
      await quickService.manualSubmit(taskId, manualScript);
      addToast({ type: 'success', message: 'Đã nhận kịch bản — đang bắt đầu dựng video…' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Gửi kịch bản thất bại' });
    } finally {
      setSubmittingManual(false);
    }
  };

  const cancelTask = async () => {
    if (!taskId) return;
    if (!window.confirm('Bạn có chắc chắn muốn hủy quá trình xử lý video này?')) return;
    setCancelling(true);
    try {
      await taskService.cancel(taskId);
      addToast({ type: 'warning', message: 'Đã gửi yêu cầu hủy tác vụ' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không thể hủy tác vụ' });
    } finally {
      setCancelling(false);
    }
  };

  const resetAll = () => {
    setFile(null);
    setTaskId(null);
    setManualPrompt('');
    setManualScript('');
    setValidation(null);
  };

  const isManualAwaiting = config.mode === 'manual' && task?.status === 'awaiting';
  const isProcessing = task && ['pending', 'queueing', 'running'].includes(task.status);
  const isDone = task?.status === 'completed';
  const isTerminated = task && ['completed', 'failed', 'cancelled'].includes(task.status);

  const formatSec = (sec?: number) => {
    if (!sec || isNaN(sec)) return '0:00';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s < 10 ? '0' : ''}${s}`;
  };

  return (
    <div className={styles.page}>
      <PageHeader
        title="Tóm tắt nhanh video"
        subtitle="Tải lên một video anime bất kỳ để tạo tóm tắt hoàn chỉnh tự động hoặc qua AI Studio"
      />

      <div className={styles.layout}>
        {/* CỘT TRÁI */}
        <div className={styles.left}>
          {!taskId ? (
            <Card>
              <h3 className={styles.sectionTitle}>1. Chọn video cần tóm tắt</h3>
              <UploadZone
                onFiles={files => {
                  if (files && files[0]) setFile(files[0]);
                }}
                multiple={false}
                label={file ? file.name : 'Kéo thả video vào đây hoặc bấm để chọn tệp'}
              />

              {file && (
                <div className={styles.fileSelectedBox}>
                  <div className={styles.fileDetails}>
                    <span className={styles.fileName}><Icon name="video" size={15} /> {file.name}</span>
                    <span className={styles.fileSize}>Dung lượng: {(file.size / 1024 / 1024).toFixed(1)} MB</span>
                  </div>
                  <Button size="sm" variant="ghost" icon="refresh" onClick={() => setFile(null)}>
                    Đổi video
                  </Button>
                </div>
              )}

              <h3 className={styles.sectionTitle} style={{ marginTop: '20px' }}>
                2. Tùy chọn biên tập & lồng tiếng
              </h3>
              {!configLoading && (
                <ConfigPanel
                  config={config}
                  onChange={c => setConfig(prev => ({ ...prev, ...c }))}
                  voices={voices}
                  models={models}
                  detailLevels={detailLevels}
                  defaultDetail={defaultDetail}
                />
              )}

              <Button
                onClick={start}
                loading={starting}
                disabled={!file}
                size="lg"
                icon="bolt"
                className={styles.startBtn}
              >
                Bắt đầu tạo video tóm tắt
              </Button>
            </Card>
          ) : isManualAwaiting ? (
            <Card>
              <div className={styles.manualHeader}>
                <div>
                  <h3>Đang chờ kịch bản từ Google AI Studio</h3>
                  <p className={styles.hint}>
                    Video đã được nén tối ưu. Bạn có thể chọn tự động 1-chạm hoặc tự dán kịch bản.
                  </p>
                </div>
              </div>

              <div className={styles.autoActionBox}>
                <div className={styles.autoActionHeader}>
                  <strong><Icon name="bolt" size={14} /> Cách 1: Tự động thao tác (khuyên dùng)</strong>
                  <span>Hệ thống tự mở Chrome, gửi video & nhận kịch bản</span>
                </div>
                <Button size="md" icon="bolt" onClick={handleAutoRun} loading={autoRunning} className={styles.autoBtn}>
                  Tự động thao tác trên Google AI Studio (1-chạm)
                </Button>
              </div>

              <div className={styles.manualSection}>
                <div className={styles.manualSubTitle}>
                  <strong><Icon name="wand" size={14} /> Cách 2: Thao tác thủ công</strong>
                </div>

                <div className={styles.toolRow}>
                  <Button size="sm" variant="secondary" icon="folder" onClick={handleOpenFolder} loading={openingFolder}>
                    Mở thư mục chứa video nén
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    icon="copy"
                    onClick={() => {
                      const text = manualPrompt || task?.prompt || '';
                      navigator.clipboard.writeText(text);
                      addToast({ type: 'info', message: 'Đã sao chép prompt vào clipboard!' });
                    }}
                  >
                    Sao chép lời nhắc (prompt)
                  </Button>
                </div>

                <label className={styles.inputLabel}>Lời nhắc đã tạo cho AI Studio:</label>
                <textarea className={styles.promptBox} readOnly value={manualPrompt || task?.prompt || ''} rows={4} />

                <label className={styles.inputLabel}>Dán kết quả kịch bản từ AI Studio vào đây:</label>
                <textarea
                  className={styles.scriptBox}
                  placeholder="Dán kịch bản từ AI Studio tại đây… (Ví dụ: 00:00:05\tLời bình cảnh 1)"
                  value={manualScript}
                  onChange={e => setManualScript(e.target.value)}
                  rows={7}
                />

                <div className={styles.scriptActions}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon="check-circle"
                    onClick={() => setValidation(validateScript(manualScript))}
                    disabled={!manualScript.trim()}
                  >
                    Kiểm tra cú pháp
                  </Button>
                  <Button size="sm" icon="play" onClick={submitManual} disabled={!manualScript.trim()} loading={submittingManual}>
                    Gửi kịch bản & bắt đầu dựng video
                  </Button>
                </div>

                {validation && (
                  <div className={styles.validation}>
                    {validation.valid ? (
                      <span className={styles.valid}>
                        <Icon name="check" size={13} strokeWidth={3} /> Cú pháp hợp lệ: {validation.segments} phân đoạn được phát hiện
                      </span>
                    ) : (
                      validation.errors.map((e, i) => (
                        <span key={i} className={styles.err}>
                          <Icon name="close" size={13} /> {e}
                        </span>
                      ))
                    )}
                  </div>
                )}
              </div>
            </Card>
          ) : (
            <Card>
              <div className={styles.inProgressInfo}>
                <h3>Đang xử lý video tóm tắt</h3>
                <p className={styles.desc}>
                  Hệ thống đang thực hiện quy trình tổng hợp video theo cấu hình bạn đã chọn.
                </p>
                {isProcessing && (
                  <div className={styles.cancelAction}>
                    <Button variant="danger" size="sm" icon="close" onClick={cancelTask} loading={cancelling}>
                      Hủy tác vụ đang chạy
                    </Button>
                  </div>
                )}
                {isTerminated && (
                  <div className={styles.resetAction}>
                    <Button variant="primary" icon="plus" onClick={resetAll}>
                      Tóm tắt video mới khác
                    </Button>
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* CỘT PHẢI */}
        <div className={styles.right}>
          <Card>
            <div className={styles.statusHeader}>
              <h3>Trạng thái & kết quả</h3>
              {task ? <StatusBadge status={task.status} size="md" /> : <span className={styles.waitingBadge}>Chưa có tác vụ</span>}
            </div>

            {!task && (
              <div className={styles.emptyPrompt}>
                <div className={styles.emptyIcon}><Icon name="film" size={30} strokeWidth={1.6} /></div>
                <p>Hãy tải lên video ở cột bên trái và bấm <strong>Bắt đầu</strong> để theo dõi tiến trình trực tiếp tại đây.</p>
              </div>
            )}

            {isProcessing && (
              <div className={styles.progressBox}>
                <div className={styles.progressTop}>
                  <span className={styles.taskMsg}>{task.message || 'Đang xử lý…'}</span>
                  <span className={styles.pct}>{task.progress}%</span>
                </div>
                <ProgressBar value={task.progress} animated size="md" />
                <div className={styles.processNote}>
                  <Icon name="info" size={14} /> Quá trình bao gồm: Nén video → Phân tích Gemini → Tạo giọng TTS → Biên tập FFmpeg & ghép phụ đề.
                </div>
                <DurationStats
                  targetSec={task.target_sec}
                  estSec={task.est_sec}
                  ttsSec={task.tts_sec}
                  outputSec={task.output_sec}
                />
                {task.segments && task.segments.length > 0 && (
                  <ScriptPreview segments={task.segments} title="Kịch bản AI (cập nhật theo tiến trình)" />
                )}
              </div>
            )}

            {task?.status === 'failed' && (
              <div className={styles.errorBox}>
                <strong><Icon name="alert" size={14} /> Đã xảy ra lỗi khi tạo video:</strong>
                <p className={styles.error}>{task.error || task.message || 'Lỗi không xác định'}</p>
                <div className={styles.errorActions}>
                  <Button variant="secondary" size="sm" icon="refresh" onClick={resetAll}>
                    Thử lại với video mới
                  </Button>
                </div>
              </div>
            )}

            {task?.status === 'cancelled' && (
              <div className={styles.cancelledBox}>
                <p>Tác vụ đã được hủy theo yêu cầu của bạn.</p>
                <Button variant="secondary" size="sm" icon="plus" onClick={resetAll}>
                  Bắt đầu video khác
                </Button>
              </div>
            )}

            {isDone && task.result?.video_url && (
              <div className={styles.result}>
                <h4 className={styles.resultTitle}><Icon name="check-circle" size={16} /> Video hoàn chỉnh đã sẵn sàng</h4>

                <div className={styles.statsSummary}>
                  <div className={styles.summaryItem}>
                    <label>Thời lượng gốc</label>
                    <span>{formatSec(task.result.duration_original)}</span>
                  </div>
                  <div className={styles.summaryItem}>
                    <label>Thời lượng tóm tắt</label>
                    <span className={styles.highlightVal}>{formatSec(task.result.duration_output)}</span>
                  </div>
                  <div className={styles.summaryItem}>
                    <label>Số phân đoạn</label>
                    <span>{task.result.segments_count || 0} cảnh</span>
                  </div>
                </div>

                <div className={styles.playerWrapper}>
                  <VideoPlayer src={task.result.video_url} />
                </div>

                <div className={styles.resultActions}>
                  <a href={task.result.video_url} download className={styles.downloadLink}>
                    <Button variant="primary" icon="download">Tải video hoàn chỉnh (.mp4)</Button>
                  </a>
                  {task.result.srt_url && (
                    <a href={task.result.srt_url} download className={styles.downloadLink}>
                      <Button variant="secondary" icon="download">Tải phụ đề (.srt)</Button>
                    </a>
                  )}
                  <Button variant="ghost" icon="plus" onClick={resetAll}>
                    Tạo video mới
                  </Button>
                </div>

                {task.segments && task.segments.length > 0 && (
                  <ScriptPreview segments={task.segments} title="Kịch bản AI đã dùng" />
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
