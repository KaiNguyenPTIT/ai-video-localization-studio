import styles from './Icon.module.css';
import type { CSSProperties } from 'react';

export type IconName =
  | 'dashboard' | 'film' | 'bolt' | 'clock' | 'library' | 'sparkles' | 'settings'
  | 'storage' | 'logs' | 'search' | 'plus' | 'close' | 'chevron-left' | 'chevron-right'
  | 'chevron-down' | 'play' | 'pause' | 'trash' | 'refresh' | 'download' | 'check'
  | 'alert' | 'info' | 'check-circle' | 'external' | 'folder' | 'upload' | 'menu'
  | 'key' | 'cpu' | 'activity' | 'waveform' | 'users' | 'video' | 'wand' | 'eye'
  | 'copy' | 'filter' | 'more' | 'arrow-right' | 'calendar' | 'volume' | 'clipboard'
  | 'layers' | 'dot' | 'sun' | 'moon' | 'link' | 'edit' | 'grid' | 'list' | 'server';

const PATHS: Record<IconName, React.ReactNode> = {
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /></>,
  list: <><line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" /><circle cx="4" cy="6" r="1" /><circle cx="4" cy="12" r="1" /><circle cx="4" cy="18" r="1" /></>,
  film: <><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="7" y1="4" x2="7" y2="20" /><line x1="17" y1="4" x2="17" y2="20" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="3" y1="15" x2="21" y2="15" /></>,
  bolt: <path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z" />,
  clock: <><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15.5 14" /></>,
  library: <><rect x="3" y="4" width="5" height="16" rx="1" /><rect x="10" y="4" width="5" height="16" rx="1" /><path d="M17.5 5.2 21 19.4" /></>,
  layers: <><polygon points="12 3 21 8 12 13 3 8 12 3" /><polyline points="3 12 12 17 21 12" /><polyline points="3 16 12 21 21 16" /></>,
  sparkles: <><path d="M12 3l1.9 4.9L19 9.8l-5.1 1.9L12 16.5l-1.9-4.8L5 9.8l5.1-1.9L12 3z" /><path d="M19 15l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8.8-2z" /></>,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></>,
  storage: <><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6" /><path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" /></>,
  server: <><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="13" width="18" height="7" rx="2" /><line x1="7" y1="7.5" x2="7" y2="7.5" /><line x1="7" y1="16.5" x2="7" y2="16.5" /></>,
  logs: <><path d="M6 3h9l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" /><polyline points="14 3 14 8 19 8" /><line x1="8.5" y1="13" x2="15" y2="13" /><line x1="8.5" y1="16.5" x2="13" y2="16.5" /></>,
  clipboard: <><rect x="6" y="4" width="12" height="17" rx="2" /><path d="M9 4V3a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1" /><line x1="9" y1="11" x2="15" y2="11" /><line x1="9" y1="15" x2="13" y2="15" /></>,
  search: <><circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></>,
  plus: <><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></>,
  close: <><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></>,
  'chevron-left': <polyline points="15 5 8 12 15 19" />,
  'chevron-right': <polyline points="9 5 16 12 9 19" />,
  'chevron-down': <polyline points="5 9 12 16 19 9" />,
  play: <polygon points="6 4 20 12 6 20 6 4" />,
  pause: <><line x1="9" y1="5" x2="9" y2="19" /><line x1="15" y1="5" x2="15" y2="19" /></>,
  trash: <><polyline points="4 7 20 7" /><path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" /><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /></>,
  refresh: <><polyline points="21 5 21 11 15 11" /><polyline points="3 19 3 13 9 13" /><path d="M20.5 11a8.5 8.5 0 0 0-14.9-5.1L3 8.5" /><path d="M3.5 13a8.5 8.5 0 0 0 14.9 5.1L21 15.5" /></>,
  download: <><path d="M12 3v12" /><polyline points="7 12 12 17 17 12" /><line x1="4" y1="20" x2="20" y2="20" /></>,
  check: <polyline points="5 12.5 10 17.5 19 6.5" />,
  'check-circle': <><circle cx="12" cy="12" r="9" /><polyline points="8 12.5 11 15.5 16 9.5" /></>,
  alert: <><path d="M10.3 3.9 2.4 17a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><line x1="12" y1="9" x2="12" y2="14" /><line x1="12" y1="17.5" x2="12" y2="17.5" /></>,
  info: <><circle cx="12" cy="12" r="9" /><line x1="12" y1="11" x2="12" y2="16.5" /><line x1="12" y1="7.8" x2="12" y2="7.8" /></>,
  external: <><path d="M14 4h6v6" /><polyline points="20 4 11 13" /><path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" /></>,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />,
  upload: <><path d="M12 17V5" /><polyline points="7 10 12 5 17 10" /><path d="M4 19h16" /></>,
  menu: <><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></>,
  key: <><circle cx="8" cy="15" r="4" /><line x1="10.8" y1="12.2" x2="20" y2="3" /><path d="M17 4l3 3" /><path d="M14.5 6.5l2.5 2.5" /></>,
  cpu: <><rect x="6" y="6" width="12" height="12" rx="2" /><rect x="9.5" y="9.5" width="5" height="5" rx="1" /><line x1="9" y1="2" x2="9" y2="6" /><line x1="15" y1="2" x2="15" y2="6" /><line x1="9" y1="18" x2="9" y2="22" /><line x1="15" y1="18" x2="15" y2="22" /><line x1="2" y1="9" x2="6" y2="9" /><line x1="2" y1="15" x2="6" y2="15" /><line x1="18" y1="9" x2="22" y2="9" /><line x1="18" y1="15" x2="22" y2="15" /></>,
  activity: <polyline points="3 12 7 12 10 4 14 20 17 12 21 12" />,
  waveform: <><line x1="4" y1="9" x2="4" y2="15" /><line x1="8" y1="5" x2="8" y2="19" /><line x1="12" y1="8" x2="12" y2="16" /><line x1="16" y1="4" x2="16" y2="20" /><line x1="20" y1="10" x2="20" y2="14" /></>,
  volume: <><polygon points="4 9 8 9 12 5 12 19 8 15 4 15 4 9" /><path d="M16 8.5a4 4 0 0 1 0 7" /><path d="M18.5 6a7 7 0 0 1 0 12" /></>,
  users: <><circle cx="9" cy="8" r="3.2" /><path d="M3.5 20a5.5 5.5 0 0 1 11 0" /><path d="M16 5.2a3.2 3.2 0 0 1 0 6.1" /><path d="M17.5 14.2A5.5 5.5 0 0 1 21 20" /></>,
  video: <><rect x="3" y="6" width="12" height="12" rx="2" /><polygon points="15 10 21 7 21 17 15 14 15 10" /></>,
  wand: <><path d="M15 4V2" /><path d="M15 10V8" /><path d="M12 7h-2" /><path d="M20 7h-2" /><path d="m17.5 4.5 1.4-1.4" /><path d="m17.5 9.5 1.4 1.4" /><path d="M4 20 14 10" /><path d="M4 20l1.5-.5L6 18z" /></>,
  eye: <><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7z" /><circle cx="12" cy="12" r="3" /></>,
  copy: <><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1" /></>,
  filter: <polygon points="3 5 21 5 14 13 14 20 10 18 10 13 3 5" />,
  more: <><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>,
  'arrow-right': <><line x1="4" y1="12" x2="19" y2="12" /><polyline points="13 6 19 12 13 18" /></>,
  calendar: <><rect x="3.5" y="4.5" width="17" height="16" rx="2" /><line x1="3.5" y1="9.5" x2="20.5" y2="9.5" /><line x1="8" y1="2.5" x2="8" y2="6" /><line x1="16" y1="2.5" x2="16" y2="6" /></>,
  link: <><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1.5 1.5" /><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1.5-1.5" /></>,
  edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></>,
  dot: <circle cx="12" cy="12" r="4" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
  moon: <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />,
};

export const ICON_NAMES = new Set<string>(Object.keys(PATHS));

/** Runtime detection so legacy emoji props can coexist with the SVG icon set during migration. */
export function isIconName(value: string): value is IconName {
  return ICON_NAMES.has(value);
}

interface IconProps {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
  style?: CSSProperties;
  'aria-hidden'?: boolean;
}

export function Icon({ name, size = 18, strokeWidth = 2, className, style }: IconProps) {
  return (
    <svg
      className={`${styles.icon} ${className ?? ''}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={style}
    >
      {PATHS[name]}
    </svg>
  );
}
