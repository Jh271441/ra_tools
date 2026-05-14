import { state } from "./state.js";
import { escapeHtml, formatEpoch } from "./utils.js";

export function flowItems(summary) {
  return [
    {
      key: "pick",
      group: "main",
      shortTitle: "Pick",
      title: "1. Pick Epoch",
      note: `epoch ${formatEpoch(summary.selected_epoch)}`,
      detail: "Inspect experiment and recommend epoch from metrics. Creates a new release record. Use 'Preview epoch' to check the recommendation first.",
      actionKeys: ["pick"],
    },
    {
      key: "export",
      group: "main",
      shortTitle: "Export",
      title: "2. Model Export",
      note: "ONNX to NFS",
      detail: "Create or re-export ONNX from the selected experiment and epoch.",
      actionKeys: ["export"],
    },
    {
      key: "upload",
      group: "main",
      shortTitle: "Upload",
      title: "3. Upload ONNX",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Upload the exported ONNX to fileserver with truck.py and bind the ONNX version to this release.",
      actionKeys: ["upload"],
    },
    {
      key: "ifx",
      group: "main",
      shortTitle: "IFX",
      title: "4. IFX Convert",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Trigger Jenkins IFX conversion from uploaded ONNX, or poll an already-triggered Jenkins build and collect artifact versions.",
      actionKeys: ["ifx-convert", "ifx-poll"],
    },
    {
      key: "handoff",
      group: "main",
      shortTitle: "Handoff",
      title: "5. Handoff",
      note: "manifest commit",
      detail: "Generate or apply Voyager MANIFEST updates, then use DCL commands from Release Details.",
      actionKeys: ["handoff", "apply-handoff"],
    },
    {
      key: "dcl",
      group: "main",
      shortTitle: "DCL",
      title: "6. DCL Diff",
      note: "review diff",
      detail: "Run dcl diff inside the Voyager docker checkout. The runner returns to the configured base branch after it finishes.",
      actionKeys: ["dcl"],
    },
    {
      key: "offboard",
      group: "offboard",
      shortTitle: "Offboard",
      title: "7. Offboard",
      note: "validate model",
      detail: "Run release validation against the selected experiment and epoch. Available independently after Pick — does not require the Onboard path.",
      actionKeys: ["offboard"],
    },
  ];
}

export function renderPickForm() {
  const record = (state.selectedRun || {}).record || {};
  const experimentPath = record.experiment_path || "";
  return `
    <div class="export-form">
      <input id="pickExperiment" placeholder="experiment path" value="${escapeHtml(experimentPath)}" />
      <div class="export-row">
        <input id="pickRemote" placeholder="remote" value="luban_2_card" />
        <input id="pickDesc" placeholder="description / release note" />
      </div>
      <div class="export-row" style="align-items:center;gap:12px">
        <button id="pickPreviewBtn" class="action-button" type="button">Preview epoch ↗</button>
        <span id="pickPreviewResult" class="helper-text"></span>
      </div>
      <p class="helper-text">Pick runs on Luban and creates a new release. Use Preview to check the recommendation without saving.</p>
    </div>
  `;
}

export function renderExportForm() {
  const record = (state.selectedRun || {}).record || {};
  const experimentPath = record.experiment_path || "";
  return `
    <div class="export-form">
      <input id="exportExperiment" placeholder="experiment path" value="${escapeHtml(experimentPath)}" />
      <div class="export-row">
        <input id="exportEpoch" placeholder="epoch, e.g. 007" />
        <input id="exportRemote" placeholder="remote" value="luban_2_card" />
      </div>
      <input id="exportDesc" placeholder="description / release note" />
      <p class="helper-text">Real export confirmation text is <b>EXPORT</b>.</p>
    </div>
  `;
}

export function renderUploadForm() {
  const copyInfo = (state.selectedRun || {}).onnx_local_copy || {};
  const copyBlock = copyInfo.available
    ? `
      <div class="copy-onnx-panel">
        <button id="copyVersionedOnnxBtn" class="action-button" type="button">Copy versioned ONNX</button>
        <span id="copyVersionedOnnxResult" class="helper-text">${escapeHtml(copyInfo.target_path || "")}</span>
      </div>
    `
    : "";
  return `
    <div class="export-form">
      <div class="export-row">
        <input id="uploadVersion" placeholder="optional ONNX version, e.g. 67" />
        <label class="inline-check">
          <input id="uploadReplace" type="checkbox" />
          replace existing binding
        </label>
      </div>
      <input id="uploadDesc" placeholder="fileserver description / release note" />
      <p class="helper-text">Real upload confirmation text is the current <b>release_id</b>.</p>
      ${copyBlock}
    </div>
  `;
}

export function renderIfxForm() {
  const record = (state.selectedRun || {}).record || {};
  const jenkins = ((record.ifx || {}).jenkins || {});
  const buildUrl = jenkins.build_url || "";
  return `
    <div class="export-form">
      <input id="ifxBuildUrl" placeholder="optional Jenkins build URL, e.g. http://10.79.18.51:8088/job/.../11669/" value="${escapeHtml(buildUrl)}" />
      <p class="helper-text">Use this when the saved Jenkins queue item has expired but the build URL is known.</p>
    </div>
  `;
}

export function renderHandoffForm() {
  const branches = state.configBranches || [];
  const options = branches
    .map((b) => `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}</option>`)
    .join("");
  return `
    <div class="export-form">
      <div class="export-row">
        <select id="handoffBranch" class="branch-select">
          <option value="">all configured branches</option>
          ${options}
        </select>
        <input id="handoffDesc" placeholder="description (optional)" />
      </div>
      <p class="helper-text">Leave branch empty to apply all branches. Select a specific branch to supplement a previously completed release.</p>
    </div>
  `;
}

export function renderDclForm() {
  const branches = state.configBranches || [];
  const options = branches
    .map((b) => `<option value="${escapeHtml(b.name)}">${escapeHtml(b.name)}</option>`)
    .join("");
  return `
    <div class="export-form">
      <select id="dclBranch" class="branch-select">
        <option value="">all configured branches</option>
        ${options}
      </select>
      <p class="helper-text">Leave empty to run DCL diff for all branches, or select one to supplement a specific CR.</p>
    </div>
  `;
}

export function renderActionButtons(actions, size = "") {
  const sizeClass = size ? ` ${size}` : "";
  return actions
    .map((action) => {
      const disabled = action.needs_run_id && !state.selectedId;
      const disabledAttrs = disabled
        ? ` disabled title="Export first to create a release_id."`
        : "";
      const dryButton = action.supports_dry_run
        ? `<button class="action-button${sizeClass}" data-action="${action.key}" data-dry-run="true"${disabledAttrs}>${escapeHtml(action.label)} Dry-run</button>`
        : "";
      const realButton = action.requires_confirm
        ? `<button class="action-button danger${sizeClass}" data-action="${action.key}" data-dry-run="false"${disabledAttrs}>${escapeHtml(action.label)}</button>`
        : `<button class="action-button${sizeClass}" data-action="${action.key}" data-dry-run="false"${disabledAttrs}>${escapeHtml(action.label)}</button>`;
      return `${dryButton}${realButton}`;
    })
    .join("");
}
