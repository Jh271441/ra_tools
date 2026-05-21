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

export const listRuns = () => fetchJson<ListRunsResponse>('/api/runs');

export const getRun = (releaseId: string) =>
  fetchJson<GetRunResponse>(`/api/runs/${releaseId}`);

export const getRunStageConfig = (releaseId: string) =>
  fetchJson<StageConfig>(`/api/runs/${releaseId}/stage-config`);

export const patchRunStageConfig = (releaseId: string, patch: Partial<Record<string, StageValues>>) =>
  patchJson<StageConfig>(`/api/runs/${releaseId}/stage-config`, patch);

export const copyVersionedOnnx = (releaseId: string) =>
  postJson<Record<string, unknown>>(`/api/runs/${releaseId}/copy-versioned-onnx`);

// ---------------------------------------------------------------------------
// Actions & Jobs
// ---------------------------------------------------------------------------

export const startAction = (
  releaseId: string,
  action: string,
  payload: StartActionPayload = {},
) => postJson<StartActionResponse>(`/api/runs/${releaseId}/actions/${action}`, payload);

export const listJobs = () => fetchJson<ListJobsResponse>('/api/jobs');

export const getJob = (jobId: string) => fetchJson<Job>(`/api/jobs/${jobId}`);

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const getConfigBranches = () =>
  fetchJson<ConfigBranchesResponse>('/api/config/branches');

export const getLubanHosts = () =>
  fetchJson<LubanHostsResponse>('/api/config/luban-hosts');

export const getOffboardTestYamls = () =>
  fetchJson<OffboardTestYamlsResponse>('/api/config/offboard-test-yamls');

export const getStageDefaults = () =>
  fetchJson<StageDefaultsResponse>('/api/config/stage-defaults');

export const patchStageDefaults = (patch: Partial<Record<string, StageValues>>) =>
  patchJson<StageConfig>('/api/config/stage-defaults', patch);

// ---------------------------------------------------------------------------
// Experiment & Pick
// ---------------------------------------------------------------------------

export const listExperimentFolders = (root?: string, limit?: number, remote?: string) => {
  const params = new URLSearchParams();
  if (root) params.set('root', root);
  if (limit != null) params.set('limit', String(limit));
  if (remote) params.set('remote', remote);
  return fetchJson<ExperimentFoldersResponse>(`/api/experiment-folders?${params}`);
};

export const previewPick = (experiment: string, remote?: string, remotePython?: string) => {
  const params = new URLSearchParams({ experiment });
  if (remote) params.set('remote', remote);
  if (remotePython) params.set('remote_python', remotePython);
  return fetchJson<PickPreviewResponse>(`/api/pick?${params}`);
};
