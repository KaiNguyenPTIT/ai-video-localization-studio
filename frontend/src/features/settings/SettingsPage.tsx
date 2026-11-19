import { useState, useEffect, useCallback } from 'react';
import { settingsService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button, IconButton } from '@/shared/ui/Button';
import { Card, StatCard } from '@/shared/ui/Card';
import { Icon, type IconName } from '@/shared/ui/Icon';
import { Input } from '@/shared/ui/Field';
import { useConfig } from '@/shared/hooks/useConfig';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { TuningPanel } from '@/features/settings/admin/TuningPanel';
import { KeyManager } from '@/features/settings/KeyManager';
import { AdminGate } from '@/features/settings/admin/AdminGate';
import { ModelsManager } from '@/features/settings/admin/ModelsManager';
import { SystemPanel } from '@/features/settings/admin/SystemPanel';
import { LogsViewer } from '@/features/settings/admin/LogsViewer';
import { formatBytes } from '@/shared/lib/utils/format';
import type { Stats, StorageStats, HealthInfo } from '@/shared/lib/types';
import styles from './SettingsPage.module.css';

type Tab = 'general' | 'api' | 'voice' | 'ai' | 'processing' | 'tuning' | 'tools';

const TABS: { id: Tab; label: string; icon: IconName }[] = [
  { id: 'general', label: 'Tổng quan hệ thống', icon: 'dashboard' },
  { id: 'api', label: 'Khóa API Gemini', icon: 'key' },
  { id: 'voice', label: 'Giọng đọc (VoiceStudio / CapCut)', icon: 'waveform' },
  { id: 'ai', label: 'Mô hình & kịch bản', icon: 'sparkles' },
  { id: 'processing', label: 'Hiệu năng & tài nguyên', icon: 'cpu' },
  { id: 'tuning', label: 'Tinh chỉnh đầu ra', icon: 'wand' },
  { id: 'tools', label: 'Công cụ admin', icon: 'settings' },
];

