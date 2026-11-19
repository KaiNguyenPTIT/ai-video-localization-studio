import { useRef, useState } from 'react';
import { projectService } from '@/shared/lib/services';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { Button } from '@/shared/ui/Button';

interface Props {
  projectId: string;
  refAudio?: string;
  refText?: string;
  onChanged: (refAudio: string, refText: string) => void;
}

/** Upload giọng mẫu cho VoiceStudio-clone (cấp dự án, các tập kế thừa). */
export function VoiceRefPanel({ projectId, refAudio, refText, onChanged }: Props) {
  const addToast = useUIStore(s => s.addToast);
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [text, setText] = useState(refText || '');
  const [busy, setBusy] = useState(false);

  const doUpload = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const res = await projectService.uploadVoiceRef(projectId, file, text);
      onChanged(res.ref_audio, text);
      setFile(null);
      if (fileRef.current) fileRef.current.value = '';
      if (res.transcript_warning) {
        addToast({ type: 'error', message: res.transcript_warning });
      } else {
        addToast({
          type: 'success',
          message: `Đã lưu giọng mẫu (${res.duration}s)${res.has_text ? ' kèm transcript' : ''}`,
        });
      }
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Upload giọng mẫu thất bại' });
    } finally {
      setBusy(false);
    }
  };

  const doDelete = async () => {
    if (!window.confirm('Xóa giọng mẫu của phim này? Các tập dùng giọng Clone sẽ báo thiếu mẫu.')) return;
    setBusy(true);
    try {
      await projectService.deleteVoiceRef(projectId);
      onChanged('', '');
      addToast({ type: 'success', message: 'Đã xóa giọng mẫu' });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Xóa giọng mẫu thất bại' });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ border: '1px dashed var(--border, #334155)', borderRadius: 10, padding: 12, marginTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>🎙️ Giọng mẫu nhân bản (VoiceStudio Clone)</div>
      <div style={{ fontSize: '.8rem', opacity: 0.75, marginBottom: 8 }}>
        Chỉ dùng khi chọn giọng <b>VoiceStudio - Clone Profile</b>. Upload 1 đoạn audio mẫu 3-10s
        (cùng người nói). File được chuẩn hóa 24kHz mono, ≤12s đầu.
      </div>
      {refAudio ? (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '.8rem' }} title={refAudio}>
            ✅ Đã có mẫu{refText ? ' (kèm transcript)' : ' (chưa có transcript)'}
          </span>
          <Button size="sm" variant="ghost" onClick={doDelete} disabled={busy}>Xóa mẫu</Button>
        </div>
      ) : (
        <>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac,.opus"
            onChange={e => setFile(e.target.files?.[0] || null)}
            style={{ fontSize: '.8rem', marginBottom: 8 }}
          />
          <input
            placeholder="Transcript của đoạn mẫu (tùy chọn — bỏ trống thì tự chép)"
            value={text}
            onChange={e => setText(e.target.value)}
            style={{ width: '100%', fontSize: '.8rem', padding: '6px 8px', borderRadius: 8, marginBottom: 8 }}
          />
          <Button size="sm" onClick={doUpload} disabled={!file || busy} loading={busy}>
            Tải giọng mẫu lên
          </Button>
        </>
      )}
    </div>
  );
}
