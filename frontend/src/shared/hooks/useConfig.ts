import { useState, useEffect, useCallback } from 'react';
import { settingsService } from '@/shared/lib/services';
import type { Voice, Model, DetailLevel } from '@/shared/lib/types';

export function useConfig() {
  const [voices, setVoices] = useState<Record<string, Voice>>({});
  const [models, setModels] = useState<Model[]>([]);
  const [detailLevels, setDetailLevels] = useState<Record<string, DetailLevel>>({});
  const [defaultDetail, setDefaultDetail] = useState('vua');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      settingsService.getVoices(),
      settingsService.getModels(),
      settingsService.getDetailLevels(),
    ]).then(([v, m, d]) => {
      setVoices(v);
      setModels(m);
      setDetailLevels(d.levels);
      setDefaultDetail(d.default);
    }).finally(() => setLoading(false));
  }, []);

  // Tải lại danh sách giọng sau khi thêm/xóa giọng custom.
  const refreshVoices = useCallback(async () => {
    const v = await settingsService.getVoices();
    setVoices(v);
  }, []);

  return { voices, models, detailLevels, defaultDetail, loading, refreshVoices };
}
