import { useRef, useState } from 'react';
import styles from './ConfigPanel.module.css';
import type { Voice, Model, DetailLevel } from '@/shared/lib/types';
import { settingsService } from '@/shared/lib/services';
import { useUIStore } from '@/shared/lib/state/uiStore';

export const STYLE_OPTIONS = [
  { id: 'narrative', name: 'Điện ảnh' },
  { id: 'humorous', name: 'Hài hước' },
  { id: 'analytical', name: 'Phân tích' },
  { id: 'concise', name: 'Súc tích' },
];

const FX_OPTIONS = [
  { key: 'fx_flip', label: 'Lật gương xen kẽ', desc: 'Cảnh chẵn lật ngang, cảnh lẻ giữ nguyên' },
  { key: 'fx_zoom', label: 'Phóng to ngẫu nhiên', desc: 'Ken Burns tĩnh 125% vào 1 vị trí ngẫu nhiên' },
  { key: 'fx_speed', label: 'Tăng tốc ngẫu nhiên', desc: 'Phát nhanh 1.0–1.5× theo từng cảnh' },
  { key: 'fx_reverse', label: 'Chạy ngược shot ngắn', desc: '1/3–1/2 số shot mỗi cảnh, tối đa 2 shot liền kề' },
];

interface ConfigPanelProps {
  config: Record<string, string>;
  onChange: (c: Record<string, string>) => void;
  voices: Record<string, Voice>;
  models: Model[];
  detailLevels: Record<string, DetailLevel>;
  defaultDetail: string;
  projectDefaults?: Record<string, string | undefined>;
}

