/* Daily automation view. Uses only the same-origin, read-only monitor adapter. */
const dailyCronState = { data: null, error: false, active: false, timer: null, controller: null, selectedDay: "", selectedNode: "" };

function cronTime(value) {
  if (value == null || value === "") return "—";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString(state.uiLanguage === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

function cronCount(value) { return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—"; }
function cronFraction(done, total) { return `${cronCount(done)} / ${cronCount(total)}`; }
function cronLabel(value) {
  const labels = {
    success: ["已完成", "Complete"], complete: ["已完成", "Complete"], partial: ["已完成 · 有缺失", "Complete with gaps"],
    complete_with_gaps: ["已完成 · 有缺失", "Complete with gaps"], empty: ["无数据 · 正常结束", "No data · Complete"],
    waiting: ["等待任务", "Waiting"], running: ["运行中", "Running"], collecting: ["媒体采集中", "Collecting media"],
    failed: ["执行失败", "Failed"], media_failed: ["媒体失败", "Media failed"], missed: ["未按时启动", "Missed schedule"],
    stalled: ["进度停滞", "Progress stalled"], unknown: ["证据不足", "Insufficient evidence"],
    inferred: ["推理完成 · 未回刷", "Inferred · Not published"], inferred_with_gaps: ["推理完成 · 有缺失", "Inferred with gaps"],
    planned: ["仅计划", "Planned only"], recent: ["近期有活动", "Recent activity"], old: ["较久未更新", "Older activity"],
    finished: ["退出正常", "Exited normally"], launching: ["已启动", "Launched"], launch_error: ["启动异常", "Launch error"],
    partial_failed: ["部分失败", "Partial failure"], unavailable: ["暂不可用", "Unavailable"],
    awaiting_frontend_release: ["等待播放器验收", "Awaiting player validation"],
  };
  return labels[value] ? uiText(...labels[value]) : value || "—";
}

function cronTone(value) {
  if (["success", "complete", "empty", "finished"].includes(value)) return "ok";
  if (["failed", "media_failed", "missed", "launch_error"].includes(value)) return "fail";
  if (["partial", "complete_with_gaps", "stalled", "partial_failed", "inferred_with_gaps", "unavailable"].includes(value)) return "warn";
  return "neutral";
}

function cronChip(value) { return `<span class="cron-chip" data-tone="${cronTone(value)}">${escapeHtml(cronLabel(value))}</span>`; }
function cronMetric(label, value, detail, tone = "neutral") {
  return `<article class="cron-metric" data-tone="${tone}"><span class="muted">${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small class="muted">${escapeHtml(detail)}</small></article>`;
}

function cronLatestRun(data) {
  return (data?.overview?.daily?.runs || []).find((run) => /^daily-\d{4}-\d{2}-\d{2}$/.test(run.id));
}

function cronLatestLaunch(daily, run) {
  const launches = [...(daily?.launches || []), ...(daily?.recoveries || [])]
    .filter((item) => item.target_date_cst === run?.target_date_cst);
  return launches.sort((a, b) => String(b.started_at).localeCompare(String(a.started_at)))[0];
}

function renderDailyCron() {
  if (!$("#dailyCronPage")) return;
  const data = dailyCronState.data;
  if (!data) return;
  const overview = data.overview, daily = overview?.daily, run = typeof cronSelectedRuns === "function" ? cronSelectedRuns(data).main : cronLatestRun(data), sidecar = data.sidecar;
  const observationAge = Date.now() / 1000 - (overview?.collected_at || 0);
  const stale = Boolean(overview && (overview.stale || overview.collector_error || observationAge > 90));
  const unavailable = Object.values(data.sources || {}).some((value) => value !== "ready");
  const connection = $("#dailyCronConnection");
  connection.dataset.tone = dailyCronState.error || stale || unavailable ? "warn" : "ok";
  connection.textContent = (dailyCronState.error
    ? uiText("连接失败 · 保留上次快照，可能已过期", "Connection failed · Last snapshot may be stale")
    : stale ? uiText("采集异常或数据过期", "Collector error or stale data")
    : unavailable ? uiText("部分数据源不可用 · 其他状态独立显示", "Some sources unavailable · Other outcomes remain visible")
    : uiText("监控已连接 · 每 30 秒刷新", "Monitor connected · Refreshes every 30s"))
    + ` · ${uiText("采集于", "Collected")} ${cronTime(overview?.collected_at || data.observed_at)} CST`;
  const outcome = run?.health || daily?.health || "unavailable";
  if ($("#dailyCronMainStatus")) {
    const picked = cronSelectedRuns(data), runtime = data.media_daily, media = picked.media;
    $("#dailyCronMainStatus").innerHTML = cronChip(outcome);
    $("#dailyCronMainValue").textContent = `${picked.day || "—"} · ${cronFraction(run?.verified, run?.selected)}`;
    $("#dailyCronMainNote").textContent = `${uiText("已验证 / 选中", "Verified / Selected")} · ${uiText("跳过", "Skipped")} ${cronCount(run?.skipped)}`;
    const mediaHealth = !runtime ? "unavailable" : runtime.controller_error ? "failed" : runtime.stale ? "stalled" : (media?.state === "complete" && (media.imported !== media.selected || media.assigned !== media.selected) ? "unknown" : media?.state) || "waiting";
    $("#dailyCronMediaStatus").innerHTML = cronChip(mediaHealth);
    $("#dailyCronMediaValue").textContent = `${picked.day || "—"} · ${cronFraction(media?.verified, media?.selected)}`;
    $("#dailyCronMediaNote").textContent = `${uiText("双媒体验证 / 目标", "Both videos / Target")} · ${uiText("终态失败", "Terminal failures")} ${cronCount(media?.failure_count)}`;
  }
  $("#dailyCronSchedule").textContent = daily
    ? `${uiText("下次计划", "Next schedule")} ${cronTime(daily.next_run_at)} CST · ${uiText("对应目标日", "Target")} ${daily.target_date || "—"} · ${uiText("调度心跳", "Scheduler heartbeat")} ${cronTime(daily.heartbeat_at)} CST`
    : uiText("主流程监控暂不可用", "Pipeline monitor unavailable");
  const alerts = [];
  const launch = cronLatestLaunch(daily, run);
  const recovered = ["success", "partial", "empty"].includes(outcome) && ["failed", "launch_error"].includes(launch?.state);
  if (recovered) alerts.push(`<div class="cron-alert" data-tone="warn">${escapeHtml(uiText("调度退出记录仍为失败；最终回执已完成。两份证据分别保留，请查看流水线详情。", "Scheduler exit records a failure; the final receipt is complete. Both records are retained below."))}</div>`);
  const messages = {
    heartbeat: ["调度心跳超过 3 分钟未更新", "Scheduler heartbeat is over 3 minutes old"],
    evidence: ["首次启用时间缺失，无法判定漏跑", "First activation time is missing"],
    missed: ["计划启动后 5 分钟仍无启动记录", "No launch record 5 minutes after the schedule"],
    partial: ["主流程已完成，少量采集缺失已如实记录", "Pipeline complete; acquisition gaps recorded"],
    failed: ["调度存在失败退出记录，请结合最终回执判断", "A scheduler failure exit is recorded; check the final receipt"],
    stalled: ["流水线进度超过阈值未更新", "Pipeline progress has not updated within its threshold"],
    unknown: ["启动记录与完成证据不完整", "Launch or completion evidence is incomplete"],
    source: ["部分状态文件读取异常", "Some state files could not be read"],
    cron: ["未发现每日定时任务或无法读取", "Daily scheduled task missing or unreadable"],
  };
  for (const alert of daily?.alerts || []) {
    if (recovered && alert.kind === "failed") continue;
    alerts.push(`<div class="cron-alert" data-tone="${alert.severity === "critical" ? "fail" : "warn"}">${escapeHtml(uiText(...(messages[alert.kind] || ["监控有提醒，请查看运行详情", "Monitor alert; inspect the run details"])))}</div>`);
  }
  $("#dailyCronAlerts").innerHTML = alerts.join("") || `<p class="cron-note muted">${escapeHtml(daily ? uiText("本次观测未发现调度异常。", "No scheduler alerts in this observation.") : uiText("等待主流程观测恢复。", "Waiting for pipeline observations."))}</p>`;
  const hour = Math.floor(Date.now() / 3600000) * 3600;
  $("#dailyCronHistory").innerHTML = Array.from({ length: 24 }, (_, index) => {
    const at = hour - (23 - index) * 3600;
    const bucket = data.history?.find((item) => item.at === at);
    const label = `${cronTime(at)} CST · ${bucket ? `${cronCount(bucket.observations)} ${uiText("次观测", "observations")}` : uiText("无观测", "No observations")}`;
    return `<span class="cron-history-hour" data-tone="${bucket ? ["ok", "warn", "fail"][bucket.severity] || "neutral" : "neutral"}" tabindex="0" role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}"></span>`;
  }).join("");
  renderDailyCronRuns(data);
  renderDailyCronSidecar(sidecar);
  renderDailyCronJobs();
  if (typeof renderCronRunSelector === "function") renderCronRunSelector();
  if (typeof renderDailyCronGraph === "function") void renderDailyCronGraph();
}

function renderDailyCronRuns(data) {
  const box = $("#dailyCronRuns");
  const open = new Set([...box.querySelectorAll("details[open]")].map((item) => item.dataset.run));
  const runs = data.overview?.daily?.runs || [];
  const stages = { inference: ["模型推理", "Inference"], publication: ["Trail 回刷", "Trail publication"], sample_hook: ["抽样与验证", "Sampling and verification"], complete: ["完成", "Complete"] };
  box.innerHTML = runs.map((run) => {
    const launch = cronLatestLaunch(data.overview.daily, run);
    const failures = [...(run.skipped_cases || []), ...(run.failure_details || [])];
    const cases = [...new Map(failures.map((row) => [row.issue_id, row])).values()];
    const stageLabel = run.health === "empty" ? uiText("无数据，正常结束", "No data, completed") : stages[run.stage] ? uiText(...stages[run.stage]) : run.stage || run.state;
    const progress = run.percent == null ? "" : `<div class="cron-stage-progress"><progress max="100" value="${Math.max(0, Math.min(100, run.percent))}" aria-label="${escapeHtml(uiText("当前阶段完成百分比", "Current stage progress"))}"></progress><span class="muted">${escapeHtml(`${stageLabel} · ${cronFraction(run.finished, run.total)} · ${run.percent}%`)}</span></div>`;
    return `<article class="cron-run">
      <div class="cron-run-heading"><div><strong>${escapeHtml(run.target_date_cst || run.id)}</strong>${run.target_is_weekend ? `<span class="cron-chip" data-tone="neutral">${escapeHtml(uiText("CST 周末", "CST weekend"))}</span>` : ""}</div>${cronChip(run.health)}</div>
      <div class="cron-run-counts">${escapeHtml(`${uiText("选中", "Selected")} ${cronCount(run.selected)} · ${uiText("已推理", "Inferred")} ${cronCount(run.inferred)} · ${uiText("已回刷", "Published")} ${cronCount(run.published)} · ${uiText("已验证", "Verified")} ${cronCount(run.verified)} · ${uiText("跳过", "Skipped")} ${cronCount(run.skipped)}`)}</div>
      ${progress}
      <details class="cron-run-detail" data-run="${escapeHtml(run.id)}"${open.has(run.id) ? " open" : ""}><summary>${escapeHtml(uiText("运行证据与缺失案例", "Run evidence and missing cases"))}${cases.length ? ` · ${cases.length}` : ""}</summary>
        <dl><div><dt>Run</dt><dd>${escapeHtml(run.id)}</dd></div><div><dt>${escapeHtml(uiText("最终状态", "Final state"))}</dt><dd>${escapeHtml(run.state)}</dd></div><div><dt>${escapeHtml(uiText("开始 / 更新 · CST", "Started / Updated · CST"))}</dt><dd>${escapeHtml(`${cronTime(run.started_at)} / ${cronTime(run.updated_at)}`)}</dd></div><div><dt>${escapeHtml(uiText("最近调度退出", "Latest scheduler exit"))}</dt><dd>${escapeHtml(launch ? `${cronLabel(launch.state)} · exit ${cronCount(launch.returncode)} · ${cronTime(launch.finished_at || launch.started_at)}` : "—")}</dd></div></dl>
        ${run.percent != null ? `<p class="cron-note muted">${escapeHtml(uiText("进度条只代表当前阶段，包含失败项；全链路结果由最终回执判定。", "Progress applies to the current stage and includes failed items; the final receipt determines completion."))}</p>` : ""}
        ${run.evidence_error ? `<p class="cron-alert" data-tone="warn">${escapeHtml(uiText("状态证据读取异常", "Run evidence could not be read"))}</p>` : ""}
        ${cases.length ? `<ul class="cron-case-list">${cases.map((item) => `<li><a href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(item.issue_id)}?view_id=2410" target="_blank" rel="noopener noreferrer">${escapeHtml(item.issue_id)} ↗</a><span class="muted">${escapeHtml(item.code || uiText("采集失败", "Acquisition failed"))}</span></li>`).join("")}</ul>` : `<p class="cron-note muted">${escapeHtml(uiText("未记录跳过或失败案例。", "No skipped or failed cases recorded."))}</p>`}
      </details></article>`;
  }).join("") || `<p class="cron-note muted">${escapeHtml(data.overview ? uiText("尚无流水线记录，首次执行后显示。", "Runs appear after the first execution.") : uiText("流水线数据源暂不可用。", "Pipeline source unavailable."))}</p>`;
}

function renderDailyCronSidecar(sidecar) {
  const box = $("#dailyCronSidecar");
  const backfillOpen = Boolean(box.querySelector("details[open]"));
  if (!sidecar) { box.innerHTML = `<p class="cron-alert" data-tone="warn">${escapeHtml(uiText("旁路监控暂不可用，主任务状态独立显示。", "Sidecar monitor unavailable; main pipeline remains independent."))}</p>`; return; }
  box.innerHTML = `<div class="cron-sidecar-heading"><span>${escapeHtml(uiText("每日自动导入", "Daily import"))} · ${escapeHtml(uiText(sidecar.daily_enabled ? "已启用" : "等待启用", sidecar.daily_enabled ? "Enabled" : "Waiting"))}</span><span class="muted">${escapeHtml(uiText("更新", "Updated"))} ${escapeHtml(cronTime(sidecar.updated_at))} CST</span></div>
    ${sidecar.controller_error || sidecar.stale ? `<p class="cron-alert" data-tone="warn">${escapeHtml(uiText(sidecar.controller_error ? "旁路控制器异常" : "旁路状态超过一小时未更新", sidecar.controller_error ? "Sidecar controller error" : "Sidecar status over one hour old"))}</p>` : ""}
    <details class="cron-backfill"${backfillOpen ? " open" : ""}><summary>${escapeHtml(uiText("历史回溯媒体", "Historical media backfill"))} · ${escapeHtml(cronFraction(sidecar.media_verified, sidecar.total))} ${cronChip(sidecar.state)}</summary>
      <div class="cron-sidecar-metrics">${cronMetric(uiText("历史 Run 导入", "Historical Run imports"), cronFraction(sidecar.imported, sidecar.total), uiText("历史回溯口径，非当天数据量", "Historical scope, not today's volume"))}${cronMetric(uiText("媒体最终验证", "Final media validation"), cronFraction(sidecar.media_verified, sidecar.total), `${uiText("未解决失败", "Unresolved failures")} ${cronCount(sidecar.failure_count)}`)}${cronMetric(uiText("Camera 已采集", "Camera collected"), cronFraction(sidecar.camera?.completed, sidecar.camera?.total), uiText("以最终媒体验证为准", "Final media validation is authoritative"))}</div>
      <p class="cron-note muted">${escapeHtml(`${uiText("Orion 原始 BEV 任务", "Original Orion BEV jobs")} · ${uiText("完成", "Completed")} ${cronCount(sidecar.bev_pilot?.completed == null || sidecar.bev_backfill?.completed == null ? null : sidecar.bev_pilot.completed + sidecar.bev_backfill.completed)} · ${uiText("失败", "Failed")} ${cronCount(sidecar.bev_pilot?.failed == null || sidecar.bev_backfill?.failed == null ? null : sidecar.bev_pilot.failed + sidecar.bev_backfill.failed)}`)}</p><p class="cron-note muted">${escapeHtml(uiText("原始 Orion 失败数保留历史；重试或本地修复后的结果计入“媒体最终验证”。历史回溯数量与每日新增 Run 分别统计。", "Original Orion failures are retained as history. Successful retries/local repairs count in final media validation. Historical backfill and daily Runs use separate scopes."))}</p>
    </details>`;
}

function renderDailyCronJobs() {
  const box = $("#dailyCronJobs");
  if (!box) return;
  const query = ($("#dailyCronSearch")?.value || "").toLowerCase();
  const jobs = (dailyCronState.data?.overview?.jobs || []).filter((job) => `${job.name} ${job.schedule}`.toLowerCase().includes(query));
  box.innerHTML = jobs.map((job) => `<tr><td>${escapeHtml(job.name)}</td><td><code>${escapeHtml(job.schedule)}</code></td><td>${escapeHtml(cronTime(job.log_updated_at))}</td><td>${cronChip(job.evidence)}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">${escapeHtml(uiText("暂无匹配任务或清单不可用", "No matching tasks or inventory unavailable"))}</td></tr>`;
}

async function loadDailyCron() {
  if (!dailyCronState.active || dailyCronState.controller) return;
  const controller = new AbortController();
  dailyCronState.controller = controller;
  const button = $("#dailyCronRefresh");
  if (button) button.disabled = true;
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  try {
    const data = await api("/api/daily-cron", { signal: controller.signal });
    if (!dailyCronState.active || dailyCronState.controller !== controller || controller.signal.aborted) return;
    dailyCronState.data = data;
    dailyCronState.error = false;
    renderDailyCron();
  } catch (_error) {
    if (!dailyCronState.active || dailyCronState.controller !== controller) return;
    dailyCronState.error = true;
    if (dailyCronState.data) renderDailyCron();
    else {
      const connection = $("#dailyCronConnection");
      connection.dataset.tone = "warn";
      connection.textContent = uiText("监控暂时无法连接，将自动重试。", "Monitor unavailable; retrying automatically.");
    }
  } finally {
    window.clearTimeout(timeout);
    if (dailyCronState.controller === controller) {
      dailyCronState.controller = null;
      if (button) button.disabled = false;
    }
  }
}

function setDailyCronActive(active) {
  if (dailyCronState.active === active) return;
  dailyCronState.active = active;
  window.clearInterval(dailyCronState.timer);
  dailyCronState.timer = null;
  dailyCronState.controller?.abort();
  dailyCronState.controller = null;
  if (active) {
    renderDailyCron();
    dailyCronState.timer = window.setInterval(() => {
      if (!document.hidden) void loadDailyCron();
    }, 30000);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && dailyCronState.active) void loadDailyCron();
});
