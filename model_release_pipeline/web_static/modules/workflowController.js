import { STEP_LOG_MAP } from "./constants.js";
import { fetchJson, patchJson, postJson } from "./api.js";
import { renderLog } from "./logs.js";
import { actionSpecs, draftPayload } from "./releaseData.js";
import { $, state } from "./state.js";
import { escapeHtml, formatEpoch, statusClass } from "./utils.js";
import {
  flowItems,
  renderActionButtons,
  renderDclForm,
  renderExportForm,
  renderHandoffForm,
  renderIfxForm,
  renderOffboardForm,
  renderPickForm,
  renderSimPlanPlaceholder,
  renderStageConfigPanel,
  renderUploadForm,
} from "./workflow.js";

// True only when the user explicitly clicks a flow node; suppresses animation on run switch.
let _animateNextInspector = false;

function fmt(val, digits = 3) {
  return val != null ? Number(val).toFixed(digits) : "N/A";
}

function formatPickLog(data) {
  const pick = data.pick || {};
  const lines = [];
  const epoch = pick.recommended_epoch;
  lines.push(`=== Pick Preview ===`);
  lines.push(`Recommended epoch: ${epoch != null ? formatEpoch(epoch) : "none"}`);
  lines.push(`Policy: ${pick.policy || "?"} | top_n: ${pick.top_n ?? "?"} | loss_tolerance_pct: ${pick.loss_tolerance_pct ?? "?"}`);
  lines.push("");
  const notes = pick.notes || [];
  if (notes.length) {
    lines.push("Notes:");
    for (const note of notes) lines.push(`  - ${note}`);
    lines.push("");
  }
  const candidates = pick.candidates || [];
  if (candidates.length) {
    lines.push("Top candidates:");
    for (const [i, c] of candidates.entries()) {
      const marker = c.epoch === epoch ? " ◀ recommended" : "";
      // combined_recommendations store metrics under metrics_by_task; single-task uses flat fields
      const mbt = c.metrics_by_task || {};
      const taskKeys = Object.keys(mbt);
      if (taskKeys.length) {
        lines.push(`  ${String(i + 1).padStart(2)}.  epoch ${formatEpoch(c.epoch)}${marker}`);
        for (const task of taskKeys) {
          const m = mbt[task];
          lines.push(
            `        [${task}]  precision=${fmt(m.precision)}  recall=${fmt(m.recall)}` +
            `  loss=${fmt(m.loss)}  pr_auc=${fmt(m.pr_auc)}  roc_auc=${fmt(m.roc_auc)}`
          );
        }
      } else {
        const task = c.task ? ` [${c.task}]` : "";
        lines.push(
          `  ${String(i + 1).padStart(2)}.  epoch ${formatEpoch(c.epoch)}${task}` +
          `  precision=${fmt(c.precision)}  recall=${fmt(c.recall)}  loss=${fmt(c.loss)}` +
          `  pr_auc=${fmt(c.pr_auc)}  roc_auc=${fmt(c.roc_auc)}${marker}`
        );
        for (const note of c.notes || []) lines.push(`        note: ${note}`);
      }
    }
    lines.push("");
  }
  const perTask = pick.per_task || {};
  const taskKeys = Object.keys(perTask);
  if (taskKeys.length > 1) {
    lines.push("Per-task recommendations:");
    for (const task of taskKeys) {
      const tr = perTask[task];
      lines.push(`  ${task}: recommended epoch ${tr.recommended_epoch != null ? formatEpoch(tr.recommended_epoch) : "none"}`);
    }
  }
  return lines;
}

function ensurePickPreviewOption() {
  const logSelect = $("logSelect");
  if (!logSelect) return;
  if (![...logSelect.options].some((o) => o.value === "pick_preview")) {
    const option = document.createElement("option");
    option.value = "pick_preview";
    option.textContent = "Pick preview";
    logSelect.prepend(option);
  }
  logSelect.value = "pick_preview";
}

function renderExperimentOptions(inputId, data) {
  const input = $(inputId);
  const select = $(`${inputId}Select`);
  if (!input || !select) return;
  const folders = data?.folders || [];
  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = folders.length ? "Select..." : "No folders found";
  select.appendChild(placeholder);
  for (const folder of folders) {
    const option = document.createElement("option");
    option.value = folder.path || "";
    option.textContent = folder.name || folder.path || "";
    option.title = folder.path || "";
    option.selected = input.value.trim() === option.value;
    select.appendChild(option);
  }
}

