import { useEffect } from 'react';
import { useUIStore } from '@/shared/lib/state/uiStore';

export function useKeyboardShortcuts() {
  const setOpen = useUIStore(s => s.setCommandPaletteOpen);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [setOpen]);
}
