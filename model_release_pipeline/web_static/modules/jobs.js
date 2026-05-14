import { fetchJson, postJson } from "./api.js";
import { NEXT_STEP_BY_ACTION } from "./constants.js";
import { renderLog, setSelectedLogToJob } from "./logs.js";
import { $, state } from "./state.js";
import { escapeHtml, statusClass } from "./utils.js";

export async function startAction(action, dryRun, confirmText, callbacks) {
  const jobStatus = $("jobStatus");
  if (!state.selectedId && action !== "export") {
    jobStatus.textContent = "Export first to create a release_id.";
    jobStatus.className = "job-status empty-state";
    return;
  }
  try {
    jobStatus.textContent = `Starting ${action}${dryRun ? " dry-run" : ""}...`;
    const payload = { dry_run: dryRun, confirm_text: confirmText };
    if (action === "pick") {
      payload.experiment = $("pickExperiment") ? $("pickExperiment").value.trim() : "";
      payload.remote = $("pickRemote") ? $("pickRemote").value.trim() : "";
      payload.desc = $("pickDesc") ? $("pickDesc").value.trim() : "";
    } else if (action === "export") {
      payload.experiment = $("exportExperiment") ? $("exportExperiment").value.trim() : "";
      payload.epoch = $("exportEpoch") ? $("exportEpoch").value.trim() : "";
      payload.remote = $("exportRemote") ? $("exportRemote").value.trim() : "";
      payload.desc = $("exportDesc") ? $("exportDesc").value.trim() : "";
    } else if (action === "upload") {
      payload.version = $("uploadVersion") ? $("uploadVersion").value.trim() : "";
      payload.desc = $("uploadDesc") ? $("uploadDesc").value.trim() : "";
      payload.replace_upload = $("uploadReplace") ? $("uploadReplace").checked : false;
    } else if (action === "ifx-poll") {
      payload.build_url = $("ifxBuildUrl") ? $("ifxBuildUrl").value.trim() : "";
    } else if (action === "apply-handoff") {
      payload.branch = $("handoffBranch") ? $("handoffBranch").value : "";
      payload.desc = $("handoffDesc") ? $("handoffDesc").value.trim() : "";
    } else if (action === "dcl") {
      payload.branch = $("dclBranch") ? $("dclBranch").value : "";
    }
    const releaseId = state.selectedId || "__draft__";
    const job = await postJson(
      `/api/runs/${encodeURIComponent(releaseId)}/actions/${encodeURIComponent(action)}`,
      payload
    );
    state.activeJobId = job.job_id;
    setSelectedLogToJob();
    await pollJob(true, callbacks);
    if (state.jobTimer) clearInterval(state.jobTimer);
    state.jobTimer = setInterval(() => pollJob(false, callbacks), 2500);
  } catch (error) {
    if (error.message.includes("Unsupported action: upload")) {
      jobStatus.textContent = "Web backend is stale: restart `python -m model_release_pipeline.cli web` to enable upload.";
    } else {
      jobStatus.textContent = error.message;
    }
    jobStatus.className = "job-status failed";
  }
}

export async function pollJob(forceReloadRun, callbacks) {
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
    const completedDraftCreate = !state.selectedId && ["export", "pick"].includes(job.action);
    if (completedDraftCreate && !job.dry_run) {
      state.draftRun = false;
    }
    const nextStep = NEXT_STEP_BY_ACTION[job.action];
    if (job.status === "completed" && !job.dry_run && nextStep) {
      state.activeStep = nextStep;
    }
    if (state.selectedId || (completedDraftCreate && !job.dry_run)) {
      const selectedBeforeReload = state.selectedId;
      await callbacks.loadRuns(false);
      if (selectedBeforeReload) {
        await callbacks.selectRun(selectedBeforeReload);
      } else if (completedDraftCreate && !job.dry_run && state.runs.length) {
        await callbacks.selectRun(state.runs[0].release_id);
      }
    }
  }
}

export function renderActiveJob() {
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
