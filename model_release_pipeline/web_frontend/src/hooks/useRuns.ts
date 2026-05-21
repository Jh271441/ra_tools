import { useCallback, useEffect, useState } from 'react';
import { listRuns, getRun } from '../api/client';
import type { GetRunResponse, ListRunsResponse } from '../types/api';

export function useRuns() {
  const [data, setData] = useState<ListRunsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setData(await listRuns());
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return { data, error, loading, refresh };
}

export function useRun(releaseId: string | null) {
  const [data, setData] = useState<GetRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!releaseId) { setData(null); return; }
    try {
      setLoading(true);
      setData(await getRun(releaseId));
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [releaseId]);

  useEffect(() => { refresh(); }, [refresh]);

  return { data, error, loading, refresh };
}
