import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';
import { ToastContainer } from '@/shared/ui/Toast';
import { CommandPalette } from './CommandPalette';
import { useKeyboardShortcuts } from '@/shared/hooks/useKeyboardShortcuts';
import styles from './AppLayout.module.css';

export function AppLayout() {
  useKeyboardShortcuts();

  return (
    <div className={styles.layout}>
      <Sidebar />
      <div className={styles.content}>
        <Topbar />
        <main className={styles.main}>
          <Outlet />
        </main>
      </div>
      <ToastContainer />
      <CommandPalette />
    </div>
  );
}
