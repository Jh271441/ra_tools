import { state } from "./state.js";
import { escapeHtml, formatEpoch } from "./utils.js";

export function flowItems(summary) {
  return [
    {
      key: "inspect",
      shortTitle: "Inspect",
      title: "1. Inspect",
      note: "metadata",
      detail: "Inspect experiment metadata, checkpoints, logs, hparams, and existing exports. This is handled inside Model Export for a new run.",
      actionKeys: [],
    },
    {
      key: "pick",
      shortTitle: "Pick",
      title: "2. Pick Epoch",
      note: `epoch ${formatEpoch(summary.selected_epoch)}`,
      detail: "Recommend or confirm the epoch from log/TensorBoard metrics. Supplying an epoch makes this a manual picker decision.",
      actionKeys: [],
    },
    {
      key: "export",
      shortTitle: "Export",
      title: "3. Model Export",
      note: "new release run",
      detail: "Create or re-export ONNX from the selected experiment and epoch.",
      actionKeys: ["export"],
    },
    {
      key: "upload",
      shortTitle: "Upload",
      title: "4. Upload ONNX",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Upload the exported ONNX to fileserver with truck.py and bind the ONNX version to this release.",
      actionKeys: ["upload"],
    },
    {
      key: "ifx",
      shortTitle: "IFX",
      title: "5. IFX Convert",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Trigger Jenkins IFX conversion from uploaded ONNX, or poll an already-triggered Jenkins build and collect artifact versions.",
      actionKeys: ["ifx-convert", "ifx-poll"],
    },
    {
      key: "handoff",
      shortTitle: "Handoff",
      title: "6. Handoff",
      note: "manifest commit",
      detail: "Generate or apply Voyager MANIFEST updates, then use DCL commands from Release Details.",
      actionKeys: ["handoff", "apply-handoff"],
    },
    {
      key: "dcl",
      shortTitle: "DCL",
      title: "7. DCL Diff",
      note: "review diff",
      detail: "Run dcl diff inside the Voyager docker checkout. The runner returns to the configured base branch after it finishes.",
      actionKeys: ["dcl"],
    },
    {
      key: "offboard",
      shortTitle: "Offboard",
      title: "8. Offboard",
      note: "validate model",
      detail: "Run release validation against the selected experiment and epoch.",
      actionKeys: ["offboard"],
    },
  ];
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
