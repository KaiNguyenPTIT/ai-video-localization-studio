import { apiGet, apiPost, apiPut, apiPutJson, apiDelete, apiPostJson, ApiError } from './apiClient';
import type { Project, Episode, Task, Stats, LibraryItem, StorageStats, HealthInfo, Voice, Model, DetailLevel, SystemLogResponse, Character } from '@/shared/lib/types';

export const projectService = {
  list: () => apiGet<{ projects: Project[] }>('/api/projects').then(r => r.projects),
  get: (id: string) => apiGet<Project>(`/api/projects/${id}`),
  create: (name: string, settings?: Record<string, string>) => {
    const fd = new FormData();
    fd.append('name', name);
    if (settings) fd.append('settings', JSON.stringify(settings));
    return apiPost<Project>('/api/projects', fd);
  },
  update: (id: string, data: { name?: string; settings?: Record<string, string> }) => {
    const fd = new FormData();
    if (data.name) fd.append('name', data.name);
    if (data.settings) fd.append('settings', JSON.stringify(data.settings));
    return apiPut<Project>(`/api/projects/${id}`, fd);
  },
  delete: (id: string) => apiDelete<{ ok: boolean }>(`/api/projects/${id}`),
  uploadVoiceRef: (id: string, file: File, refText = '') => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('ref_text', refText);
    return apiPost<{ ok: boolean; ref_audio: string; duration: number; has_text: boolean; transcript_warning: string | null }>(
      `/api/projects/${id}/voice-ref`, fd
    );
  },
  deleteVoiceRef: (id: string) => apiDelete<{ ok: boolean }>(`/api/projects/${id}/voice-ref`),
  saveCharacters: (id: string, characters: Character[]) =>
    apiPutJson<Project>(`/api/projects/${id}/characters`, characters),
  syncCharactersToScripts: (id: string) =>
    apiPost<{ ok: boolean; updated_episodes: number; updated_segments: number; message: string }>(
      `/api/projects/${id}/characters/sync-scripts`
    ),
  processAll: (id: string) => apiPost<{ enqueued: number }>(`/api/projects/${id}/process`),
  merge: async (id: string, episodeIds: string[]): Promise<{ task_id: string; status: string }> => {
    const res = await fetch(`/api/projects/${id}/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ episode_ids: episodeIds }),
    });
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || res.statusText; }
      catch { detail = res.statusText; }
      throw new ApiError(`HTTP ${res.status}`, res.status, String(detail));
    }
    return res.json();
  },
};

export const episodeService = {
  add: (projectId: string, files: File[], opts: Record<string, string> = {}) => {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    for (const [k, v] of Object.entries(opts)) {
      if (v) fd.append(k, v);
    }
    return apiPost<{ episodes: Episode[] }>(`/api/projects/${projectId}/episodes`, fd);
  },
  process: (projectId: string, episodeId: string) =>
    apiPost<{ ok: boolean; task_id: string }>(`/api/projects/${projectId}/episodes/${episodeId}/process`),
  cancel: (projectId: string, episodeId: string) =>
    apiPost<{ ok: boolean }>(`/api/projects/${projectId}/episodes/${episodeId}/cancel`),
  retry: (projectId: string, episodeId: string) =>
    apiPost<{ ok: boolean; task_id?: string; mode?: string }>(`/api/projects/${projectId}/episodes/${episodeId}/retry`),
  delete: (projectId: string, episodeId: string) =>
    apiDelete<{ ok: boolean }>(`/api/projects/${projectId}/episodes/${episodeId}`),
  updateOptions: (projectId: string, episodeId: string, opts: Record<string, string>) => {
    const fd = new FormData();
    for (const [k, v] of Object.entries(opts)) fd.append(k, v);
    return apiPut<Episode>(`/api/projects/${projectId}/episodes/${episodeId}/options`, fd);
  },
  manualPrepare: (projectId: string, episodeId: string) =>
    apiPost<{ task_id: string; prompt: string; compressed_url: string; num_segments: number; target_words: number }>(
      `/api/projects/${projectId}/episodes/${episodeId}/manual-prepare`
    ),
  manualRun: (projectId: string, episodeId: string) =>
    apiPost<{ ok: boolean; task_id: string }>(`/api/projects/${projectId}/episodes/${episodeId}/manual-run`),
  manualSubmit: (projectId: string, episodeId: string, resultText: string) => {
    const fd = new FormData();
    fd.append('result_text', resultText);
    return apiPost<{ task_id: string }>(`/api/projects/${projectId}/episodes/${episodeId}/manual-submit`, fd);
  },
  manualFolder: (projectId: string, episodeId: string) =>
    apiPost<{ ok: boolean; folder: string }>(`/api/projects/${projectId}/episodes/${episodeId}/manual-folder`),
  suggestCharacters: (projectId: string, episodeId: string, force = false) =>
    apiPost<{ characters: Character[]; name_mode: string; narration_count: number; cached?: boolean }>(
      `/api/projects/${projectId}/episodes/${episodeId}/suggest-characters${force ? '?force=true' : ''}`
    ),
  getCharacters: (projectId: string, episodeId: string) =>
    apiGet<{ characters: Character[]; narration_count: number; name_mode: string; reviewed: boolean; reviewed_auto: boolean }>(
      `/api/projects/${projectId}/episodes/${episodeId}/characters`
    ),
  saveEpisodeCharacters: (projectId: string, episodeId: string, characters: Character[]) =>
    apiPutJson<{ characters: Character[]; saved: number; reviewed: boolean }>(
      `/api/projects/${projectId}/episodes/${episodeId}/characters`, characters
    ),
  setCharactersReviewed: (projectId: string, episodeId: string, reviewed: boolean) =>
    apiPutJson<{ ok: boolean; reviewed: boolean }>(
      `/api/projects/${projectId}/episodes/${episodeId}/characters-reviewed`, { reviewed }
    ),
};


export const taskService = {
  list: (status?: string) => {
    const q = status ? `?status=${status}` : '';
    return apiGet<{ tasks: Task[] }>(`/api/tasks${q}`).then(r => r.tasks);
  },
  get: (id: string) => apiGet<Task>(`/api/task/${id}`),
  cancel: (id: string) => apiPost<{ ok: boolean }>(`/api/tasks/${id}/cancel`),
  delete: (id: string) => apiDelete<{ ok: boolean }>(`/api/tasks/${id}`),
  clearFinished: () => apiPost<{ ok: boolean; count: number }>('/api/tasks/clear-finished'),
};

export const logService = {
  getLogs: (params?: { lines?: number; level?: string; search?: string }) => {
    const sp = new URLSearchParams();
    if (params?.lines) sp.set('lines', String(params.lines));
    if (params?.level && params.level !== 'all') sp.set('level', params.level);
    if (params?.search) sp.set('search', params.search);
    const q = sp.toString() ? `?${sp.toString()}` : '';
    return apiGet<SystemLogResponse>(`/api/logs${q}`);
  },
  clearLogs: () => apiDelete<{ ok: boolean }>('/api/logs'),
};

export const libraryService = {
  list: () => apiGet<{ items: LibraryItem[]; total: number }>('/api/library'),
  delete: (baseName: string) =>
    apiDelete<{ ok: boolean; deleted: string[]; failed?: { file: string; error: string }[] }>(
      `/api/library/${encodeURIComponent(baseName)}`
    ),
};

export const settingsService = {
  getVoices: () => apiGet<{ voices: Record<string, Voice> }>('/api/voices').then(r => r.voices),
  getModels: () => apiGet<{ models: Model[] }>('/api/models').then(r => r.models),
  getDetailLevels: () => apiGet<{ levels: Record<string, DetailLevel>; default: string }>('/api/detail-levels'),
  getKeys: () => apiGet<{ keys: string[]; count: number; masked: string[] }>('/api/keys'),
  setKeys: (keys: string) => {
    const fd = new FormData();
    fd.append('keys', keys);
    return apiPost<{ saved: string[]; count: number; workers: number; masked: string[] }>('/api/keys', fd);
  },
  testKey: (index: number) =>
    apiPostJson<{ ok: boolean; key_index: number; masked: string; model_count?: number; error?: string }>('/api/keys/test', { index }),
  previewVoice: (voice: string, text = '') => {
    const q = text.trim()
      ? `?voice=${encodeURIComponent(voice)}&text=${encodeURIComponent(text.trim().slice(0, 200))}`
      : `?voice=${encodeURIComponent(voice)}`;
    return `/api/preview${q}`;
  },
  uploadCustomVoice: (name: string, file: File, refText = '') => {
    const fd = new FormData();
    fd.append('name', name);
    fd.append('file', file);
    fd.append('ref_text', refText);
    return apiPost<{ ok: boolean; voice_key: string; name: string; duration: number; transcript_warning: string | null }>(
      '/api/voices/custom', fd
    );
  },
  deleteCustomVoice: (id: string) => apiDelete<{ ok: boolean }>(`/api/voices/custom/${id}`),
  cleanup: () => apiPost<{ ok: boolean; freed_mb: number; deleted_count: number }>('/api/cleanup'),
  getStats: () => apiGet<Stats>('/api/stats'),
  getStorage: () => apiGet<StorageStats>('/api/storage'),
  getHealth: () => apiGet<HealthInfo>('/api/health'),
  getVoiceStudioStatus: () =>
    apiGet<{ online: boolean; message: string; api_base: string }>('/api/voicestudio/status'),
  heartbeat: () => apiPost<{ ok: boolean }>('/api/heartbeat'),
};

async function adminJson<T>(url: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || data.message || JSON.stringify(data);
    } catch { /* giữ statusText */ }
    throw new ApiError(`HTTP ${res.status}`, res.status, String(detail));
  }
  return res.json() as Promise<T>;
}

export interface GeminiAdminModel {
  id: string;
  name: string;
}

export interface SystemInfo {
  python: string;
  ffmpeg: string;
  gpu: string;
  platform: string;
  ram_total_gb: number;
  ram_avail_gb: number;
  disk_total_gb: number;
  disk_free_gb: number;
  api_keys: number;
  workers: number;
  queue_depth: number;
}

export const adminService = {
  login: (password: string) => {
    const fd = new FormData();
    fd.append('password', password);
    return apiPost<{ ok: boolean }>('/api/admin/login', fd);
  },
  getSettings: () => apiGet<{ settings: Record<string, unknown>; schema: Record<string, AdminSettingSchema> }>('/api/admin/settings'),
  getModels: () => apiGet<{ models: GeminiAdminModel[]; current: string }>('/api/admin/models'),
  addModel: (id: string, name: string) => adminJson<{ ok: boolean; models: GeminiAdminModel[] }>('/api/admin/models', 'POST', { id, name }),
  updateModel: (index: number, id?: string, name?: string) =>
    adminJson<{ ok: boolean; models: GeminiAdminModel[] }>(`/api/admin/models/${index}`, 'PUT', { id, name }),
  removeModel: (index: number) =>
    adminJson<{ ok: boolean; models: GeminiAdminModel[]; current: string }>(`/api/admin/models/${index}`, 'DELETE'),
  restart: () => apiPost<{ ok: boolean; message: string }>('/api/admin/restart'),
  getLogs: (lines = 200) => apiGet<{ log: string; lines: number }>(`/api/admin/logs?lines=${lines}`),
  getSystem: () => apiGet<SystemInfo>('/api/admin/system'),
  saveSettings: (updates: Record<string, unknown>) =>
    adminJson<{ ok: boolean; settings: Record<string, unknown> }>('/api/admin/settings', 'POST', updates),
};

export interface AdminSettingSchema {
  type: 'bool' | 'int' | 'float' | 'str';
  default: unknown;
  min?: number;
  max?: number;
  options?: string[];
  label: string;
  group: string;
}

export const quickService = {
  upload: (file: File, opts: Record<string, string>) => {
    const fd = new FormData();
    fd.append('file', file);
    for (const [k, v] of Object.entries(opts)) fd.append(k, v);
    return apiPost<{ task_id: string }>('/api/upload', fd);
  },
  manualStart: (file: File, opts: Record<string, string>) => {
    const fd = new FormData();
    fd.append('file', file);
    for (const [k, v] of Object.entries(opts)) fd.append(k, v);
    return apiPost<{ task_id: string; prompt: string; compressed_url: string; num_segments: number; target_words: number }>(
      '/api/manual/start', fd
    );
  },
  manualSubmit: (taskId: string, resultText: string) => {
    const fd = new FormData();
    fd.append('task_id', taskId);
    fd.append('result_text', resultText);
    return apiPost<{ task_id: string }>('/api/manual/submit', fd);
  },
  manualAutoRun: (taskId: string) => {
    const fd = new FormData();
    fd.append('task_id', taskId);
    return apiPost<{ task_id: string }>('/api/manual/auto-run', fd);
  },
  manualOpenFolder: (taskId: string) => {
    const fd = new FormData();
    fd.append('task_id', taskId);
    return apiPost<{ ok: boolean; folder: string }>('/api/manual/open-folder', fd);
  },
};

export interface AIStudioAccountInfo {
  logged_in: boolean;
  email: string | null;
  full_name: string | null;
  picture_url: string | null;
  profile_dir: string;
  profile_name: string;
  is_running: boolean;
  cdp_alive: boolean;
}

export const aiStudioService = {
  getAccount: () => apiGet<AIStudioAccountInfo>('/api/ai-studio/account'),
  openLogin: () => apiPost<{ ok: boolean; message: string }>('/api/ai-studio/open-login'),
  closeBrowser: () => apiPost<{ ok: boolean; closed: boolean; is_running: boolean }>('/api/ai-studio/close-browser'),
};


