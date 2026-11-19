import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { projectService, episodeService, aiStudioService } from '@/shared/lib/services';
import type { AIStudioAccountInfo } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { Icon } from '@/shared/ui/Icon';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { SegmentedControl } from '@/shared/ui/SegmentedControl';
import { EmptyState } from '@/shared/ui/EmptyState';
import { VideoPlayer } from '@/features/library/VideoPlayer';
import { validateScript } from '@/shared/lib/utils/scriptValidation';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { episodeLabel } from '@/shared/lib/utils/format';
import type { Episode } from '@/shared/lib/types';
import styles from './AIStudioPage.module.css';

interface AwaitingEpisode extends Episode {
  project_id: string;
  project_name?: string;
}

const STEP_LABELS = [
  '1. Nén video',
  '2. Lời nhắc (prompt)',
  '3. AI Studio',
  '4. Kịch bản lời bình',
  '5. Dựng thành phẩm',
];

type FilterTab = 'all' | 'awaiting' | 'running' | 'completed' | 'failed';

// ── Thẻ tài khoản Google AI Studio ───────────────────────────────────
function AccountStatusCard() {
  const addToast = useUIStore(s => s.addToast);
  const [account, setAccount] = useState<AIStudioAccountInfo | null>(null);
  const [checking, setChecking] = useState(false);
  const [opening, setOpening] = useState(false);
  const [closing, setClosing] = useState(false);

  const checkAccount = useCallback(async (silent = false) => {
    if (!silent) setChecking(true);
    try {
      const info = await aiStudioService.getAccount();
      setAccount(info);
    } catch {
      setAccount(null);
    } finally {
      if (!silent) setChecking(false);
    }
  }, []);

  useEffect(() => {
    checkAccount(true);
    const t = setInterval(() => checkAccount(true), 10000);
    return () => clearInterval(t);
  }, [checkAccount]);

  const handleOpenLogin = async () => {
    setOpening(true);
    try {
      const res = await aiStudioService.openLogin();
      addToast({ type: 'success', message: res.message });
      setTimeout(() => checkAccount(true), 2500);
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không mở được Chrome' });
    } finally {
      setOpening(false);
    }
  };

  const handleCloseBrowser = async () => {
    setClosing(true);
    try {
      const res = await aiStudioService.closeBrowser();
      addToast({
        type: res.closed ? 'success' : 'info',
        message: res.closed ? 'Đã đóng Chrome thành công.' : 'Chrome không đang chạy hoặc đã đóng rồi.',
      });
      setTimeout(() => checkAccount(true), 800);
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không đóng được Chrome' });
    } finally {
      setClosing(false);
    }
  };

  const isRunning = account?.is_running || false;
  const loggedIn = account?.logged_in || false;
  const email = account?.email;
  const fullName = account?.full_name;
  const pictureUrl = account?.picture_url;
  const anyBusy = checking || opening || closing;

  return (
    <div className={styles.accountSection}>
      <div className={styles.accountCard}>
        <div className={styles.accountHeader}>
          <div className={styles.accountProfile}>
            <div className={styles.avatarWrapper}>
              {pictureUrl ? (
                <img
                  className={styles.avatarImg}
                  src={pictureUrl}
                  alt={fullName || 'Google Account'}
                  referrerPolicy="no-referrer"
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              ) : (
                <span className={styles.avatarPlaceholder}>
                  <Icon name="users" size={24} />
                </span>
              )}
            </div>
            <div className={styles.accountInfo}>
              <div className={styles.accountTitleRow}>
                <span className={styles.accountTitle}>Tài khoản Google AI Studio</span>
                {loggedIn ? (
                  <span className={styles.badgeSuccess}>
                    <span className={styles.statusDotGreen} /> Đã đăng nhập
                  </span>
                ) : (
                  <span className={styles.badgeWarning}>
                    <span className={styles.statusDotYellow} /> Chưa đăng nhập
                  </span>
                )}
                {isRunning && (
                  <span className={styles.badgeRunning}><Icon name="activity" size={11} /> Chrome đang mở</span>
                )}
              </div>
              <div className={styles.accountSubtitle}>
                {loggedIn
                  ? <>{fullName && <strong>{fullName}</strong>} &nbsp;{email}</>
                  : 'Bấm "Mở Chrome đăng nhập" để kết nối tài khoản Google cho chế độ tự động AI Studio.'}
              </div>
            </div>
          </div>

          <div className={styles.accountActions}>
            <Button
              size="sm"
              variant="secondary"
              icon="refresh"
              onClick={() => checkAccount(false)}
              loading={checking}
              disabled={anyBusy}
              title="Kiểm tra lại trạng thái tài khoản"
            >
              Kiểm tra
            </Button>
            <Button
              size="sm"
              icon="link"
              variant={loggedIn ? 'secondary' : 'primary'}
              onClick={handleOpenLogin}
              loading={opening}
              disabled={anyBusy}
              title={loggedIn
                ? 'Mở Chrome để kiểm tra hoặc đổi tài khoản'
                : 'Mở Chrome để đăng nhập tài khoản Google (an toàn, không có cờ bot)'}
            >
              {loggedIn ? 'Mở Chrome / Kiểm tra' : 'Mở Chrome đăng nhập'}
            </Button>
            {isRunning && (
              <Button
                size="sm"
                variant="danger"
                icon="close"
                onClick={handleCloseBrowser}
                loading={closing}
                disabled={anyBusy}
                title="Đóng Chrome trước khi chạy tác vụ tự động"
              >
                Đóng Chrome
              </Button>
            )}
          </div>
        </div>

        <div className={styles.accountTip}>
          <Icon name="info" size={15} />
          <span><strong>Hướng dẫn:</strong> Bấm <em>Mở Chrome đăng nhập</em> → Đăng nhập tài khoản Google trong cửa sổ Chrome → Đóng Chrome (hoặc bấm nút <em>Đóng Chrome</em>) → Bấm <em>Chạy tự động AI Studio</em> trong thẻ tập phim bên dưới. Chrome sẽ tự mở lại với cổng điều khiển để thực hiện tác vụ.</span>
        </div>
      </div>
    </div>
  );
}

