const state = {
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

const $ = (id) => document.getElementById(id);

const DEFAULT_ACTIONS = [
  { key: "export", label: "Model Export", supports_dry_run: true, requires_confirm: true, needs_run_id: false },
  { key: "upload", label: "Upload ONNX", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "ifx-convert", label: "Trigger IFX Convert", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "handoff", label: "Generate Handoff", supports_dry_run: false, requires_confirm: false, needs_run_id: true },
  { key: "apply-handoff", label: "Apply Handoff", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "dcl", label: "Run DCL Diff", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
  { key: "offboard", label: "Run Offboard", supports_dry_run: true, requires_confirm: true, needs_run_id: true },
];

const LOG_LABELS = {
  export_stdout: "Export stdout",
  export_stderr: "Export stderr",
  upload_stdout: "Upload stdout",
  upload_stderr: "Upload stderr",
  ifx_stdout: "IFX stdout",
  ifx_stderr: "IFX stderr",
  jenkins_console: "Jenkins console",
  handoff_stdout: "Handoff stdout",
  handoff_stderr: "Handoff stderr",
  dcl_stdout: "DCL stdout",
  dcl_stderr: "DCL stderr",
  offboard_stdout: "Offboard stdout",
  offboard_stderr: "Offboard stderr",
};

const STEP_LOG_MAP = {
  inspect: "export_stdout",
  pick: "export_stdout",
  export: "export_stdout",
  upload: "upload_stdout",
  ifx: "ifx_stdout",
  handoff: "handoff_stdout",
  dcl: "dcl_stdout",
  offboard: "offboard_stdout",
};

const NEXT_STEP_BY_ACTION = {
  export: "upload",
  upload: "ifx",
  "ifx-convert": "handoff",
  handoff: "handoff",
  "apply-handoff": "dcl",
  dcl: "offboard",
};

function actionSpecs(payloadActions = []) {
  const byKey = Object.fromEntries(DEFAULT_ACTIONS.map((action) => [action.key, action]));
  for (const action of payloadActions || []) {
    byKey[action.key] = { ...(byKey[action.key] || {}), ...action };
  }
  return Object.values(byKey);
}

function draftPayload() {
  return {
    summary: {
      release_id: "New release draft",
      experiment_name: "Waiting for export to create release_id",
      selected_epoch: null,
      onnx_version: null,
      stage: "pending",
      status: "pending",
    },
    actions: actionSpecs(),
    timeline: [],
    logs: {},
  };
}

function statusClass(status) {
  if (!status) return "";
  if (["failed", "export_failed", "offboard_failed"].includes(status)) return "failed";
  if (["done", "completed", "ok"].includes(status)) return "done";
  return String(status).replace(/[^a-z0-9_-]/gi, "");
}

function formatEpoch(epoch) {
  if (epoch === null || epoch === undefined) return "NA";
  return String(Number(epoch)).padStart(3, "0");
}

function shortName(value) {
  if (!value) return "manual / unknown";
  return value.length > 58 ? `${value.slice(0, 55)}...` : value;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`${response.status} ${text}`);
  }
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `${response.status} ${response.statusText}`);
  }
  return data;
}

async function loadRuns(selectFirst = false) {
  const payload = await fetchJson("/api/runs");
  state.runs = payload.runs || [];
  $("runsDir").textContent = `runs_dir: ${payload.runs_dir}`;
  renderRuns();
  // Do NOT select first by default anymore, just render empty state or selected run
  if (state.selectedId) {
     await selectRun(state.selectedId);
  } else {
     renderEmptyState();
  }
}

