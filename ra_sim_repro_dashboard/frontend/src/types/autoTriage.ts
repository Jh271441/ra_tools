export interface AutoTriageMetrics {
  precision_auto_tp: number;
  precision_denominator: number;
  recall_auto_tp: number;
  recall_denominator: number;
  available: boolean;
  eligible: number;
  covered: number;
  missing_results: number;
  missing_labels: number;
  unclassified: number;
  excluded: number;
  coverage: number | null;
  online_precision: number | null;
  online_recall: number | null;
  precision: number | null;
  recall: number | null;
  covered_precision: number | null;
  covered_recall: number | null;
  tp: number;
  fp: number;
  fn: number;
  tn: number;
}

export interface AutoTriageIssue {
  issue_id: string;
  issue_topic: string;
  ra_type: number;
  baseline_label: string | null;
  auto_label: string | null;
  label_source: string;
  old_cohort: string | null;
  new_cohort: string | null;
  changed: boolean;
  scope_excluded: boolean;
  result_status: string;
  scenario_ids: string[];
  sim_triggered: boolean | null;
  precision_label: string | null;
  raw_model_result: string | null;
  sim_memberships: { precision_numerator: number; precision_denominator: number; recall_numerator: number; recall_denominator: number } | null;
  job_ids: number[];
}

export interface AutoTriageResult {
  revision_key: string;
  release: string;
  source_count: number;
  source_snapshot_id: number;
  source_as_of: string;
  generated_at: string;
  label_synced_at: string;
  source_complete: boolean;
  base_job_id: number | null;
  binary_id: number | null;
  source_job_ids: number[];
  metrics: AutoTriageMetrics;
  baseline: AutoTriageMetrics;
  changed_count: number;
  newly_eligible: number;
  no_longer_eligible: number;
  label_sources: Record<string, number>;
  coverage_reasons: Record<string, number>;
  transitions: { before: string; after: string; count: number }[];
  scope: { release: string; date_start: string; date_end: string };
  reconciliation: { status: string; checked_issues: number; dashboard_only_ids: string[]; inventory_only_ids: string[] };
}

export interface AutoTriageReport {
  release: string | null;
  status: string;
  source_count?: number;
  source_snapshot_id?: number;
  label_checked_at?: string;
  scope?: { release: string; date_start: string; date_end: string };
  refresh: { status?: string; error?: string; finished_at?: string; requested_at?: string };
  result: AutoTriageResult | null;
  versions: { release: string; snapshot_id: number; source_count: number; source_complete: boolean; job_id: number | null }[];
}

export interface AutoTriageIssuePage {
  items: AutoTriageIssue[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  revision_key?: string;
}
