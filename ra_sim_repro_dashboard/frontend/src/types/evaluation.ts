import type { AutoTriageIssue } from './autoTriage';
import type { SimulationProgress } from './simulation';
import type { ReproductionSummary, ReproductionResult } from './reproduction';

export interface EvaluationContext {
  release: string;
  profile_id?: string;
  date_start?: string;
  date_end?: string;
}
export interface ProfileConfig {
  schema_version: number;
  population: { date_field: string; filters: Record<string, (string | number)[]> };
  label: { source: string; priority?: string[]; mapping: Record<string, string | null> };
  memberships: Record<string, { triggers: number[]; include?: string[]; exclude?: string[] }>;
}
export interface MetricProfile {
  id: string;
  name: string;
  description: string;
  status: string;
  config: ProfileConfig;
  config_hash: string;
  created_at: string | null;
  parent: string | null;
}
export interface EvaluationMetrics {
  available: boolean;
  eligible: number;
  covered: number;
  missing_results: number;
  coverage: number | null;
  online_precision: number | null;
  online_recall: number | null;
  precision: number | null;
  recall: number | null;
  sim_repro_rate: number | null;
  covered_repro_rate: number | null;
  covered_precision: number | null;
  covered_recall: number | null;
  road_matches: number;
  reproduction?: ReproductionSummary;
  counts: Record<string, number>;
  sim_counts: Record<string, number>;
  covered_source_counts?: Record<string, number>;
  cohorts: Record<string, { count: number; matches: number; evaluated?: number }>;
}
export interface EvaluationRevision {
  source_distribution?: EvaluationSourceDistribution;
  revision_key: string;
  context: EvaluationContext;
  profile: MetricProfile;
  metrics: EvaluationMetrics;
  baseline: EvaluationMetrics;
  generated_at: string;
  label_checked_at: string;
  source_count: number;
  source_snapshot_id: number;
  reconciliation: { status: string; checked_issues: number };
  specification: { binary_id: number | null; template_job_id: number | null };
}
export interface EvaluationSourceGroup {
  id: string;
  count: number;
  classified_count: number;
  classes: Record<'correct' | 'false' | 'no_assist' | 'other', number>;
  memberships: Record<string, number>;
  triggers: { auto: number; manual: number };
  labels: { label: string | null; count: number }[];
  raw_labels: { label: string | null; count: number }[];
}
export interface EvaluationSourceDistribution {
  available: boolean;
  error?: string;
  schema_version?: number;
  revision_key?: string;
  context?: EvaluationContext;
  total?: number;
  sample_snapshot_id?: string;
  observed_at?: string;
  label_source?: string;
  label_priority?: string[];
  label_mapping?: Record<string, string | null>;
  groups?: EvaluationSourceGroup[];
  counts?: Record<string, number>;
  correct_not_precision?: number;
  rules?: ProfileConfig['memberships'];
}
export interface IncrementalPlan {
  id: string;
  revision_key: string;
  reuse_count: number;
  gap_count: number;
  review_count: number;
  prepare_count: number;
  simulate_count: number;
  created_at: string;
  runnable_count?: number;
  blocked_count?: number;
  actions: { issue_id: string; reason: string; scenario_ids: string[]; action: string }[];
}
export interface EvaluationExecution {
  id: string;
  status: string;
  job_id?: number;
  error?: string;
  created_at: string;
  plan_id?: string;
  metrics_status?: string;
  metrics_error?: string;
  metrics_finished_at?: string;
  context?: EvaluationContext;
  progress?: Partial<SimulationProgress>;
}
export interface EvaluationBoard {
  context: EvaluationContext;
  profile: MetricProfile;
  revision: EvaluationRevision | null;
  stale: boolean;
  recall_comparison?: {
    covered: number;
    road_numerator: number;
    road_denominator: number;
    sim_numerator: number;
    sim_denominator: number;
    gains: number;
    losses: number;
    net: number;
    denominator_changed: number;
    road_recall: number | null;
    sim_recall: number | null;
    gap: number | null;
    behavior_validated: boolean;
  } | null;
  refresh: { status?: string; error?: string; requested_at?: string; finished_at?: string };
  sample_source: {
    status: 'ready' | 'missing';
    mode: 'database';
    provider?: string;
    pending_count?: number;
    snapshot_id?: string;
    row_count?: number;
    observed_at?: string;
    stored_at?: string;
    error?: string;
  };
  plan: IncrementalPlan | Record<string, never>;
  versions: { release: string; source_count: number }[];
  cron: {
    enabled: boolean;
    effective?: boolean;
    processing_enabled?: boolean;
    poll_seconds?: number;
    interval_seconds: number;
    next_check_at?: string;
  };
  executions: EvaluationExecution[];
  starts: { id: string; status: string; error?: string; created_at?: string; plan_id?: string }[];
}
export interface EvaluationIssue extends AutoTriageIssue {
  eligible: boolean;
  auto_memberships: Record<string, number>;
  reproduction?: ReproductionResult;
  baseline_available?: boolean;
  label_resolution?: {
    label: string | null;
    raw_label: string | null;
    source: string | null;
    status: string;
    policy_version: string;
    source_revision: string | null;
    trace: { source: string; state: string }[];
  };
}
export interface EvaluationIssuePage {
  items: EvaluationIssue[];
  total: number;
  page: number;
  pages: number;
  page_size: number;
  revision_key?: string;
}
export interface ProfilePreview {
  profile_id: string;
  preview_hash: string;
  metrics: EvaluationMetrics;
  previous_metrics: EvaluationMetrics;
  population_added: number;
  population_removed: number;
  changed_labels: number;
  newly_eligible: number;
  no_longer_eligible: number;
}
