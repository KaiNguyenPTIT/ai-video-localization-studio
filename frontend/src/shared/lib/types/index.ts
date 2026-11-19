export type EpisodeStatus =
  | 'pending'
  | 'queueing'
  | 'running'
  | 'awaiting'
  | 'awaiting_result'
  | 'completed'
  | 'failed'
  | 'cancelled';

export type TaskStatus =
  | 'pending'
  | 'queueing'
  | 'running'
  | 'awaiting'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface EpisodeOptions {
  voice_id: string;
  style: string;
  model: string;
  mode: 'api' | 'manual';
  detail: string;
  custom_minutes?: string;
  edit_mode?: 'legacy' | 'smart_shot';
  character_name_mode?: 'vietnamese' | 'romaji';
  free_order?: '0' | '1';
  fx_flip?: '0' | '1';
  fx_zoom?: '0' | '1';
  fx_speed?: '0' | '1';
  fx_reverse?: '0' | '1';
}

export interface Segment {
  index?: number;
  start_time: string;
  end_time: string;
  narration: string;
  tts_duration?: number | null;
  shot_count?: number | null;
}

export interface Episode {
  id: string;
  project_id: string;
  filename: string;
  video_path?: string;
  options: EpisodeOptions;
  status: EpisodeStatus;
  progress: number;
  message: string;
  result_url?: string | null;
  srt_url?: string | null;
  error?: string | null;
  task_id?: string | null;
  created_at: string;
  completed_at?: string | null;
  segments?: Segment[] | null;
  manual_prompt?: string | null;
  manual_result?: string | null;
  manual_compressed_url?: string | null;
  num_segments?: number;
  target_words?: number;
  target_sec?: number | null;
  est_sec?: number | null;
  tts_sec?: number | null;
  characters_reviewed?: number | null;
}

export interface LastMergeInfo {
  video_url: string;
  srt_url?: string | null;
  source_count?: number;
  total_duration?: number;
  episode_ranges?: EpisodeRange[];
}

export interface ProjectSettings {
  voice_id?: string;
  model?: string;
  style?: string;
  detail?: string;
  mode?: string;
  custom_minutes?: string;
  edit_mode?: 'legacy' | 'smart_shot';
  character_name_mode?: 'vietnamese' | 'romaji';
  free_order?: '0' | '1';
  fx_flip?: '0' | '1';
  fx_zoom?: '0' | '1';
  fx_speed?: '0' | '1';
  fx_reverse?: '0' | '1';
  last_merge?: LastMergeInfo;
  series_description?: string;
  tts_ref_audio?: string;
  tts_ref_text?: string;
}

export interface Character {
  name: string;
  aliases: string[];
}

export interface Project {
  id: string;
  name: string;
  created_at: string;
  updated_at?: string;
  settings: ProjectSettings;
  episodes: Episode[];
  characters?: Character[];
}

export interface Task {
  id: string;
  status: TaskStatus;
  progress: number;
  message: string;
  result?: {
    video_url?: string;
    srt_url?: string;
    duration_original?: number;
    duration_output?: number;
    segments_count?: number;
  } | null;
  error?: string | null;
  prompt?: string | null;
  created_at: string;
  completed_at?: string | null;
  compressed_url?: string | null;
  target_sec?: number | null;
  est_sec?: number | null;
  tts_sec?: number | null;
  output_sec?: number | null;
  segments?: Segment[];
  video_name?: string;
}

export interface Voice {
  name: string;
  type?: string;
  id?: string;
  custom?: boolean;
  builtin?: boolean;
}

export interface Model {
  id: string;
  name: string;
}

export interface DetailLevel {
  name: string;
  target_sec: number;
  min_sec: number;
  max_sec: number;
  target_words: number;
}

export interface Stats {
  projects: number;
  episodes: { total: number; completed: number };
  tasks: Record<string, number>;
  output_files: number;
  output_size_mb: number;
  queue_depth: number;
}

export interface EpisodeRange {
  episode_id: string;
  filename: string;
  start_time: number;
  end_time: number;
  duration: number;
  video_url?: string | null;
  srt_url?: string | null;
}

export interface LibraryMerge {
  project_id?: string;
  project_name?: string;
  srt_url?: string | null;
  episode_ranges: EpisodeRange[];
  total_duration?: number;
}

export interface LibraryItem {
  base_name: string;
  title: string;
  modified_at: string;
  video: { filename: string; size_mb: number; url: string; media_url: string } | null;
  srt: { filename: string; size_kb: number; url: string } | null;
  merge?: LibraryMerge;
}

export interface StorageStats {
  output: number;
  temporary: number;
  audio: number;
  segments: number;
  uploads: number;
  project_uploads?: number;
  orphan_uploads?: number;
  cleanable?: number;
  manual: number;
  total: number;
}

export interface HealthInfo {
  status: string;
  gemini_keys: number;
  workers: number;
  queue_depth: number;
  active_tasks?: number;
  model: string;
}

export interface SystemLogEntry {
  id: string;
  time: string;
  level: string;
  source: string;
  message: string;
  raw: string;
}

export interface SystemLogResponse {
  entries: SystemLogEntry[];
  total: number;
  filtered_count: number;
  raw: string;
}
