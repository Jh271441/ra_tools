import { useCallback, useEffect, useRef, useState } from 'react';
import { getJob } from '../api/client';
import type { Job } from '../types/api';

const POLL_INTERVAL_MS = 2500;

export function useJobPoller(): {
  activeJob: Job | null;
  trackJob: (jobId: string) => void;
  clearJob: () => void;
} {
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const trackedIdRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current != null) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const poll = useCallback(async () => {
    const id = trackedIdRef.current;
    if (!id) return;
    try {
      const job = await getJob(id);
      setActiveJob(job);
      if (job.status !== 'running') {
        stopPolling();
        trackedIdRef.current = null;
      }
    } catch {
      // keep polling on transient errors
    }
  }, [stopPolling]);

  const trackJob = useCallback((jobId: string) => {
    stopPolling();
    trackedIdRef.current = jobId;
    setActiveJob(null);
    // fetch immediately, then on interval
    void poll();
    intervalRef.current = setInterval(() => { void poll(); }, POLL_INTERVAL_MS);
  }, [poll, stopPolling]);

  const clearJob = useCallback(() => {
    stopPolling();
    trackedIdRef.current = null;
    setActiveJob(null);
  }, [stopPolling]);

  // cleanup on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  return { activeJob, trackJob, clearJob };
}
