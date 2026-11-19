import { create } from 'zustand';
import type { Toast } from '@/shared/ui/Toast';

const COLLAPSE_KEY = 'ui.sidebarCollapsed';

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSE_KEY) === '1';
  } catch {
    return false;
  }
}

interface UIState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toasts: Toast[];
  addToast: (toast: Omit<Toast, 'id'>) => void;
  removeToast: (id: string) => void;
  commandPaletteOpen: boolean;
  setCommandPaletteOpen: (open: boolean) => void;
}

let toastCounter = 0;

export const useUIStore = create<UIState>((set) => ({
  sidebarCollapsed: readCollapsed(),
  toggleSidebar: () => set(s => {
    const next = !s.sidebarCollapsed;
    try { localStorage.setItem(COLLAPSE_KEY, next ? '1' : '0'); } catch { /* ignore */ }
    return { sidebarCollapsed: next };
  }),
  setSidebarCollapsed: (collapsed) => {
    try { localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0'); } catch { /* ignore */ }
    set({ sidebarCollapsed: collapsed });
  },
  toasts: [],
  addToast: (toast) => {
    const id = `toast-${++toastCounter}`;
    set(s => ({ toasts: [...s.toasts, { ...toast, id }] }));
    setTimeout(() => {
      set(s => ({ toasts: s.toasts.filter(t => t.id !== id) }));
    }, toast.duration ?? 4000);
  },
  removeToast: (id) => set(s => ({ toasts: s.toasts.filter(t => t.id !== id) })),
  commandPaletteOpen: false,
  setCommandPaletteOpen: (open) => set({ commandPaletteOpen: open }),
}));
