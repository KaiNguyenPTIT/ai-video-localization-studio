import { useCallback, useEffect, useState } from 'react';
import { settingsService } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './KeyManager.module.css';

interface KeyStatus {
  state: 'untested' | 'testing' | 'ok' | 'fail';
  detail?: string;
}

function mask(k: string): string {
  return k.length > 12 ? `${k.slice(0, 6)}...${k.slice(-4)}` : '***';
}

function splitKeys(raw: string): string[] {
  return raw
    .split(/[\n,;]+/)
    .map(k => k.trim().replace(/^["']+|["']+$/g, '').trim())
    .filter(Boolean);
}

/** Quản lý key Gemini theo từng dòng: thêm, kiểm tra sống/chết, lên/xuống,
 *  xóa, rồi lưu một lần. Thay thế ô textarea dán cả đống cũ. */
export function KeyManager({ onCountChange }: { onCountChange?: (n: number) => void }) {
  const addToast = useUIStore(s => s.addToast);
  const [keys, setKeys] = useState<string[]>([]);
  const [snapshot, setSnapshot] = useState<string[]>([]);
  const [status, setStatus] = useState<Record<number, KeyStatus>>({});
  const [newKey, setNewKey] = useState('');
  const [showNew, setShowNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((list: string[]) => {
    setKeys(list);
    onCountChange?.(list.length);
  }, [onCountChange]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await settingsService.getKeys();
      const list = d.keys || [];
      setKeys(list);
      setSnapshot([...list]);
      onCountChange?.(list.length);
    } catch {
      // Bỏ qua lỗi kết nối ban đầu
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => { load(); }, [load]);

  const dirty = JSON.stringify(keys) !== JSON.stringify(snapshot);

  const clearStatus = () => setStatus({});

  const handleAdd = () => {
    const parts = splitKeys(newKey);
    if (!parts.length) return;
    const existing = new Set(keys);
    const fresh = parts.filter(k => !existing.has(k));
    if (!fresh.length) {
      addToast({ type: 'info', message: 'Các key này đã có trong danh sách' });
      return;
    }
    apply([...keys, ...fresh]);
    setNewKey('');
    clearStatus();
    addToast({ type: 'success', message: `Đã thêm ${fresh.length} key (bấm Lưu để áp dụng)` });
  };

  const handleRemove = (i: number) => {
    if (!window.confirm(`Xóa key ${mask(keys[i])} khỏi danh sách? (chưa lưu)`)) return;
    apply(keys.filter((_, j) => j !== i));
    clearStatus();
  };

  const handleMove = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= keys.length) return;
    const next = [...keys];
    [next[i], next[j]] = [next[j], next[i]];
    apply(next);
    clearStatus();
  };

  const handleTest = async (i: number) => {
    setStatus(prev => ({ ...prev, [i]: { state: 'testing' } }));
    try {
      const r = await settingsService.testKey(i);
      if (r.ok) {
        setStatus(prev => ({ ...prev, [i]: { state: 'ok', detail: `${r.model_count ?? '?'} models` } }));
        addToast({ type: 'success', message: `Key ${r.masked} sống — kết nối Gemini OK` });
      } else {
        setStatus(prev => ({ ...prev, [i]: { state: 'fail', detail: r.error || 'Lỗi không rõ' } }));
        addToast({ type: 'error', message: `Key ${r.masked} chết: ${r.error || 'lỗi không rõ'}` });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Kiểm tra thất bại';
      setStatus(prev => ({ ...prev, [i]: { state: 'fail', detail: msg } }));
      addToast({ type: 'error', message: msg });
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await settingsService.setKeys(keys.join(','));
      setSnapshot([...(res.saved || keys)]);
      apply(res.saved || keys);
      clearStatus();
      addToast({
        type: 'success',
        message: `Đã lưu ${res.count} khóa API (Hệ thống chạy ${res.workers} luồng xử lý)`,
      });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lưu khóa API thất bại' });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className={styles.message}>Đang tải danh sách key…</p>;

  return (
    <div>
      <div className={styles.guideBox}>
        💡 Thêm từng key (hoặc dán nhiều key một lúc), bấm <strong>▶ Kiểm tra</strong> để biết key sống hay chết,
        xếp thứ tự xoay vòng bằng ↑↓, rồi bấm <strong>Lưu</strong> để áp dụng. Nhận khóa miễn phí tại{' '}
        <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className={styles.linkText}>
          Google AI Studio ↗
        </a>
      </div>

      <div className={styles.addRow}>
        <input
          className={styles.keyInput}
          type={showNew ? 'text' : 'password'}
          value={newKey}
          onChange={e => setNewKey(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleAdd(); }}
          placeholder="Dán 1 hoặc nhiều key (mỗi key một dòng, hoặc cách nhau bằng dấu phẩy)"
        />
        <button
          type="button"
          className={styles.eyeBtn}
          onClick={() => setShowNew(v => !v)}
          title={showNew ? 'Ẩn key' : 'Hiện key'}
        >
          {showNew ? '🙈' : '👁'}
        </button>
        <Button size="sm" onClick={handleAdd} disabled={!newKey.trim()}>＋ Thêm key</Button>
      </div>

      <div className={styles.keyList}>
        {keys.map((k, i) => {
          const st = status[i]?.state || 'untested';
          return (
            <div key={`${i}-${mask(k)}`} className={styles.keyRow}>
              <div className={styles.keyOrderBadge}>#{i + 1}</div>
              <code className={styles.keyCode}>{mask(k)}</code>
              <span className={`${styles.keyStatus} ${styles[`st_${st}`]}`} title={status[i]?.detail || ''}>
                {st === 'testing' ? '⏳ Đang kiểm tra…' : st === 'ok' ? `● Sống${status[i]?.detail ? ` (${status[i].detail})` : ''}` : st === 'fail' ? '● Chết' : '○ Chưa kiểm tra'}
              </span>
              {st === 'fail' && status[i]?.detail && (
                <span className={styles.failDetail} title={status[i].detail}>{status[i].detail}</span>
              )}
              <div className={styles.keyActions}>
                <Button size="sm" variant="ghost" onClick={() => handleTest(i)} loading={st === 'testing'} title="Kiểm tra key có kết nối được Gemini không">
                  ▶ Kiểm tra
                </Button>
                <button type="button" className={styles.moveBtn} disabled={i === 0} onClick={() => handleMove(i, -1)} title="Lên trên (ưu tiên xoay vòng trước)">↑</button>
                <button type="button" className={styles.moveBtn} disabled={i === keys.length - 1} onClick={() => handleMove(i, 1)} title="Xuống dưới">↓</button>
                <button type="button" className={styles.deleteKeyBtn} onClick={() => handleRemove(i)} title="Xóa key này">✕</button>
              </div>
            </div>
          );
        })}
        {keys.length === 0 && (
          <p className={styles.message}>Chưa có key nào — dán key vào ô trên rồi bấm Thêm key.</p>
        )}
      </div>

      <div className={styles.actions}>
        {dirty && <span className={styles.dirtyNote}>Có thay đổi chưa lưu</span>}
        <Button onClick={handleSave} loading={saving} disabled={!dirty}>
          💾 Lưu & Áp Dụng {dirty ? `(${keys.length} key)` : 'Khóa API'}
        </Button>
      </div>
    </div>
  );
}