async function loadExperimentOptions(inputId, forceReload = false) {
  const select = $(`${inputId}Select`);
  if (!select) return;
  const picker = select.closest(".experiment-picker");
  const root = picker?.dataset.root || "";
  const cacheKey = root || "__default__";
  if (!forceReload && state.experimentFolderCache[cacheKey]) {
    renderExperimentOptions(inputId, state.experimentFolderCache[cacheKey]);
    return;
  }
  select.disabled = true;
  select.innerHTML = `<option value="">Loading...</option>`;
  try {
    const params = new URLSearchParams();
    if (root) params.set("root", root);
    const data = await fetchJson(`/api/experiment-folders?${params}`);
    state.experimentFolderCache[cacheKey] = {
      ...data,
      fetchedAt: Date.now(),
    };
    renderExperimentOptions(inputId, data);
  } catch (e) {
    select.innerHTML = "";
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Load failed";
    option.title = e.message;
    select.appendChild(option);
  } finally {
    select.disabled = false;
  }
}

function bindExperimentPicker(inputId) {
  const input = $(inputId);
  const select = $(`${inputId}Select`);
  const refresh = $(`${inputId}Refresh`);
  if (!input || !select) return;
  select.onchange = () => {
    if (select.value) input.value = select.value;
  };
  if (refresh) {
    refresh.onclick = () => loadExperimentOptions(inputId, true);
  }
  loadExperimentOptions(inputId);
}

function bindActionButtons(onAction) {
  document.querySelectorAll(".action-button").forEach((button) => {
    button.onclick = async () => {
      const action = button.dataset.action;
      const dryRun = button.dataset.dryRun === "true";
      const confirmText = $("confirmText") ? $("confirmText").value.trim() : "";
      await onAction(action, dryRun, confirmText);
    };
  });
}

function selectedOffboardMode() {
  return document.querySelector('input[name="offboardMode"]:checked')?.value || (state.selectedId ? "selected" : "explicit");
}

function bindFlowNodes(onAction) {
  document.querySelectorAll(".flow-node").forEach((node) => {
    node.onclick = () => {
      state.activeStep = node.dataset.step;
      _animateNextInspector = true;
      renderFlowControls(state.selectedRun || draftPayload(), onAction);
    };
  });
}

function supportsStageConfig(stepKey) {
  return ["handoff", "dcl"].includes(stepKey);
}

function collectStageConfig() {
  const diffIds = $("stageConfigDiffIds") ? $("stageConfigDiffIds").value.trim() : "";
  return {
    branch: $("stageConfigBranch") ? $("stageConfigBranch").value : "",
    checkout_branch: $("stageConfigCheckout") ? $("stageConfigCheckout").value.trim() : "",
    update_diff_ids: diffIds,
    sim_plan: $("stageConfigSimPlan") ? $("stageConfigSimPlan").value.trim() : "",
    lint: $("stageConfigLint") ? $("stageConfigLint").checked : false,
    allow_dirty: $("stageConfigAllowDirty") ? $("stageConfigAllowDirty").checked : false,
  };
}

function bindStageConfigPanel(stepKey, onAction) {
  const toggle = $("stageConfigToggle");
  if (toggle) {
    toggle.onclick = () => {
      state.openStageSettings = state.openStageSettings === stepKey ? null : stepKey;
      renderFlowControls(state.selectedRun || draftPayload(), onAction);
    };
  }
  const saveRun = $("saveRunStageConfig");
  const saveDefault = $("saveDefaultStageConfig");
  const result = $("stageConfigResult");
  if (saveRun) {
    saveRun.onclick = async () => {
      if (!state.selectedId) return;
      saveRun.disabled = true;
      if (result) result.textContent = "Saving...";
      try {
        const data = await patchJson(
          `/api/runs/${encodeURIComponent(state.selectedId)}/stage-config`,
          { [stepKey]: collectStageConfig() }
        );
        state.selectedRun.stage_config = data.stage_config || {};
        if (result) result.textContent = "Saved to run.";
        renderFlowControls(state.selectedRun || draftPayload(), onAction);
      } catch (e) {
        if (result) result.textContent = e.message;
      } finally {
        saveRun.disabled = false;
      }
    };
  }
  if (saveDefault) {
    saveDefault.onclick = async () => {
      saveDefault.disabled = true;
      if (result) result.textContent = "Saving...";
      try {
        const data = await patchJson(
          "/api/config/stage-defaults",
          { [stepKey]: collectStageConfig() }
        );
        state.stageDefaults = data.stage_defaults || {};
        if (result) result.textContent = "Saved as default.";
        renderFlowControls(state.selectedRun || draftPayload(), onAction);
      } catch (e) {
        if (result) result.textContent = e.message;
      } finally {
        saveDefault.disabled = false;
      }
    };
  }
}

