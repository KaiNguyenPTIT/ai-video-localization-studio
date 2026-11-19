import { useCallback, useState } from 'react';
import styles from './UploadZone.module.css';

interface UploadZoneProps {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  label?: string;
}

export function UploadZone({
  onFiles,
  accept = 'video/mp4,video/mkv,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm',
  multiple = true,
  label = 'Drop video files here',
}: UploadZoneProps) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  }, [onFiles]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) onFiles(files);
    e.target.value = '';
  };

  return (
    <div
      className={`${styles.zone} ${dragging ? styles.dragging : ''}`}
      onDragOver={e => { e.preventDefault(); setDragging(true); }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
    >
      <input type="file" accept={accept} multiple={multiple} onChange={handleChange} className={styles.input} />
      <div className={styles.content}>
        <div className={styles.icon}>📁</div>
        <h3>{label}</h3>
        <p>Supported: MP4, MKV, MOV, WEBM</p>
        <span className={styles.browse}>Select files</span>
      </div>
    </div>
  );
}

interface FileQueueItem {
  file: File;
  progress?: number;
}

export function FileList({ items, onRemove }: { items: FileQueueItem[]; onRemove: (i: number) => void }) {
  if (!items.length) return null;
  return (
    <div className={styles.fileList}>
      {items.map((item, i) => (
        <div key={i} className={styles.fileItem}>
          <div className={styles.fileInfo}>
            <span className={styles.fileName}>{item.file.name}</span>
            <span className={styles.fileSize}>{(item.file.size / 1024 / 1024).toFixed(1)} MB</span>
          </div>
          <button className={styles.removeBtn} onClick={() => onRemove(i)}>✕</button>
        </div>
      ))}
    </div>
  );
}
