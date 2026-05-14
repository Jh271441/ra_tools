export const DEFAULT_ACTIONS = [
  { key: "export", label: "Model Export", supports_dry_run: true, requires_confirm: true, needs_run_id: false },
  { key: "upload", label: "Upload ONNX", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "ifx-convert", label: "Trigger IFX Convert", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "ifx-poll", label: "Poll IFX Result", supports_dry_run: false, requires_confirm: false, needs_run_id: true },
  { key: "handoff", label: "Generate Handoff", supports_dry_run: false, requires_confirm: false, needs_run_id: true },
  { key: "apply-handoff", label: "Apply Handoff", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "dcl", label: "Run DCL Diff", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "offboard", label: "Run Offboard", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
];

export const LOG_LABELS = {
  export_stdout: "Export stdout",
  export_stderr: "Export stderr",
  upload_stdout: "Upload stdout",
  upload_stderr: "Upload stderr",
  ifx_stdout: "IFX stdout",
  ifx_stderr: "IFX stderr",
  jenkins_console: "Jenkins console",
  handoff_stdout: "Handoff stdout",
  handoff_stderr: "Handoff stderr",
  dcl_stdout: "DCL stdout",
  dcl_stderr: "DCL stderr",
  offboard_stdout: "Offboard stdout",
  offboard_stderr: "Offboard stderr",
};

export const STEP_LOG_MAP = {
  inspect: "export_stdout",
  pick: "export_stdout",
  export: "export_stdout",
  upload: "upload_stdout",
  ifx: "ifx_stdout",
  handoff: "handoff_stdout",
  dcl: "dcl_stdout",
  offboard: "offboard_stdout",
};

export const NEXT_STEP_BY_ACTION = {
  export: "upload",
  upload: "ifx",
  "ifx-convert": "handoff",
  "ifx-poll": "handoff",
  handoff: "handoff",
  "apply-handoff": "dcl",
  dcl: "offboard",
};
