export interface VersionItem {
  version_key: string;
  label: string;
  sim_job_id: number | null;
  baseline_job_id: number | null;
  sort_order: number;
  is_current: boolean;
  metadata_json: Record<string, unknown>;
  last_refreshed_at: string | null;
}

export interface VersionsResponse {
  current_version: string;
  compare_versions: string[];
  config_hash: string;
  versions: VersionItem[];
}

export interface KpiSummary {
  version_key: string;
  label: string;
  total_cases: number;
  road_positive_cases: number;
  sim_positive_cases: number;
  reproduced_cases: number;
  sim_repro_rate: number;
  model_repro_rate: number;
  fn_fallback_rate: number;
  fp_suppress_rate: number;
  precision: number;
  recall: number;
  f1: number;
  root_causes: Record<string, number>;
  source_gt?: Record<string, unknown> | null;
  sim_estimate?: Record<string, unknown> | null;
  sort_order?: number;
}

export interface SummaryResponse {
  current: KpiSummary;
  previous: KpiSummary | null;
  deltas: Record<string, number>;
  generated_at: string;
}

export interface IssueListItem {
  issue_id: string | null;
  scenario_id: string;
  scenario_name: string;
  version_key: string;
  issue_topic: string;
  status: string;
  priority: string;
  poi: string;
  road_triggered: boolean;
  sim_triggered: boolean;
  reproduced: boolean;
  precision_label: string;
  trigger_type: string;
  root_cause: string;
  model_score_max: number | null;
  threshold: number | null;
  unstuck_status: string;
  fp_reasons: string[];
  fn_reasons: string[];
}

export interface SelectedIssueResult {
  issue_id: string | null;
  scenario_id: string;
  version_key: string;
}

export interface PaginatedIssuesResponse {
  page: number;
  page_size: number;
  total: number;
  items: IssueListItem[];
}

export interface ScenarioResult {
  version_key: string;
  scenario_id: string;
  issue_id: string | null;
  road_triggered: boolean;
  sim_triggered: boolean;
  reproduced: boolean;
  precision_label: string;
  trigger_type: string;
  root_cause: string;
  model_score_max: number | null;
  threshold: number | null;
  unstuck_status: string;
  fp_reasons: string[];
  fn_reasons: string[];
  raw_metrics: Record<string, unknown>;
  updated_at?: string;
}

export interface IssueDetailResponse {
  issue_id: string;
  issue: Record<string, unknown>;
  scenarios: Array<{
    scenario: Record<string, unknown>;
    results: ScenarioResult[];
  }>;
}

export interface ScenarioDetailResponse {
  scenario_id: string;
  scenario: Record<string, unknown>;
  results: ScenarioResult[];
}

export type SystemCheckStatus = 'ok' | 'warn' | 'error' | 'skipped';

export interface SystemCheck {
  key: string;
  status: SystemCheckStatus;
  latency_ms: number | null;
  detail: string;
  error: string;
  extra: Record<string, unknown>;
}

export interface SystemStatusResponse {
  overall: SystemCheckStatus;
  generated_at: string;
  app_started_at: string;
  uptime_seconds: number;
  enable_rq: boolean;
  checks: SystemCheck[];
}

export interface RefreshJob {
  job_id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  progress: number;
  message: string;
  error: string;
  config_hash: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}
