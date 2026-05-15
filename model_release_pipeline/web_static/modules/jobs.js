import { fetchJson, postJson } from "./api.js";
import { NEXT_STEP_BY_ACTION } from "./constants.js";
import { renderLog, setSelectedLogToJob } from "./logs.js";
import { $, currentJob, currentReleaseKey, state } from "./state.js";
import { escapeHtml, statusClass } from "./utils.js";

function applyStageConfigPayload(payload) {
  if ($("stageConfigBranch")) payload.branch = $("stageConfigBranch").value;
  if ($("stageConfigCheckout")) payload.checkout_branch = $("stageConfigCheckout").value.trim();
  if ($("stageConfigDiffIds")) payload.update_diff_ids = $("stageConfigDiffIds").value.trim();
  if ($("stageConfigSimPlan")) payload.sim_plan = $("stageConfigSimPlan").value.trim();
  if ($("stageConfigLint")) payload.lint = $("stageConfigLint").checked;
  if ($("stageConfigAllowDirty")) payload.allow_dirty = $("stageConfigAllowDirty").checked;
}

function trackJob(job) {
  state.activeJobId = job.job_id;
  state.activeJobsByRelease[job.release_id] = job;
  if (job.status === "running") {
    state.trackedJobIdsByRelease[job.release_id] = job.job_id;
  }
  state.activeJob = currentJob();
}

function ensureJobPoller(callbacks) {
  if (!Object.keys(state.trackedJobIdsByRelease).length) return;
  if (state.jobTimer) return;
  state.jobTimer = setInterval(() => pollJobs(false, callbacks), 2500);
}

export async function startAction(action, dryRun, confirmText, callbacks) {
  const jobStatus = $("jobStatus");
  const draftAllowed = ["pick", "export", "offboard"].includes(action);
  if (!state.selectedId && !draftAllowed) {
    jobStatus.textContent = "Select or create a release run first.";
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
      applyStageConfigPayload(payload);
    } else if (action === "dcl") {
      payload.branch = $("dclBranch") ? $("dclBranch").value : "";
      applyStageConfigPayload(payload);
    } else if (action === "offboard") {
      const mode = document.querySelector('input[name="offboardMode"]:checked')?.value || (state.selectedId ? "selected" : "explicit");
      payload.mode = mode;
      payload.remote = $("offboardRemote") ? $("offboardRemote").value.trim() : "";
      if (mode === "explicit" || !state.selectedId) {
        payload.experiment = $("offboardExperiment") ? $("offboardExperiment").value.trim() : "";
        payload.epoch = $("offboardEpoch") ? $("offboardEpoch").value.trim() : "";
        payload.desc = $("offboardDesc") ? $("offboardDesc").value.trim() : "";
      }
    }
    const directOffboard = action === "offboard" && (payload.mode === "explicit" || !state.selectedId);
    const releaseId = directOffboard ? "__draft__" : (state.selectedId || "__draft__");
    const job = await postJson(
      `/api/runs/${encodeURIComponent(releaseId)}/actions/${encodeURIComponent(action)}`,
      payload
    );
    trackJob(job);
    setSelectedLogToJob();
    await pollJobs(true, callbacks);
    ensureJobPoller(callbacks);
  } catch (error) {
    if (error.message.includes("Unsupported action: upload")) {
      jobStatus.textContent = "Web backend is stale: restart `python -m model_release_pipeline.cli web` to enable upload.";
    } else {
      jobStatus.textContent = error.message;
    }
    jobStatus.className = "job-status failed";
  }
}

export async function pollJobs(forceReloadRun, callbacks) {
  const tracked = Object.entries(state.trackedJobIdsByRelease);
  if (!tracked.length) {
    if (state.jobTimer) {
      clearInterval(state.jobTimer);
      state.jobTimer = null;
    }
    state.activeJob = currentJob();
    renderActiveJob();
    return;
  }

  const jobs = await Promise.all(
    tracked.map(([, jobId]) => fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`))
  );
  let shouldReloadRuns = false;
  let draftCreated = false;
  let selectedBeforeReload = state.selectedId;

  for (const job of jobs) {
    state.activeJobsByRelease[job.release_id] = job;
    if (job.status === "running") continue;

    delete state.trackedJobIdsByRelease[job.release_id];
    if (state.handledJobIds.has(job.job_id)) continue;
    state.handledJobIds.add(job.job_id);

    const completedDraftCreate = job.release_id === "__draft__" && ["export", "pick", "offboard"].includes(job.action);
    if (completedDraftCreate && !job.dry_run) {
      state.draftRun = false;
      draftCreated = true;
    }
    const nextStep = NEXT_STEP_BY_ACTION[job.action];
    if (job.status === "completed" && !job.dry_run && nextStep && currentReleaseKey() === job.release_id) {
      state.activeStep = nextStep;
    }
    if (forceReloadRun || state.selectedId || (completedDraftCreate && !job.dry_run)) {
      shouldReloadRuns = true;
    }
  }

  if (!Object.keys(state.trackedJobIdsByRelease).length && state.jobTimer) {
    clearInterval(state.jobTimer);
    state.jobTimer = null;
  }
  state.activeJob = currentJob();
  renderActiveJob();
  renderLog();

  if (shouldReloadRuns) {
    await callbacks.loadRuns(false);
    if (draftCreated && !selectedBeforeReload && state.runs.length) {
      await callbacks.selectRun(state.runs[0].release_id);
    }
  }
}

export function renderActiveJob() {
  const jobStatus = $("jobStatus");
  if (!jobStatus) return;
  const job = currentJob();
  state.activeJob = job;
  if (!job) {
    jobStatus.className = "job-status empty-state";
    jobStatus.textContent = "No backend job for selected release.";
    return;
  }
  jobStatus.className = `job-status ${statusClass(job.status)}`;
  jobStatus.innerHTML = `
    <b>${escapeHtml(job.label || job.action)}</b>
    <span>${escapeHtml(job.status)}${job.dry_run ? " / dry-run" : ""}</span>
    <span>returncode: ${job.returncode ?? "running"}</span>
  `;
}
