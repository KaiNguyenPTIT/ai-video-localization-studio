import { useCallback, useEffect, useRef, useState } from 'react';
import { settingsService } from '@/shared/lib/services';
import type { HealthInfo } from '@/shared/lib/types';

export interface SystemStatus {
  health: HealthInfo | null;
  voiceStudioOnline: boolean;
  loading: boolean;
}

/**
 * Polls lightweight system endpoints used by the topbar status indicators.
 * Fails soft — indicators simply show "unknown" if the backend is unreachable.
 */
export function useSystemStatus(interval = 15000): SystemStatus & { refresh: () => void } {
  const [health, setHealth] = useState<HealthInfo | null>(null);
  const [voiceStudioOnline, setVoiceStudioOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const busy = useRef(false);

  const refresh = useCallback(async () => {
    if (busy.current) return;
    busy.current = true;
    try {
      const [h, vs] = await Promise.allSettled([
        settingsService.getHealth(),
        settingsService.getVoiceStudioStatus(),
      ]);
      if (h.status === 'fulfilled') setHealth(h.value);
      if (vs.status === 'fulfilled') setVoiceStudioOnline(vs.value.online);
    } finally {
      busy.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, interval);
    return () => clearInterval(t);
  }, [refresh, interval]);

  return { health, voiceStudioOnline, loading, refresh };
}
