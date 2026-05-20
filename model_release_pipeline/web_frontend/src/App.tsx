import { useEffect, useState } from 'react';
import { fetchJson } from './api/client';
import type { Run } from './types/api';

export default function App() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchJson<{ runs: Run[] }>('/api/runs')
      .then((data) => setRuns(data.runs ?? []))
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ padding: 24, fontFamily: 'system-ui' }}>
      <h1>Release Agent — Vite Scaffold</h1>
      {error && <p style={{ color: 'crimson' }}>API error: {error}</p>}
      {runs === null && !error && <p>Loading…</p>}
      {runs && (
        <p>
          Loaded <strong>{runs.length}</strong> releases from /api/runs.
        </p>
      )}
    </main>
  );
}
