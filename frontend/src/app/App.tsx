import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AppLayout } from '@/app/layout/AppLayout';
import { DashboardPage } from '@/features/dashboard/DashboardPage';
import { ProjectsPage } from '@/features/projects/ProjectsPage';
import { ProjectDetailPage } from '@/features/projects/ProjectDetailPage';
import { TasksPage } from '@/features/tasks/TasksPage';
import { LibraryPage } from '@/features/library/LibraryPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { StoragePage } from '@/features/storage/StoragePage';
import { QuickRecapPage } from '@/features/quick-recap/QuickRecapPage';
import { AIStudioPage } from '@/features/ai-studio/AIStudioPage';
import { LogsPage } from '@/features/logs/LogsPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectDetailPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/storage" element={<StoragePage />} />
          <Route path="/logs" element={<LogsPage />} />
          <Route path="/quick" element={<QuickRecapPage />} />
          <Route path="/studio" element={<AIStudioPage />} />
          <Route path="/studio/:projectId" element={<AIStudioPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
