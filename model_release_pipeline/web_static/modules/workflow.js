import { state } from "./state.js";
import { escapeHtml, formatEpoch } from "./utils.js";

export const DEFAULT_EXPERIMENT_ROOT = "device:/nfs/dataset-ofs-remote-assist-stuck/user/jasperchen/ego_stuck_data/scenario_dnn_26q1/";

export function flowItems(summary) {
  const shared = [
    {
      key: "pick",
      group: "shared",
      badge: "Inspect",
      shortTitle: "Pick",
      title: "Luban Inspect / Pick",
      note: `epoch ${formatEpoch(summary.selected_epoch)}`,
      detail: "Inspect an experiment on Luban and recommend an epoch. Preview does not save; Pick creates a release record.",
      actionKeys: ["pick"],
    },
  ];
  const onboard = [
    {
      key: "export",
      group: "onboard",
      badge: "O1",
      shortTitle: "Export",
      title: "Onboard: Export to Local",
      note: "ONNX to NFS",
      detail: "Create or re-export ONNX from the selected experiment and epoch.",
      actionKeys: ["export"],
    },
    {
      key: "upload",
      group: "onboard",
      badge: "O2",
      shortTitle: "Upload",
      title: "Onboard: Upload to Cloud",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Upload the exported ONNX to fileserver with truck.py and bind the ONNX version to this release.",
      actionKeys: ["upload"],
    },
    {
      key: "ifx",
      group: "onboard",
      badge: "O3",
      shortTitle: "IFX",
      title: "Onboard: IFX Conversion",
      note: `ONNX v${summary.onnx_version ?? "NA"}`,
      detail: "Trigger Jenkins IFX conversion from uploaded ONNX, or poll an already-triggered Jenkins build and collect artifact versions.",
      actionKeys: ["ifx-convert", "ifx-poll"],
    },
    {
      key: "handoff",
      group: "onboard",
      badge: "O4",
      shortTitle: "Handoff",
      title: "Onboard: Handoff / Apply Commit",
      note: "manifest commit",
      detail: "Generate or apply Voyager MANIFEST updates, then use DCL commands from Release Details.",
      actionKeys: ["handoff", "apply-handoff"],
    },
    {
      key: "dcl",
      group: "onboard",
      badge: "O5",
      shortTitle: "DCL",
      title: "Onboard: DCL Upload to Kunpeng",
      note: "review diff",
      detail: "Run dcl diff inside the Voyager docker checkout. The runner returns to the configured base branch after it finishes.",
      actionKeys: ["dcl"],
    },
    {
      key: "sim_plan",
      group: "onboard",
      badge: "O6",
      shortTitle: "Sim Plan",
      title: "Onboard: Sim Plan",
      note: "Kunpeng SimOne",
      detail: "Trigger, refresh, or cancel Kunpeng SimOne plans after DCL creates the review revision.",
      actionKeys: ["sim-plan", "sim-plan-status", "sim-plan-cancel"],
    },
  ];
  const offboard = [
    {
      key: "offboard",
      group: "offboard",
      badge: "Test",
      shortTitle: "Offboard",
      title: "Offboard Validation",
      note: "validate model",
      detail: "Run offline validation from the selected pick, or enter an experiment and epoch directly without using the Onboard path.",
      actionKeys: ["offboard"],
    },
  ];
  return { shared, onboard, offboard };
}

function renderExperimentPathPicker(id, value) {
  const selectId = `${id}Select`;
  const refreshId = `${id}Refresh`;
  return `
    <div class="experiment-picker" data-root="${escapeHtml(DEFAULT_EXPERIMENT_ROOT)}">
      <input id="${id}" placeholder="experiment path" value="${escapeHtml(value)}" />
      <select id="${selectId}" class="experiment-select" aria-label="select experiment folder">
        <option value="">Select...</option>
      </select>
      <button id="${refreshId}" class="icon-button" type="button" title="Refresh experiment folders">↻</button>
    </div>
  `;
}

function stageConfig(stage) {
  return {
    ...((state.stageDefaults || {})[stage] || {}),
    ...((((state.selectedRun || {}).stage_config || {})[stage]) || {}),
  };
}

function selectedAttr(value, expected) {
  return String(value || "") === String(expected || "") ? " selected" : "";
}

function checkedAttr(value) {
  return value ? " checked" : "";
}

function renderBranchOptions(selected = "") {
  const branches = state.configBranches || [];
  return branches
    .map((b) => `<option value="${escapeHtml(b.name)}"${selectedAttr(selected, b.name)}>${escapeHtml(b.name)}</option>`)
    .join("");
}

