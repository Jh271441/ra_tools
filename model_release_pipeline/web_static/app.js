const state = {
  runs: [],
  selectedId: null,
  selectedRun: null,
  selectedLog: "offboard_stdout",
};

const $ = (id) => document.getElementById(id);

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

async function loadRuns(selectFirst = false) {
  const payload = await fetchJson("/api/runs");
  state.runs = payload.runs || [];
  $("runsDir").textContent = `runs_dir: ${payload.runs_dir}`;
  renderRuns();
  if (selectFirst && state.runs.length) {
    await selectRun(state.runs[0].release_id);
  }
}

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

  if (!visible.length) {
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
        <span class="chip ${statusClass(run.status)}">${escapeHtml(run.stage || "created")}</span>
        <span class="chip">epoch ${formatEpoch(run.selected_epoch)}</span>
        <span class="chip">onnx ${run.onnx_version ?? "NA"}</span>
        <span class="chip">ifx ${run.ifx_platforms ?? 0}</span>
      </div>
    `;
    runsEl.appendChild(button);
  }
}

async function selectRun(releaseId) {
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
  renderTimeline(payload.timeline || []);
  renderDetails(payload);
  renderLogSelect(payload.logs || {});
  renderLog();
}

function renderTimeline(timeline) {
  $("timeline").innerHTML = timeline
    .map(
      (step, index) => `
      <div class="step ${statusClass(step.status)}">
        <div class="step-index">${index + 1}</div>
        <div>
          <h4>${escapeHtml(step.title)}</h4>
          <p>${escapeHtml(step.description)}</p>
        </div>
        <span class="chip step-state ${statusClass(step.status)}">${escapeHtml(step.status)}</span>
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
    (commands.dcl || [])
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
}

function renderLogSelect(logs) {
  const labels = {
    export_stdout: "Export stdout",
    export_stderr: "Export stderr",
    jenkins_console: "Jenkins console",
    handoff_stdout: "Handoff stdout",
    handoff_stderr: "Handoff stderr",
    offboard_stdout: "Offboard stdout",
    offboard_stderr: "Offboard stderr",
  };
  const keys = Object.keys(logs);
  if (!keys.includes(state.selectedLog)) {
    state.selectedLog = keys.find((key) => (logs[key] || []).length) || keys[0] || "offboard_stdout";
  }
  $("logSelect").innerHTML = keys
    .map((key) => `<option value="${key}" ${key === state.selectedLog ? "selected" : ""}>${labels[key] || key}</option>`)
    .join("");
}

function renderLog() {
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

$("refreshButton").onclick = () => loadRuns(false);
$("runFilter").oninput = renderRuns;
$("logSelect").onchange = (event) => {
  state.selectedLog = event.target.value;
  renderLog();
};
$("copyRecordButton").onclick = async () => {
  if (!state.selectedRun) return;
  await navigator.clipboard.writeText(JSON.stringify(state.selectedRun.record, null, 2));
  $("copyRecordButton").textContent = "Copied";
  setTimeout(() => ($("copyRecordButton").textContent = "Copy JSON"), 1100);
};

loadRuns(true).catch((error) => {
  $("runs").innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});
