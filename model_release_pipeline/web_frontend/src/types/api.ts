// ---------------------------------------------------------------------------
// Release record (mirrors state_store.py create() + runtime fields)
// ---------------------------------------------------------------------------

export interface ReleaseRecord {
  release_id: string;
  created_at: string;
  updated_at: string;
  status: string;
  stage: string;
  description: string;
  experiment_path: string | null;
  experiment?: ExperimentInfo;
  pick?: Record<string, unknown>;
  selection: Selection;
  export: ExportInfo;
  ifx: IfxInfo;
  handoff: Record<string, unknown>;
  apply_handoff?: ApplyHandoffResult;
  dcl?: CommandResult;
  sim_plan?: CommandResult;
  offboard: CommandResult;
  errors: RecordError[];
  web_stage_config?: StageConfig;
}

export interface ExperimentInfo {
  name?: string;
  path?: string;
}

export interface Selection {
  selected_epoch?: number | null;
  selection_source?: string;
}

export interface ExportInfo {
  export?: CommandResult;
  scp?: CommandResult;
}

export interface CommandResult {
  stdout?: string;
  stderr?: string;
  returncode?: number | null;
  [key: string]: unknown;
}

export interface ApplyHandoffResult extends CommandResult {
  dcl_commands?: string[];
}

// ---------------------------------------------------------------------------
// IFX
// ---------------------------------------------------------------------------

export interface OnnxInfo {
  module?: string;
  name?: string;
  version?: number | null;
  local_path?: string;
}

export interface IfxMapping {
  onnx?: OnnxInfo;
  [platform: string]: OnnxInfo | undefined;
}

export interface JenkinsInfo {
  queue_url?: string;
  build_url?: string;
  build_number?: number | null;
  result?: string;
  console_tail?: string[];
}

export interface IfxInfo {
  onnx?: OnnxInfo;
  ifx_mapping?: IfxMapping;
  dry_run_mapping?: IfxMapping;
  dry_run_upload?: Record<string, unknown>;
  jenkins?: JenkinsInfo;
  truck_runner?: { configured?: string; selected?: string };
  precision_test_arg?: string;
  upload_description?: string;
  failed_uploads?: string[];
}

// ---------------------------------------------------------------------------
// Record error
// ---------------------------------------------------------------------------

export interface RecordError {
  time?: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Summary (from web/summary.py record_summary)
// ---------------------------------------------------------------------------

export interface RunSummary {
  release_id: string;
  created_at: string;
  updated_at: string;
  stage: string;
  status: string;
  experiment_name: string;
  experiment_path: string | null;
  selected_epoch: number | null;
  selection_source: string | null;
  onnx_version: number | null;
  ifx_platforms: number;
  offboard_status: string;
  error_count: number;
  workflow_type?: string;
}

// ---------------------------------------------------------------------------
// Timeline (from web/summary.py timeline)
// ---------------------------------------------------------------------------

export type StepStatus =
  | 'pending'
  | 'ready'
  | 'running'
  | 'done'
  | 'dry_run'
  | 'skipped'
  | 'failed'
  | 'missing';

export type StepGroup = 'shared' | 'onboard' | 'offboard';

export interface TimelineStep {
  key: string;
  title: string;
  description: string;
  group: StepGroup;
  status: StepStatus;
}

// ---------------------------------------------------------------------------
// Logs (from web/logs.py record_logs)
// ---------------------------------------------------------------------------

export type LogKey =
  | 'export_stdout'
  | 'export_stderr'
  | 'upload_stdout'
  | 'upload_stderr'
  | 'ifx_stdout'
  | 'ifx_stderr'
  | 'jenkins_console'
  | 'handoff_stdout'
  | 'handoff_stderr'
  | 'dcl_stdout'
  | 'dcl_stderr'
  | 'sim_plan_stdout'
  | 'sim_plan_stderr'
  | 'offboard_stdout'
  | 'offboard_stderr'
  | 'branch_prep_stdout'
  | 'branch_prep_stderr'
  | 'dcl_patch_stdout'
  | 'dcl_patch_stderr';

export type LogMap = Record<LogKey, string[]>;

// ---------------------------------------------------------------------------
// Actions (from web/actions.py)
// ---------------------------------------------------------------------------

export type ActionKey =
  | 'pick'
  | 'export'
  | 'upload'
  | 'ifx-convert'
  | 'ifx-poll'
  | 'handoff'
  | 'apply-handoff'
  | 'dcl'
  | 'sim-plan'
  | 'sim-plan-status'
  | 'sim-plan-cancel'
  | 'offboard'
  | 'branch-prep'
  | 'dcl-patch';

export interface ActionSpec {
  key: ActionKey;
  label: string;
  supports_dry_run: boolean;
  requires_confirm: boolean;
  needs_run_id: boolean;
}

// ---------------------------------------------------------------------------
// Jobs (from web/jobs.py)
// ---------------------------------------------------------------------------

export type JobStatus = 'running' | 'completed' | 'failed';

export interface Job {
  job_id: string;
  release_id: string;
  action: ActionKey;
  label: string;
  dry_run: boolean;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  command: string;
  returncode: number | null;
  log: string[];
}

// ---------------------------------------------------------------------------
// Stage config (from web/stage_config.py)
// ---------------------------------------------------------------------------

export interface StageValues {
  branch?: string;
  checkout_branch?: string;
  update_diff_ids?: number[];
  sim_plan?: string;
  plans?: string[];
  revision_id?: number;
  priority?: number;
  time_sensitive_hour?: number;
  lint?: boolean;
  allow_dirty?: boolean;
}

export type StageKey = 'handoff' | 'dcl' | 'sim_plan';

export type StageConfig = Partial<Record<StageKey, StageValues>>;

// ---------------------------------------------------------------------------
// API response shapes
// ---------------------------------------------------------------------------

export interface ListRunsResponse {
  runs_dir: string;
  runs: RunSummary[];
}

export interface GetRunResponse {
  record: ReleaseRecord;
  summary: RunSummary;
  timeline: TimelineStep[];
  logs: LogMap;
  commands: Record<string, string | string[]>;
  metric_table?: string[];
  actions: ActionSpec[];
  versioned_onnx?: Record<string, unknown>;
}

export interface ListJobsResponse {
  jobs: Job[];
}

export interface SimPlanEntry {
  name: string;
  enabled_by_default?: boolean | string;
}

export interface BranchInfo {
  name: string;
  checkout_branch?: string;
  sim_plans?: SimPlanEntry[];
  sim_plan?: string;
  update_diff_ids?: number[];
}

export interface ConfigBranchesResponse {
  branches: BranchInfo[];
}

export interface LubanHostsResponse {
  default_host: string;
  hosts: string[];
}

export interface OffboardTestYamlEntry {
  name: string;
  path?: string;
  [key: string]: unknown;
}

export interface OffboardTestYamlsResponse {
  source: string;
  yamls: OffboardTestYamlEntry[];
}

export interface StageDefaultsResponse {
  stage_defaults: StageConfig;
}

export interface ExperimentFolder {
  name: string;
  path: string;
}

export interface ExperimentFoldersResponse {
  folders: ExperimentFolder[];
  root: string;
}

export interface PickPreviewResponse {
  experiment?: Record<string, unknown>;
  pick?: Record<string, unknown>;
  error?: string;
}

export interface StartActionPayload {
  dry_run?: boolean;
  confirm_text?: string;
  [key: string]: unknown;
}

export interface StartActionResponse {
  job_id: string;
  release_id: string;
  action: string;
  status: string;
}
