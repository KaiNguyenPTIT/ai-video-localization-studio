import { NavLink } from 'react-router-dom';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { Icon, type IconName } from '@/shared/ui/Icon';
import styles from './Sidebar.module.css';

interface NavItem { to: string; label: string; icon: IconName; }
interface NavGroup { section: string; items: NavItem[]; }

const NAV: NavGroup[] = [
  {
    section: 'Sản xuất',
    items: [
      { to: '/', label: 'Tổng quan', icon: 'dashboard' },
      { to: '/projects', label: 'Dự án phim', icon: 'film' },
      { to: '/quick', label: 'Tóm tắt nhanh', icon: 'bolt' },
      { to: '/tasks', label: 'Tiến trình chạy', icon: 'clock' },
    ],
  },
  {
    section: 'Nội dung',
    items: [
      { to: '/library', label: 'Kho video đã xuất', icon: 'library' },
      { to: '/studio', label: 'Google AI Studio', icon: 'sparkles' },
    ],
  },
  {
    section: 'Hệ thống',
    items: [
      { to: '/settings', label: 'Cài đặt & API Key', icon: 'settings' },
      { to: '/storage', label: 'Dung lượng ổ đĩa', icon: 'storage' },
      { to: '/logs', label: 'Nhật ký hệ thống', icon: 'logs' },
    ],
  },
];

export function Sidebar() {
  const collapsed = useUIStore(s => s.sidebarCollapsed);
  const toggle = useUIStore(s => s.toggleSidebar);

  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ''}`}>
      <div className={styles.logo}>
        <div className={styles.logoIcon}>
          <Icon name="film" size={20} />
        </div>
        {!collapsed && (
          <div className={styles.logoText}>
            <div className={styles.logoTitle}>ANIME RECAP</div>
            <div className={styles.logoSub}>AI VIDEO STUDIO</div>
          </div>
        )}
      </div>

      <nav className={styles.nav}>
        {NAV.map(group => (
          <div key={group.section} className={styles.group}>
            {!collapsed && <div className={styles.sectionLabel}>{group.section}</div>}
            {group.items.map(item => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ''}`}
                title={collapsed ? item.label : undefined}
              >
                <span className={styles.navIcon}><Icon name={item.icon} size={18} /></span>
                {!collapsed && <span className={styles.navLabel}>{item.label}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <button
        className={styles.collapseBtn}
        onClick={toggle}
        title={collapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'}
        aria-label={collapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'}
      >
        <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} size={16} />
      </button>
    </aside>
  );
}
