import type {
  ConfigBranchesResponse,
  ExperimentFoldersResponse,
  GetRunResponse,
  Job,
  LubanHostsResponse,
  ListJobsResponse,
  ListRunsResponse,
  OffboardTestYamlsResponse,
  PickPreviewResponse,
  StageConfig,
  StageDefaultsResponse,
  StageValues,
  StartActionPayload,
  StartActionResponse,
} from '../types/api';

// ---------------------------------------------------------------------------
// Generic helpers
// ---------------------------------------------------------------------------

// Follows the Vite base ('/release/' behind the gateway), so API calls stay
// relative to wherever the app is mounted.
const API_BASE = `${import.meta.env.BASE_URL.replace(/\/$/, '')}/api`;

export async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export async function postJson<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T;
  if (!res.ok) {
    throw new Error(
      (data as Record<string, string>).error ?? `${res.status} ${res.statusText}`,
    );
  }
  return data;
}

export async function patchJson<T>(url: string, body: unknown = {}): Promise<T> {
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as T;
  if (!res.ok) {
    throw new Error(
      (data as Record<string, string>).error ?? `${res.status} ${res.statusText}`,
    );
  }
  return data;
}

// ---------------------------------------------------------------------------
// Runs
// ---------------------------------------------------------------------------

export const listRuns = () => fetchJson<ListRunsResponse>(`${API_BASE}/runs`);

export const getRun = (releaseId: string) =>
  fetchJson<GetRunResponse>(`${API_BASE}/runs/${releaseId}`);

export const getRunStageConfig = (releaseId: string) =>
  fetchJson<StageConfig>(`${API_BASE}/runs/${releaseId}/stage-config`);

export const patchRunStageConfig = (releaseId: string, patch: Partial<Record<string, StageValues>>) =>
  patchJson<StageConfig>(`${API_BASE}/runs/${releaseId}/stage-config`, patch);

export const copyVersionedOnnx = (releaseId: string) =>
  postJson<Record<string, unknown>>(`${API_BASE}/runs/${releaseId}/copy-versioned-onnx`);

// ---------------------------------------------------------------------------
// Actions & Jobs
// ---------------------------------------------------------------------------

export const startAction = (
  releaseId: string,
  action: string,
  payload: StartActionPayload = {},
) => postJson<StartActionResponse>(`${API_BASE}/runs/${releaseId}/actions/${action}`, payload);

export const listJobs = () => fetchJson<ListJobsResponse>(`${API_BASE}/jobs`);

export const getJob = (jobId: string) => fetchJson<Job>(`${API_BASE}/jobs/${jobId}`);

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const getConfigBranches = () =>
  fetchJson<ConfigBranchesResponse>(`${API_BASE}/config/branches`);

export const getLubanHosts = () =>
  fetchJson<LubanHostsResponse>(`${API_BASE}/config/luban-hosts`);

export const getOffboardTestYamls = () =>
  fetchJson<OffboardTestYamlsResponse>(`${API_BASE}/config/offboard-test-yamls`);

export const getStageDefaults = () =>
  fetchJson<StageDefaultsResponse>(`${API_BASE}/config/stage-defaults`);

export const patchStageDefaults = (patch: Partial<Record<string, StageValues>>) =>
  patchJson<StageConfig>(`${API_BASE}/config/stage-defaults`, patch);

// ---------------------------------------------------------------------------
// Experiment & Pick
// ---------------------------------------------------------------------------

export const listExperimentFolders = (root?: string, limit?: number, remote?: string) => {
  const params = new URLSearchParams();
  if (root) params.set('root', root);
  if (limit != null) params.set('limit', String(limit));
  if (remote) params.set('remote', remote);
  return fetchJson<ExperimentFoldersResponse>(`${API_BASE}/experiment-folders?${params}`);
};

export const previewPick = (experiment: string, remote?: string, remotePython?: string) => {
  const params = new URLSearchParams({ experiment });
  if (remote) params.set('remote', remote);
  if (remotePython) params.set('remote_python', remotePython);
  return fetchJson<PickPreviewResponse>(`${API_BASE}/pick?${params}`);
};
