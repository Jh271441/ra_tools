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

const MOBILE_MEDIA = window.matchMedia("(max-width: 860px)");

async function loadRuns(selectFirst = false, options = {}) {
  await loadRunData({ selectRun, renderEmptyState, renderRuns }, selectFirst, options);
}

function renderEmptyState() {
  renderDraftHeader();
  renderDraftFlow({ renderFlowControls, renderTimeline });
}

async function clearSelection() {
  const pane = document.querySelector(".view-pane.active");
  if (pane) {
    pane.classList.add("content-fade-out");
    await new Promise((r) => setTimeout(r, 160));
  }
  state.selectedId = null;
  state.selectedRun = null;
  state.activeStep = "export";
  state.draftRun = true;
  renderRuns();
  renderEmptyState();
  if (pane) pane.classList.remove("content-fade-out");
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
  if (isFullscreen) {
    $("workflowView").scrollTop = 0;
  }
  syncLogFullscreenButton(isFullscreen);
};

function renderRuns() {
  renderRunList({ clearSelection, selectRun });
}

async function selectRun(releaseId, options = {}) {
  await fetchRun(releaseId, { renderSelectedRun, renderRuns }, options);
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

function applyInitialResponsiveState() {
  if (MOBILE_MEDIA.matches) {
    setSidebarCollapsed(true);
    setRailCollapsed(true);
  } else {
    setRailCollapsed(false);
    setSidebarCollapsed(false);
  }
}

applyInitialResponsiveState();

function closeMobileNavigation() {
  if (!MOBILE_MEDIA.matches || state.railCollapsed) return;
  setRailCollapsed(true);
  setSidebarCollapsed(true);
}

async function startAction(action, dryRun, confirmText) {
  await startBackendAction(action, dryRun, confirmText, { loadRuns, selectRun });
}

const runsDirEl = $("runsDir");
if (runsDirEl) {
  const bubble = document.createElement("div");
  bubble.className = "popover-bubble";
  bubble.setAttribute("role", "tooltip");
  document.body.appendChild(bubble);

  function positionBubble() {
    const rect = runsDirEl.getBoundingClientRect();
    const margin = 8;
    const gap = 10;
    // Tentatively place bubble below the pill, left-aligned with it.
    let left = rect.left;
    const top = rect.bottom + gap;
    // Clamp horizontally so the bubble stays inside the viewport.
    const bubbleWidth = Math.min(bubble.offsetWidth, window.innerWidth - margin * 2);
    if (left + bubbleWidth > window.innerWidth - margin) {
      left = window.innerWidth - bubbleWidth - margin;
    }
    if (left < margin) left = margin;
    bubble.style.left = `${left}px`;
    bubble.style.top = `${top}px`;
    // Position the arrow to point at the centre of the pill.
    const arrowX = Math.max(10, Math.min(rect.left + rect.width / 2 - left - 5, bubbleWidth - 16));
    bubble.style.setProperty("--bubble-arrow", `${arrowX}px`);
    bubble.style.setProperty("--bubble-origin", `${arrowX + 5}px top`);
  }

  function openBubble() {
    bubble.textContent = runsDirEl.title || runsDirEl.textContent.replace(/^runs_dir:\s*/, "");
    bubble.classList.add("open");
    // Measure after the bubble is rendered, then place.
    requestAnimationFrame(positionBubble);
  }

  function closeBubble() {
    bubble.classList.remove("open");
  }

  runsDirEl.onclick = (event) => {
    event.stopPropagation();
    if (bubble.classList.contains("open")) closeBubble();
    else openBubble();
  };

  document.addEventListener("click", (event) => {
    if (!bubble.classList.contains("open")) return;
    if (event.target === runsDirEl || bubble.contains(event.target)) return;
    closeBubble();
  });

  window.addEventListener("resize", () => {
    if (bubble.classList.contains("open")) positionBubble();
  });
  window.addEventListener("scroll", () => {
    if (bubble.classList.contains("open")) positionBubble();
  }, { passive: true });
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
$("railToggle").onclick = (event) => {
  event.stopPropagation();
  if (MOBILE_MEDIA.matches) {
    const opening = state.railCollapsed;
    setRailCollapsed(!opening);
    setSidebarCollapsed(!opening ? true : false);
    return;
  }
  setRailCollapsed(!state.railCollapsed);
};

const mobileNavToggle = $("mobileNavToggle");
if (mobileNavToggle) {
  mobileNavToggle.onclick = (event) => {
    event.stopPropagation();
    if (!MOBILE_MEDIA.matches) return;
    const opening = state.railCollapsed;
    setRailCollapsed(!opening);
    setSidebarCollapsed(opening ? false : true);
    mobileNavToggle.setAttribute("aria-expanded", String(opening));
  };
}

function syncMobileNavAria() {
  if (!mobileNavToggle) return;
  const expanded = MOBILE_MEDIA.matches && !state.railCollapsed;
  mobileNavToggle.setAttribute("aria-expanded", String(expanded));
}
MOBILE_MEDIA.addEventListener?.("change", () => {
  applyInitialResponsiveState();
  syncMobileNavAria();
});
document.querySelectorAll(".view-tab").forEach((tab) => {
  tab.onclick = () => {
    setView(tab.dataset.view);
    closeMobileNavigation();
  };
});
document.addEventListener("click", (event) => {
  if (!MOBILE_MEDIA.matches || state.railCollapsed) return;
  const rail = $("sideRail");
  if (rail && !rail.contains(event.target)) closeMobileNavigation();
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

fetchJson("/api/config/luban-hosts")
  .then((data) => {
    state.lubanHosts = data.hosts || [];
    state.defaultLubanHost = data.default_host || state.defaultLubanHost;
    state.selectedLubanHost = state.selectedLubanHost || state.defaultLubanHost;
    if (state.selectedRun || state.draftRun) {
      renderFlowControls(state.selectedRun || null);
    }
  })
  .catch(() => {});

fetchJson("/api/config/stage-defaults")
  .then((data) => {
    state.stageDefaults = data.stage_defaults || {};
    if (state.selectedRun || state.draftRun) {
      renderFlowControls(state.selectedRun || null);
    }
  })
  .catch(() => {});

fetchJson("/api/config/offboard-test-yamls")
  .then((data) => {
    state.offboardTestYamls = data.yamls || [];
    if (state.selectedRun || state.draftRun) {
      renderFlowControls(state.selectedRun || null);
    }
  })
  .catch(() => {});

loadRuns(true).catch((error) => {
  $("runs").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
