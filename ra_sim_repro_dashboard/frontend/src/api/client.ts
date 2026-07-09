import type {
  IssueDetailResponse,
  PaginatedIssuesResponse,
  RefreshJob,
  ScenarioDetailResponse,
  SummaryResponse,
  SystemStatusResponse,
  VersionsResponse,
  KpiSummary,
} from '../types';

// Follows the Vite base ('/sim/' behind the gateway), so API calls stay
// relative to wherever the app is mounted.
const API_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api`;

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  versions: () => fetchJson<VersionsResponse>(`${API_BASE}/dashboard/versions`),
  summary: () => fetchJson<SummaryResponse>(`${API_BASE}/dashboard/summary`),
  comparison: () => fetchJson<KpiSummary[]>(`${API_BASE}/dashboard/version-comparison`),
  issues: (params: URLSearchParams) =>
    fetchJson<PaginatedIssuesResponse>(`${API_BASE}/dashboard/issues?${params}`),
  issueDetail: (issueId: string) =>
    fetchJson<IssueDetailResponse>(`${API_BASE}/dashboard/issues/${encodeURIComponent(issueId)}`),
  scenarioDetail: (scenarioId: string) =>
    fetchJson<ScenarioDetailResponse>(`${API_BASE}/dashboard/scenarios/${encodeURIComponent(scenarioId)}`),
  refresh: () =>
    fetchJson<RefreshJob>(`${API_BASE}/dashboard/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    }),
  refreshStatus: (jobId: string) =>
    fetchJson<RefreshJob>(`${API_BASE}/dashboard/refresh/${encodeURIComponent(jobId)}`),
  systemStatus: () => fetchJson<SystemStatusResponse>(`${API_BASE}/system/status`),
};
