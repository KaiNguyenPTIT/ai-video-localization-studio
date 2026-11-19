import { useCallback, useEffect, useState } from 'react';
import { adminService, type GeminiAdminModel } from '@/shared/lib/services';
import { Button } from '@/shared/ui/Button';
import { useUIStore } from '@/shared/lib/state/uiStore';
import styles from './AdminTools.module.css';

/** Quản lý model Gemini tùy chỉnh (thêm/sửa/xóa) — port từ trang /admin cũ. */
export function ModelsManager() {
  const addToast = useUIStore(s => s.addToast);
  const [models, setModels] = useState<GeminiAdminModel[]>([]);
  const [current, setCurrent] = useState('');
  const [newId, setNewId] = useState('');
  const [newName, setNewName] = useState('');
  const [editing, setEditing] = useState<number | null>(null);
  const [editId, setEditId] = useState('');
  const [editName, setEditName] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await adminService.getModels();
      setModels(d.models || []);
      setCurrent(d.current || '');
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không tải được danh sách model' });
    }
  }, [addToast]);

  useEffect(() => { load(); }, [load]);

  const apply = (d: { models: GeminiAdminModel[] }) => setModels(d.models || []);

  const handleAdd = async () => {
    if (!newId.trim()) return;
    setBusy(true);
    try {
      apply(await adminService.addModel(newId.trim(), newName.trim()));
      setNewId('');
      setNewName('');
      addToast({ type: 'success', message: 'Đã thêm model' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Thêm model thất bại' });
    } finally {
      setBusy(false);
    }
  };

  const startEdit = (i: number) => {
    setEditing(i);
    setEditId(models[i].id);
    setEditName(models[i].name);
  };

  const handleEdit = async () => {
    if (editing === null || !editId.trim()) return;
    setBusy(true);
    try {
      apply(await adminService.updateModel(editing, editId.trim(), editName.trim()));
      setEditing(null);
      addToast({ type: 'success', message: 'Đã cập nhật model' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Cập nhật thất bại' });
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (i: number) => {
    if (!window.confirm(`Xóa model "${models[i].id}"?`)) return;
    setBusy(true);
    try {
      const d = await adminService.removeModel(i);
      apply(d);
      if (d.current) setCurrent(d.current);
      addToast({ type: 'success', message: 'Đã xóa model' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Xóa thất bại' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className={styles.rows}>
        {models.map((m, i) => (
          <div key={i} className={styles.row}>
            {editing === i ? (
              <div className={styles.editRow}>
                <input className={styles.text} value={editId} onChange={e => setEditId(e.target.value)} placeholder="Model ID" />
                <input className={styles.text} value={editName} onChange={e => setEditName(e.target.value)} placeholder="Tên hiển thị" />
                <Button size="sm" onClick={handleEdit} loading={busy}>Lưu</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Hủy</Button>
              </div>
            ) : (
              <>
                <div className={styles.rowInfo}>
                  <span className={styles.rowLabel}>
                    {m.name}
                    {m.id === current && <span className={styles.currentBadge}>Đang dùng</span>}
                  </span>
                  <code className={styles.rowKey}>{m.id}</code>
                </div>
                <div className={styles.rowActions}>
                  <Button size="sm" variant="ghost" onClick={() => startEdit(i)}>Sửa</Button>
                  <Button size="sm" variant="ghost" onClick={() => handleDelete(i)}>✕</Button>
                </div>
              </>
            )}
          </div>
        ))}
        {models.length === 0 && <p className={styles.message}>Chưa có model tùy chỉnh.</p>}
      </div>
      <div className={styles.addRow}>
        <input className={styles.text} value={newId} onChange={e => setNewId(e.target.value)} placeholder="Model ID mới (vd: gemini-3.9-flash)" />
        <input className={styles.text} value={newName} onChange={e => setNewName(e.target.value)} placeholder="Tên hiển thị" />
        <Button size="sm" onClick={handleAdd} loading={busy} disabled={!newId.trim()}>＋ Thêm</Button>
      </div>
    </div>
  );
}