export function SettingsPage() {
  const addToast = useUIStore(s => s.addToast);
  const { voices, models, detailLevels, defaultDetail, refreshVoices } = useConfig();
  const [tab, setTab] = useState<Tab>('api');

  const [newVoiceName, setNewVoiceName] = useState('');
  const [newVoiceFile, setNewVoiceFile] = useState<File | null>(null);
  const [newVoiceText, setNewVoiceText] = useState('');
  const [uploadingVoice, setUploadingVoice] = useState(false);

  const handleUploadVoice = async () => {
    if (!newVoiceName.trim() || !newVoiceFile) return;
    setUploadingVoice(true);
    try {
      const res = await settingsService.uploadCustomVoice(newVoiceName.trim(), newVoiceFile, newVoiceText);
      await refreshVoices();
      setNewVoiceName('');
      setNewVoiceFile(null);
      setNewVoiceText('');
      if (res.transcript_warning) {
        addToast({ type: 'error', message: res.transcript_warning });
      } else {
        addToast({ type: 'success', message: `Đã thêm giọng "${res.name}" (${res.duration}s mẫu)` });
      }
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Thêm giọng thất bại' });
    } finally {
      setUploadingVoice(false);
    }
  };

  const handleDeleteVoice = async (key: string, name: string) => {
    const id = key.replace(/^vs_custom_/, '').replace(/^omni_clone_/, '');
    if (!window.confirm(`Xóa giọng "${name}" khỏi thư viện?`)) return;
    try {
      await settingsService.deleteCustomVoice(id);
      await refreshVoices();
      addToast({ type: 'success', message: `Đã xóa giọng "${name}"` });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Xóa giọng thất bại' });
    }
  };

  const [keyCount, setKeyCount] = useState(0);

  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [storage, setStorage] = useState<StorageStats | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [cleaning, setCleaning] = useState(false);

  const [previewing, setPreviewing] = useState<string | null>(null);
  const [previewText, setPreviewText] = useState('');

  const fetchSystemData = useCallback(async () => {
    setRefreshing(true);
    try {
      const [h, st, strg] = await Promise.allSettled([
        settingsService.getHealth(),
        settingsService.getStats(),
        settingsService.getStorage(),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (st.status === 'fulfilled') setStats(st.value);
      if (strg.status === 'fulfilled') setStorage(strg.value);
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchSystemData();
  }, [fetchSystemData]);

  const handlePreviewVoice = async (key: string) => {
    if (previewing) return;
    setPreviewing(key);
    try {
      const res = await fetch(settingsService.previewVoice(key, previewText));
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Lỗi HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const audio = new Audio(blobUrl);
      audio.onended = () => {
        setPreviewing(null);
        URL.revokeObjectURL(blobUrl);
      };
      audio.onerror = () => {
        setPreviewing(null);
        URL.revokeObjectURL(blobUrl);
        addToast({ type: 'error', message: 'Không thể phát âm thanh nghe thử' });
      };
      await audio.play();
    } catch (e) {
      setPreviewing(null);
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không thể phát âm thanh nghe thử' });
    }
  };

  const handleCleanup = async () => {
    if (!window.confirm('Bạn có chắc chắn muốn dọn dẹp các tệp tạm, âm thanh TTS và phân đoạn rác? Các video thành phẩm và video gốc trong dự án sẽ được bảo vệ tuyệt đối.')) {
      return;
    }
    setCleaning(true);
    try {
      const res = await settingsService.cleanup();
      addToast({
        type: 'success',
        message: `Đã dọn dẹp ${res.freed_mb} MB và xóa ${res.deleted_count} tệp tin rác`,
      });
      fetchSystemData();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Dọn dẹp thất bại' });
    } finally {
      setCleaning(false);
    }
  };

  const vsVoices = Object.entries(voices).filter(([, v]) => v.type === 'voicestudio');
  const ccVoices = Object.entries(voices).filter(([, v]) => v.type === 'capcut');

  return (
    <div className={styles.page}>
      <PageHeader
        title="Cài đặt & cấu hình hệ thống"
        subtitle="Quản lý khóa API, giọng đọc VoiceStudio/CapCut, tham số AI và giám sát tài nguyên"
      />

      <div className={styles.layout}>
        <nav className={styles.sideNav}>
          {TABS.map(t => (
            <button
              key={t.id}
              className={`${styles.sideTab} ${tab === t.id ? styles.sideTabActive : ''}`}
              onClick={() => setTab(t.id)}
            >
              <Icon name={t.icon} size={16} className={styles.tabIcon} />
              <span className={styles.tabLabel}>{t.label}</span>
            </button>
          ))}
        </nav>

        <div className={styles.content}>
          {tab === 'general' && (
            <div className={styles.tabSection}>
              <Card>
                <div className={styles.cardHeaderWithAction}>
                  <div>
                    <h3>Tổng quan không gian sản xuất video</h3>
                    <p className={styles.desc}>Thống kê quy mô dự án và hiệu năng sản xuất hiện tại</p>
                  </div>
                  <Button variant="secondary" size="sm" icon="refresh" onClick={fetchSystemData} loading={refreshing}>
                    Cập nhật
                  </Button>
                </div>

                <div className={styles.overviewGrid}>
                  <StatCard label="Dự án phim" value={stats?.projects ?? 0} icon="film" accent="primary" />
                  <StatCard
                    label="Tập hoàn thành"
                    value={`${stats?.episodes.completed ?? 0} / ${stats?.episodes.total ?? 0}`}
                    icon="layers"
                    accent="info"
                  />
                  <StatCard label="Video xuất bản" value={stats?.output_files ?? 0} icon="video" accent="success" />
                  <StatCard label="Dung lượng thành phẩm" value={formatBytes(stats?.output_size_mb ?? 0)} icon="storage" accent="warning" />
                </div>

                <h3 className={styles.subHeading}>Quản lý dung lượng & bộ nhớ tạm</h3>
                <p className={styles.desc}>
                  Hệ thống tự động phát hiện và dọn dẹp các tệp âm thanh trung gian, phân đoạn video cắt thử
                </p>

                <div className={styles.storageGrid}>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Video thành phẩm (final)</span>
                    <span className={styles.storageVal}>{formatBytes(storage?.output ?? 0)}</span>
                  </div>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Tệp nén AI Studio (manual)</span>
                    <span className={styles.storageVal}>{formatBytes(storage?.manual ?? 0)}</span>
                  </div>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Âm thanh thuyết minh (audio)</span>
                    <span className={styles.storageVal}>{formatBytes(storage?.audio ?? 0)}</span>
                  </div>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Phân đoạn cắt ghép (segments)</span>
                    <span className={styles.storageVal}>{formatBytes(storage?.segments ?? 0)}</span>
                  </div>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Có thể giải phóng an toàn</span>
                    <span className={`${styles.storageVal} ${styles.cleanableText}`}>{formatBytes(storage?.cleanable ?? 0)}</span>
                  </div>
                  <div className={styles.storageItem}>
                    <span className={styles.storageLabel}>Tổng dung lượng sử dụng</span>
                    <span className={styles.storageValTotal}>{formatBytes(storage?.total ?? 0)}</span>
                  </div>
                </div>

                <div className={styles.actionsBar}>
                  <Button variant="danger" icon="trash" onClick={handleCleanup} loading={cleaning}>
                    Dọn dẹp tệp rác & bộ nhớ tạm ({formatBytes(storage?.cleanable ?? 0)})
                  </Button>
                </div>
              </Card>

              <Card>
                <h3>Thông tin kiến trúc ứng dụng</h3>
                <div className={styles.techList}>
                  <div className={styles.techRow}>
                    <strong>Trí tuệ nhân tạo (Vision & Script)</strong>
                    <span>Google Gemini 3.6 Flash / Google AI Studio Bridge</span>
                  </div>
                  <div className={styles.techRow}>
                    <strong>Giọng đọc thuyết minh (TTS)</strong>
                    <span>VoiceStudio local (voice clone) + CapCut ByteDance TTS (tiếng Việt)</span>
                  </div>
                  <div className={styles.techRow}>
                    <strong>Công nghệ biên tập & dựng hình</strong>
                    <span>FFmpeg Hardware Acceleration + Smart Shot Boundary Detection</span>
                  </div>
                  <div className={styles.techRow}>
                    <strong>Cơ sở dữ liệu & tác vụ</strong>
                    <span>SQLite WAL Engine + Worker Pool đa luồng</span>
                  </div>
                </div>
              </Card>
            </div>
          )}

          {tab === 'api' && (
            <Card>
              <div className={styles.cardHeaderWithAction}>
                <div>
                  <h3>Quản lý khóa API Google Gemini</h3>
                  <p className={styles.desc}>
                    Hệ thống hỗ trợ cơ chế xoay vòng (Round-Robin) tự động khi có nhiều khóa để tăng tốc độ và tránh chạm hạn ngạch (Rate Limit).
                  </p>
                </div>
                <span className={styles.keyCountBadge}>{keyCount} khóa đang sẵn sàng</span>
              </div>

              <div className={styles.guideBox}>
                <Icon name="info" size={15} />
                <span><strong>Mẹo:</strong> Hệ thống tự xoay vòng (Round-Robin) qua các key để tăng tốc và tránh rate limit. Key xếp trên được dùng trước.</span>
              </div>

              <KeyManager onCountChange={setKeyCount} />
            </Card>
          )}

          {tab === 'voice' && (
            <Card>
              <h3>Danh sách giọng đọc thuyết minh</h3>
              <p className={styles.desc}>
                Hai nhà cung cấp: <b>VoiceStudio</b> chạy local (chỉ tiếng Việt, voice clone)
                và <b>CapCut TTS</b> qua máy chủ cloud. Chọn từ dropdown và bấm loa để nghe thử.
              </p>

              <div className={styles.previewRow}>
                <Input
                  placeholder="Câu nghe thử (tối đa 200 ký tự, bỏ trống = câu demo mặc định)"
                  value={previewText}
                  onChange={e => setPreviewText(e.target.value)}
                  maxLength={200}
                />
              </div>

              {vsVoices.length > 0 && (
                <div className={styles.voiceGroup}>
                  <div className={styles.voiceGroupTitle}>
                    <Icon name="server" size={15} /> VoiceStudio (local · tiếng Việt)
                  </div>
                  <div className={styles.voiceGrid}>
                    {vsVoices.map(([key, v]) => (
                      <div key={key} className={styles.voiceCard}>
                        <div className={styles.voiceMeta}>
                          <div className={styles.voiceName}>{v.name}</div>
                          <code className={styles.voiceKey}>
                            {key}{v.custom && !v.builtin ? ' · của bạn' : v.builtin ? ' · dựng sẵn' : ''}
                          </code>
                        </div>
                        <div className={styles.voiceActions}>
                          <IconButton
                            icon="volume"
                            label={`Nghe thử ${v.name}`}
                            size="sm"
                            loading={previewing === key}
                            disabled={!!previewing && previewing !== key}
                            onClick={() => handlePreviewVoice(key)}
                          />
                          {v.custom && !v.builtin && (
                            <IconButton
                              icon="trash"
                              label={`Xóa giọng ${v.name}`}
                              variant="danger"
                              size="sm"
                              onClick={() => handleDeleteVoice(key, v.name)}
                            />
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {ccVoices.length > 0 && (
                <div className={styles.voiceGroup}>
                  <div className={styles.voiceGroupTitle}>
                    <Icon name="sparkles" size={15} /> CapCut TTS (cloud · tiếng Việt)
                  </div>
                  <div className={styles.voiceGrid}>
                    {ccVoices.map(([key, v]) => (
                      <div key={key} className={styles.voiceCard}>
                        <div className={styles.voiceMeta}>
                          <div className={styles.voiceName}>{v.name}</div>
                          <code className={styles.voiceKey}>{key}</code>
                        </div>
                        <div className={styles.voiceActions}>
                          <IconButton
                            icon="volume"
                            label={`Nghe thử ${v.name}`}
                            size="sm"
                            loading={previewing === key}
                            disabled={!!previewing && previewing !== key}
                            onClick={() => handlePreviewVoice(key)}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              <div className={styles.addVoiceBox}>
                <div className={styles.addVoiceTitle}><Icon name="plus" size={14} /> Thêm giọng VoiceStudio Clone</div>
                <p className={styles.addVoiceHint}>
                  Tải lên 1 đoạn mẫu (3-10s, cùng người nói) — hệ thống tạo profile clone mới qua VoiceStudio.
                  Transcript tùy chọn, bỏ trống nếu không chắc.
                </p>
                <div className={styles.addVoiceRow}>
                  <Input
                    className={styles.voiceNameInput}
                    placeholder='Tên giọng (vd "Chị Lan")'
                    value={newVoiceName}
                    onChange={e => setNewVoiceName(e.target.value)}
                  />
                  <input
                    className={styles.fileInput}
                    type="file"
                    accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.opus"
                    onChange={e => setNewVoiceFile(e.target.files?.[0] || null)}
                  />
                  <Input
                    className={styles.voiceTextInput}
                    placeholder="Transcript mẫu (tùy chọn)"
                    value={newVoiceText}
                    onChange={e => setNewVoiceText(e.target.value)}
                  />
                  <Button
                    size="sm"
                    icon="plus"
                    onClick={handleUploadVoice}
                    disabled={!newVoiceName.trim() || !newVoiceFile || uploadingVoice}
                    loading={uploadingVoice}
                  >
                    Thêm giọng
                  </Button>
                </div>
              </div>
            </Card>
          )}

          {tab === 'ai' && (
            <Card>
              <h3>Mô hình trí tuệ nhân tạo (Gemini Multimodal)</h3>
              <p className={styles.desc}>
                Các mô hình ngôn ngữ lớn được cấu hình để xem và phân tích trực quan từng cảnh quay của anime.
              </p>

              <div className={styles.modelList}>
                {models.map(m => (
                  <div key={m.id} className={styles.modelItem}>
                    <div className={styles.modelInfo}>
                      <span className={styles.modelName}>{m.name}</span>
                      <code className={styles.modelId}>{m.id}</code>
                    </div>
                    {m.id.includes('flash') && (
                      <span className={styles.speedBadge}><Icon name="bolt" size={12} /> Tốc độ cao</span>
                    )}
                  </div>
                ))}
              </div>

              <h3 className={styles.subHeading}>Mức độ chi tiết kịch bản (Detail Levels)</h3>
              <p className={styles.desc}>
                Quy định dung lượng từ ngữ và độ dài dự kiến của video tóm tắt đầu ra.
              </p>

              <div className={styles.detailList}>
                {Object.entries(detailLevels).map(([key, level]) => (
                  <div key={key} className={styles.detailItem}>
                    <div className={styles.detailMain}>
                      <strong>{level.name}</strong>
                      <span className={styles.detailSub}>
                        Mục tiêu: ~{level.target_words} từ · Khoảng {Math.round(level.target_sec / 60)} phút video
                      </span>
                    </div>
                    {key === defaultDetail && <span className={styles.defaultBadge}>Mặc định</span>}
                  </div>
                ))}
              </div>
            </Card>
          )}

          {tab === 'processing' && (
            <Card>
              <div className={styles.cardHeaderWithAction}>
                <div>
                  <h3>Hiệu năng & trạng thái xử lý nền</h3>
                  <p className={styles.desc}>
                    Theo dõi các luồng xử lý song song và trạng thái hàng đợi video trong hệ thống.
                  </p>
                </div>
                <Button size="sm" variant="secondary" icon="refresh" onClick={fetchSystemData} loading={refreshing}>
                  Cập nhật
                </Button>
              </div>

              {health && (
                <div className={styles.healthGrid}>
                  <div className={styles.healthItem}>
                    <label>Luồng xử lý đồng thời (Workers)</label>
                    <span className={styles.healthValPrimary}>{health.workers} luồng</span>
                    <p className={styles.healthSub}>Tự động scale theo số lượng API keys</p>
                  </div>
                  <div className={styles.healthItem}>
                    <label>Hàng đợi hiện tại (Queue Depth)</label>
                    <span className={styles.healthVal}>{health.queue_depth} tác vụ</span>
                    <p className={styles.healthSub}>Số lượng tập phim đang xếp hàng chờ</p>
                  </div>
                  <div className={styles.healthItem}>
                    <label>Số lượng khóa API hoạt động</label>
                    <span className={styles.healthVal}>{health.gemini_keys} khóa</span>
                    <p className={styles.healthSub}>Xoay vòng tải cho Gemini Studio API</p>
                  </div>
                  <div className={styles.healthItem}>
                    <label>Mô hình mặc định hiện tại</label>
                    <span className={styles.healthValModel}>{health.model}</span>
                    <p className={styles.healthSub}>Được nạp sẵn từ cấu hình backend</p>
                  </div>
                </div>
              )}

              <h3 className={styles.subHeading}>Trạng thái lưu trữ & bộ nhớ ổ đĩa</h3>
              <div className={styles.storageGrid}>
                <div className={styles.storageItem}>
                  <span className={styles.storageLabel}>Video đầu ra thành phẩm (final)</span>
                  <span className={styles.storageVal}>{formatBytes(storage?.output ?? 0)}</span>
                </div>
                <div className={styles.storageItem}>
                  <span className={styles.storageLabel}>Video nén phục vụ AI Studio</span>
                  <span className={styles.storageVal}>{formatBytes(storage?.manual ?? 0)}</span>
                </div>
                <div className={styles.storageItem}>
                  <span className={styles.storageLabel}>Tệp âm thanh lồng tiếng TTS</span>
                  <span className={styles.storageVal}>{formatBytes(storage?.audio ?? 0)}</span>
                </div>
                <div className={styles.storageItem}>
                  <span className={styles.storageLabel}>Các cảnh cắt ghép trung gian</span>
                  <span className={styles.storageVal}>{formatBytes(storage?.segments ?? 0)}</span>
                </div>
              </div>
            </Card>
          )}

          {tab === 'tuning' && (
            <Card>
              <div className={styles.cardHeaderWithAction}>
                <div>
                  <h3>Tinh chỉnh thông số đầu ra (Admin)</h3>
                  <p className={styles.desc}>
                    Toàn bộ thông số hệ thống ảnh hưởng trực tiếp đến video đầu ra — mã hóa, dựng cảnh, hiệu ứng — đồng bộ 2 chiều với backend.
                  </p>
                </div>
              </div>
              <TuningPanel />
            </Card>
          )}

          {tab === 'tools' && (
            <div className={styles.tabSection}>
              <AdminGate>
                <Card>
                  <h3>Quản lý model Gemini tùy chỉnh</h3>
                  <p className={styles.desc}>Thêm/sửa/xóa model AI dùng để viết kịch bản. Model đang dùng được đánh dấu riêng.</p>
                  <ModelsManager />
                </Card>
                <Card>
                  <h3>Thông tin hệ thống & Restart</h3>
                  <p className={styles.desc}>Phiên bản phần mềm, GPU, RAM, ổ đĩa và khởi động lại server khi cần.</p>
                  <SystemPanel />
                </Card>
                <Card>
                  <h3>Nhật ký server</h3>
                  <p className={styles.desc}>Xem log vận hành mới nhất để chẩn đoán lỗi.</p>
                  <LogsViewer />
                </Card>
              </AdminGate>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
