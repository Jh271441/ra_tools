export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  includedSteps: string[];
}

export const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'full_release',
    name: 'Full Model Release',
    description: 'Complete pipeline: pick, export, upload, IFX, handoff, DCL, sim plan, offboard',
    includedSteps: ['pick', 'export', 'upload', 'ifx', 'handoff', 'dcl', 'sim_plan', 'offboard'],
  },
  {
    id: 'rule_change',
    name: 'Rule Change',
    description: 'Patch a branch config, run DCL diff and trigger sim plans — no model upload',
    includedSteps: ['handoff', 'dcl', 'sim_plan'],
  },
  {
    id: 'offboard_only',
    name: 'Offboard Only',
    description: 'Standalone offline validation without onboarding',
    includedSteps: ['pick', 'offboard'],
  },
];

export function getTemplate(id: string): WorkflowTemplate {
  return WORKFLOW_TEMPLATES.find((t) => t.id === id) ?? WORKFLOW_TEMPLATES[0];
}
