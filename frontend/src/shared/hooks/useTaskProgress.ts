import { useState, useEffect, useCallback, useRef } from 'react';
import { taskService } from '@/shared/lib/services';
import type { Task } from '@/shared/lib/types';

const ACTIVE_STATUSES = ['pending', 'queueing', 'running', 'awaiting'];

interface UseTaskProgressOptions {
  enabled?: boolean;
  interval?: number;
  onComplete?: (task: Task) => void;
  onFailed?: (task: Task) => void;
}

export function useTaskProgress(taskId: string | null | undefined, opts: UseTaskProgressOptions = {}) {
  const { enabled = true, interval = 2000, onComplete, onFailed } = opts;
  const [task, setTask] = useState<Task | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const prevStatus = useRef<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const isPollingRef = useRef(false);

  const poll = useCallback(async () => {
    if (!taskId || !enabled || isPollingRef.current) return null;
    isPollingRef.current = true;
    try {
      const t = await taskService.get(taskId);
      setTask(t);
      setError(null);
      if (prevStatus.current && prevStatus.current !== t.status) {
        if (t.status === 'completed') onComplete?.(t);
        if (t.status === 'failed') onFailed?.(t);
      }
      prevStatus.current = t.status;
      if (!ACTIVE_STATUSES.includes(t.status)) stopPolling();
      return t;
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Poll failed');
      return null;
    } finally {
      isPollingRef.current = false;
      setLoading(false);
    }
  }, [taskId, enabled, onComplete, onFailed, stopPolling]);

  useEffect(() => {
    if (!taskId || !enabled) return;
    setLoading(true);
    poll();
    stopPolling();
    timerRef.current = setInterval(poll, interval);
    return stopPolling;
  }, [taskId, enabled, interval, poll, stopPolling]);

  return { task, loading, error, refresh: poll, isActive: task ? ACTIVE_STATUSES.includes(task.status) : false };
}

export function usePolling<T>(fetcher: () => Promise<T>, interval = 5000, enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isFetchingRef = useRef(false);

  const refresh = useCallback(async () => {
    if (isFetchingRef.current) return;
    isFetchingRef.current = true;
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed');
    } finally {
      isFetchingRef.current = false;
      setLoading(false);
    }
  }, [fetcher]);

  useEffect(() => {
    if (!enabled) return;
    refresh();
    const timer = setInterval(refresh, interval);
    return () => clearInterval(timer);
  }, [refresh, interval, enabled]);

  return { data, loading, error, refresh };
}