function renderEmptyState() {
  $("runTitle").textContent = "New Release";
  $("runSubtitle").textContent = "Create a new release by selecting an experiment below.";
  $("runBadges").innerHTML = `<span class="badge">pending</span>`;
  renderFlowControls(draftPayload());
  renderTimeline([]);
  // Clear details
  $("details").innerHTML = `<div class="empty-state">Pick a release run from the left or create a new one.</div>`;
  $("logOutput").textContent = "Select a run or start a job to view logs.";
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

$("fullscreenLog").onclick = (e) => {
  e.preventDefault(); // Prevent details toggle
  e.stopPropagation();
  $("logDrawer").classList.toggle("fullscreen");
};

function renderRuns() {
  const filter = $("runFilter").value.trim().toLowerCase();
  const runsEl = $("runs");
  runsEl.innerHTML = "";
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

  if (state.draftRun) {
    const draft = document.createElement("button");
    draft.className = "run-item draft active";
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
  }

  if (!visible.length && !state.draftRun) {
    runsEl.innerHTML = `<div class="empty-state">No matching release runs.</div>`;
    return;
  }

  for (const run of visible) {
    const button = document.createElement("button");
    button.className = `run-item ${run.release_id === state.selectedId ? "active" : ""}`;
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

async function selectRun(releaseId) {
  state.draftRun = false;
  state.selectedId = releaseId;
  renderRuns();
  const payload = await fetchJson(`/api/runs/${encodeURIComponent(releaseId)}`);
  state.selectedRun = payload;
  renderSelectedRun();
}

function renderSelectedRun() {
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
  renderFlowControls(payload);
  renderTimeline(payload.timeline || []);
  renderDetails(payload);
  renderLogSelect(payload.logs || {});
  renderLog();
}

function renderFlowControls(payload) {
  payload = payload || draftPayload();
  const actions = actionSpecs(payload.actions);
  const flow = flowItems(payload.summary || {});
  const statusByStep = Object.fromEntries((payload.timeline || []).map((step) => [step.key, step.status]));
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
  bindFlowNodes();
  renderFlowInspector(flow, actions, statusByStep);
}

function flowItems(summary) {
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
      detail: "Trigger Jenkins IFX conversion from uploaded ONNX and collect generated artifact versions.",
      actionKeys: ["ifx-convert"],
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

function bindFlowNodes() {
  document.querySelectorAll(".flow-node").forEach((node) => {
    node.onclick = () => {
      state.activeStep = node.dataset.step;
      renderFlowControls(state.selectedRun || draftPayload());
    };
  });
}

function renderFlowInspector(flow, actions, statusByStep) {
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
    <div class="flow-actions">${renderActionButtons(itemActions, "primary")}</div>
  `;
  bindActionButtons();

  renderConfirmHint(itemActions);

  // Auto-select corresponding log channel
  if (state.selectedRun && state.selectedRun.logs) {
    const targetLog = STEP_LOG_MAP[state.activeStep];
    if (targetLog) {
      state.selectedLog = targetLog;
      if ($("logSelect")) $("logSelect").value = targetLog;
      renderLog();
    }
  }
}

function renderConfirmHint(actions) {
  const hint = $("confirmHint");
  const input = $("confirmText");
  if (!hint || !input) return;
  const hasRealAction = actions.some((action) => action.requires_confirm);
  const exportOnly = actions.length > 0 && actions.every((action) => action.key === "export");
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

function renderExportForm() {
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

function renderUploadForm() {
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

function renderTimeline(timeline) {
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

function renderDetails(payload) {
  const record = payload.record || {};
  const summary = payload.summary || {};
  const ifx = record.ifx || {};
  const mapping = ifx.ifx_mapping || {};
  const apply = record.apply_handoff || {};
  const commands = payload.commands || {};
  const errors = record.errors || [];

  const artifacts =
    Object.entries(mapping)
      .map(
        ([platform, item]) =>
          `<div class="kv"><span>${escapeHtml(platform)}</span><b>${escapeHtml(item.name || "NA")} -v ${item.version ?? "NA"}</b></div>`
      )
      .join("") || `<div class="empty-state">No IFX mapping yet.</div>`;

  const branches =
    (apply.results || [])
      .map(
        (item) =>
          `<div class="kv"><span>${escapeHtml(item.branch)}</span><b>${escapeHtml(item.checkout_branch)}: ${item.returncode === 0 ? "OK" : `FAILED(${item.returncode})`}</b></div>`
      )
      .join("") || `<div class="empty-state">No applied handoff branches yet.</div>`;

  const metrics = (payload.offboard_metrics || []).length
    ? `<pre class="metric-table">${escapeHtml(payload.offboard_metrics.join("\n"))}</pre>`
    : `<div class="empty-state">No offboard metrics captured yet.</div>`;

  const dcl =
    (commands.dcl_commands || [])
      .map((command) => `<div class="code-line">${escapeHtml(command)}</div>`)
      .join("") || `<div class="empty-state">DCL commands are not ready.</div>`;

  $("details").className = "details";
  $("details").innerHTML = `
    <div class="detail-block">
      <h4>Release</h4>
      <div class="kv"><span>stage</span><b>${escapeHtml(summary.stage || "NA")} / ${escapeHtml(summary.status || "NA")}</b></div>
      <div class="kv"><span>experiment</span><b>${escapeHtml(summary.experiment_name || "NA")}</b></div>
      <div class="kv"><span>epoch</span><b>${formatEpoch(summary.selected_epoch)} (${escapeHtml(summary.selection_source || "unknown")})</b></div>
      <div class="kv"><span>updated</span><b>${escapeHtml(summary.updated_at || "NA")}</b></div>
    </div>

    <div class="detail-block">
      <h4>IFX Artifacts</h4>
      ${artifacts}
    </div>

    <div class="detail-block">
      <h4>Handoff Branches</h4>
      ${branches}
      ${dcl}
    </div>

    <div class="detail-block">
      <h4>Offboard Metrics</h4>
      ${metrics}
    </div>

    <div class="detail-block">
      <h4>Next CLI Commands</h4>
      <div class="code-line">${escapeHtml(commands.ifx_convert || "")}</div>
      <div class="code-line">${escapeHtml(commands.apply_handoff || "")}</div>
      <div class="code-line">${escapeHtml(commands.dcl || "")}</div>
      <div class="code-line">${escapeHtml(commands.offboard || "")}</div>
    </div>

    <div class="detail-block">
      <h4>Errors</h4>
      ${
        errors.length
          ? errors
              .slice(-6)
              .map((item) => `<div class="code-line">${escapeHtml(item.message || String(item))}</div>`)
              .join("")
          : `<div class="empty-state">No recorded errors.</div>`
      }
    </div>
  `;
  bindActionButtons();
  renderActiveJob();
}

function setView(view) {
  state.activeView = view;
  document.querySelectorAll(".view-tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  $("workflowView").classList.toggle("active", view === "workflow");
  $("releaseView").classList.toggle("active", view === "release");
}

function setSidebarCollapsed(collapsed) {
  state.sidebarCollapsed = collapsed;
  document.querySelector(".app-shell").classList.toggle("sidebar-collapsed", collapsed);
  const toggle = $("sidebarToggle");
  if (toggle) {
    toggle.classList.toggle("active", !collapsed);
    toggle.title = collapsed ? "Show Release Runs" : "Hide Release Runs";
    toggle.textContent = collapsed ? "›" : "⌄";
  }
}

function setRailCollapsed(collapsed) {
  state.railCollapsed = collapsed;
  document.querySelector(".app-shell").classList.toggle("rail-collapsed", collapsed);
  const toggle = $("railToggle");
  if (toggle) {
    toggle.title = collapsed ? "Expand toolbar" : "Collapse toolbar";
    const icon = toggle.querySelector(".rail-icon");
    if (icon) icon.textContent = collapsed ? "›" : "‹";
  }
}

function renderActionButtons(actions, size = "") {
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

function bindActionButtons() {
  document.querySelectorAll(".action-button").forEach((button) => {
    button.onclick = async () => {
      const action = button.dataset.action;
      const dryRun = button.dataset.dryRun === "true";
      const confirmText = $("confirmText") ? $("confirmText").value.trim() : "";
      await startAction(action, dryRun, confirmText);
    };
  });
}

async function startAction(action, dryRun, confirmText) {
  const jobStatus = $("jobStatus");
  if (!state.selectedId && action !== "export") {
    jobStatus.textContent = "Export first to create a release_id.";
    jobStatus.className = "job-status empty-state";
    return;
  }
  try {
    jobStatus.textContent = `Starting ${action}${dryRun ? " dry-run" : ""}...`;
    const payload = { dry_run: dryRun, confirm_text: confirmText };
    if (action === "export") {
      payload.experiment = $("exportExperiment") ? $("exportExperiment").value.trim() : "";
      payload.epoch = $("exportEpoch") ? $("exportEpoch").value.trim() : "";
      payload.remote = $("exportRemote") ? $("exportRemote").value.trim() : "";
      payload.desc = $("exportDesc") ? $("exportDesc").value.trim() : "";
    } else if (action === "upload") {
      payload.version = $("uploadVersion") ? $("uploadVersion").value.trim() : "";
      payload.desc = $("uploadDesc") ? $("uploadDesc").value.trim() : "";
      payload.replace_upload = $("uploadReplace") ? $("uploadReplace").checked : false;
    }
    const releaseId = state.selectedId || "__draft__";
    const job = await postJson(
      `/api/runs/${encodeURIComponent(releaseId)}/actions/${encodeURIComponent(action)}`,
      payload
    );
    state.activeJobId = job.job_id;
    setSelectedLogToJob();
    await pollJob(true);
    if (state.jobTimer) clearInterval(state.jobTimer);
    state.jobTimer = setInterval(() => pollJob(false), 2500);
  } catch (error) {
    if (error.message.includes("Unsupported action: upload")) {
      jobStatus.textContent = "Web backend is stale: restart `python -m model_release_pipeline.cli web` to enable upload.";
    } else {
      jobStatus.textContent = error.message;
    }
    jobStatus.className = "job-status failed";
  }
}

function setSelectedLogToJob() {
  state.selectedLog = "__job__";
  const logSelect = $("logSelect");
  const logDrawer = $("logDrawer");
  if (logDrawer) {
    logDrawer.open = true;
  }
  if (![...logSelect.options].some((option) => option.value === "__job__")) {
    const option = document.createElement("option");
    option.value = "__job__";
    option.textContent = "Backend job";
    logSelect.prepend(option);
  }
  logSelect.value = "__job__";
}

async function pollJob(forceReloadRun) {
  if (!state.activeJobId) return;
  const job = await fetchJson(`/api/jobs/${encodeURIComponent(state.activeJobId)}`);
  state.activeJob = job;
  renderActiveJob();
  renderLog();
  if (job.status !== "running") {
    if (state.jobTimer) {
      clearInterval(state.jobTimer);
      state.jobTimer = null;
    }
    const completedDraftExport = !state.selectedId && job.action === "export";
    if (completedDraftExport && !job.dry_run) {
      state.draftRun = false;
    }
    const nextStep = NEXT_STEP_BY_ACTION[job.action];
    if (job.status === "completed" && !job.dry_run && nextStep) {
      state.activeStep = nextStep;
    }
    if (state.selectedId || (completedDraftExport && !job.dry_run)) {
      const selectedBeforeReload = state.selectedId;
      await loadRuns(false);
      if (selectedBeforeReload) {
        await selectRun(selectedBeforeReload);
      } else if (completedDraftExport && !job.dry_run && state.runs.length) {
        await selectRun(state.runs[0].release_id);
      }
    }
  }
}

function renderActiveJob() {
  const jobStatus = $("jobStatus");
  if (!jobStatus) return;
  const job = state.activeJob;
  if (!job) {
    jobStatus.className = "job-status empty-state";
    jobStatus.textContent = "No backend job running.";
    return;
  }
  jobStatus.className = `job-status ${statusClass(job.status)}`;
  jobStatus.innerHTML = `
    <b>${escapeHtml(job.label || job.action)}</b>
    <span>${escapeHtml(job.status)}${job.dry_run ? " / dry-run" : ""}</span>
    <span>returncode: ${job.returncode ?? "running"}</span>
  `;
}

function renderLogSelect(logs) {
  const keys = Object.keys(LOG_LABELS);
  if (state.activeJob && !keys.includes("__job__")) {
    keys.unshift("__job__");
  }
  if (!keys.includes(state.selectedLog)) {
    state.selectedLog = keys.find((key) => (logs[key] || []).length) || keys[0] || "offboard_stdout";
  }
  $("logSelect").innerHTML = keys
    .map((key) => `<option value="${key}" ${key === state.selectedLog ? "selected" : ""}>${key === "__job__" ? "Backend job" : LOG_LABELS[key] || key}</option>`)
    .join("");
}

function renderLog() {
  if (state.selectedLog === "__job__") {
    const job = state.activeJob;
    $("logOutput").textContent = job ? (job.log || []).join("\n") : "No backend job selected.";
    return;
  }
  const logs = (state.selectedRun || {}).logs || {};
  const lines = logs[state.selectedLog] || [];
  $("logOutput").textContent = lines.length ? lines.join("\n") : "No log lines captured for this channel.";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
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

loadRuns(true).catch((error) => {
  $("runs").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
