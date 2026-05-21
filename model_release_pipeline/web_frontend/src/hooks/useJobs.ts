import { useCallback, useEffect, useRef, useState } from 'react';
import { getJob, listJobs } from '../api/client';
import type { Job, ListJobsResponse } from '../types/api';

export function useJobs(pollInterval = 3000) {
  const [data, setData] = useState<ListJobsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const refresh = useCallback(async () => {
    try {
      const result = await listJobs();
      setData(result);
      setError(null);
      return result;
    } catch (e) {
      setError(String(e));
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
    timerRef.current = setInterval(refresh, pollInterval);
    return () => clearInterval(timerRef.current);
  }, [refresh, pollInterval]);

  return { data, error, refresh };
}

export function useJob(jobId: string | null, pollInterval = 2000) {
  const [data, setData] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  const refresh = useCallback(async () => {
    if (!jobId) { setData(null); return; }
    try {
      const job = await getJob(jobId);
      setData(job);
      setError(null);
      if (job.status !== 'running') {
        clearInterval(timerRef.current);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [jobId]);

  useEffect(() => {
    refresh();
    if (jobId) {
      timerRef.current = setInterval(refresh, pollInterval);
    }
    return () => clearInterval(timerRef.current);
  }, [refresh, jobId, pollInterval]);

  return { data, error, refresh };
}
