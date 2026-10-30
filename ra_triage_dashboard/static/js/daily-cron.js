/* Daily automation view. Uses only the same-origin, read-only monitor adapter. */
const dailyCronState = { data: null, error: false, active: false, timer: null, controller: null, selectedDay: "", selectedVersion: "", selectedNode: "" };

function cronVersionFamilies(value) {
  return [...new Set([...(value?.families || []), ...(value?.versions || []).map(v => v.family),
    ...(value?.datasets || []).map(d => d.release_family)].map(String).filter(v => /^\d{8}$/.test(v)))].sort().reverse();
}

function cronIncrementalEnabled(data) {
  return Boolean(data?.incremental?.enabled || dailyCronState.selectedVersion);
}

function cronSelectedIncremental(data) {
  const source = data?.incremental?.enabled ? data.incremental : {
    enabled: true, stale: true, unavailable: true, statesUnavailable: true,
    families: [], versions: [], datasets: [], states: {}, media: {},
  };
  if (!dailyCronState.selectedVersion) dailyCronState.selectedVersion = cronVersionFamilies(source)[0] || 'all';
  const family = dailyCronState.selectedVersion;
  if (family === 'all') return { ...source, stale: source.stale || dailyCronState.error };
  const version = source.versions?.find(v => v.family === family);
  return { ...source, ...version, families: [family], family,
    stale: source.stale || dailyCronState.error,
    unavailable: !version, statesUnavailable: !version || version.states_status !== 'ready',
    states: version?.states || {}, media: version?.media || {},
    datasets: (source.datasets || []).filter(d => d.release_family === family),
    increments: source.increments && { ...source.increments,
      items: (source.increments.items || []).filter(row => row.family === family) } };
}

function restoreCronScope() {
  if (!window.location) return;
  const params = new URLSearchParams(window.location.search);
  const version = params.get('cron_version'), day = params.get('cron_day');
  if (version === 'all' || /^\d{8}$/.test(version || '')) dailyCronState.selectedVersion = version;
  dailyCronState.selectedDay = /^\d{4}-\d{2}-\d{2}$/.test(day || '') ? day : '';
}

function writeCronScope(url) {
  if (dailyCronState.selectedVersion) url.searchParams.set('cron_version', dailyCronState.selectedVersion);
  if (dailyCronState.selectedDay) url.searchParams.set('cron_day', dailyCronState.selectedDay);
  else url.searchParams.delete('cron_day');
}

