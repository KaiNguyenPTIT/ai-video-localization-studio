import { useState, useEffect, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { projectService, episodeService, taskService } from '@/shared/lib/services';
import { PageHeader } from '@/app/layout/PageHeader';
import { Button, IconButton } from '@/shared/ui/Button';
import { StatCard } from '@/shared/ui/Card';
import { Icon } from '@/shared/ui/Icon';
import { Badge } from '@/shared/ui/Badge';
import { EmptyState } from '@/shared/ui/EmptyState';
import { StatusBadge } from '@/shared/ui/StatusBadge';
import { ProgressBar } from '@/shared/ui/ProgressBar';
import { Modal, ConfirmDialog } from '@/shared/ui/Modal';
import { VideoPreviewModal, type VideoPreviewModalProps } from '@/features/library/VideoPreviewModal';
import { ScriptTheaterModal } from '@/features/library/ScriptTheaterModal';
import { UploadZone, FileList } from '@/features/quick-recap/UploadZone';
import { EpisodeDetailDrawer } from '@/features/projects/EpisodeDetailDrawer';
import { ConfigPanel, STYLE_OPTIONS } from '@/features/projects/ConfigPanel';
import { VoiceRefPanel } from '@/features/projects/VoiceRefPanel';
import { useUIStore } from '@/shared/lib/state/uiStore';
import { useConfig } from '@/shared/hooks/useConfig';
import { projectStats, episodeLabel, formatDate, cn } from '@/shared/lib/utils/format';
import type { Project, Episode, Voice, Model, DetailLevel, ProjectSettings, LastMergeInfo, Character } from '@/shared/lib/types';
import styles from './ProjectDetailPage.module.css';

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const addToast = useUIStore(s => s.addToast);
  const { voices, models, detailLevels, defaultDetail } = useConfig();

  const [project, setProject] = useState<Project | null>(null);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadConfig, setUploadConfig] = useState({ mode: 'api', voice_id: '', model: '', style: '', detail: '', custom_minutes: '', edit_mode: 'smart_shot', character_name_mode: 'romaji', free_order: '0', fx_flip: '1', fx_zoom: '1', fx_speed: '1', fx_reverse: '1' });
  const [uploading, setUploading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [selectedEp, setSelectedEp] = useState<Episode | null>(null);
  const [scriptEpId, setScriptEpId] = useState<string | null>(null);
  const [configEp, setConfigEp] = useState<Episode | null>(null);
  const [epConfigValues, setEpConfigValues] = useState<Record<string, string>>({});
  const [savingEpConfig, setSavingEpConfig] = useState(false);
  const [videoPreview, setVideoPreview] = useState<VideoPreviewModalProps | null>(null);
  const [deleteEp, setDeleteEp] = useState<Episode | null>(null);
  const [confirmRerun, setConfirmRerun] = useState<{ ep: Episode; fromConfig: boolean } | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [settingsName, setSettingsName] = useState('');
  const [settingsConfig, setSettingsConfig] = useState<Record<string, string>>({});
  const [settingsDesc, setSettingsDesc] = useState('');
  const [savingSettings, setSavingSettings] = useState(false);
  const [merging, setMerging] = useState(false);
  const [showMerge, setShowMerge] = useState(false);
  const [mergeSelected, setMergeSelected] = useState<string[]>([]);
  const [mergeTask, setMergeTask] = useState<{ id: string; progress: number; message: string } | null>(null);
  const [suggestState, setSuggestState] = useState<{ ep: Episode; chars: (Character & { checked: boolean })[]; cached: boolean; reviewed: boolean; reviewedAuto: boolean } | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestSaving, setSuggestSaving] = useState(false);
  const [suggestRemove, setSuggestRemove] = useState<string[]>([]);
  const [epRemove, setEpRemove] = useState<string[]>([]);
  const [showProjectChars, setShowProjectChars] = useState(false);
  const [newCharName, setNewCharName] = useState('');
  const [newCharAliases, setNewCharAliases] = useState('');
  const [busyEpisodes, setBusyEpisodes] = useState<Record<string, boolean>>({});
  const [syncingScripts, setSyncingScripts] = useState(false);
  const mergePollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isPollingProject = useRef(false);

  const load = useCallback(async () => {
    if (!projectId || isPollingProject.current) return;
    isPollingProject.current = true;
    try {
      const p = await projectService.get(projectId);
      setProject(p);
    } catch {
      addToast({ type: 'error', message: 'Không tìm thấy dự án phim' });
      navigate('/projects');
    } finally {
      isPollingProject.current = false;
      setLoading(false);
    }
  }, [projectId, navigate, addToast]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const timer = setInterval(() => {
      if (project?.episodes?.some(e => ['running', 'queueing', 'awaiting', 'awaiting_result'].includes(e.status))) {
        load();
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [project, load]);

  useEffect(() => {
    return () => {
      if (mergePollRef.current) clearInterval(mergePollRef.current);
    };
  }, []);

  if (loading || !project) {
    return <div className={styles.page}><div className={styles.loading}>Đang tải dữ liệu phim...</div></div>;
  }

  const stats = projectStats(project.episodes || []);
  // Đồng bộ episode đang mở với dữ liệu mới nhất (poll mỗi 2.5s) để drawer hiện kịch bản live
  const liveEpisode = selectedEp
    ? (project?.episodes?.find(e => e.id === selectedEp.id) ?? selectedEp)
    : null;
  // Episode đang xem kịch bản kiểu rạp hát — đồng bộ live giống drawer
  const scriptEp = scriptEpId
    ? (project?.episodes?.find(e => e.id === scriptEpId) ?? null)
    : null;
  const scriptEpIndex = scriptEp
    ? (project?.episodes || []).findIndex(e => e.id === scriptEp.id)
    : -1;

  const handleUpload = async () => {
    if (!uploadFiles.length || !projectId) return;
    setUploading(true);
    try {
      await episodeService.add(projectId, uploadFiles, uploadConfig);
      addToast({ type: 'success', message: `Đã thêm thành công ${uploadFiles.length} tập phim` });
      setShowUpload(false);
      setUploadFiles([]);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Tải tập phim thất bại' });
    } finally {
      setUploading(false);
    }
  };

  const handleProcessAll = async () => {
    setProcessing(true);
    try {
      const r = await projectService.processAll(projectId!);
      addToast({ type: 'info', message: `Đã đưa ${r.enqueued} tập vào hàng đợi xử lý` });
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Thao tác thất bại' });
    } finally {
      setProcessing(false);
    }
  };

  const handleMerge = async () => {
    const completedIds = (project.episodes || [])
      .filter(e => e.status === 'completed')
      .map(e => e.id);
    if (completedIds.length < 2) {
      addToast({ type: 'error', message: 'Cần ít nhất 2 tập hoàn thành để ghép trọn bộ.' });
      return;
    }
    setMergeSelected(completedIds);
    setShowMerge(true);
  };

  const doMerge = async () => {
    if (mergeSelected.length < 2) {
      addToast({ type: 'error', message: 'Vui lòng chọn ít nhất 2 tập để ghép.' });
      return;
    }
    setMerging(true);
    setShowMerge(false);
    try {
      const r = await projectService.merge(projectId!, mergeSelected);
      setMergeTask({ id: r.task_id, progress: 0, message: 'Đang khởi tạo ghép video...' });
      if (mergePollRef.current) clearInterval(mergePollRef.current);
      mergePollRef.current = setInterval(async () => {
        try {
          const task = await taskService.get(r.task_id);
          setMergeTask({ id: r.task_id, progress: task.progress, message: task.message });
          if (task.status === 'completed' && task.result) {
            if (mergePollRef.current) clearInterval(mergePollRef.current);
            const res = task.result as unknown as LastMergeInfo;
            setMergeTask(null);
            setMerging(false);
            addToast({ type: 'success', message: `Đã ghép thành công ${res.source_count || 2} tập thành 1 video!` });
            load();
            handleWatchMerged(res);
          } else if (task.status === 'failed') {
            if (mergePollRef.current) clearInterval(mergePollRef.current);
            setMergeTask(null);
            setMerging(false);
            addToast({ type: 'error', message: task.error || 'Ghép video thất bại' });
          }
        } catch {}
      }, 1500);
    } catch (e) {
      setMerging(false);
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Ghép video thất bại' });
    }
  };

  const handleWatchEpisode = (ep: Episode, index: number) => {
    setVideoPreview({
      open: true,
      onClose: () => setVideoPreview(null),
      title: `${episodeLabel(ep.filename, index)}: ${ep.filename}`,
      badge: 'Tập tóm tắt',
      videoUrl: ep.result_url,
      srtUrl: ep.srt_url,
      metaItems: [
        { label: 'Tập phim', value: episodeLabel(ep.filename, index) },
        { label: 'Tệp gốc', value: ep.filename },
        { label: 'Hoàn tất lúc', value: formatDate(ep.completed_at || ep.created_at) },
        { label: 'Phụ đề SRT', value: ep.srt_url ? 'Có sẵn (Bấm câu thoại để tua video)' : 'Không có' },
      ],
      downloadVideoUrl: ep.result_url,
      downloadSrtUrl: ep.srt_url,
    });
  };

  const handleWatchMerged = (mergeInfo: LastMergeInfo) => {
    setVideoPreview({
      open: true,
      onClose: () => setVideoPreview(null),
      title: `Phim gộp trọn bộ: ${project?.name || ''}`,
      badge: 'Phim gộp liên tục',
      videoUrl: mergeInfo.video_url,
      srtUrl: mergeInfo.srt_url,
      merge: {
        episode_ranges: mergeInfo.episode_ranges || [],
        total_duration: mergeInfo.total_duration,
      },
      metaItems: [
        { label: 'Dự án', value: project?.name || '' },
        { label: 'Số tập gộp', value: `${mergeInfo.source_count || mergeInfo.episode_ranges?.length || 0} tập` },
        { label: 'Phụ đề SRT', value: mergeInfo.srt_url ? 'Đã gộp đồng bộ (Bấm câu thoại để tua)' : 'Không có' },
      ],
      downloadVideoUrl: mergeInfo.video_url,
      downloadSrtUrl: mergeInfo.srt_url,
    });
  };

  const openEpConfig = (ep: Episode) => {
    const opt = ep.options || {};
    setEpConfigValues({
      mode: opt.mode || project?.settings?.mode || 'api',
      voice_id: opt.voice_id || '',
      model: opt.model || '',
      style: opt.style || '',
      detail: opt.detail || '',
      custom_minutes: opt.custom_minutes || '',
      edit_mode: opt.edit_mode || project?.settings?.edit_mode || 'smart_shot',
      character_name_mode: opt.character_name_mode || project?.settings?.character_name_mode || 'romaji',
      free_order: opt.free_order || project?.settings?.free_order || '0',
      fx_flip: opt.fx_flip || project?.settings?.fx_flip || '1',
      fx_zoom: opt.fx_zoom || project?.settings?.fx_zoom || '1',
      fx_speed: opt.fx_speed || project?.settings?.fx_speed || '1',
      fx_reverse: opt.fx_reverse || project?.settings?.fx_reverse || '1',
    });
    setConfigEp(ep);
  };

  const saveEpConfig = async (runNow = false) => {
    if (!configEp || !projectId) return;
    setSavingEpConfig(true);
    try {
      await episodeService.updateOptions(projectId, configEp.id, epConfigValues);
      addToast({ type: 'success', message: `Đã lưu cài đặt cho ${episodeLabel(configEp.filename, 0)}` });
      const targetEpId = configEp.id;
      const prevStatus = configEp.status;
      const targetMode = epConfigValues.mode || 'api';
      setConfigEp(null);

      if (runNow) {
        if (['completed', 'failed'].includes(prevStatus)) {
          await episodeService.retry(projectId, targetEpId);
          addToast({ type: 'info', message: 'Đã đưa vào hàng đợi để chạy lại với cấu hình mới' });
        } else {
          if (targetMode === 'manual') await episodeService.manualRun(projectId, targetEpId);
          else await episodeService.process(projectId, targetEpId);
          addToast({ type: 'info', message: 'Đã bắt đầu xử lý với cấu hình mới' });
        }
      }
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lưu cấu hình thất bại' });
    } finally {
      setSavingEpConfig(false);
    }
  };

  const handleEpisodeAction = async (action: string, ep: Episode) => {
    // Các thao tác mở dialog/modal xem thì không cần gọi API nền
    if (action === 'retry' || action === 'reprocess') {
      setConfirmRerun({ ep, fromConfig: false });
      return;
    }
    if (action === 'delete') { setDeleteEp(ep); return; }
    if (action === 'config') { openEpConfig(ep); return; }
    if (action === 'view') {
      if (ep.options?.mode === 'manual' && ep.status === 'awaiting_result') { setSelectedEp(ep); return; }
      setScriptEpId(ep.id); return;
    }
    if (action === 'watch') {
      const epIndex = (project?.episodes || []).findIndex(e => e.id === ep.id);
      handleWatchEpisode(ep, epIndex >= 0 ? epIndex : 0);
      return;
    }

    // Chống spam click kép / xung đột đồng thời trên cùng 1 tập
    if (busyEpisodes[ep.id]) return;
    setBusyEpisodes(prev => ({ ...prev, [ep.id]: true }));

    try {
      if (action === 'run') {
        if (ep.options?.mode === 'manual') await episodeService.manualRun(projectId!, ep.id);
        else await episodeService.process(projectId!, ep.id);
        addToast({ type: 'info', message: `Đã bắt đầu xử lý ${ep.filename}` });
      }
      else if (action === 'cancel') {
        await episodeService.cancel(projectId!, ep.id);
        addToast({ type: 'info', message: 'Đã hủy tác vụ' });
      }
      else if (action === 'prepare') {
        await episodeService.manualPrepare(projectId!, ep.id);
        addToast({ type: 'info', message: 'Đã chuẩn bị prompt xong — hãy dán kịch bản' });
      }
      else if (action === 'suggest') {
        await suggestCharactersForProject(ep);
        return;
      }
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Thao tác thất bại' });
    } finally {
      setBusyEpisodes(prev => {
        const next = { ...prev };
        delete next[ep.id];
        return next;
      });
    }
  };

  const handleRerunConfirm = () => {
    const c = confirmRerun;
    if (!c) return;
    setConfirmRerun(null);
    if (c.fromConfig) { void saveEpConfig(true); return; }
    episodeService.retry(projectId!, c.ep.id).then(() => {
      addToast({ type: 'info', message: 'Đã đưa vào hàng đợi để chạy lại' });
      load();
    }).catch((e: unknown) => {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không thể chạy lại' });
    });
  };

  const confirmDelete = async () => {
    if (!deleteEp) return;
    await episodeService.delete(projectId!, deleteEp.id);
    addToast({ type: 'success', message: 'Đã xóa tập phim khỏi dự án' });
    setDeleteEp(null);
    load();
  };

  const suggestCharactersForProject = async (ep: Episode) => {
    setSuggestLoading(true);
    try {
      const res = await episodeService.getCharacters(projectId!, ep.id);
      const existing = new Set((project?.characters || []).map(c => c.name.toLowerCase()));
      setSuggestRemove([]);
      setEpRemove([]);
      setSuggestState({
        ep,
        cached: false,
        chars: res.characters.map(c => ({ ...c, checked: !existing.has(c.name.toLowerCase()) })),
        reviewed: !!res.reviewed,
        reviewedAuto: !!res.reviewed_auto,
      });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Không lấy được nhân vật của tập' });
    } finally {
      setSuggestLoading(false);
    }
  };

  const recreateCharacters = async () => {
    if (!suggestState) return;
    setSuggestLoading(true);
    try {
      const res = await episodeService.suggestCharacters(projectId!, suggestState.ep.id, true);
      const existing = new Set((project?.characters || []).map(c => c.name.toLowerCase()));
      setSuggestRemove([]);
      setEpRemove([]);
      setSuggestState(prev => prev ? {
        ...prev,
        cached: false,
        chars: res.characters.map(c => ({ ...c, checked: !existing.has(c.name.toLowerCase()) })),
      } : prev);
      addToast({ type: 'success', message: `Đã trích xuất lại ${res.characters.length} nhân vật — ghi đè dữ liệu cũ của tập` });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Trích xuất lại thất bại' });
    } finally {
      setSuggestLoading(false);
    }
  };

  const updateSuggestChar = (i: number, patch: Partial<Character & { checked: boolean }>) => {
    setSuggestState(prev => prev ? {
      ...prev,
      chars: prev.chars.map((c, j) => (j === i ? { ...c, ...patch } : c)),
    } : prev);
  };

  const saveSuggestions = async () => {
    if (!suggestState) return;
    const removed = new Set(epRemove);
    const epChars: Character[] = suggestState.chars
      .filter(c => !removed.has(c.name.toLowerCase()))
      .map(({ name, aliases }) => ({ name: name.trim(), aliases: aliases.filter(a => a && a.trim() !== name.trim()) }));
    const picked: Character[] = suggestState.chars
      .filter(c => c.checked && !removed.has(c.name.toLowerCase()))
      .map(({ name, aliases }) => ({ name: name.trim(), aliases: aliases.filter(a => a && a.trim() !== name.trim()) }));
    const toRemove = new Set(suggestRemove);
    if (!picked.length && toRemove.size === 0 && epChars.length === suggestState.chars.length) {
      addToast({ type: 'warning', message: 'Chưa có thay đổi nào — sửa tên/alias, tick các nhân vật muốn chốt vào dự án, hoặc bỏ với ✕' });
      return;
    }
    const combined: Character[] = (project?.characters || []).filter(c => !toRemove.has(c.name.toLowerCase()));
    for (const n of picked) {
      const idx = combined.findIndex(e => e.name.toLowerCase() === n.name.toLowerCase());
      if (idx >= 0) combined[idx] = n;
      else combined.push(n);
    }
    setSuggestSaving(true);
    try {
      await episodeService.saveEpisodeCharacters(projectId!, suggestState.ep.id, epChars);
      const updated = await projectService.saveCharacters(projectId!, combined);
      setProject(prev => prev ? { ...prev, characters: updated.characters || [] } : prev);
      const epMsg = `${epChars.length} nhân vật của tập (dùng chung cho các tập sau)`;
      const approvedMsg = toRemove.size > 0 ? ` · gỡ ${toRemove.size} khỏi dự án` : (picked.length > 0 ? ` · chốt ${picked.length} vào dự án` : '');
      addToast({ type: 'success', message: `Đã lưu ${epMsg}${approvedMsg}` });
      setSuggestState(null);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lưu nhân vật thất bại' });
    } finally {
      setSuggestSaving(false);
    }
  };

  const toggleReviewed = async () => {
    if (!suggestState || !projectId) return;
    const next = !suggestState.reviewed;
    setSuggestLoading(true);
    try {
      const res = await episodeService.setCharactersReviewed(projectId, suggestState.ep.id, next);
      setSuggestState(prev => prev ? { ...prev, reviewed: res.reviewed, reviewedAuto: false } : prev);
      addToast({
        type: 'success',
        message: res.reviewed
          ? 'Đã đánh dấu đã xét — nhân vật riêng của tập sẽ không gửi vào prompt các tập sau (chỉ còn bảng chung)'
          : 'Đã bỏ xét — nhân vật của tập sẽ được gửi kèm vào prompt các tập sau',
      });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Đổi trạng thái xét thất bại' });
    } finally {
      setSuggestLoading(false);
    }
  };

  const handleAddProjectChar = async () => {
    if (!newCharName.trim() || !projectId) return;
    const name = newCharName.trim();
    const aliases = newCharAliases.split(',').map(a => a.trim()).filter(Boolean);
    const current = project?.characters || [];
    if (current.some(c => c.name.toLowerCase() === name.toLowerCase())) {
      addToast({ type: 'warning', message: `Nhân vật "${name}" đã có trong danh sách` });
      return;
    }
    const updated = [...current, { name, aliases }];
    try {
      const res = await projectService.saveCharacters(projectId, updated);
      setProject(prev => prev ? { ...prev, characters: res.characters || [] } : prev);
      setNewCharName('');
      setNewCharAliases('');
      addToast({ type: 'success', message: `Đã thêm nhân vật "${name}"` });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Thêm nhân vật thất bại' });
    }
  };

  const handleRemoveProjectChar = async (charName: string) => {
    if (!projectId) return;
    const current = (project?.characters || []).filter(c => c.name.toLowerCase() !== charName.toLowerCase());
    try {
      const res = await projectService.saveCharacters(projectId, current);
      setProject(prev => prev ? { ...prev, characters: res.characters || [] } : prev);
      addToast({ type: 'info', message: `Đã gỡ nhân vật "${charName}" khỏi dự án` });
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Gỡ nhân vật thất bại' });
    }
  };

  const handleSyncScripts = async () => {
    if (!projectId) return;
    setSyncingScripts(true);
    try {
      const res = await projectService.syncCharactersToScripts(projectId);
      addToast({ type: 'success', message: res.message });
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Đồng bộ kịch bản thất bại' });
    } finally {
      setSyncingScripts(false);
    }
  };

  const openSettings = () => {
    setSettingsName(project.name);
    setSettingsConfig({
      mode: project.settings?.mode || 'api',
      voice_id: project.settings?.voice_id || '',
      model: project.settings?.model || '',
      style: project.settings?.style || 'narrative',
      detail: project.settings?.detail || defaultDetail,
      custom_minutes: project.settings?.custom_minutes || '',
      edit_mode: project.settings?.edit_mode || 'smart_shot',
      character_name_mode: project.settings?.character_name_mode || 'romaji',
      free_order: project.settings?.free_order || '0',
      fx_flip: project.settings?.fx_flip || '1',
      fx_zoom: project.settings?.fx_zoom || '1',
      fx_speed: project.settings?.fx_speed || '1',
      fx_reverse: project.settings?.fx_reverse || '1',
    });
    setSettingsDesc(project.settings?.series_description || '');
    setShowSettings(true);
  };

  const openUpload = () => {
    setUploadConfig({
      mode: project.settings?.mode || 'api',
      voice_id: '',
      model: '',
      style: '',
      detail: '',
      custom_minutes: '',
      edit_mode: project.settings?.edit_mode || 'smart_shot',
      character_name_mode: project.settings?.character_name_mode || 'romaji',
      free_order: project.settings?.free_order || '0',
      fx_flip: project.settings?.fx_flip || '1',
      fx_zoom: project.settings?.fx_zoom || '1',
      fx_speed: project.settings?.fx_speed || '1',
      fx_reverse: project.settings?.fx_reverse || '1',
    });
    setShowUpload(true);
  };

  const saveSettings = async () => {
    setSavingSettings(true);
    try {
      await projectService.update(projectId!, {
        name: settingsName.trim() || project.name,
        settings: { ...settingsConfig, series_description: settingsDesc },
      });
      addToast({ type: 'success', message: 'Đã lưu cài đặt mặc định phim' });
      setShowSettings(false);
      load();
    } catch (e) {
      addToast({ type: 'error', message: e instanceof Error ? e.message : 'Lưu thất bại' });
    } finally {
      setSavingSettings(false);
    }
  };

  return (
    <div className={styles.page}>
      <PageHeader
        title={project.name}
        subtitle={`${stats.total} tập phim · ${stats.completed} hoàn thành`}
        back={{ label: 'Danh sách phim', onClick: () => navigate('/projects') }}
        actions={
          <>
            <Button icon="plus" onClick={openUpload}>Thêm tập</Button>
            <Button variant="secondary" icon="play" onClick={handleProcessAll} loading={processing}>
              Chạy tất cả
            </Button>
            <Button variant="secondary" icon="layers" onClick={handleMerge} loading={merging} disabled={stats.completed < 2}>
              Ghép trọn bộ ({stats.completed})
            </Button>
            <Button variant="ghost" icon="users" onClick={() => setShowProjectChars(true)}>
              Nhân vật ({project.characters?.length || 0})
            </Button>
            <IconButton icon="settings" label="Cài đặt phim" onClick={openSettings} />
          </>
        }
      />

      <div className={styles.overview}>
        <StatCard label="Tổng số tập" value={stats.total} icon="layers" />
        <StatCard label="Hoàn thành" value={stats.completed} icon="check-circle" accent="success" />
        <StatCard label="Đang xử lý" value={stats.processing} icon="activity" accent="primary" />
        <StatCard label="Chờ xử lý" value={stats.pending} icon="clock" accent="warning" />
        <StatCard label="Thất bại" value={stats.failed} icon="alert" accent={stats.failed ? 'error' : 'default'} />
        <StatCard label="Tiến độ phim" value={`${stats.progress}%`} icon="activity" accent="info" />
      </div>

      {project.settings?.last_merge && (
        <div className={styles.mergeBanner}>
          <div className={styles.mergeBannerLeft}>
            <span className={styles.mergeBannerIcon}><Icon name="film" size={22} /></span>
            <div>
              <div className={styles.mergeBannerTitle}>Video ghép trọn bộ đã sẵn sàng</div>
              <div className={styles.mergeBannerSubtitle}>
                Đã ghép {project.settings.last_merge.source_count || project.settings.last_merge.episode_ranges?.length || stats.completed} tập phim thành một video liền mạch
              </div>
            </div>
          </div>
          <div className={styles.mergeBannerActions}>
            <Button icon="play" onClick={() => handleWatchMerged(project.settings!.last_merge!)}>
              Xem trọn bộ
            </Button>
            {project.settings.last_merge.video_url && (
              <a href={project.settings.last_merge.video_url} download target="_blank" rel="noreferrer" className={styles.linkBtn}>
                <Button variant="secondary" icon="download">Tải MP4</Button>
              </a>
            )}
            {project.settings.last_merge.srt_url && (
              <a href={project.settings.last_merge.srt_url} download target="_blank" rel="noreferrer" className={styles.linkBtn}>
                <Button variant="secondary" icon="download">Tải SRT</Button>
              </a>
            )}
          </div>
        </div>
      )}

      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Tập Phim & File Gốc</th>
              <th>Cấu Hình Xử Lý</th>
              <th>Trạng Thái & Tiến Trình</th>
              <th style={{ textAlign: 'right' }}>Thao Tác</th>
            </tr>
          </thead>
          <tbody>
            {(project.episodes || []).map((ep, i) => (
              <EpisodeRow
                key={ep.id}
                ep={ep}
                index={i}
                voices={voices}
                models={models}
                detailLevels={detailLevels}
                settings={project.settings}
                busy={!!busyEpisodes[ep.id]}
                onAction={action => handleEpisodeAction(action, ep)}
              />
            ))}
          </tbody>
        </table>
        {!project.episodes?.length && (
          <EmptyState
            glyph="upload"
            title="Chưa có tập phim nào"
            description="Bấm “Thêm tập” để tải video lên và bắt đầu tóm tắt."
            action={{ label: 'Thêm tập mới', onClick: openUpload }}
          />
        )}
      </div>

      <Modal
        open={showUpload}
        onClose={() => setShowUpload(false)}
        title="Thêm tập phim vào dự án"
        icon="upload"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowUpload(false)}>Đóng</Button>
            <Button icon="upload" onClick={handleUpload} loading={uploading} disabled={!uploadFiles.length}>
              Tải lên {uploadFiles.length ? `(${uploadFiles.length} file)` : ''}
            </Button>
          </>
        }
      >
        <UploadZone onFiles={files => setUploadFiles(prev => [...prev, ...files])} />
        <FileList items={uploadFiles.map(f => ({ file: f }))} onRemove={i => setUploadFiles(prev => prev.filter((_, j) => j !== i))} />
        <ConfigPanel
          config={uploadConfig}
          onChange={c => setUploadConfig(prev => ({ ...prev, ...c }))}
          voices={voices}
          models={models}
          detailLevels={detailLevels}
          defaultDetail={defaultDetail}
          projectDefaults={project.settings as Record<string, string | undefined>}
        />
      </Modal>

      <EpisodeDetailDrawer
        episode={liveEpisode}
        projectId={projectId!}
        onClose={() => { setSelectedEp(null); load(); }}
        onEditConfig={openEpConfig}
        voices={voices}
        models={models}
      />

      {scriptEp && (
        <ScriptTheaterModal
          open
          onClose={() => setScriptEpId(null)}
          episode={scriptEp}
          title={`Kịch bản: ${episodeLabel(scriptEp.filename, scriptEpIndex >= 0 ? scriptEpIndex : 0)}`}
          badge={['running', 'queueing'].includes(scriptEp.status) ? 'Đang dựng' : scriptEp.status === 'completed' ? 'Kịch bản AI' : scriptEp.status === 'failed' ? 'Thất bại' : 'Kịch bản'}
          live={['running', 'queueing'].includes(scriptEp.status)}
          onEditConfig={!['running', 'queueing'].includes(scriptEp.status)
            ? () => { const ep = scriptEp; setScriptEpId(null); openEpConfig(ep); }
            : undefined}
        />
      )}

      <Modal
        open={!!configEp}
        onClose={() => setConfigEp(null)}
        title={`Cài đặt riêng cho tập: ${configEp ? episodeLabel(configEp.filename, 0) : ''}`}
        icon="settings"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfigEp(null)}>Đóng</Button>
            <Button variant="secondary" icon="check" onClick={() => saveEpConfig(false)} loading={savingEpConfig}>
              Lưu cài đặt
            </Button>
            {configEp && ['pending', 'cancelled'].includes(configEp.status) && (
              <Button icon="play" onClick={() => saveEpConfig(true)} loading={savingEpConfig}>
                Lưu &amp; tạo video
              </Button>
            )}
            {configEp && configEp.status === 'completed' && (
              <Button icon="refresh" onClick={() => setConfirmRerun({ ep: configEp, fromConfig: true })} loading={savingEpConfig}>
                Lưu &amp; chạy lại
              </Button>
            )}
            {configEp && configEp.status === 'failed' && (
              <Button icon="refresh" onClick={() => setConfirmRerun({ ep: configEp, fromConfig: true })} loading={savingEpConfig}>
                Lưu &amp; thử lại
              </Button>
            )}
          </>
        }
      >
        {configEp && (
          <div>
            <div className={styles.fileBadge}>
              <div className={styles.fileBadgeName}>
                <span className={styles.fileBadgeLabel}>Tệp video:</span>
                <span className={styles.fileBadgeValue} title={configEp.filename}>{configEp.filename}</span>
              </div>
              <StatusBadge status={configEp.status} />
            </div>
            <p className={styles.settingsHint} style={{ marginBottom: 12 }}>
              Cấu hình riêng này sẽ được áp dụng khi tạo video cho tập này. Các mục để trống sẽ tự động lấy theo cài đặt chung của phim.
            </p>
            <ConfigPanel
              config={epConfigValues}
              onChange={c => setEpConfigValues(prev => ({ ...prev, ...c }))}
              voices={voices}
              models={models}
              detailLevels={detailLevels}
              defaultDetail={defaultDetail}
              projectDefaults={project.settings as Record<string, string | undefined>}
            />
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!deleteEp}
        onClose={() => setDeleteEp(null)}
        onConfirm={confirmDelete}
        title={`Xóa tập "${deleteEp?.filename}"?`}
        message="Hành động này sẽ gỡ bỏ tập phim khỏi dự án và giải phóng các dữ liệu liên quan."
      />

      <ConfirmDialog
        open={!!confirmRerun}
        onClose={() => setConfirmRerun(null)}
        onConfirm={handleRerunConfirm}
        title={`Chạy lại tập "${confirmRerun?.ep.filename || ''}"?`}
        confirmLabel="Chạy Lại"
        danger={false}
        message={confirmRerun
          ? (confirmRerun.fromConfig
              ? 'Cấu hình sẽ được lưu rồi tạo lại từ đầu. Toàn bộ kịch bản AI, giọng đọc và video thành phẩm sẽ được tái sinh — tốn thời gian và token.'
              : 'Hành động này sẽ tạo lại từ đầu toàn bộ kịch bản AI, giọng đọc và video thành phẩm — tốn thời gian và token.')
          : ''}
      />

      <Modal
        open={showSettings}
        onClose={() => setShowSettings(false)}
        title="Cài đặt mặc định phim"
        icon="settings"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowSettings(false)}>Hủy</Button>
            <Button icon="check" onClick={saveSettings} loading={savingSettings}>Lưu cài đặt</Button>
          </>
        }
      >
        <label className={styles.label}>Tên dự án / Anime</label>
        <input
          className={styles.settingsInput}
          value={settingsName}
          onChange={e => setSettingsName(e.target.value)}
        />
        <p className={styles.settingsHint}>Cài đặt mặc định sẽ tự động áp dụng cho các tập thêm mới hoặc chạy lại.</p>
        <label className={styles.label}>Mô tả cốt truyện series</label>
        <textarea
          className={styles.settingsTextarea}
          rows={5}
          placeholder="Mô tả ngắn về nội dung/bối cảnh toàn bộ series: nhân vật chính, quan hệ, mạch truyện chính... Nội dung này sẽ được đưa vào prompt của mọi tập như bối cảnh."
          value={settingsDesc}
          onChange={e => setSettingsDesc(e.target.value)}
        />
        <p className={styles.settingsHint}>Dùng làm bối cảnh cho AI hiểu diễn biến xuyên các tập; không bắt buộc.</p>
        <ConfigPanel
          config={settingsConfig}
          onChange={c => setSettingsConfig(prev => ({ ...prev, ...c }))}
          voices={voices}
          models={models}
          detailLevels={detailLevels}
          defaultDetail={defaultDetail}
        />
        {project && (
          <VoiceRefPanel
            projectId={project.id}
            refAudio={project.settings?.tts_ref_audio}
            refText={project.settings?.tts_ref_text}
            onChanged={(refAudio, refText) =>
              setProject(prev => prev && ({
                ...prev,
                settings: { ...prev.settings, tts_ref_audio: refAudio, tts_ref_text: refText },
              }))
            }
          />
        )}
      </Modal>

      <Modal
        open={showMerge}
        onClose={() => setShowMerge(false)}
        title="Ghép video trọn bộ"
        icon="layers"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowMerge(false)}>Hủy</Button>
            <Button onClick={doMerge} loading={merging} disabled={mergeSelected.length < 2}>
              Bắt Đầu Ghép ({mergeSelected.length} tập)
            </Button>
          </>
        }
      >
        <p className={styles.settingsHint} style={{ marginBottom: 12 }}>
          Chọn các tập đã hoàn thành để ghép thành 1 video dài liên tục kèm phụ đề tổng hợp:
        </p>
        <div className={styles.mergeList}>
          {(project.episodes || [])
            .filter(e => e.status === 'completed')
            .map((ep, i) => {
              const checked = mergeSelected.includes(ep.id);
              return (
                <label
                  key={ep.id}
                  className={`${styles.mergeItem}${checked ? ' ' + styles.mergeItemChecked : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      setMergeSelected(prev =>
                        checked ? prev.filter(id => id !== ep.id) : [...prev, ep.id],
                      )
                    }
                  />
                  <span className={styles.mergeEpNo}>{episodeLabel(ep.filename, i)}</span>
                  <span className={styles.mergeDur}><Icon name="check" size={12} /> Hoàn thành</span>
                </label>
              );
            })}
        </div>
      </Modal>

      <Modal
        open={!!suggestState}
        onClose={() => { if (!suggestSaving) setSuggestState(null); }}
        title={suggestState
          ? `Nhân vật của tập — ${episodeLabel(suggestState.ep.filename, Math.max(0, (project?.episodes || []).findIndex(e => e.id === suggestState.ep.id)))}`
          : 'Nhân vật của tập'}
        icon="users"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setSuggestState(null)} disabled={suggestSaving}>Đóng</Button>
            <Button variant="ghost" icon="wand" onClick={recreateCharacters} loading={suggestLoading} disabled={suggestSaving || !suggestState}>
              Tạo lại nhân vật
            </Button>
            <Button icon="check" onClick={saveSuggestions} loading={suggestSaving} disabled={suggestLoading}>
              Lưu nhân vật
            </Button>
          </>
        }
      >
        <p className={styles.settingsHint} style={{ marginBottom: 12 }}>
          Danh sách là <b>nhân vật đang lưu của tập này</b> — được gộp chung cho các tập sau
          <b> khi tập này chưa xét</b>. Tập đã xét thì prompt các tập sau chỉ còn bảng chung + nhân vật các tập chưa xét.
          Sửa tên/alias rồi Lưu để đổi (Lưu = đánh dấu đã xét). Nút gỡ bỏ khỏi tập, ô tick để chốt tên chuẩn vào dự án.
        </p>
        {suggestState && (
          <div className={styles.chipsRow}>
            <Badge tone={suggestState.reviewed ? 'success' : 'warning'} dot>
              {suggestState.reviewed
                ? (suggestState.reviewedAuto ? 'Đã xét (tự động)' : 'Đã xét')
                : 'Chưa xét'}
            </Badge>
            <Button
              variant="ghost"
              size="sm"
              icon="refresh"
              onClick={toggleReviewed}
              loading={suggestLoading}
              disabled={suggestSaving}
              title={suggestState.reviewed
                ? 'Bỏ xét: nhân vật của tập sẽ được gửi kèm vào prompt các tập sau'
                : 'Đánh dấu đã xét: prompt các tập sau chỉ còn bảng chung + tập chưa xét'}
            >
              {suggestState.reviewed ? 'Bỏ xét' : 'Đánh dấu đã xét'}
            </Button>
          </div>
        )}
        <p className={styles.settingsHint} style={{ marginBottom: 12, opacity: 0.7 }}>
          Nút <b>Tạo lại nhân vật</b> gửi kịch bản lại cho AI, ghi đè dữ liệu cũ của tập. Kịch bản chưa đổi mà không bấm nút đó thì mỗi bản chạy đều dùng cache, không tốn AI.
        </p>
        {!!project?.characters?.length && (
          <div style={{ marginBottom: 12 }}>
            <p className={styles.settingsHint} style={{ marginBottom: 6, opacity: 0.7 }}>
              Nhân vật đã chốt trong dự án (bấm gỡ để bỏ):
            </p>
            {project.characters.map((c, j) => {
              const removing = suggestRemove.includes(c.name.toLowerCase());
              return (
                <div key={j} className={cn(styles.suggestRow, removing && styles.rowRemoving)}>
                  <IconButton
                    icon={removing ? 'refresh' : 'close'}
                    label={removing ? 'Bỏ gỡ' : 'Gỡ khỏi dự án'}
                    variant="ghost"
                    size="sm"
                    onClick={() => setSuggestRemove(prev =>
                      removing ? prev.filter(n => n !== c.name.toLowerCase()) : [...prev, c.name.toLowerCase()])}
                  />
                  <span className={cn(styles.suggestNameStatic, removing && styles.strike)}>{c.name}</span>
                  <span className={styles.suggestAliasStatic}>{c.aliases.join(', ')}</span>
                </div>
              );
            })}
          </div>
        )}
        {suggestLoading ? (
          <p className={styles.settingsHint}>Đang xử lý kịch bản…</p>
        ) : suggestState && suggestState.chars.length === 0 ? (
          <p className={styles.settingsHint}>Chưa có nhân vật lưu cho tập này. Bấm <b>Tạo lại nhân vật</b> để AI trích xuất (hoặc để tự động sau khi tập chạy xong).</p>
        ) : (
          suggestState?.chars.map((c, i) => {
            const removing = epRemove.includes(c.name.toLowerCase());
            return (
              <div key={i} className={cn(styles.suggestRow, removing && styles.rowRemoving)}>
                <IconButton
                  icon={removing ? 'refresh' : 'close'}
                  label={removing ? 'Giữ lại trong tập' : 'Gỡ khỏi nhân vật của tập'}
                  variant="ghost"
                  size="sm"
                  onClick={() => setEpRemove(prev =>
                    removing ? prev.filter(n => n !== c.name.toLowerCase()) : [...prev, c.name.toLowerCase()])}
                />
                <input
                  type="checkbox"
                  className={styles.suggestCheckbox}
                  checked={c.checked}
                  disabled={removing}
                  onChange={e => updateSuggestChar(i, { checked: e.target.checked })}
                />
                <input
                  className={cn(styles.suggestNameInput, removing && styles.strike)}
                  value={c.name}
                  disabled={removing}
                  onChange={e => updateSuggestChar(i, { name: e.target.value })}
                  placeholder="Tên nhân vật"
                />
                <input
                  className={styles.suggestAliasInput}
                  value={c.aliases.join(', ')}
                  disabled={removing}
                  onChange={e => updateSuggestChar(i, { aliases: e.target.value.split(',').map(x => x.trim()).filter(Boolean) })}
                  placeholder="Alias / tên gọi khác, phân tách bằng dấu phẩy"
                />
              </div>
            );
          })
        )}
      </Modal>

      <Modal
        open={showProjectChars}
        onClose={() => setShowProjectChars(false)}
        title={`Quản lý nhân vật phim: ${project.name}`}
        icon="users"
        size="lg"
        footer={
          <>
            <Button variant="ghost" onClick={() => setShowProjectChars(false)}>Đóng</Button>
            <Button
              variant="secondary"
              icon="refresh"
              onClick={handleSyncScripts}
              loading={syncingScripts}
              disabled={!project.characters?.length}
              title="Áp dụng tên chuẩn và alias vào kịch bản các tập đã có"
            >
              Đồng bộ tên vào kịch bản
            </Button>
          </>
        }
      >
        <p className={styles.settingsHint} style={{ marginBottom: 14 }}>
          Danh sách nhân vật chính thức của phim — được <b>ưu tiên cao nhất</b> khi đưa vào prompt của mọi tập.
          Bạn có thể thêm trước các nhân vật chính ngay từ đầu, hoặc bấm <b>Đồng bộ tên vào kịch bản</b> để tự động chuẩn hóa tên nhân vật trong toàn bộ các tập đã chạy.
        </p>

        <div className={styles.charAddRow}>
          <input
            className={styles.settingsInput}
            placeholder="Tên nhân vật chính (VD: Jin)"
            value={newCharName}
            onChange={e => setNewCharName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleAddProjectChar(); }}
          />
          <input
            className={styles.settingsInput}
            placeholder="Alias / tên gọi khác, cách nhau bằng dấu phẩy (VD: Cậu bé, Tiểu Jin)"
            value={newCharAliases}
            onChange={e => setNewCharAliases(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleAddProjectChar(); }}
          />
          <Button icon="plus" onClick={handleAddProjectChar} disabled={!newCharName.trim()}>Thêm</Button>
        </div>

        <div className={styles.charListWrap}>
          {project.characters && project.characters.length > 0 ? (
            project.characters.map((c, idx) => (
              <div key={idx} className={styles.charRow}>
                <IconButton icon="trash" label={`Gỡ "${c.name}" khỏi dự án`} variant="danger" size="sm" onClick={() => handleRemoveProjectChar(c.name)} />
                <div className={styles.charNameCol}>{c.name}</div>
                <div className={styles.charAliasCol}>
                  {c.aliases && c.aliases.length > 0 ? c.aliases.join(', ') : <span className={styles.mutedItalic}>Không có alias</span>}
                </div>
              </div>
            ))
          ) : (
            <p className={styles.settingsHint} style={{ textAlign: 'center', padding: '24px 0' }}>
              Chưa có nhân vật nào được chốt cho phim này. Hãy nhập tên ở trên và bấm <b>Thêm</b>, hoặc chạy các tập để hệ thống tự động phát hiện.
            </p>
          )}
        </div>
      </Modal>

      {mergeTask && (
        <Modal
          open={!!mergeTask}
          onClose={() => { if (mergePollRef.current) clearInterval(mergePollRef.current); setMergeTask(null); setMerging(false); }}
          title="Đang ghép video trọn bộ…"
          size="sm"
        >
          <p className={styles.settingsHint}>Quá trình ghép đang diễn ra ngầm. Bạn có thể tiếp tục thao tác các tập khác.</p>
          <ProgressBar value={mergeTask.progress} animated={mergeTask.progress < 100} />
          <p className={styles.settingsHint} style={{ marginTop: 10 }}>{mergeTask.progress}% · {mergeTask.message}</p>
        </Modal>
      )}

      {videoPreview && (
        <VideoPreviewModal
          {...videoPreview}
          onClose={() => setVideoPreview(null)}
        />
      )}
    </div>
  );
}

function EpisodeRow({ ep, index, voices, models, detailLevels, settings, busy = false, onAction }: {
  ep: Episode;
  index: number;
  voices: Record<string, Voice>;
  models: Model[];
  detailLevels: Record<string, DetailLevel>;
  settings?: ProjectSettings;
  busy?: boolean;
  onAction: (a: string) => void;
}) {
  const opt = ep.options;
  const voiceKey = opt?.voice_id || settings?.voice_id || '';
  const modelKey = opt?.model || settings?.model || '';
  const detailKey = opt?.detail || settings?.detail || '';
  const styleKey = opt?.style || settings?.style || 'narrative';
  const customMinutes = opt?.custom_minutes || settings?.custom_minutes || '';
  const isManual = opt?.mode === 'manual';
  const isAwaiting = ep.status === 'awaiting_result' || ep.status === 'awaiting';
  const isRunning = ['running', 'queueing'].includes(ep.status);
  const voiceName = voices[voiceKey]?.name || voiceKey || 'Mặc định';
  const modelName = models.find(m => m.id === modelKey)?.name || modelKey || 'Default';
  const styleName = STYLE_OPTIONS.find(s => s.id === styleKey)?.name || styleKey || 'Kể chuyện';
  const detailName = detailKey === 'custom'
    ? (customMinutes ? `Tùy chỉnh (${customMinutes} phút)` : 'Tùy chỉnh')
    : (detailLevels[detailKey]?.name || detailKey || 'Vừa (~7p)');

  return (
    <tr className={isRunning ? styles.runningRow : ''}>
      <td className={styles.epMainCell}>
        <div className={styles.epName}>{episodeLabel(ep.filename, index)}</div>
        <div className={styles.fileName} title={ep.filename}>{ep.filename}</div>
      </td>

      <td className={styles.configCell}>
        <div className={styles.configChips}>
          <span className={isManual ? styles.modeBadgeManual : styles.modeBadgeApi}>
            {isManual ? 'Thủ công' : 'API tự động'}
          </span>
          <span className={styles.configVoice} title={`Giọng đọc: ${voiceName}`}>
            <Icon name="volume" size={11} /> {voiceName}
          </span>
        </div>
        <div className={styles.configSub}>
          <span><Icon name="clock" size={11} /> {detailName}</span>
          <span className={styles.configDot}>•</span>
          <span>{styleName}</span>
          {modelKey && (
            <>
              <span className={styles.configDot}>•</span>
              <span className={styles.configModel} title={`Model: ${modelName}`}>
                {modelKey.replace('gemini-', '')}
              </span>
            </>
          )}
        </div>
      </td>

      <td className={styles.statusProgressCell}>
        {isAwaiting ? (
          <div className={styles.statusBlock}>
            <StatusBadge status="awaiting_result" />
            <span className={styles.awaitingLabel}>Chờ dán kịch bản</span>
          </div>
        ) : isRunning ? (
          <div className={styles.progressBlock}>
            <div className={styles.progressTop}>
              <StatusBadge status={ep.status} />
              <span className={styles.progressPct}>{ep.progress}%</span>
            </div>
            <ProgressBar value={ep.progress} animated={true} />
            {ep.message && <span className={styles.runningMsg} title={ep.message}>{ep.message}</span>}
          </div>
        ) : ep.status === 'completed' ? (
          <div className={styles.statusBlock}>
            <StatusBadge status="completed" />
            <span className={styles.completedSub}>Sẵn sàng xuất / xem</span>
          </div>
        ) : ep.status === 'failed' ? (
          <div className={styles.statusBlock}>
            <StatusBadge status="failed" />
            {ep.message && <span className={styles.failedSub} title={ep.message}>{ep.message}</span>}
          </div>
        ) : (
          <div className={styles.statusBlock}>
            <StatusBadge status={ep.status} />
            <span className={styles.pendingSub}>Chờ xử lý</span>
          </div>
        )}
      </td>

      <td>
        <div className={styles.actions}>
          {['pending', 'cancelled'].includes(ep.status) && (
            <>
              <Button size="sm" icon="play" className={styles.btnPrimaryRun} onClick={() => onAction('run')} loading={busy} disabled={busy}>
                Tạo video
              </Button>
              <Button size="sm" variant="ghost" icon="settings" onClick={() => onAction('config')} title="Tùy chỉnh cấu hình riêng cho tập này" disabled={busy}>
                Cấu hình
              </Button>
            </>
          )}

          {isManual && isAwaiting && (
            <>
              <Button size="sm" icon="edit" className={styles.btnPrimaryRun} onClick={() => onAction('view')} disabled={busy}>
                Dán kịch bản &amp; xuất
              </Button>
              <Button size="sm" variant="ghost" icon="settings" onClick={() => onAction('config')} title="Chỉnh sửa giọng đọc / cấu hình tập" disabled={busy}>
                Cấu hình
              </Button>
            </>
          )}

          {isRunning && (
            <>
              <Button size="sm" variant="ghost" icon="clipboard" onClick={() => onAction('view')} title="Xem kịch bản AI & thời lượng ước tính theo tiến trình" disabled={busy}>
                Kịch bản
              </Button>
              <Button size="sm" variant="secondary" icon="pause" className={styles.btnCancel} onClick={() => onAction('cancel')} loading={busy} disabled={busy}>
                Dừng
              </Button>
            </>
          )}

          {ep.status === 'completed' && (
            <>
              <Button size="sm" icon="eye" className={styles.btnWatch} onClick={() => onAction('watch')} title="Xem trước video kèm phụ đề" disabled={busy}>
                Xem
              </Button>
              <Button size="sm" variant="ghost" icon="clipboard" onClick={() => onAction('view')} title="Xem chi tiết kịch bản phân cảnh" disabled={busy}>
                Kịch bản
              </Button>
              <Button size="sm" variant="ghost" icon="settings" onClick={() => onAction('config')} title="Chỉnh sửa cấu hình riêng (giọng đọc, model, phong cách, độ dài)" disabled={busy}>
                Cấu hình
              </Button>
              <Button size="sm" variant="ghost" icon="refresh" onClick={() => onAction('reprocess')} title="Chạy lại tập này" disabled={busy}>
                Chạy lại
              </Button>
              <Button size="sm" variant="ghost" icon="users" onClick={() => onAction('suggest')} title="Xem/sửa/chọn nhân vật đã lưu của tập — dùng chung cho các tập sau; Tạo lại = gửi AI trích xuất" disabled={busy}>
                Nhân vật
              </Button>
            </>
          )}

          {ep.status === 'failed' && (
            <>
              <Button size="sm" icon="refresh" className={styles.btnRetry} onClick={() => onAction('retry')} loading={busy} disabled={busy}>
                Thử lại
              </Button>
              <Button size="sm" variant="ghost" icon="settings" onClick={() => onAction('config')} title="Chỉnh sửa cấu hình (model, giọng, độ dài...) trước khi thử lại" disabled={busy}>
                Cấu hình
              </Button>
              <Button size="sm" variant="ghost" icon="alert" onClick={() => onAction('view')} title="Xem chi tiết nguyên nhân lỗi" disabled={busy}>
                Chi tiết lỗi
              </Button>
            </>
          )}

          {!isRunning && (
            <IconButton icon="trash" label="Xóa tập phim này" variant="danger" size="sm" onClick={() => onAction('delete')} disabled={busy} />
          )}
        </div>
      </td>
    </tr>
  );
}
