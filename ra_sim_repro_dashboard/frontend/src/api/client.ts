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

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    throw new Error(`${res.status} ${await res.text()}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  versions: () => fetchJson<VersionsResponse>('/api/dashboard/versions'),
  summary: () => fetchJson<SummaryResponse>('/api/dashboard/summary'),
  comparison: () => fetchJson<KpiSummary[]>('/api/dashboard/version-comparison'),
  issues: (params: URLSearchParams) =>
    fetchJson<PaginatedIssuesResponse>(`/api/dashboard/issues?${params}`),
  issueDetail: (issueId: string) =>
    fetchJson<IssueDetailResponse>(`/api/dashboard/issues/${encodeURIComponent(issueId)}`),
  scenarioDetail: (scenarioId: string) =>
    fetchJson<ScenarioDetailResponse>(`/api/dashboard/scenarios/${encodeURIComponent(scenarioId)}`),
  refresh: () =>
    fetchJson<RefreshJob>('/api/dashboard/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ force: true }),
    }),
  refreshStatus: (jobId: string) =>
    fetchJson<RefreshJob>(`/api/dashboard/refresh/${encodeURIComponent(jobId)}`),
  systemStatus: () => fetchJson<SystemStatusResponse>('/api/system/status'),
};
