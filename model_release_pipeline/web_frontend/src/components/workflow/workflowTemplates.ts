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
    id: 'rule_patch',
    name: 'Rule Patch',
    description: 'Checkout release branch, apply DCL patch CR, run DCL diff and sim plan',
    includedSteps: ['branch_prep', 'dcl_patch', 'dcl', 'sim_plan'],
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
