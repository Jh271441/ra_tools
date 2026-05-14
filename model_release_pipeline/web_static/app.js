import { renderDetails } from "./modules/details.js";
import { fetchJson } from "./modules/api.js";
import { renderActiveJob, startAction as startBackendAction } from "./modules/jobs.js";
import { renderLog, renderLogSelect } from "./modules/logs.js";
import { setRailCollapsed, setSidebarCollapsed, setView } from "./modules/navigation.js";
import {
  fetchRun,
  loadRuns as loadRunData,
  renderDraftFlow,
  renderDraftHeader,
  renderRunHeader,
  renderRunList,
} from "./modules/runs.js";
import { $, state } from "./modules/state.js";
import { escapeHtml } from "./modules/utils.js";
import {
  renderFlowControls as renderWorkflowControls,
  renderTimeline,
} from "./modules/workflowController.js";

async function loadRuns(selectFirst = false) {
  await loadRunData({ selectRun, renderEmptyState, renderRuns }, selectFirst);
}

function renderEmptyState() {
  renderDraftHeader();
  renderDraftFlow({ renderFlowControls, renderTimeline });
}

function clearSelection() {
  state.selectedId = null;
  state.selectedRun = null;
  state.activeStep = "export";
  state.draftRun = true;
  renderRuns();
  renderEmptyState();
}

$("newReleaseBtn").onclick = clearSelection;

function syncLogFullscreenButton(isFullscreen) {
  const fullscreenButton = $("fullscreenLog");
  fullscreenButton.setAttribute("aria-pressed", isFullscreen ? "true" : "false");
  fullscreenButton.title = isFullscreen ? "Exit Fullscreen" : "Toggle Fullscreen";
}

$("logDrawer").ontoggle = () => {
  const logDrawer = $("logDrawer");
  if (!logDrawer.open && logDrawer.classList.contains("fullscreen")) {
    logDrawer.classList.remove("fullscreen");
    syncLogFullscreenButton(false);
  }
};

$("fullscreenLog").onclick = (e) => {
  e.preventDefault(); // Prevent details toggle
  e.stopPropagation();
  const logDrawer = $("logDrawer");
  logDrawer.open = true;
  const isFullscreen = logDrawer.classList.toggle("fullscreen");
  syncLogFullscreenButton(isFullscreen);
};

function renderRuns() {
  renderRunList({ clearSelection, selectRun });
}

async function selectRun(releaseId) {
  await fetchRun(releaseId, { renderSelectedRun, renderRuns });
}

function renderSelectedRun() {
  const payload = state.selectedRun;
  if (!payload) return;
  renderRunHeader();
  renderFlowControls(payload);
  renderTimeline(payload.timeline || []);
  renderDetails(payload);
  renderActiveJob();
  renderLogSelect(payload.logs || {});
  renderLog();
}

function renderFlowControls(payload) {
  renderWorkflowControls(payload, startAction);
}

async function startAction(action, dryRun, confirmText) {
  await startBackendAction(action, dryRun, confirmText, { loadRuns, selectRun });
}

$("refreshButton").onclick = () => {
  state.selectedId = null;
  state.selectedRun = null;
  state.activeStep = "export";
  state.draftRun = true;
  loadRuns(false);
};
$("sidebarToggle").onclick = (event) => {
  event.stopPropagation();
  setSidebarCollapsed(!state.sidebarCollapsed);
};
$("railToggle").onclick = () => setRailCollapsed(!state.railCollapsed);
document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.onclick = () => setView(tab.dataset.view);
});
$("runFilter").oninput = renderRuns;
$("logSelect").onchange = (event) => {
  state.selectedLog = event.target.value;
  renderLog();
};
$("logSelect").onclick = (event) => event.stopPropagation();
$("copyRecordButton").onclick = async () => {
  if (!state.selectedRun) return;
  await navigator.clipboard.writeText(JSON.stringify(state.selectedRun.record, null, 2));
  $("copyRecordButton").textContent = "Copied";
  setTimeout(() => ($("copyRecordButton").textContent = "Copy JSON"), 1100);
};

fetchJson("/api/config/branches")
  .then((data) => { state.configBranches = data.branches || []; })
  .catch(() => {});

loadRuns(true).catch((error) => {
  $("runs").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