function renderConfirmHint(actions) {
  const hint = $("confirmHint");
  const input = $("confirmText");
  if (!hint || !input) return;
  const hasRealAction = actions.some((action) => action.requires_confirm);
  const exportOnly =
    actions.length > 0 && actions.every((action) => action.key === "export");
  const offboardOnly =
    actions.length > 0 && actions.every((action) => action.key === "offboard");
  if (!hasRealAction) {
    hint.innerHTML = "This step has no destructive backend action.";
    input.placeholder = "no confirmation required";
    return;
  }
  if (exportOnly) {
    hint.innerHTML = "Real export requires <b>EXPORT</b>.";
    input.placeholder = "EXPORT";
    return;
  }
  if (offboardOnly && (!state.selectedId || selectedOffboardMode() === "explicit")) {
    hint.innerHTML = "Direct real offboard requires <b>OFFBOARD</b>.";
    input.placeholder = "OFFBOARD";
    return;
  }
  hint.innerHTML = "Real actions require current <b>release_id</b>.";
  input.placeholder = state.selectedId || "release_id";
}

function renderFlowInspector(flow, actions, statusByStep, onAction) {
  const item = flow.find((step) => step.key === state.activeStep) || flow[0];
  const itemActions = item.actionKeys
    .map((key) => actions.find((action) => action.key === key))
    .filter(Boolean);
  const stepStatus = statusByStep[item.key] || "pending";
  const inspector = $("flowInspector");
  const shouldAnimate = _animateNextInspector;
  _animateNextInspector = false;
  if (shouldAnimate) {
    inspector.classList.remove("animate-update");
    void inspector.offsetWidth; // force reflow to restart animation
    inspector.classList.add("animate-update");
  } else {
    inspector.classList.remove("animate-update");
  }
  inspector.innerHTML = `
    <div class="inspector-head">
      <div>
        <p class="eyebrow">Selected Step</p>
        <h3>${escapeHtml(item.title)}</h3>
        <p class="muted">${escapeHtml(item.detail)}</p>
      </div>
      <div class="inspector-tools">
        ${supportsStageConfig(item.key) ? `<button id="stageConfigToggle" class="icon-button" type="button" title="Stage settings">⚙</button>` : ""}
        <span class="chip ${statusClass(stepStatus)}">${escapeHtml(stepStatus)}</span>
      </div>
    </div>
    ${item.key === "pick" ? renderPickForm() : ""}
    ${item.key === "export" ? renderExportForm() : ""}
    ${item.key === "upload" ? renderUploadForm() : ""}
    ${item.key === "ifx" ? renderIfxForm() : ""}
    ${item.key === "handoff" ? renderHandoffForm() : ""}
    ${item.key === "dcl" ? renderDclForm() : ""}
    ${item.key === "offboard" ? renderOffboardForm() : ""}
    ${item.key === "sim_plan" ? renderSimPlanPlaceholder() : ""}
    ${state.openStageSettings === item.key ? renderStageConfigPanel(item.key) : ""}
    <div class="flow-actions">${renderActionButtons(itemActions, "primary")}</div>
  `;
  bindActionButtons(onAction);
  bindStageConfigPanel(item.key, onAction);
  bindExperimentPicker("pickExperiment");
  bindExperimentPicker("exportExperiment");
  bindExperimentPicker("offboardExperiment");
  renderConfirmHint(itemActions);

  document.querySelectorAll('input[name="offboardMode"]').forEach((input) => {
    input.onchange = () => renderConfirmHint(itemActions);
  });

  const previewBtn = $("pickPreviewBtn");
  if (previewBtn) {
    previewBtn.onclick = async () => {
      const experiment = ($("pickExperiment")?.value || "").trim();
      const remote = ($("pickRemote")?.value || "").trim();
      const resultEl = $("pickPreviewResult");
      if (!experiment) { if (resultEl) resultEl.textContent = "Enter experiment path first."; return; }
      if (resultEl) resultEl.textContent = "Loading…";
      try {
        const params = new URLSearchParams({ experiment });
        if (remote) params.set("remote", remote);
        const data = await fetchJson(`/api/pick?${params}`);
        const epoch = data.pick?.recommended_epoch;
        if (resultEl) resultEl.textContent = epoch != null
          ? `Recommended: epoch ${formatEpoch(epoch)}`
          : "No recommendation found.";
        state.pickPreviewLines = formatPickLog(data);
        state.selectedLog = "pick_preview";
        ensurePickPreviewOption();
        renderLog();
        const logDrawer = $("logDrawer");
        if (logDrawer) logDrawer.open = true;
      } catch (e) {
        if (resultEl) resultEl.textContent = e.message;
      }
    };
  }

  if (state.selectedRun && state.selectedRun.logs) {
    const targetLog = STEP_LOG_MAP[state.activeStep];
    if (targetLog) {
      state.selectedLog = targetLog;
      if ($("logSelect")) $("logSelect").value = targetLog;
      renderLog();
    }
  }

  const copyOnnxBtn = $("copyVersionedOnnxBtn");
  if (copyOnnxBtn) {
    copyOnnxBtn.onclick = async () => {
      const resultEl = $("copyVersionedOnnxResult");
      copyOnnxBtn.disabled = true;
      if (resultEl) resultEl.textContent = "Copying...";
      try {
        const data = await postJson(
          `/api/runs/${encodeURIComponent(state.selectedId)}/copy-versioned-onnx`,
          {}
        );
        if (resultEl) resultEl.textContent = `Copied to ${data.target}`;
      } catch (e) {
        if (resultEl) resultEl.textContent = e.message;
      } finally {
        copyOnnxBtn.disabled = false;
      }
    };
  }
}

