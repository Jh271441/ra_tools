import { LOG_LABELS } from "./constants.js";
import { $, currentJob, state } from "./state.js";

export function setSelectedLogToJob() {
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

export function renderLogSelect(logs) {
  const keys = Object.keys(LOG_LABELS);
  if (currentJob() && !keys.includes("__job__")) {
    keys.unshift("__job__");
  }
  if (!keys.includes(state.selectedLog)) {
    state.selectedLog = keys.find((key) => (logs[key] || []).length) || keys[0] || "offboard_stdout";
  }
  $("logSelect").innerHTML = keys
    .map((key) => `<option value="${key}" ${key === state.selectedLog ? "selected" : ""}>${key === "__job__" ? "Backend job" : LOG_LABELS[key] || key}</option>`)
    .join("");
}

export function renderLog() {
  if (state.selectedLog === "__job__") {
    const job = currentJob();
    $("logOutput").textContent = job ? (job.log || []).join("\n") : "No backend job selected.";
    return;
  }
  if (state.selectedLog === "pick_preview") {
    $("logOutput").textContent = state.pickPreviewLines.length
      ? state.pickPreviewLines.join("\n")
      : "No pick preview loaded.";
    return;
  }
  const logs = (state.selectedRun || {}).logs || {};
  const lines = logs[state.selectedLog] || [];
  $("logOutput").textContent = lines.length ? lines.join("\n") : "No log lines captured for this channel.";
}
