import { useEffect, useRef, useState } from 'react';
import { timestampToSeconds } from './VideoPlayer';
import styles from './SubtitlePanel.module.css';

interface SubtitleCue {
  id: string;
  start: number;
  end: number;
  timecode: string;
  text: string;
}

function parseSrt(srt: string): SubtitleCue[] {
  return srt.trim().split(/\r?\n\r?\n/).flatMap((block, index) => {
    const lines = block.split(/\r?\n/).filter(Boolean);
    const timeIndex = lines.findIndex(line => line.includes('-->'));
    if (timeIndex < 0) return [];
    const [start, end] = lines[timeIndex].split('-->');
    const text = lines.slice(timeIndex + 1).join(' ').trim();
    if (!text) return [];
    return [{ id: `${index}-${start}`, start: timestampToSeconds(start), end: timestampToSeconds(end), timecode: start.trim(), text }];
  });
}

interface SubtitlePanelProps {
  src: string | null;
  currentTime: number;
  onSeek: (seconds: number) => void;
}

export function SubtitlePanel({ src, currentTime, onSeek }: SubtitlePanelProps) {
  const [cues, setCues] = useState<SubtitleCue[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'missing' | 'error'>(src ? 'loading' : 'missing');
  const cueRefs = useRef(new Map<string, HTMLButtonElement>());
  const activeCueId = cues.find(cue => currentTime >= cue.start && currentTime < cue.end)?.id;

  useEffect(() => {
    if (!src) {
      setCues([]);
      setStatus('missing');
      return;
    }
    let active = true;
    setStatus('loading');
    fetch(src)
      .then(response => response.ok ? response.text() : Promise.reject())
      .then(text => {
        if (!active) return;
        setCues(parseSrt(text));
        setStatus('ready');
      })
      .catch(() => active && setStatus('error'));
    return () => { active = false; };
  }, [src]);

  useEffect(() => {
    if (!activeCueId) return;
    cueRefs.current.get(activeCueId)?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [activeCueId]);

  return (
    <aside className={styles.panel} aria-label="Subtitles">
      <div className={styles.header}>
        <div>
          <span className={styles.eyebrow}>Transcript</span>
          <h3>Subtitles</h3>
        </div>
        {status === 'ready' && <span className={styles.count}>{cues.length} cues</span>}
      </div>
      {status === 'loading' && <p className={styles.message}>Loading subtitles…</p>}
      {status === 'missing' && <p className={styles.message}>No subtitle track is available for this video.</p>}
      {status === 'error' && <p className={styles.message}>Could not load the subtitle track.</p>}
      {status === 'ready' && (
        <div className={styles.cues}>
          {cues.length ? cues.map(cue => {
            const isActive = cue.id === activeCueId;
            return (
            <button type="button" className={`${styles.cue} ${isActive ? styles.cueActive : ''}`} key={cue.id} onClick={() => onSeek(cue.start)} aria-current={isActive ? 'true' : undefined} ref={element => {
              if (element) cueRefs.current.set(cue.id, element);
              else cueRefs.current.delete(cue.id);
            }}>
              <time>{cue.timecode}</time>
              <span>{cue.text}</span>
            </button>
            );
          }) : <p className={styles.message}>This subtitle file has no readable cues.</p>}
        </div>
      )}
    </aside>
  );
}