export function renderFlowControls(payload, onAction) {
  payload = payload || draftPayload();
  const actions = actionSpecs(payload.actions);
  const flowGroups = flowItems(payload.summary || {});
  const flow = [
    ...(flowGroups.shared || []),
    ...(flowGroups.offboard || []),
    ...(flowGroups.onboard || []),
  ];
  const statusByStep = Object.fromEntries(
    (payload.timeline || []).map((step) => [step.key, step.status])
  );
  if (!flow.some((item) => item.key === state.activeStep)) {
    state.activeStep = flow[0].key;
  }

  const renderNode = (item) => {
    const stepStatus = statusByStep[item.key] || "pending";
    return `
      <button class="flow-node ${item.key} ${state.activeStep === item.key ? "selected" : ""} ${statusClass(stepStatus)}" data-step="${item.key}">
        <div class="flow-top">
          <div class="flow-number">${escapeHtml(item.badge || "")}</div>
          <div>
            <h4>${escapeHtml(item.shortTitle)}</h4>
            <p>${escapeHtml(item.note)}</p>
          </div>
          <span class="chip flow-state ${statusClass(stepStatus)}">${escapeHtml(stepStatus)}</span>
        </div>
      </button>
    `;
  };

  $("flowControls").innerHTML = `
    <div class="flow-entry-row">
      <div class="flow-group shared-flow">
        <div class="flow-group-title">Luban Inspect / Pick</div>
        <div class="flow-lane shared-lane">
          ${(flowGroups.shared || []).map(renderNode).join("")}
        </div>
      </div>
      <div class="flow-group offboard-flow">
        <div class="flow-group-title">Standalone Offboard</div>
        <div class="flow-lane offboard-lane">
          ${(flowGroups.offboard || []).map(renderNode).join("")}
        </div>
      </div>
    </div>
    <div class="flow-group onboard-flow">
      <div class="flow-group-title">Onboard</div>
      <div class="flow-lane onboard-lane">
        ${(flowGroups.onboard || []).map(renderNode).join("")}
      </div>
    </div>
  `;
  bindFlowNodes(onAction);
  renderFlowInspector(flow, actions, statusByStep, onAction);
}

export function renderTimeline(timeline) {
  let html = "";
  let prevGroup = null;
  for (const [index, step] of timeline.entries()) {
    if (step.group && step.group !== prevGroup && prevGroup !== null) {
      html += `<div class="timeline-group-sep"><span>Offboard Validation</span></div>`;
    }
    prevGroup = step.group ?? prevGroup;
    html += `
      <div class="step ${statusClass(step.status)}">
        <div class="step-index">${index + 1}</div>
        <div class="step-card">
          <div class="step-text">
            <h4>${escapeHtml(step.title)}</h4>
            <p>${escapeHtml(step.description)}</p>
          </div>
          <span class="chip step-state ${statusClass(step.status)}">${escapeHtml(step.status)}</span>
        </div>
      </div>
    `;
  }
  $("timeline").innerHTML = html;
}
