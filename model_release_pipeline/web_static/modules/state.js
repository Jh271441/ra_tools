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
  jobTimer: null,
};

export const $ = (id) => document.getElementById(id);
