import { fetchJson } from "./api.js";
import { renderLog, renderLogSelect } from "./logs.js";
import { draftPayload } from "./releaseData.js";
import { $, state } from "./state.js";
import { escapeHtml, formatEpoch, shortName, statusClass } from "./utils.js";

let _animateNextRender = false;

export async function loadRuns({ selectRun, renderEmptyState, renderRuns }, selectFirst = false, options = {}) {
  const payload = await fetchJson("/api/runs");
  state.runs = payload.runs || [];
  const runsDirEl = $("runsDir");
  runsDirEl.textContent = `runs_dir: ${payload.runs_dir}`;
  runsDirEl.title = payload.runs_dir;
  _animateNextRender = !options.silent;
  renderRuns();
  if (state.selectedId) {
    await selectRun(state.selectedId, { silent: options.silent });
  } else if (selectFirst && !state.draftRun && state.runs.length) {
    await selectRun(state.runs[0].release_id, { silent: options.silent });
  } else {
    renderEmptyState();
  }
}

export function renderRunList({ clearSelection, selectRun }) {
  const animate = _animateNextRender;
  _animateNextRender = false;
  const filter = $("runFilter").value.trim().toLowerCase();
  const runsEl = $("runs");

  const visible = state.runs.filter((run) => {
    const haystack = [
      run.release_id,
      run.experiment_name,
      run.stage,
      run.status,
      run.onnx_version,
    ]
      .join(" ")
      .toLowerCase();
    return !filter || haystack.includes(filter);
  });

  // Fast path: if only the selected item changed, update active classes in-place
  // without touching the DOM structure (avoids flash from full innerHTML rebuild).
  if (!animate) {
    const existingItems = runsEl.querySelectorAll(".run-item[data-run-id]");
    const expectedIds = [
      ...(state.draftRun ? ["__draft__"] : []),
      ...visible.map((r) => r.release_id),
    ];
    const match =
      existingItems.length === expectedIds.length &&
      [...existingItems].every((el, i) => el.dataset.runId === expectedIds[i]);
    if (match) {
      existingItems.forEach((el) => {
        const id = el.dataset.runId;
        el.classList.toggle("active", id === "__draft__" ? state.draftRun : id === state.selectedId);
      });
      return;
    }
  }

  // Full rebuild (fresh load, filter change, or list structure changed)
  runsEl.innerHTML = "";
  let staggerIndex = 0;

  if (state.draftRun) {
    const draft = document.createElement("button");
    draft.className = "run-item draft active";
    draft.dataset.runId = "__draft__";
    if (animate) draft.style.animationDelay = "0ms";
    draft.onclick = clearSelection;
    draft.innerHTML = `
      <div class="run-id">New release draft</div>
      <div class="run-name">Waiting for export to create release_id</div>
      <div class="run-meta">
        <span class="chip pending">pending</span>
        <span class="chip">epoch NA</span>
        <span class="chip">onnx NA</span>
        <span class="chip">ifx 0</span>
      </div>
    `;
    runsEl.appendChild(draft);
    staggerIndex = 1;
  }

  if (!visible.length && !state.draftRun) {
    runsEl.innerHTML = `<div class="empty-state">No matching release runs.</div>`;
    return;
  }

  for (const [i, run] of visible.entries()) {
    const button = document.createElement("button");
    button.className = `run-item ${run.release_id === state.selectedId ? "active" : ""}`;
    button.dataset.runId = run.release_id;
    if (animate) button.style.animationDelay = `${Math.min((i + staggerIndex) * 30, 240)}ms`;
    button.onclick = () => selectRun(run.release_id);
    button.innerHTML = `
      <div class="run-id">${escapeHtml(run.release_id)}</div>
      <div class="run-name" title="${escapeHtml(run.experiment_name || "")}">${escapeHtml(shortName(run.experiment_name))}</div>
      <div class="run-meta">
        <span class="chip ${statusClass(run.stage || run.status)}">${escapeHtml(run.stage || "created")}</span>
        <span class="chip">epoch ${formatEpoch(run.selected_epoch)}</span>
        <span class="chip">onnx ${run.onnx_version ?? "NA"}</span>
        <span class="chip">ifx ${run.ifx_platforms ?? 0}</span>
      </div>
    `;
    runsEl.appendChild(button);
  }
}

export async function fetchRun(releaseId, { renderSelectedRun, renderRuns }, options = {}) {
  state.draftRun = false;
  state.selectedId = releaseId;

  const pane = document.querySelector(".view-pane.active");
  if (pane && !options.silent) pane.classList.add("content-fade-out");

  renderRuns();

  const payload = await fetchJson(`/api/runs/${encodeURIComponent(releaseId)}`);
  state.selectedRun = payload;
  renderSelectedRun();

  if (pane) pane.classList.remove("content-fade-out");
}

export function renderRunHeader() {
  const payload = state.selectedRun;
  if (!payload) return;
  const summary = payload.summary;
  $("runTitle").textContent = summary.release_id;
  $("runSubtitle").textContent = summary.experiment_name || summary.experiment_path || "";
  $("runBadges").innerHTML = `
    <span class="badge">${escapeHtml(summary.stage || "created")}</span>
    <span class="badge">epoch ${formatEpoch(summary.selected_epoch)}</span>
    <span class="badge">ONNX v${summary.onnx_version ?? "NA"}</span>
  `;
}

export function renderDraftHeader() {
  $("runTitle").textContent = "New Release";
  $("runSubtitle").textContent = "Create a new release by selecting an experiment below.";
  $("runBadges").innerHTML = `<span class="badge">pending</span>`;
  $("details").innerHTML = `<div class="empty-state">Pick a release run from the left or create a new one.</div>`;
  $("logOutput").textContent = "Select a run or start a job to view logs.";
}

export function renderDraftFlow({ renderFlowControls, renderTimeline }) {
  renderFlowControls(draftPayload());
  renderTimeline([]);
  renderLogSelect({});
  renderLog();
}