export function renderPickForm() {
  const record = (state.selectedRun || {}).record || {};
  const experimentPath = record.experiment_path || "";
  return `
    <div class="export-form">
      ${renderExperimentPathPicker("pickExperiment", experimentPath)}
      <div class="export-row">
        <input id="pickRemote" placeholder="remote" value="luban_2_card" />
        <input id="pickDesc" placeholder="description / release note" />
      </div>
      <div class="export-row action-row">
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
      ${renderExperimentPathPicker("exportExperiment", experimentPath)}
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
  const config = stageConfig("handoff");
  return `
    <div class="export-form">
      <div class="export-row">
        <select id="handoffBranch" class="branch-select">
          <option value=""${selectedAttr(config.branch, "")}>all configured branches</option>
          ${renderBranchOptions(config.branch)}
        </select>
        <input id="handoffDesc" placeholder="description (optional)" />
      </div>
      <p class="helper-text">Leave branch empty to apply all branches. Select a specific branch to supplement a previously completed release.</p>
      <p class="helper-text todo-note">TODO: sim plan remains a manual trigger until CLI support lands.</p>
    </div>
  `;
}

export function renderDclForm() {
  const config = stageConfig("dcl");
  return `
    <div class="export-form">
      <select id="dclBranch" class="branch-select">
        <option value=""${selectedAttr(config.branch, "")}>all configured branches</option>
        ${renderBranchOptions(config.branch)}
      </select>
      <p class="helper-text">Leave empty to run DCL diff for all branches, or select one to supplement a specific CR.</p>
      <p class="helper-text">O6 Sim Plan uses the DCL revision id from this branch after DCL completes.</p>
    </div>
  `;
}

function branchByName(name) {
  return (state.configBranches || []).find((b) => b.name === name || b.checkout_branch === name);
}

function renderSimPlanChecks(config) {
  const branches = state.configBranches || [];
  const selectedPlans = Array.isArray(config.plans) ? new Set(config.plans) : null;
  const selectedBranch = config.branch || "";
  const cards = branches
    .map((branch) => {
      const plans = branch.sim_plans || (branch.sim_plan ? [{
        name: branch.sim_plan,
        enabled_by_default: branch.name !== "master" && branch.sim_plan !== "topic_ra_auto_trigger",
      }] : []);
      if (!plans.length) return "";
      const hidden = selectedBranch && selectedBranch !== branch.name ? " style=\"display:none\"" : "";
      return `
        <div class="sim-plan-branch-plans" data-branch="${escapeHtml(branch.name)}"${hidden}>
          <div class="sim-plan-branch-title">${escapeHtml(branch.name)} <span>CR ${(branch.update_diff_ids || []).join(",") || "from DCL"}</span></div>
          <div class="sim-plan-checks">
            ${plans.map((plan) => {
              const enabledByDefault = plan.enabled_by_default === true || plan.enabled_by_default === "true";
              const checked = selectedPlans ? selectedPlans.has(plan.name) : enabledByDefault;
              return `
                <label class="inline-check sim-plan-option">
                  <input class="sim-plan-check" type="checkbox" value="${escapeHtml(plan.name)}"${checkedAttr(checked)} />
                  ${escapeHtml(plan.name)}
                </label>
              `;
            }).join("")}
          </div>
        </div>
      `;
    })
    .join("");
  return `<div class="sim-plan-list">${cards}</div>`;
}

export function renderOffboardForm() {
  const record = (state.selectedRun || {}).record || {};
  const experimentPath = record.experiment_path || "";
  const selectedEpoch = (record.selection || {}).selected_epoch;
  const useSelectedChecked = state.selectedId ? " checked" : "";
  const explicitChecked = state.selectedId ? "" : " checked";
  return `
    <div class="export-form offboard-form">
      <div class="mode-switch">
        <label class="inline-check">
          <input type="radio" name="offboardMode" value="selected"${useSelectedChecked}${state.selectedId ? "" : " disabled"} />
          Use selected pick
        </label>
        <label class="inline-check">
          <input type="radio" name="offboardMode" value="explicit"${explicitChecked} />
          Run explicit experiment/epoch
        </label>
      </div>
      <div class="offboard-selected-note helper-text">
        Selected pick: ${state.selectedId ? escapeHtml(state.selectedId) : "none"}
      </div>
      ${renderExperimentPathPicker("offboardExperiment", experimentPath)}
      <div class="export-row">
        <input id="offboardEpoch" placeholder="epoch, e.g. 007" value="${selectedEpoch != null ? escapeHtml(formatEpoch(selectedEpoch)) : ""}" />
        <input id="offboardRemote" placeholder="remote" value="luban_2_card" />
      </div>
      <input id="offboardDesc" placeholder="description / release note" />
      <p class="helper-text">Explicit offboard confirmation text is <b>OFFBOARD</b>. Selected-pick offboard uses the current <b>release_id</b>.</p>
    </div>
  `;
}

export function renderSimPlanForm() {
  const config = stageConfig("sim_plan");
  const record = (state.selectedRun || {}).record || {};
  const simPlan = record.sim_plan || {};
  return `
    <div class="export-form sim-plan-form">
      <div class="export-row">
        <select id="simPlanBranch" class="branch-select">
          <option value=""${selectedAttr(config.branch, "")}>all enabled branches</option>
          ${renderBranchOptions(config.branch)}
        </select>
        <input id="simPlanRevision" value="${escapeHtml(config.revision_id || "")}" placeholder="optional revision id, defaults to DCL result" />
      </div>
      ${renderSimPlanChecks(config)}
      <div class="export-row">
        <input id="simPlanPriority" value="${escapeHtml(config.priority || "")}" placeholder="priority override" />
        <input id="simPlanSensitiveHour" value="${escapeHtml(config.time_sensitive_hour || "")}" placeholder="time sensitive hour" />
      </div>
      <input id="simPlanCancelRecord" placeholder="record id for cancel, e.g. o123456" />
      <p class="helper-text">Default selections come from branch config. Master is configured but unchecked by default because it is resource-heavy.</p>
      <p class="helper-text">${simPlan.stdout ? escapeHtml(simPlan.stdout.split("\n").slice(-1)[0]) : "No Sim Plan result recorded yet."}</p>
    </div>
  `;
}

export function renderStageConfigPanel(stage) {
  const config = stageConfig(stage);
  if (stage === "sim_plan") {
    const plans = Array.isArray(config.plans) ? config.plans.join(",") : (config.plans || "");
    const runDisabled = state.selectedId ? "" : " disabled title=\"Select a release run first.\"";
    return `
      <div class="stage-config-panel">
        <div class="stage-config-grid">
          <label>
            <span>Branch</span>
            <select id="stageConfigBranch" class="branch-select">
              <option value=""${selectedAttr(config.branch, "")}>all enabled branches</option>
              ${renderBranchOptions(config.branch)}
            </select>
          </label>
          <label>
            <span>Revision id</span>
            <input id="stageConfigRevision" value="${escapeHtml(config.revision_id || "")}" placeholder="from DCL result" />
          </label>
          <label>
            <span>Plans</span>
            <input id="stageConfigPlanNames" value="${escapeHtml(plans)}" placeholder="comma-separated plan names" />
          </label>
          <label>
            <span>Priority</span>
            <input id="stageConfigPriority" value="${escapeHtml(config.priority || "")}" placeholder="optional" />
          </label>
          <label>
            <span>Time sensitive hour</span>
            <input id="stageConfigSensitiveHour" value="${escapeHtml(config.time_sensitive_hour || "")}" placeholder="optional" />
          </label>
        </div>
        <div class="stage-config-actions">
          <button id="saveRunStageConfig" class="action-button" type="button"${runDisabled}>Save to current run</button>
          <button id="saveDefaultStageConfig" class="action-button" type="button">Save as global default</button>
          <span id="stageConfigResult" class="helper-text"></span>
        </div>
      </div>
    `;
  }
  const diffIds = Array.isArray(config.update_diff_ids)
    ? config.update_diff_ids.join(",")
    : (config.update_diff_ids || "");
  const runDisabled = state.selectedId ? "" : " disabled title=\"Select a release run first.\"";
  return `
    <div class="stage-config-panel">
      <div class="stage-config-grid">
        <label>
          <span>Branch</span>
          <select id="stageConfigBranch" class="branch-select">
            <option value=""${selectedAttr(config.branch, "")}>all configured branches</option>
            ${renderBranchOptions(config.branch)}
          </select>
        </label>
        <label>
          <span>Checkout branch</span>
          <input id="stageConfigCheckout" value="${escapeHtml(config.checkout_branch || "")}" placeholder="temporary checkout branch" />
        </label>
        <label>
          <span>CR / update diff ids</span>
          <input id="stageConfigDiffIds" value="${escapeHtml(diffIds)}" placeholder="5716859,6115905" />
        </label>
        <label>
          <span>Sim plan</span>
          <input id="stageConfigSimPlan" value="${escapeHtml(config.sim_plan || "")}" placeholder="sim plan" />
          <span class="helper-text todo-note">TODO: manual trigger until CLI support lands.</span>
        </label>
      </div>
      <div class="stage-config-checks">
        <label class="inline-check">
          <input id="stageConfigLint" type="checkbox"${checkedAttr(config.lint)} />
          lint
        </label>
        <label class="inline-check">
          <input id="stageConfigAllowDirty" type="checkbox"${checkedAttr(config.allow_dirty)} />
          allow dirty
        </label>
      </div>
      <div class="stage-config-actions">
        <button id="saveRunStageConfig" class="action-button" type="button"${runDisabled}>Save to current run</button>
        <button id="saveDefaultStageConfig" class="action-button" type="button">Save as global default</button>
        <span id="stageConfigResult" class="helper-text"></span>
      </div>
    </div>
  `;
}

export function renderActionButtons(actions, size = "") {
  const sizeClass = size ? ` ${size}` : "";
  return actions
    .map((action) => {
      const disabled = action.needs_run_id && !state.selectedId;
      const disabledAttrs = disabled
        ? ` disabled title="Select or create a release run first."`
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
