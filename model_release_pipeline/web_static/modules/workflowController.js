import { STEP_LOG_MAP } from "./constants.js";
import { renderLog } from "./logs.js";
import { actionSpecs, draftPayload } from "./releaseData.js";
import { $, state } from "./state.js";
import { escapeHtml, statusClass } from "./utils.js";
import {
  flowItems,
  renderActionButtons,
  renderExportForm,
  renderIfxForm,
  renderUploadForm,
} from "./workflow.js";

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

function bindFlowNodes(onAction) {
  document.querySelectorAll(".flow-node").forEach((node) => {
    node.onclick = () => {
      state.activeStep = node.dataset.step;
      renderFlowControls(state.selectedRun || draftPayload(), onAction);
    };
  });
}

function renderConfirmHint(actions) {
  const hint = $("confirmHint");
  const input = $("confirmText");
  if (!hint || !input) return;
  const hasRealAction = actions.some((action) => action.requires_confirm);
  const exportOnly =
    actions.length > 0 && actions.every((action) => action.key === "export");
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
  hint.innerHTML = "Real actions require current <b>release_id</b>.";
  input.placeholder = state.selectedId || "release_id";
}

function renderFlowInspector(flow, actions, statusByStep, onAction) {
  const item = flow.find((step) => step.key === state.activeStep) || flow[0];
  const itemActions = item.actionKeys
    .map((key) => actions.find((action) => action.key === key))
    .filter(Boolean);
  const stepStatus = statusByStep[item.key] || "pending";
  $("flowInspector").innerHTML = `
    <div class="inspector-head">
      <div>
        <p class="eyebrow">Selected Step</p>
        <h3>${escapeHtml(item.title)}</h3>
        <p class="muted">${escapeHtml(item.detail)}</p>
      </div>
      <span class="chip ${statusClass(stepStatus)}">${escapeHtml(stepStatus)}</span>
    </div>
    ${item.key === "export" ? renderExportForm() : ""}
    ${item.key === "upload" ? renderUploadForm() : ""}
    ${item.key === "ifx" ? renderIfxForm() : ""}
    <div class="flow-actions">${renderActionButtons(itemActions, "primary")}</div>
  `;
  bindActionButtons(onAction);
  renderConfirmHint(itemActions);

  if (state.selectedRun && state.selectedRun.logs) {
    const targetLog = STEP_LOG_MAP[state.activeStep];
    if (targetLog) {
      state.selectedLog = targetLog;
      if ($("logSelect")) $("logSelect").value = targetLog;
      renderLog();
    }
  }
}

export function renderFlowControls(payload, onAction) {
  payload = payload || draftPayload();
  const actions = actionSpecs(payload.actions);
  const flow = flowItems(payload.summary || {});
  const statusByStep = Object.fromEntries(
    (payload.timeline || []).map((step) => [step.key, step.status])
  );
  if (!flow.some((item) => item.key === state.activeStep)) {
    state.activeStep = flow[0].key;
  }
  $("flowControls").innerHTML = flow
    .map((item, index) => {
      const stepStatus = statusByStep[item.key] || "pending";
      return `
        <button class="flow-node ${item.key} ${state.activeStep === item.key ? "selected" : ""} ${statusClass(stepStatus)}" data-step="${item.key}">
          <div class="flow-top">
            <div class="flow-number">${index + 1}</div>
            <div>
              <h4>${escapeHtml(item.shortTitle)}</h4>
              <p>${escapeHtml(item.note)}</p>
            </div>
            <span class="chip flow-state ${statusClass(stepStatus)}">${escapeHtml(stepStatus)}</span>
          </div>
        </button>
      `;
    })
    .join("");
  bindFlowNodes(onAction);
  renderFlowInspector(flow, actions, statusByStep, onAction);
}

export function renderTimeline(timeline) {
  $("timeline").innerHTML = timeline
    .map(
      (step, index) => `
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
    `
    )
    .join("");
}