export function ConfigPanel({ config, onChange, voices, models, detailLevels, defaultDetail, projectDefaults }: ConfigPanelProps) {
  const set = (key: string, val: string) => onChange({ ...config, [key]: val });

  const addToast = useUIStore(s => s.addToast);
  const [previewing, setPreviewing] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const previewVoice = async (voiceKey?: string) => {
    const key = voiceKey || voice;
    if (!key || previewing) return;
    setPreviewing(key);
    try {
      if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
      const res = await fetch(settingsService.previewVoice(key));
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Lỗi HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const blobUrl = URL.createObjectURL(blob);
      const audio = new Audio(blobUrl);
      audioRef.current = audio;
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
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không nghe thử được giọng này' });
    }
  };

  const inherited = (key: string): boolean =>
    !!projectDefaults && !(config[key] || '') && !!projectDefaults[key];

  const voice = config.voice_id || projectDefaults?.voice_id || '';

  // ── Provider TTS: suy từ giọng đang chọn (mặc định VoiceStudio theo backend) ──
  const voiceTypeOf = (k: string) => voices[k]?.type || 'capcut';
  const provider: 'voicestudio' | 'capcut' =
    voice && voiceTypeOf(voice) === 'capcut' ? 'capcut' : 'voicestudio';
  const providerVoices = Object.entries(voices).filter(([, v]) => (v.type || 'capcut') === provider);
  const switchProvider = (p: 'voicestudio' | 'capcut') => {
    const first = Object.keys(voices).find(k => voiceTypeOf(k) === p);
    if (first) set('voice_id', first);
  };
  const model = config.model || projectDefaults?.model || '';
  const detail = config.detail || projectDefaults?.detail || defaultDetail;
  const style = config.style || projectDefaults?.style || 'narrative';
  const customMinutes = config.custom_minutes || projectDefaults?.custom_minutes || '';

  return (
    <div className={styles.panel}>
      {projectDefaults && (
        <div className={styles.defaultsNote}>Đang kế thừa từ cài đặt của phim — có thể chỉnh riêng cho tập này bên dưới</div>
      )}

      <div className={styles.row}>
        <label>Phương thức tóm tắt</label>
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={config.mode === 'api' ? styles.active : ''}
            onClick={() => set('mode', 'api')}
          >
            ⚡ API Tự Động
          </button>
          <button
            type="button"
            className={config.mode === 'manual' ? styles.active : ''}
            onClick={() => set('mode', 'manual')}
          >
            🖐 Thủ Công (AI Studio)
          </button>
        </div>
      </div>

      <div className={styles.row}>
        <label>Chế độ dựng video</label>
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={(config.edit_mode || 'smart_shot') === 'legacy' ? styles.active : ''}
            onClick={() => set('edit_mode', 'legacy')}
            title="Giữ nguyên cách cắt chia đôi truyền thống"
          >
            Cắt chia đôi
          </button>
          <button
            type="button"
            className={(config.edit_mode || 'smart_shot') === 'smart_shot' ? styles.active : ''}
            onClick={() => set('edit_mode', 'smart_shot')}
            title="Tự động nhận diện phân cảnh và khớp cảnh video theo timestamp lời bình"
          >
            Khớp cảnh thông minh (Mặc định)
          </button>
        </div>
        <span className={styles.editModeHint}>
          {(config.edit_mode || 'smart_shot') === 'smart_shot'
            ? 'Tự động phát hiện cảnh và chọn các đoạn hình khớp chuẩn xác với thời điểm lời bình.'
            : 'Cắt cảnh theo phân đoạn chia đôi mượt mà truyền thống.'}
        </span>
      </div>

      <div className={styles.row}>
        <label>Tên nhân vật</label>
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={(config.character_name_mode || 'romaji') === 'vietnamese' ? styles.active : ''}
            onClick={() => set('character_name_mode', 'vietnamese')}
            title="Lời bình chỉ dùng tên tiếng Việt (tên Việt hóa), không xen tên gốc Kanji/Romaji"
          >
            Tiếng Việt
          </button>
          <button
            type="button"
            className={(config.character_name_mode || 'romaji') === 'romaji' ? styles.active : ''}
            onClick={() => set('character_name_mode', 'romaji')}
            title="Lời bình giữ nguyên tên gốc Latin hóa (Romaji), không dịch sang tiếng Việt"
          >
            Tên gốc (Romaji)
          </button>
        </div>
        <span className={styles.editModeHint}>
          {(config.character_name_mode || 'romaji') === 'romaji'
            ? 'Giữ tên nhân vật ở dạng gốc Latin hóa (Jin, Sakura) trong lời bình.'
            : 'Dùng tên tiếng Việt (tên Việt hóa) cho nhân vật trong lời bình.'}
        </span>
      </div>

      <div className={styles.row}>
        <label>Mạch kể</label>
        <div className={styles.modeToggle}>
          <button
            type="button"
            className={(config.free_order || projectDefaults?.free_order || '0') === '0' ? styles.active : ''}
            onClick={() => set('free_order', '0')}
            title="Kể theo đúng trình tự thời gian của phim, timestamp tăng dần"
          >
            Theo thứ tự phim
          </button>
          <button
            type="button"
            className={(config.free_order || projectDefaults?.free_order || '0') === '1' ? styles.active : ''}
            onClick={() => set('free_order', '1')}
            title="AI tự do chọn cảnh, đảo mạch kể để tạo hook/cao trào hấp dẫn; timestamp là khoảng neo vị trí thật, không cần tăng dần"
          >
            Tự do đảo mạch kể
          </button>
        </div>
        <span className={styles.editModeHint}>
          {(config.free_order || projectDefaults?.free_order || '0') === '1'
            ? 'AI tự chọn cảnh quan trọng và đảo thứ tự kể thoải mái (in medias res, cliffhanger…); mỗi dòng kèm khoảng timestamp gần đúng để cắt đúng hình.'
            : 'AI kể lần lượt theo đúng tiến trình thời gian của video, phủ đều các sự kiện.'}
        </span>
      </div>

      <div className={styles.fxSection}>
        <label className={styles.fxTitle}>Hiệu ứng dựng cảnh (Khớp cảnh thông minh)</label>
        <p className={styles.editModeHint}>
          Chỉ áp dụng ở chế độ "Khớp cảnh thông minh". Mỗi cơ chế độc lập — chọn cái nào áp dụng cái đó, chọn nhiều thì chồng lên nhau.
        </p>
        <div className={styles.fxGrid}>
          {FX_OPTIONS.map(({ key, label, desc }) => {
            const inheritedFx = !!projectDefaults && !(config[key] || '') && !!projectDefaults[key];
            const checked = (config[key] || projectDefaults?.[key] || '1') !== '0';
            return (
              <label key={key} className={`${styles.fxItem}${checked ? ' ' + styles.fxItemOn : ''}`}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={e => set(key, e.target.checked ? '1' : '0')}
                />
                <div className={styles.fxBody}>
                  <div className={styles.fxName}>
                    {label}
                    {inheritedFx && <span className={styles.inheritTag}>Theo phim</span>}
                  </div>
                  <div className={styles.fxDesc}>{desc}</div>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div className={styles.row}>
        <label>
          Nhà cung cấp giọng đọc
          {inherited('voice_id') && <span className={styles.inheritTag}>Theo phim</span>}
        </label>
        <div className={styles.detailGrid}>
          <button
            type="button"
            className={`${styles.detailCard} ${provider === 'voicestudio' ? styles.selected : ''}`}
            onClick={() => switchProvider('voicestudio')}
          >
            <div className={styles.detailName}>🖥️ VoiceStudio</div>
            <div className={styles.detailMeta}>Local · voice clone · chỉ tiếng Việt</div>
          </button>
          <button
            type="button"
            className={`${styles.detailCard} ${provider === 'capcut' ? styles.selected : ''}`}
            onClick={() => switchProvider('capcut')}
          >
            <div className={styles.detailName}>☁️ CapCut</div>
            <div className={styles.detailMeta}>Cloud · nhiều giọng Việt</div>
          </button>
        </div>
      </div>

      <div className={styles.row}>
        <label>Giọng cụ thể</label>
        {providerVoices.length > 0 ? (
          <div className={styles.voiceSelectRow}>
            <select
              className={styles.select}
              value={voice}
              onChange={e => set('voice_id', e.target.value)}
              style={{ flex: 1 }}
            >
              {providerVoices.map(([key, v]) => (
                <option key={key} value={key}>{v.name}</option>
              ))}
            </select>
            <button
              type="button"
              className={styles.previewBtn}
              onClick={() => previewVoice(voice)}
              disabled={!voice || !!previewing}
              title="Nghe thử giọng đang chọn"
            >
              {previewing === voice ? '⏸ Đang phát...' : '🔊'}
            </button>
          </div>
        ) : (
          <div style={{ fontSize: '.8rem', opacity: 0.7 }}>Chưa có giọng nào cho provider này.</div>
        )}
        {voices[voice]?.type === 'voicestudio' && voice === 'vs_clone' && (
          <div style={{ fontSize: '.75rem', opacity: 0.7, marginTop: 4 }}>
            Cần tạo Profile giọng mẫu trên VoiceStudio trước (mục 🎙️ trong Cài Đặt Mặc Định Phim).
          </div>
        )}
        {voices[voice]?.type === 'voicestudio' && voice === 'vs_default' && (
          <div style={{ fontSize: '.75rem', opacity: 0.7, marginTop: 4 }}>
            Chạy local qua VoiceStudio (localhost:3900) — cần khởi động VoiceStudio trước.
          </div>
        )}
      </div>

      <div className={styles.row}>
        <label>
          Mô hình AI (Gemini)
          {inherited('model') && <span className={styles.inheritTag}>Theo phim</span>}
        </label>
        <select className={styles.select} value={model} onChange={e => set('model', e.target.value)}>
          <option value="">Mặc định hệ thống</option>
          {models.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
      </div>

      <div className={styles.row}>
        <label>
          Phong cách kịch bản
          {inherited('style') && <span className={styles.inheritTag}>Theo phim</span>}
        </label>
        <select className={styles.select} value={style} onChange={e => set('style', e.target.value)}>
          {STYLE_OPTIONS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      <div className={styles.row}>
        <label>Thời lượng / Mức độ chi tiết</label>
        <div className={styles.detailGrid}>
          {Object.entries(detailLevels).map(([key, level]) => (
            <button
              type="button"
              key={key}
              className={`${styles.detailCard} ${detail === key ? styles.selected : ''}`}
              onClick={() => set('detail', key)}
            >
              <div className={styles.detailName}>
                {level.name}
                {inherited('detail') && <span className={styles.inheritTag}>Theo phim</span>}
              </div>
              <div className={styles.detailMeta}>{level.target_words} từ · ~{Math.round(level.target_sec / 60)} phút</div>
            </button>
          ))}
          <button
            type="button"
            className={`${styles.detailCard} ${detail === 'custom' ? styles.selected : ''}`}
            onClick={() => set('detail', 'custom')}
          >
            <div className={styles.detailName}>
              Tùy chỉnh độ dài
              {inherited('detail') && <span className={styles.inheritTag}>Theo phim</span>}
            </div>
            <div className={styles.detailMeta}>Nhập số phút mong muốn</div>
          </button>
        </div>
        {detail === 'custom' && (
          <div className={styles.customMinutesRow}>
            <input
              className={styles.minutesInput}
              type="number"
              min={1}
              max={60}
              step={1}
              value={customMinutes}
              placeholder="Số phút"
              onChange={e => set('custom_minutes', e.target.value)}
            />
            <span className={styles.minutesUnit}>phút</span>
          </div>
        )}
      </div>
    </div>
  );
}
