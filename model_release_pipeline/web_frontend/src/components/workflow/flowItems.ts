import type { RunSummary } from '../../types/api';

export interface FlowItem {
  key: string;
  group: 'shared' | 'onboard' | 'offboard';
  badge: string;
  shortTitle: string;
  title: string;
  note: string;
  detail: string;
  actionKeys: string[];
}

export interface FlowGroups {
  shared: FlowItem[];
  onboard: FlowItem[];
  offboard: FlowItem[];
}

function fmtEpoch(val: number | null | undefined): string {
  if (val == null) return 'NA';
  return Number.isInteger(val) ? String(val).padStart(3, '0') : Number(val).toFixed(1);
}

export function getFlowItems(summary: RunSummary | null): FlowGroups {
  const s = summary ?? ({ selected_epoch: null, onnx_version: null } as Partial<RunSummary>);
  return {
    shared: [
      {
        key: 'pick',
        group: 'shared',
        badge: 'Inspect',
        shortTitle: 'Pick',
        title: 'Luban Inspect / Pick',
        note: `epoch ${fmtEpoch(s.selected_epoch)}`,
        detail: 'Inspect an experiment on Luban and recommend an epoch. Preview does not save; Pick creates a release record.',
        actionKeys: ['pick'],
      },
    ],
    onboard: [
      { key: 'export', group: 'onboard', badge: 'O1', shortTitle: 'Export', title: 'Onboard: Export to Local', note: 'ONNX to NFS', detail: 'Create or re-export ONNX from the selected experiment and epoch.', actionKeys: ['export'] },
      { key: 'upload', group: 'onboard', badge: 'O2', shortTitle: 'Upload', title: 'Onboard: Upload to Cloud', note: `ONNX v${s.onnx_version ?? 'NA'}`, detail: 'Upload the exported ONNX to fileserver with truck.py and bind the ONNX version to this release.', actionKeys: ['upload'] },
      { key: 'ifx', group: 'onboard', badge: 'O3', shortTitle: 'IFX', title: 'Onboard: IFX Conversion', note: `ONNX v${s.onnx_version ?? 'NA'}`, detail: 'Trigger Jenkins IFX conversion from uploaded ONNX, or poll an already-triggered Jenkins build and collect artifact versions.', actionKeys: ['ifx-convert', 'ifx-poll'] },
      { key: 'handoff', group: 'onboard', badge: 'O4', shortTitle: 'Handoff', title: 'Onboard: Handoff / Apply Commit', note: 'manifest commit', detail: 'Generate or apply Voyager MANIFEST updates, then use DCL commands from Release Details.', actionKeys: ['handoff', 'apply-handoff'] },
      { key: 'dcl', group: 'onboard', badge: 'O5', shortTitle: 'DCL', title: 'Onboard: DCL Upload to Kunpeng', note: 'review diff', detail: 'Run dcl diff inside the Voyager docker checkout.', actionKeys: ['dcl'] },
      { key: 'sim_plan', group: 'onboard', badge: 'O6', shortTitle: 'Sim Plan', title: 'Onboard: Sim Plan', note: 'Kunpeng SimOne', detail: 'Trigger, refresh, or cancel Kunpeng SimOne plans after DCL creates the review revision.', actionKeys: ['sim-plan', 'sim-plan-status', 'sim-plan-cancel'] },
    ],
    offboard: [
      { key: 'offboard', group: 'offboard', badge: 'Test', shortTitle: 'Offboard', title: 'Offboard Validation', note: 'validate model', detail: 'Run offline validation from the selected pick, or enter an experiment and epoch directly without using the Onboard path.', actionKeys: ['offboard'] },
    ],
  };
}

export const STEP_LOG_MAP: Record<string, string> = {
  pick: 'export_stdout',
  export: 'export_stdout',
  upload: 'upload_stdout',
  ifx: 'ifx_stdout',
  handoff: 'handoff_stdout',
  dcl: 'dcl_stdout',
  sim_plan: 'sim_plan_stdout',
  offboard: 'offboard_stdout',
};

export const LOG_LABELS: Record<string, string> = {
  export_stdout: 'Export stdout',
  export_stderr: 'Export stderr',
  upload_stdout: 'Upload stdout',
  upload_stderr: 'Upload stderr',
  ifx_stdout: 'IFX stdout',
  ifx_stderr: 'IFX stderr',
  jenkins_console: 'Jenkins console',
  handoff_stdout: 'Handoff stdout',
  handoff_stderr: 'Handoff stderr',
  dcl_stdout: 'DCL stdout',
  dcl_stderr: 'DCL stderr',
  sim_plan_stdout: 'Sim Plan stdout',
  sim_plan_stderr: 'Sim Plan stderr',
  offboard_stdout: 'Offboard stdout',
  offboard_stderr: 'Offboard stderr',
};