function cronTime(value) {
  if (value == null || value === "") return "—";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString(state.uiLanguage === "en" ? "en-GB" : "zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  });
}

function cronDuration(value, { compact = false } = {}) {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return "—";
  if (value > 0 && value < 1) return uiText("<1秒", "<1s");
  const seconds = Math.floor(value), days = Math.floor(seconds / 86400), hours = Math.floor(seconds / 3600) % 24, minutes = Math.floor(seconds / 60) % 60, rest = seconds % 60;
  const parts = [];
  if (days) parts.push(uiText(`${days}天`, `${days}d`));
  if (hours) parts.push(uiText(`${hours}小时`, `${hours}h`));
  if (minutes && !(compact && days)) parts.push(uiText(`${minutes}分钟`, `${minutes}m`));
  if (!(compact && (days || hours)) && (rest || !parts.length)) parts.push(uiText(`${rest}秒`, `${rest}s`));
  return parts.join(uiText("", " "));
}

function cronTimingText(timing, { compact = false, stale = false } = {}) {
  if (!timing || timing.mode === "unavailable" || typeof timing.elapsed_seconds !== "number" || !Number.isFinite(timing.elapsed_seconds) || timing.elapsed_seconds < 0) return uiText("耗时 —", "Duration —");
  const prefix = timing.mode === "running"
    ? stale ? uiText("上次已运行", "Last elapsed") : uiText("已运行", "Elapsed")
    : timing.kind === "p50" ? uiText("任务 P50", "Task P50")
    : timing.kind === "span" ? timing.mode === "observed" ? uiText("已观测跨度", "Observed span") : uiText("阶段用时", "Stage duration")
    : timing.basis === "media_registration_to_verified" ? uiText("注册后耗时", "Since registration")
    : timing.basis === "camera_latest_attempt" ? uiText("本轮耗时", "Attempt duration") : uiText("耗时", "Duration");
  return `${prefix} ${cronDuration(timing.elapsed_seconds, { compact })}`;
}

function cronTimingRows(timing, { stale = false } = {}) {
  const scopes = {
    pipeline_registration: ["注册至本次执行回执；包含恢复等待的墙钟时间", "Registration to execution receipt, including recovery waits"],
    launch_to_registration: ["调度启动至冻结选集注册，包含进程准备", "Scheduler launch to cohort registration, including startup"],
    registration_to_publication: ["从选集注册到开始回刷，包含采集、模型推理和等待；未单独记录纯推理耗时", "Cohort registration to first publication attempt, including acquisition, model inference and waits; inference-only runtime is not recorded separately"],
    publication_receipts: ["首条回刷尝试至最后验证回执，包含重试等待", "First publication attempt to final verification receipt, including retry waits"],
    sample_hook_receipts: ["首条抽样更新尝试至最后抽样验证回执", "First sample-update attempt to final sample verification receipt"],
    media_registration_to_verified: ["本批注册至最后双媒体发布验证；不含注册前耗时", "Cohort registration to final dual-media publication; excludes pre-registration work"],
    media_publication_receipts: ["首条至最后双媒体发布验证；并非视频处理耗时", "First to final dual-media publication receipt; not video processing duration"],
    orion_task_runtime_p50: ["单任务运行耗时中位数；不等于整批墙钟耗时", "Median task runtime; not the batch wall-clock duration"],
    camera_latest_attempt: ["最近采集进程启动至本轮结果回执", "Latest capture process start to its final result receipt"],
    local_recovery_receipts: ["本批首次本地尝试至最后结果；并发不累加", "First local attempt to final result; parallel runtimes are not summed"],
  };
  const rows = [[uiText("计时", "Timing"), cronTimingText(timing, { stale })]];
  if (timing?.started_at) rows.push([uiText("开始 · CST", "Start · CST"), cronTime(timing.started_at)]);
  if (timing?.finished_at) rows.push([uiText("结束 · CST", "End · CST"), cronTime(timing.finished_at)]);
  if (timing?.mode === "running" && timing.observed_at) rows.push([uiText("观测于 · CST", "Observed · CST"), cronTime(timing.observed_at)]);
  if (timing?.observed != null) rows.push([uiText("时间回执覆盖", "Timed receipts"), cronFraction(timing.observed, timing.total)]);
  rows.push([uiText("计时口径", "Timing scope"), scopes[timing?.basis] ? uiText(...scopes[timing.basis]) : uiText("缺少有效起止回执", "No valid timing receipts")]);
  return rows;
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
  const incremental = cronIncrementalEnabled(data) && !dailyCronState.selectedDay ? cronSelectedIncremental(data) : null;
  renderCloseupCron(data.closeup, incremental?.family);
  const scopeNote = $('#dailyCronScopeNote');
  if (scopeNote) {
    scopeNote.hidden = !incremental;
    scopeNote.textContent = uiText('同一套流水线，按版本查看；旧版本仍继续采集和补齐。', 'One shared pipeline, viewed by version. Older versions continue collection and source checks.');
  }
  if (incremental) { renderIncrementalCron(data); return; }
  if ($('#dailyCronIncrements')) $('#dailyCronIncrements').hidden = true;
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
    const processing = !["complete", "complete_with_gaps", "empty"].includes(run?.state)
      && Number.isSafeInteger(run?.finished) && Number.isSafeInteger(run?.total) && run.total > 0 && run.finished >= 0 && run.finished <= run.total;
    const stages = { inference: ["采集 / 推理", "Acquisition / inference"], publication: ["回刷", "Publication"], sample_hook: ["抽样验证", "Sample verification"] };
    $("#dailyCronMainValue").textContent = `${picked.day || "—"} · ${processing ? cronFraction(run.finished, run.total) : cronFraction(run?.verified, run?.selected)}`;
    if ($("#dailyCronMainTiming")) $("#dailyCronMainTiming").textContent = cronTimingText(run?.timing, { stale: stale || dailyCronState.error });
    if ($("#dailyCronMediaTiming")) $("#dailyCronMediaTiming").textContent = cronTimingText(media?.timing, { stale: runtime?.stale || runtime?.controller_error || dailyCronState.error });
    $("#dailyCronMainNote").textContent = `${processing ? `${stages[run.stage] ? uiText(...stages[run.stage]) : uiText("当前阶段", "Current stage")} · ${uiText("已处理", "Processed")} ${Math.round(run.finished / run.total * 1000) / 10}%` : uiText("已验证 / 选中", "Verified / Selected")} · ${uiText("跳过", "Skipped")} ${cronCount(run?.skipped)}`;
    const mediaHealth = !runtime ? "unavailable" : runtime.controller_error ? "failed" : runtime.stale ? "stalled" : (media?.state === "complete" && (media.imported !== media.selected || media.assigned !== media.selected) ? "unknown" : media?.state) || "waiting";
    $("#dailyCronMediaStatus").innerHTML = cronChip(mediaHealth);
    const waitingForMedia = media?.state === "waiting" && media?.selected === 0;
    $("#dailyCronMediaValue").textContent = `${picked.day || "—"} · ${waitingForMedia ? uiText("等待上游", "Waiting upstream") : cronFraction(media?.verified, media?.selected)}`;
    $("#dailyCronMediaNote").textContent = waitingForMedia ? uiText("主流程完成后生成媒体任务", "Media tasks follow the main pipeline") : `${uiText("双媒体验证 / 目标", "Both videos / Target")} · ${uiText("终态失败", "Terminal failures")} ${cronCount(media?.failure_count)}`;
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
      <div class="cron-run-timing">${escapeHtml(cronTimingText(run.timing, { stale: dailyCronState.error || data.overview?.stale || Date.now() / 1000 - (data.overview?.collected_at || 0) > 90 }))}</div>
      <details class="cron-run-detail" data-run="${escapeHtml(run.id)}"${open.has(run.id) ? " open" : ""}><summary>${escapeHtml(uiText("运行证据与缺失案例", "Run evidence and missing cases"))}${cases.length ? ` · ${cases.length}` : ""}</summary>
        <dl><div><dt>Run</dt><dd>${escapeHtml(run.id)}</dd></div><div><dt>${escapeHtml(uiText("最终状态", "Final state"))}</dt><dd>${escapeHtml(run.state)}</dd></div><div><dt>${escapeHtml(uiText("开始 / 更新 · CST", "Started / Updated · CST"))}</dt><dd>${escapeHtml(`${cronTime(run.started_at)} / ${cronTime(run.updated_at)}`)}</dd></div><div><dt>${escapeHtml(uiText("最近调度退出", "Latest scheduler exit"))}</dt><dd>${escapeHtml(launch ? `${cronLabel(launch.state)} · exit ${cronCount(launch.returncode)} · ${cronTime(launch.finished_at || launch.started_at)}` : "—")}</dd></div>${cronTimingRows(run.timing, { stale: dailyCronState.error || data.overview?.stale || Date.now() / 1000 - (data.overview?.collected_at || 0) > 90 }).map(([key, value]) => `<div><dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
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
    restoreCronScope();
    // Download the graph while the snapshot is in flight, not after it arrives.
    // Rendering owns the visible error/retry state if loading fails.
    void ensureCronGraphLibrary().catch(() => {});
    renderDailyCron();
    dailyCronState.timer = window.setInterval(() => {
      if (!document.hidden) void loadDailyCron();
    }, 30000);
  }
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && dailyCronState.active) void loadDailyCron();
});


function renderIncrementalCron(data) {
  const v=cronSelectedIncremental(data),c=v.states||{},m=v.media||{};
  const eligible=Object.entries(c).filter(([k])=>!['excluded','waiting_metadata'].includes(k)).reduce((n,[,x])=>n+x,0);
  const inferred=(c.inferred||0)+(c.published||0);
  const scope = v.family ? v.family.slice(4) : uiText('全部版本汇总', 'All versions');
  const pending = (c.ready||0)+(c.running||0)+(c.retry_wait||0)+(c.inferred||0);
  const attention = (c.needs_attention||0)+(c.identity_conflict||0);
  $('#dailyCronConnection').textContent=`${scope} · ${uiText('版本增量','Version incremental')} · ${cronTime(v.updated_at)} CST`;
  $('#dailyCronConnection').dataset.tone=v.stale||v.statesUnavailable?'warn':'ok';
  $('#dailyCronMainStatus').innerHTML=cronChip(v.statesUnavailable?'unavailable':v.stale?'stalled':attention?'partial':pending?'running':c.waiting_metadata?'waiting':'complete');
  $('#dailyCronMainValue').textContent=`${scope} · ${v.statesUnavailable ? '— / —' : cronFraction(inferred,eligible)}`;
  $('#dailyCronMainNote').textContent=uiText(`已推理 ${inferred} · 已回刷 ${c.published||0} · 待源 ${c.waiting_metadata||0} · 待核实 ${attention}`,`Inferred ${inferred} · Published ${c.published||0} · Pending source ${c.waiting_metadata||0} · Attention ${attention}`);
  if(v.statesUnavailable) $('#dailyCronMainNote').textContent=uiText('该版本队列状态暂不可用；不以其他版本或导入快照替代。','Version queue status unavailable; other versions and import snapshots are not substituted.');
  $('#dailyCronMediaStatus').innerHTML=cronChip(v.unavailable?'unavailable':v.stale?'stalled':m.failure_count?'partial':m.verified===m.selected&&m.selected?'complete':!m.selected?'waiting':'running');
  $('#dailyCronMediaValue').textContent=cronFraction(m.verified,m.selected);
  $('#dailyCronMediaNote').textContent=uiText(`复用 ${m.reused||0} · 待媒体 ${m.queued||0} · 最终失败 ${m.failure_count||0}`,`Reused ${m.reused||0} · Media pending ${m.queued||0} · Terminal failures ${m.failure_count||0}`);
  if(v.unavailable) $('#dailyCronMediaNote').textContent=uiText('该版本媒体状态暂不可用。','Version media status unavailable.');
  $('#dailyCronSchedule').textContent=v.discovery_schedule?.hours?.length?uiText('每天07:00、19:00 CST全量发现及补查；队列独立持续处理，无单轮总量上限。','Full discovery and source checks at07:00/19:00 CST; the queue continues independently without a per-round case cap.'):uiText('按版本持续处理；查询计划等待同步。','Version-scoped processing; awaiting discovery schedule.');
  renderCronIncrements(v.increments);
  $('#dailyCronAlerts').innerHTML=`<p class="cron-note">${escapeHtml(v.stale?uiText('增量心跳过期，请核实任务。','Incremental heartbeat is stale.'):uiText('逐 case 完成后进入回刷和媒体；不等待整批。各节点为当前累计进度，缺源与异常单独等待。','Completed cases stream to publication and media independently. Nodes show cumulative progress; missing sources and ambiguous cases wait separately.'))}</p>`;
  for(const id of ['dailyCronMainTiming','dailyCronMediaTiming'])if($('#'+id))$('#'+id).textContent='';
  renderDailyCronRuns(data);renderDailyCronSidecar(data.sidecar);renderDailyCronJobs();renderCronRunSelector();void renderDailyCronGraph();
}

function renderCloseupCron(value, family = '') {
  const panel = $('#dailyCronCloseup');
  if (!panel) return;
  panel.hidden = !value;
  if (!value) return;
  const labels = {
    queued: ['已入队', 'Queued'], collecting: ['录制中', 'Recording'], waiting: ['等待重试', 'Waiting to retry'],
    idle: ['队列空闲', 'Queue idle'], blocked_auth: ['需要刷新 Ares 登录', 'Ares login refresh required'],
    pilot_failed_requires_review: ['小批失败待排查', 'Pilot failures need review'],
    pilot_visual_review_required: ['小批待画面验收', 'Pilot visual review required'],
    resource_wait: ['等待资源', 'Waiting for resources'], stopped: ['已停止', 'Stopped'],
    interrupted_claim_requires_review: ['中断任务待恢复', 'Interrupted jobs need recovery'],
    unavailable: ['状态不可用', 'Status unavailable'], unknown: ['状态未知', 'Unknown status']
  };
  const pair = value.stale ? ['心跳过期', 'Stale heartbeat'] : labels[value.state] || labels.unknown;
  $('#dailyCronCloseupStatus').textContent = uiText(...pair);
  const versions = [...new Set([...Object.keys(value.versions || {}), ...Object.keys(value.source_members || {})])].sort()
    .filter(version => !family || version === family || version === family.slice(4));
  $('#dailyCronCloseupValue').innerHTML = versions.map(version => {
    const states = value.versions?.[version] || {}, source = value.source_members?.[version] || {};
    const published = Object.entries(source).filter(([key]) => key.startsWith('published:'));
    const total = published.length ? published.reduce((n, [, count]) => n + count, 0) : Object.values(states).reduce((n, count) => n + count, 0);
    const missing = published.filter(([key]) => key !== 'published:ready').reduce((n, [, count]) => n + count, 0);
    const detail = uiText(`待处理 ${Math.max(0, total - (states.verified || 0))} · 失败 ${states.failed || 0} · 锚点待解决 ${missing}`, `Pending ${Math.max(0, total - (states.verified || 0))} · Failed ${states.failed || 0} · Unresolved anchors ${missing}`);
    return cronMetric(version, cronFraction(states.verified || 0, total), detail, states.failed || missing ? 'warn' : 'neutral');
  }).join('') + `<p class="cron-note muted">${escapeHtml(!versions.length
    ? uiText('该版本暂无局部 BEV 回执。', 'No closeup BEV receipts for this version.')
    : uiText('所选范围的已发布成员 · 调度状态为全局共享；不影响原双视频或主推理。', 'Published members in the selected scope. Scheduler status is shared globally; original videos and inference are unaffected.'))}</p>`;
}

// These are independent completion-window counts, never a conversion funnel.
const cronIncrementKeys = ['new', 'filled', 'published', 'target_added', 'target_removed'];
function cronIncrementKnown(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
function cronIncrementIdle(row) { return row.scan_state === 'success' && cronIncrementKeys.every(k => row[k] === 0); }
function cronIncrementFamily(row) {
  const family = String(row.family || '');
  return /^\d{8}$/.test(family) ? family.slice(4) : family || uiText('未知版本', 'Unknown version');
}
function cronIncrementStatus(rows) {
  if (rows.some(r => r.scan_state === 'failed')) return ['fail', uiText('扫描失败', 'Scan failed')];
  if (rows.some(r => r.scan_state === 'running')) return ['neutral', uiText('扫描中', 'Scanning')];
  if (rows.some(r => r.scan_state !== 'success')) return ['warn', uiText('扫描未知', 'Scan unknown')];
  return ['ok', uiText('扫描成功', 'Scan succeeded')];
}
function cronIncrementRounds(items) {
  const rounds = new Map();
  for (const row of items || []) {
    const key = String(row.start_at);
    if (!rounds.has(key)) rounds.set(key, []);
    rounds.get(key).push(row);
  }
  const epoch = value => typeof value === 'number' ? value * 1000 : Date.parse(value);
  return [...rounds].sort((a, b) => epoch(b[1][0].start_at) - epoch(a[1][0].start_at)).slice(0, 14);
}
function cronIncrementBody(rows) {
  const metrics = [['new', uiText('新发现', 'New cases')], ['filled', uiText('旧案例补齐', 'Source filled')],
    ['published', uiText('回刷完成', 'Published')], ['target_added', uiText('目标入库', 'Targets added')]];
  const active = rows.filter(r => !cronIncrementIdle(r));
  const idle = rows.filter(cronIncrementIdle);
  const cards = active.map(row => {
    const [tone, status] = cronIncrementStatus([row]);
    const unknown = cronIncrementKeys.some(k => !cronIncrementKnown(row[k]));
    const cells = metrics.map(([key, label]) => `<div><dt>${escapeHtml(label)}</dt><dd${cronIncrementKnown(row[key]) ? '' : ' class="muted"'}>${escapeHtml(cronIncrementKnown(row[key]) ? cronCount(row[key]) : uiText('未知', 'Unknown'))}</dd></div>`).join('');
    const removed = row.target_removed === 0 ? '' : `<span>${escapeHtml(uiText('目标移出', 'Targets removed'))} <b>${escapeHtml(cronIncrementKnown(row.target_removed) ? cronCount(row.target_removed) : uiText('未知', 'Unknown'))}</b></span>`;
    return `<article class="cron-increment-version"><header><strong>${escapeHtml(cronIncrementFamily(row))}</strong>${row.scan_state !== 'success' ? `<span class="cron-chip" data-tone="${tone}">${escapeHtml(status)}</span>` : ''}${unknown ? `<span class="muted">${escapeHtml(uiText('数据不完整', 'Incomplete data'))}</span>` : ''}${removed}</header><dl class="cron-increment-metrics">${cells}</dl></article>`;
  }).join('');
  return `${cards}${idle.length ? `<p class="cron-increment-idle"><span class="muted">${escapeHtml(uiText('无增量', 'No changes'))}</span><strong>${escapeHtml(idle.map(cronIncrementFamily).join(' / '))}</strong></p>` : ''}`;
}
function renderCronIncrements(history) {
  const panel = $('#dailyCronIncrements'), host = $('#dailyCronIncrementRows');
  if (!panel || !host) return;
  panel.hidden = false;
  const key = JSON.stringify([state.uiLanguage, history]);
  if (host.dataset.historyKey === key) return;
  // Reuse disclosure and summary nodes even when counts or language change.
  // This preserves open state and keyboard focus across background polls.
  if (!host.querySelector('.cron-increment-rounds')) {
    host.innerHTML = '<p class="cron-increment-message muted" role="status" hidden></p><div class="cron-increment-rounds"></div><details class="cron-increment-explanation"><summary></summary><p class="cron-note muted"></p></details>';
  }
  const list = host.querySelector('.cron-increment-rounds');
  const message = host.querySelector('.cron-increment-message');
  const explanation = host.querySelector('.cron-increment-explanation');
  const anchor = [...host.querySelectorAll('summary')].find(el => {
    const rect = el.getBoundingClientRect();
    return rect.top >= 0 && rect.top < window.innerHeight;
  });
  const anchorTop = anchor?.getBoundingClientRect().top;
  const rounds = history?.status === 'ready' ? cronIncrementRounds(history.items) : [];
  message.hidden = rounds.length > 0;
  message.textContent = history?.status === 'empty' || (history?.status === 'ready' && !rounds.length)
    ? uiText('尚无定时扫描记录。', 'No scheduled scans yet.')
    : uiText('增量记录暂不可用。', 'Increment history is unavailable.');
  // Keep existing disclosures through temporary source errors; don't present them as current.
  list.hidden = !rounds.length;
  if (rounds.length) {
    const old = new Map([...list.children].map(el => [el.dataset.round, el]));
    rounds.forEach(([at, rows], index) => {
      let node = old.get(at);
      if (!node) {
        node = document.createElement('details');
        node.className = 'cron-increment-round'; node.dataset.round = at;
        node.innerHTML = '<summary></summary><div class="cron-increment-body"></div>';
        node.open = index === 0;
      }
      old.delete(at);
      node.dataset.latest = String(index === 0);
      const [tone, status] = cronIncrementStatus(rows);
      const changed = rows.filter(r => cronIncrementKeys.some(k => cronIncrementKnown(r[k]) && r[k] > 0));
      const incomplete = rows.some(r => r.scan_state !== 'success' || cronIncrementKeys.some(k => !cronIncrementKnown(r[k])));
      const brief = changed.length ? uiText(`有变化 ${changed.map(cronIncrementFamily).join(' / ')}`, `Changed: ${changed.map(cronIncrementFamily).join(' / ')}`)
        : incomplete ? uiText('数据待确认', 'Data unconfirmed') : uiText('所选范围无增量', 'No changes in the selected scope');
      node.querySelector('summary').innerHTML = `<span class="cron-round-time">${index === 0 ? `<span class="muted">${escapeHtml(uiText('最近一轮', 'Latest round'))}</span>` : ''}<strong>${escapeHtml(cronTime(rows[0].start_at).replace(/:\d{2}$/, ''))}</strong></span><span class="cron-chip" data-tone="${tone}">${escapeHtml(status)}</span><span class="cron-round-brief muted">${escapeHtml(brief)}${incomplete && changed.length ? ` · ${escapeHtml(uiText('含未知', 'Includes unknowns'))}` : ''}</span><span class="cron-round-chevron" aria-hidden="true">⌄</span>`;
      node.querySelector('.cron-increment-body').innerHTML = cronIncrementBody(rows);
      if (list.children[index] !== node) list.insertBefore(node, list.children[index] || null);
    });
    old.forEach(node => node.remove());
  }
  explanation.querySelector('summary').textContent = uiText('统计口径 · 最近14轮', 'Counting rules · Latest 14 rounds');
  explanation.querySelector('p').textContent = uiText('新发现：首次发现。补齐：旧案例触发源齐备并入队。回刷与目标入库按实际完成时段统计，可含前轮待办；目标移出取导入回执。各项独立，不能相加或计算转化率。未知不等于零。底层历史保留。', 'New: first discoveries. Source filled: previously waiting cases now ready and queued. Published and targets added follow actual completion windows and may include earlier work; removals come from import receipts. Metrics are independent, not additive or conversion rates. Unknown is not zero. Underlying history is retained.');
  host.dataset.historyKey = key;
  if (anchor?.isConnected && anchorTop != null && !list.hidden) {
    const shift = anchor.getBoundingClientRect().top - anchorTop;
    if (Math.abs(shift) > 1) window.scrollBy(0, shift);
  }
}
