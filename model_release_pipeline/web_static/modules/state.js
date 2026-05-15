export const state = {
  runs: [],
  selectedId: null,
  selectedRun: null,
  selectedLog: "offboard_stdout",
  activeView: "workflow",
  activeStep: "export",
  sidebarCollapsed: false,
  railCollapsed: false,
  draftRun: true,
  activeJobId: null,
  activeJob: null,
  activeJobsByRelease: {},
  trackedJobIdsByRelease: {},
  handledJobIds: new Set(),
  jobTimer: null,
  pickPreviewLines: [],
  configBranches: [],
  stageDefaults: {},
  openStageSettings: null,
  experimentFolderCache: {},
};

export const $ = (id) => document.getElementById(id);

export function currentReleaseKey() {
  return state.selectedId || (state.draftRun ? "__draft__" : null);
}

export function currentJob() {
  const key = currentReleaseKey();
  return key ? state.activeJobsByRelease[key] || null : null;
}