// ── Trang chính AIStudioPage ─────────────────────────────────────────
export function AIStudioPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const [eps, setEps] = useState<AwaitingEpisode[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<FilterTab>('all');

  const load = useCallback(async () => {
    try {
      if (projectId) {
        const p = await projectService.get(projectId);
        setEps(
          (p.episodes || [])
            .filter(e => e.options?.mode === 'manual')
            .map(e => ({ ...e, project_id: p.id, project_name: p.name }))
        );
      } else {
        const projects = await projectService.list();
        const all: AwaitingEpisode[] = [];
        for (const p of projects) {
          for (const ep of p.episodes || []) {
            if (ep.options?.mode === 'manual') {
              all.push({ ...ep, project_id: p.id, project_name: p.name });
            }
          }
        }
        setEps(all);
      }
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [load]);

  const ordered = useMemo(() => {
    const rank: Record<string, number> = {
      awaiting_result: 0,
      awaiting: 0,
      pending: 1,
      running: 2,
      queueing: 2,
      completed: 3,
      failed: 4,
      cancelled: 5,
    };
    return [...eps].sort(
      (a, b) =>
        (rank[a.status] ?? 9) - (rank[b.status] ?? 9) ||
        a.filename.localeCompare(b.filename)
    );
  }, [eps]);

  const isAwaiting = (e: AwaitingEpisode) =>
    ['awaiting', 'awaiting_result'].includes(e.status) || (!e.manual_prompt && e.status === 'pending');

  const counts = useMemo(() => ({
    all: ordered.length,
    awaiting: ordered.filter(isAwaiting).length,
    running: ordered.filter(e => ['running', 'queueing'].includes(e.status)).length,
    completed: ordered.filter(e => e.status === 'completed').length,
    failed: ordered.filter(e => ['failed', 'cancelled'].includes(e.status)).length,
  }), [ordered]);

  const filtered = useMemo(() => {
    if (filter === 'awaiting') return ordered.filter(isAwaiting);
    if (filter === 'running') return ordered.filter(e => ['running', 'queueing'].includes(e.status));
    if (filter === 'completed') return ordered.filter(e => e.status === 'completed');
    if (filter === 'failed') return ordered.filter(e => ['failed', 'cancelled'].includes(e.status));
    return ordered;
  }, [ordered, filter]);

  return (
    <div className={styles.page}>
      <PageHeader
        title="Không gian làm việc Google AI Studio"
        subtitle="Quy trình bán tự động: Nén video nhẹ → Tạo prompt tối ưu → Lấy kịch bản từ AI Studio → Dựng video với giọng đọc TTS"
      />

      <AccountStatusCard />

      <div className={styles.filterBar}>
        <SegmentedControl<FilterTab>
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'Tất cả', count: counts.all },
            { value: 'awaiting', label: 'Chờ kịch bản', icon: 'clock', count: counts.awaiting },
            { value: 'running', label: 'Đang xử lý', icon: 'bolt', count: counts.running },
            { value: 'completed', label: 'Đã hoàn thành', icon: 'check-circle', count: counts.completed },
            { value: 'failed', label: 'Thất bại / Hủy', icon: 'alert', count: counts.failed },
          ]}
        />

        <Button size="sm" variant="secondary" icon="refresh" onClick={load} loading={loading}>
          Làm mới danh sách
        </Button>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          glyph="sparkles"
          title={
            ordered.length === 0
              ? 'Chưa có tập phim nào ở chế độ Thủ công (AI Studio)'
              : 'Không có tập phim nào khớp với bộ lọc đã chọn'
          }
          description={
            ordered.length === 0
              ? 'Hãy mở một Dự án phim, thêm tập và chọn chế độ "Thủ công (AI Studio)" để sử dụng quy trình này.'
              : 'Thử chuyển sang tab bộ lọc "Tất cả" để xem toàn bộ danh sách tập.'
          }
        />
      ) : (
        <div className={styles.list}>
          {filtered.map(ep => (
            <EpisodeWorkspace
              key={`${ep.project_id}-${ep.id}`}
              ep={ep}
              onRefresh={load}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface StepState {
  active: boolean;
  done: boolean;
}

function computeSteps(ep: AwaitingEpisode): StepState[] {
  const hasPrompt = !!ep.manual_prompt;
  const hasCompressed = !!ep.manual_compressed_url;
  const hasScript = !!ep.manual_result;
  const rendering = ['queueing', 'running'].includes(ep.status) && hasScript;
  const autoRunning = ep.status === 'running' && !hasScript;

  return [
    { active: !hasPrompt && ep.status === 'pending', done: hasPrompt && hasCompressed },
    { active: false, done: hasPrompt },
    { active: autoRunning, done: hasScript },
    { active: !hasScript && ['awaiting_result', 'awaiting'].includes(ep.status), done: hasScript },
    { active: rendering, done: ep.status === 'completed' },
  ];
}

function EpisodeWorkspace({ ep, onRefresh }: { ep: AwaitingEpisode; onRefresh: () => void }) {
  const navigate = useNavigate();
  const addToast = useUIStore(s => s.addToast);
  const [script, setScript] = useState(ep.manual_result || '');
  const [validation, setValidation] = useState<ReturnType<typeof validateScript> | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [autoRunning, setAutoRunning] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [openingFolder, setOpeningFolder] = useState(false);
  const [copiedPrompt, setCopiedPrompt] = useState(false);
  const [promptOpen, setPromptOpen] = useState(false);
  const isActionBusy = preparing || autoRunning || submitting || cancelling || retrying;

  const steps = useMemo(
    () => computeSteps(ep),
    [ep.status, ep.manual_prompt, ep.manual_compressed_url, ep.manual_result]
  );

  useEffect(() => {
    if (ep.manual_result && !script.trim()) setScript(ep.manual_result);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ep.manual_result]);

  const label = episodeLabel(ep.filename, 0);

  const handlePrepare = async () => {
    if (isActionBusy) return;
    setPreparing(true);
    try {
      await episodeService.manualPrepare(ep.project_id, ep.id);
      addToast({ type: 'success', message: 'Đã nén video tối ưu và tạo xong lời nhắc (prompt)' });
      onRefresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Nén video thất bại' });
    } finally {
      setPreparing(false);
    }
  };

  const handleAutoRun = async () => {
    if (isActionBusy) return;
    setAutoRunning(true);
    try {
      await episodeService.manualRun(ep.project_id, ep.id);
      addToast({
        type: 'info',
        message: 'Đã kích hoạt tự động AI Studio! Cửa sổ Chrome riêng sẽ tự thao tác.',
      });
      onRefresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Tự động hóa thất bại' });
    } finally {
      setAutoRunning(false);
    }
  };

  const handleOpenFolder = async () => {
    setOpeningFolder(true);
    try {
      await episodeService.manualFolder(ep.project_id, ep.id);
      addToast({ type: 'success', message: 'Đã mở thư mục data/media/manual trên máy tính' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không mở được thư mục' });
    } finally {
      setOpeningFolder(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm(`Bạn có chắc chắn muốn dừng tác vụ của tập "${ep.filename}"?`)) return;
    setCancelling(true);
    try {
      await episodeService.cancel(ep.project_id, ep.id);
      addToast({ type: 'warning', message: 'Đã hủy tác vụ theo yêu cầu' });
      onRefresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không thể hủy' });
    } finally {
      setCancelling(false);
    }
  };

  const handleRetry = async () => {
    setRetrying(true);
    try {
      await episodeService.retry(ep.project_id, ep.id);
      addToast({ type: 'info', message: 'Đã đặt lại tập phim — bắt đầu quy trình mới' });
      onRefresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lỗi khi đặt lại tập' });
    } finally {
      setRetrying(false);
    }
  };

  const handleCopyPrompt = async () => {
    if (!ep.manual_prompt) return;
    await navigator.clipboard.writeText(ep.manual_prompt);
    setCopiedPrompt(true);
    setTimeout(() => setCopiedPrompt(false), 2000);
  };

  const handleValidate = () => setValidation(validateScript(script));

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await episodeService.manualSubmit(ep.project_id, ep.id, script);
      addToast({ type: 'success', message: 'Đã nhận kịch bản — đang bắt đầu dựng video hoàn chỉnh…' });
      onRefresh();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Gửi kịch bản thất bại' });
    } finally {
      setSubmitting(false);
    }
  };

  const downloadPrompt = () => {
    if (!ep.manual_prompt) return;
    const blob = new Blob([ep.manual_prompt], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `prompt_${ep.filename}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const rendering = ['queueing', 'running'].includes(ep.status) && !!ep.manual_result;
  const isAutoRunning = ep.status === 'running' && !ep.manual_result;
  const awaitingScript = ['awaiting_result', 'awaiting'].includes(ep.status) && !ep.manual_result;

  return (
    <Card className={styles.card}>
      <div className={styles.cardHeader}>
        <div className={styles.epTitle}>
          <div className={styles.titleRow}>
            <button
              type="button"
              className={styles.viewBtn}
              onClick={() => navigate(`/projects/${ep.project_id}`)}
              title="Đến trang quản lý tập phim"
            >
              <Icon name="film" size={15} /> {label}
            </button>
            {ep.project_name && (
              <button
                type="button"
                className={styles.projectLink}
                onClick={() => navigate(`/projects/${ep.project_id}`)}
              >
                (Thuộc phim: {ep.project_name})
              </button>
            )}
          </div>
          <span className={styles.fileName}><Icon name="folder" size={13} /> Tệp gốc: {ep.filename}</span>
        </div>

        <div className={styles.statusActions}>
          <StatusBadge status={ep.status} size="md" />
          {(rendering || isAutoRunning) && (
            <Button
              size="sm"
              variant="danger"
              icon="close"
              onClick={handleCancel}
              loading={cancelling}
              disabled={isActionBusy}
              title="Dừng tác vụ này"
            >
              Dừng
            </Button>
          )}
          {['completed', 'failed', 'cancelled'].includes(ep.status) && (
            <Button
              size="sm"
              variant="secondary"
              icon="refresh"
              onClick={handleRetry}
              loading={retrying}
              disabled={isActionBusy}
              title="Làm lại từ đầu với kịch bản mới"
            >
              Làm lại
            </Button>
          )}
        </div>
      </div>

      <Stepper steps={steps} labels={STEP_LABELS} />

      {ep.message && <div className={styles.message}><Icon name="info" size={13} /> {ep.message}</div>}

      <div className={styles.content}>
        {!ep.manual_prompt && ep.status === 'pending' && (
          <section className={styles.stepPanel}>
            <div>
              <h4>Bước 1 · Chuẩn bị &amp; nén video tối ưu</h4>
              <p className={styles.panelHint}>
                Hệ thống sẽ nén video thành bản nhẹ (480p, giữ audio) và tự động tạo lời nhắc kịch bản tiêu chuẩn cho Google AI Studio.
                Lần đầu mất ~1 phút (chạy trên card rời), các lần sau dùng bản nén có sẵn nên xong ngay.
              </p>
            </div>
            <Button onClick={handlePrepare} loading={preparing} disabled={isActionBusy} size="md" icon="bolt">
              Bắt đầu nén video &amp; tạo prompt
            </Button>
          </section>
        )}

        {ep.manual_prompt && !rendering && ep.status !== 'completed' && (
          <section className={styles.stepPanelColumn}>
            <div className={styles.promptHeader}>
              <div>
                <h4>Bước 2 · Lời nhắc (prompt) đã sẵn sàng</h4>
                {ep.target_words && (
                  <span className={styles.promptMeta}>
                    Mục tiêu: ~{ep.target_words} từ · Khoảng {ep.num_segments} phân đoạn ·{' '}
                    {ep.manual_compressed_url ? 'Đã có video nén sẵn' : 'Đang xử lý nén…'}
                  </span>
                )}
              </div>
              <div className={styles.promptActions}>
                <Button size="sm" variant="ghost" icon="eye" onClick={() => setPromptOpen(o => !o)}>
                  {promptOpen ? 'Ẩn lời nhắc' : 'Xem chi tiết lời nhắc'}
                </Button>
                <Button size="sm" variant="secondary" icon="copy" onClick={handleCopyPrompt}>
                  {copiedPrompt ? 'Đã sao chép!' : 'Sao chép prompt'}
                </Button>
                <Button size="sm" variant="ghost" icon="download" onClick={downloadPrompt}>
                  Tải file .txt
                </Button>
              </div>
            </div>

            {promptOpen && (
              <textarea readOnly value={ep.manual_prompt} className={styles.promptText} rows={8} />
            )}

            <div className={styles.methodsContainer}>
              <div className={styles.autoMethodBox}>
                <div className={styles.methodHeader}>
                  <span className={styles.methodBadge}><Icon name="bolt" size={12} /> Khuyên dùng</span>
                  <strong>Cách 1: Tự động thao tác 1-chạm (Playwright CDP)</strong>
                </div>
                <p className={styles.methodDesc}>
                  Hệ thống tự động điều khiển trình duyệt Chrome riêng, tải video nén lên Google AI Studio, dán prompt, bấm Run và trích xuất kịch bản hoàn toàn tự động.
                </p>
                <div className={styles.autoBtnRow}>
                  <Button
                    size="md"
                    icon="bolt"
                    onClick={handleAutoRun}
                    loading={autoRunning || isAutoRunning}
                    disabled={isActionBusy}
                    className={styles.autoRunBtn}
                  >
                    {isAutoRunning ? 'Đang tự động thao tác trên AI Studio…' : 'Chạy tự động AI Studio (1-chạm)'}
                  </Button>
                </div>
              </div>

              <div className={styles.manualMethodBox}>
                <div className={styles.methodHeader}>
                  <strong><Icon name="wand" size={14} /> Cách 2: Thao tác thủ công</strong>
                </div>
                <p className={styles.methodDesc}>
                  Tự mở Google AI Studio, đính kèm file video nén từ máy tính, dán prompt và sau đó dán kết quả kịch bản vào ô bên dưới.
                </p>

                <div className={styles.toolActionsRow}>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon="folder"
                    onClick={handleOpenFolder}
                    loading={openingFolder}
                    disabled={isActionBusy}
                  >
                    Mở thư mục chứa video nén
                  </Button>
                  <a href="https://aistudio.google.com" target="_blank" rel="noreferrer">
                    <Button size="sm" variant="ghost" icon="external">
                      Mở Google AI Studio
                    </Button>
                  </a>
                </div>

                <label className={styles.inputLabel}>
                  Dán kết quả kịch bản nhận được từ AI Studio vào đây:
                </label>
                <textarea
                  className={styles.scriptInput}
                  placeholder="00:00:01,500&#9;Lời bình cho phân cảnh 1&#10;00:00:07,000&#9;Lời bình cho phân cảnh 2"
                  value={script}
                  onChange={e => {
                    setScript(e.target.value);
                    setValidation(null);
                  }}
                  disabled={isActionBusy}
                  rows={8}
                />

                <div className={styles.validation}>
                  {validation?.valid && (
                    <span className={styles.valid}>
                      <Icon name="check" size={13} strokeWidth={3} /> Cú pháp hợp lệ: {validation.segments} phân cảnh được nhận dạng
                    </span>
                  )}
                  {validation?.errors.map((err, i) => (
                    <span key={i} className={styles.invalid}>
                      <Icon name="close" size={13} /> {err}
                    </span>
                  ))}
                  {validation?.warnings.map((w, i) => (
                    <span key={i} className={styles.warn}>
                      <Icon name="alert" size={13} /> {w}
                    </span>
                  ))}
                </div>

                <div className={styles.submitActions}>
                  <Button
                    variant="secondary"
                    size="sm"
                    icon="check-circle"
                    onClick={handleValidate}
                    disabled={!script.trim() || isActionBusy}
                  >
                    Kiểm tra cú pháp
                  </Button>
                  <Button
                    size="md"
                    icon="play"
                    onClick={handleSubmit}
                    loading={submitting}
                    disabled={!script.trim() || isActionBusy}
                  >
                    Gửi kịch bản &amp; bắt đầu dựng video
                  </Button>
                </div>
              </div>
            </div>

            {awaitingScript && (
              <div className={styles.awaitingHint}>
                <Icon name="clock" size={14} />
                <span><strong>Trạng thái:</strong> Đang chờ kịch bản. Bạn có thể bấm <strong>"Chạy tự động AI Studio"</strong> hoặc dán kịch bản thủ công ở trên.</span>
              </div>
            )}
          </section>
        )}

        {rendering && (
          <section className={styles.stepPanel}>
            <div className={styles.progressHeader}>
              <div>
                <h4>Bước 5 · Đang dựng video thành phẩm (FFmpeg &amp; TTS)</h4>
                <p className={styles.panelHint}>{ep.message || 'Đang biên tập video tóm tắt…'}</p>
              </div>
              <span className={styles.pct}>{ep.progress}%</span>
            </div>
            <ProgressBar value={ep.progress} animated size="md" />
          </section>
        )}

        {ep.status === 'completed' && (
          <section className={styles.resultPanel}>
            <div className={styles.resultHeader}>
              <h4><Icon name="check-circle" size={16} /> Video tóm tắt đã hoàn thành</h4>
              <div className={styles.studioActions}>
                {ep.result_url && (
                  <a href={ep.result_url} download>
                    <Button size="sm" variant="primary" icon="download">Tải video hoàn chỉnh (.mp4)</Button>
                  </a>
                )}
                {ep.srt_url && (
                  <a href={ep.srt_url} download>
                    <Button size="sm" variant="secondary" icon="download">Tải phụ đề (.srt)</Button>
                  </a>
                )}
                <Button size="sm" variant="ghost" icon="refresh" onClick={handleRetry} loading={retrying}>
                  Tạo lại kịch bản mới
                </Button>
              </div>
            </div>

            {ep.result_url ? (
              <div className={styles.playerWrap}>
                <VideoPlayer src={ep.result_url} />
              </div>
            ) : (
              <p className={styles.panelHint}>
                Đã hoàn thành xử lý. Bạn có thể xem và tải video trong mục Thư viện.
              </p>
            )}

            {ep.manual_result && (
              <div className={styles.completedScript}>
                <Button size="sm" variant="ghost" icon="eye" onClick={() => setPromptOpen(o => !o)}>
                  {promptOpen ? 'Ẩn kịch bản đã dùng' : 'Xem kịch bản lời bình đã dùng'}
                </Button>
                {promptOpen && (
                  <textarea readOnly value={ep.manual_result} className={styles.promptText} rows={8} />
                )}
              </div>
            )}
          </section>
        )}

        {ep.status === 'failed' && (
          <section className={`${styles.stepPanel} ${styles.errorPanel}`}>
            <div>
              <h4><Icon name="alert" size={16} /> Xử lý thất bại</h4>
              <p className={styles.errorDesc}>{ep.error || ep.message || 'Lỗi không xác định'}</p>
            </div>
            <div className={styles.errorActions}>
              <Button variant="secondary" icon="refresh" onClick={handleRetry} loading={retrying}>
                Thử lại
              </Button>
            </div>
          </section>
        )}

        {ep.status === 'cancelled' && (
          <section className={styles.stepPanel}>
            <div>
              <h4><Icon name="alert" size={16} /> Tác vụ đã bị hủy</h4>
              <p className={styles.panelHint}>Tập phim này đã được dừng xử lý theo yêu cầu của bạn.</p>
            </div>
            <Button variant="secondary" icon="refresh" onClick={handleRetry} loading={retrying}>
              Khởi động lại
            </Button>
          </section>
        )}
      </div>
    </Card>
  );
}

function Stepper({ steps, labels }: { steps: StepState[]; labels: string[] }) {
  return (
    <ol className={styles.stepper} aria-label="Tiến độ quy trình">
      {steps.map((s, i) => (
        <li
          key={labels[i]}
          className={`${styles.step} ${s.done ? styles.stepDone : ''} ${s.active ? styles.stepActive : ''}`}
        >
          <span className={styles.stepDot} aria-hidden="true">
            {s.done ? <Icon name="check" size={12} strokeWidth={3} /> : i + 1}
          </span>
          <span className={styles.stepLabel}>{labels[i]}</span>
          {i < steps.length - 1 && <span className={styles.stepLine} aria-hidden="true" />}
        </li>
      ))}
    </ol>
  );
}
