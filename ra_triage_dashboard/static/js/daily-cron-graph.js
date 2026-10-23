/* Airflow-style run selection + React Flow/ELK task graph + task details. */
let cronGraphLibrary = null;

function cronGraphStateLabel(status) {
  const labels = { success: ["完成", "Complete"], warn: ["有缺失 / 已恢复", "Gaps / Recovered"], failed: ["失败", "Failed"], running: ["运行中", "Running"], pending: ["等待", "Waiting"], skipped: ["未执行", "Not executed"], unknown: ["无回执", "No evidence"], definition: ["流程说明", "Definition"] };
  return uiText(...(labels[status] || labels.unknown));
}

function cronSelectedRuns(data) {
  const runs = (data?.overview?.daily?.runs || []).filter(run => /^daily-\d{4}-\d{2}-\d{2}$/.test(run.id));
  const day = dailyCronState.selectedDay || runs[0]?.target_date_cst;
  return { day, main: runs.find(run => run.target_date_cst === day), media: data?.media_daily?.runs?.find(run => run.day === day) };
}

// Counts describe one explicit cohort/stage; absent or inconsistent receipts stay unknown.
function cronTaskProgress(done, total, { label, failed = null, skipped = null, stale = false, empty = false, waiting = false } = {}) {
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if (empty && total === 0) return { mode: "empty", text: uiText("无待处理项", "No work items"), label, stale };
  if (waiting) return { mode: "waiting", text: uiText("等待上游", "Waiting upstream"), label, stale };
  if (!count(done) || !count(total) || !total || done > total || (failed != null && (!count(failed) || failed > done)) || (skipped != null && (!count(skipped) || skipped > done))) {
    return { mode: "unknown", text: uiText("进度待回执", "Awaiting counts"), label, stale };
  }
  const percent = Math.round(done / total * 1000) / 10;
  return { mode: "count", done, total, remaining: total - done, failed, skipped, percent,
    text: cronFraction(done, total), percentText: `${percent}%`, label, stale,
    failurePercent: failed == null ? 0 : failed / total * 100,
    completePercent: (done - (failed || 0)) / total * 100 };
}

function cronTaskProgressRows(progress) {
  if (!progress) return [];
  const rows = [[uiText("进度口径", "Progress scope"), progress.label],
    [uiText("已处理 / 总数", "Processed / Total"), progress.mode === "count" ? `${progress.text} · ${progress.percentText}` : progress.text]];
  if (progress.mode === "count") {
    rows.push([uiText("待处理", "Remaining"), cronCount(progress.remaining)]);
    if (progress.failed != null) rows.push([uiText("失败", "Failed"), cronCount(progress.failed)]);
    if (progress.skipped != null) rows.push([uiText("跳过", "Skipped"), cronCount(progress.skipped)]);
  }
  if (progress.stale) rows.push([uiText("进度快照", "Progress snapshot"), uiText("数据已过期，显示最后一次观测", "Stale: showing the last observation")]);
  return rows;
}

function cronTaskProgressMarkup(progress) {
  if (!progress) return "";
  if (progress.mode !== "count") return `<span class="cron-task-progress-empty">${escapeHtml(progress.text)}</span>`;
  return `<div class="cron-task-progress" data-stale="${progress.stale}"><div class="cron-task-progress-values"><span>${escapeHtml(progress.text)}</span><strong>${escapeHtml(progress.percentText)}</strong></div><div class="cron-task-progress-track" role="progressbar" aria-label="${escapeHtml(progress.label)}" aria-valuemin="0" aria-valuemax="${progress.total}" aria-valuenow="${progress.done}" aria-valuetext="${escapeHtml(`${progress.text} · ${progress.percentText}`)}"><span style="width:${progress.completePercent}%"></span><i style="width:${progress.failurePercent}%"></i></div></div>`;
}

function buildDailyCronGraph(data, definitionLane = "") {
  if (data?.incremental?.enabled && !dailyCronState.selectedDay) return buildIncrementalCronGraph(data.incremental, definitionLane);
  const { day, main: run, media } = cronSelectedRuns(data);
  const daily = data?.overview?.daily, runtime = data?.media_daily;
  const launch = cronLatestLaunch(daily, run);
  const terminal = ["complete", "complete_with_gaps"].includes(run?.state);
  const empty = run?.health === "empty";
  const mainStale = !data?.overview || data.overview.stale || data.overview.collector_error || Date.now() / 1000 - (data.overview.collected_at || 0) > 90 || dailyCronState.error;
  const activeRun = !mainStale && run?.health === "running";
  const mediaStale = !runtime || runtime.stale || runtime.controller_error || dailyCronState.error;
  const node = (id, label, detail, status, rows = [], issues = []) => ({ id, data: { label, detail, status, stateLabel: cronGraphStateLabel(status), rows, issues } });
  const progressState = stage => activeRun && run?.stage === stage ? "running" : run?.health === "failed" && run?.stage === stage ? "failed" : "unknown";
  const mainNodes = [
    node("main-schedule", uiText("定时启动", "Schedule"), launch ? cronTime(launch.started_at) : "09:00 CST", launch?.started_at ? "success" : "pending", [[uiText("最近调度退出", "Scheduler exit"), launch ? `${cronLabel(launch.state)} · exit ${cronCount(launch.returncode)}` : "—"], [uiText("下次运行", "Next run"), cronTime(daily?.next_run_at)]]),
    node("main-query", uiText("查询 / 冻结选集", "Query / Freeze cohort"), `${uiText("选中", "Selected")} ${cronCount(run?.selected)}`, run?.selected != null ? "success" : "unknown", [[uiText("目标日期", "Target day"), day || "—"], [uiText("选中", "Selected"), cronCount(run?.selected)]]),
    node("main-infer", uiText("采集 / 模型推理", "Collect / Infer"), cronFraction(run?.inferred, run?.selected), empty ? "skipped" : terminal ? run.skipped > 0 ? "warn" : "success" : run?.state === "inferred" ? "success" : progressState("inference"), [[uiText("已推理", "Inferred"), cronCount(run?.inferred)], [uiText("跳过", "Skipped"), cronCount(run?.skipped)]], [...(run?.skipped_cases || []), ...(run?.failure_details || [])].map(row => row.issue_id)),
    node("main-publish", uiText("Trail 回刷", "Trail publication"), cronFraction(run?.published, run?.inferred), empty ? "skipped" : terminal || (run?.published != null && run?.published === run?.inferred && run?.inferred > 0) ? "success" : progressState("publication"), [[uiText("已回刷", "Published"), cronCount(run?.published)], [uiText("已验证", "Verified"), cronCount(run?.verified)]]),
    node("main-verify", uiText("抽样 / 验证", "Sample / Verify"), `${uiText("验证", "Verified")} ${cronCount(run?.verified)}`, empty ? "skipped" : terminal ? "success" : progressState("sample_hook"), [[uiText("最终状态", "Final state"), cronLabel(run?.health || "unknown")], [uiText("当前阶段", "Current stage"), `${run?.stage || "—"} · ${cronFraction(run?.finished, run?.total)}`], [uiText("更新 · CST", "Updated · CST"), cronTime(run?.updated_at)]]),
  ];
  const allMedia = Boolean(media && media.selected > 0 && media.verified === media.selected);
  const noMedia = media?.state === "empty" && media.selected === 0;
  const mediaActive = !mediaStale && media?.state === "collecting";
  const retryObserved = media?.retry_state && media.retry_state !== "not_observed";
  const recoveryUnneeded = noMedia || (allMedia && media.original_orion_total === media.selected && media.original_orion_failed === 0);
  const mediaNodes = [
    node("media-source", uiText("低置信度 / 抽样", "Low confidence / Sample"), `${day || "—"} · ${cronCount(media?.selected)}`, media?.selected > 0 || noMedia ? "success" : runtime ? "pending" : "unknown", [[uiText("所选日期", "Selected day"), day || "—"], [uiText("目标案例", "Target cases"), cronCount(media?.selected)]]),
    node("media-import", uiText("Run 导入 / 分配", "Import / Assign"), `${cronCount(media?.imported)} / ${cronCount(media?.assigned)}`, noMedia ? "skipped" : media?.imported === media?.selected && media?.assigned === media?.selected && media?.selected > 0 ? "success" : media ? "pending" : "unknown", [[uiText("导入", "Imported"), cronCount(media?.imported)], [uiText("已分配", "Assigned"), cronCount(media?.assigned)], ["Run", media?.run_id || "—"]]),
    node("media-camera", "Camera · ±20s", cronFraction(media?.camera_verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : mediaActive ? "running" : "unknown", [[uiText("已验证", "Verified"), cronFraction(media?.camera_verified, media?.selected)]]),
    node("media-orion", "BEV · Orion", `${uiText("验证", "Verified")} ${cronCount(media?.bev_verified)}`, noMedia ? "skipped" : allMedia ? media.original_orion_failed > 0 ? "warn" : "success" : mediaActive ? "running" : "unknown", [[uiText("最终已验证", "Final verified"), cronCount(media?.bev_verified)], [uiText("可见原始队列范围", "Observed original queue scope"), cronFraction(media?.original_orion_total, media?.selected)], [uiText("队列完成 / 失败", "Queue completed / failed"), cronFraction(media?.original_orion_completed, media?.original_orion_failed)]]),
    node("media-retry", uiText("Orion 重试 ×1", "Orion retry ×1"), retryObserved ? `${cronCount(media?.retry_completed)} ${uiText("完成", "completed")}` : uiText("未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : retryObserved ? media.retry_state === "completed" ? "success" : media.retry_state === "partial_failed" ? "warn" : mediaActive ? "running" : "unknown" : "unknown", [[uiText("重试状态", "Retry state"), media?.retry_state || "—"], [uiText("完成 / 失败", "Complete / Failed"), cronFraction(media?.retry_completed, media?.retry_failed)]]),
    node("media-local", uiText("本地兜底 · 最多2次", "Local · At most 2 tries"), media?.local_attempts ? `${media.local_attempts} ${uiText("次回执", "receipts")}` : uiText("未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : media?.local_attempts ? media.local_verified > 0 ? "success" : "warn" : "unknown", [[uiText("尝试回执", "Attempt receipts"), cronCount(media?.local_attempts)], [uiText("本地验证", "Local verified"), cronCount(media?.local_verified)]]),
    node("media-verify", uiText("双媒体验证", "Verify both videos"), cronFraction(media?.verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : media?.state === "media_failed" ? "failed" : mediaActive ? "running" : "unknown", [[uiText("已验证", "Verified"), cronFraction(media?.verified, media?.selected)], [uiText("终态失败", "Terminal failures"), cronCount(media?.failure_count)]], media?.failure_ids || []),
    node("media-ready", uiText("平台就绪", "Platform ready"), media ? cronLabel(media.state) : uiText("等待当日回执", "Awaiting daily receipt"), noMedia ? "skipped" : allMedia && media.assigned === media.selected ? "success" : media?.state === "complete_with_gaps" ? "warn" : media?.state === "media_failed" ? "failed" : "pending", [[uiText("目标日期", "Target day"), day || "—"], [uiText("更新 · CST", "Updated · CST"), cronTime(media?.updated_at)], [uiText("主任务影响", "Main pipeline impact"), uiText("独立判定", "Independent outcome")]]),
  ];
  const attach = (item, done, total, options = {}) => {
    item.data.progress = cronTaskProgress(done, total, options);
    item.data.rows.push(...cronTaskProgressRows(item.data.progress));
    if (data?.observed_at) item.data.rows.push([uiText("进度观测 · CST", "Progress observed · CST"), cronTime(data.observed_at)]);
  };
  const currentStage = (stage, fallbackDone, fallbackTotal) => run?.stage === stage && run?.finished != null && run?.total != null
    ? [run.finished, run.total] : [fallbackDone, fallbackTotal];
  const mainOptions = { stale: Boolean(mainStale), empty, waiting: false };
  const inferredDone = Number.isSafeInteger(run?.inferred) && Number.isSafeInteger(run?.skipped) ? run.inferred + run.skipped : null;
  attach(mainNodes[2], ...currentStage("inference", inferredDone, run?.selected), { ...mainOptions, label: uiText("采集 / 推理已处理（含失败和跳过）", "Acquisition / inference processed, including failures and skips"),
    failed: run?.stage === "inference" && Number.isSafeInteger(run?.succeeded) && Number.isSafeInteger(run?.finished) ? run.finished - run.succeeded : null,
    skipped: run?.skipped });
  attach(mainNodes[3], ...currentStage("publication", run?.published, run?.inferred), { ...mainOptions,
    waiting: !empty && run?.stage === "inference", label: uiText("本批回刷目标", "Publication cohort") });
  const sample = run?.stage_timings?.["main-verify"];
  attach(mainNodes[4], ...currentStage("sample_hook", sample?.observed, sample?.total), { ...mainOptions,
    waiting: !empty && ["inference", "publication"].includes(run?.stage), label: uiText("本批抽样验证目标", "Sample verification cohort"), empty: empty || sample?.total === 0 });
  const waitingMedia = !noMedia && Boolean(media) && media.selected === 0;
  const mediaOptions = { stale: Boolean(mediaStale), empty: noMedia, waiting: waitingMedia };
  attach(mediaNodes[1], media?.assigned, media?.selected, { ...mediaOptions, label: uiText("本批任务分配；导入数量单列", "Assignment cohort; imports shown separately") });
  attach(mediaNodes[2], media?.camera_verified, media?.selected, { ...mediaOptions, label: uiText("本批已确认完成的 Camera", "Confirmed Camera completion in this cohort") });
  const orionDone = Number.isSafeInteger(media?.original_orion_completed) && Number.isSafeInteger(media?.original_orion_failed)
    ? media.original_orion_completed + media.original_orion_failed : null;
  attach(mediaNodes[3], orionDone, media?.original_orion_total, { ...mediaOptions,
    label: uiText("原始 Orion 队列（含失败）；最终验证单列", "Original Orion queue, including failures; final validation shown separately"), failed: media?.original_orion_failed });
  const retryDone = Number.isSafeInteger(media?.retry_completed) && Number.isSafeInteger(media?.retry_failed) ? media.retry_completed + media.retry_failed : null;
  attach(mediaNodes[4], retryDone, media?.retry_total, { ...mediaOptions, waiting: waitingMedia,
    label: uiText("本轮 Orion 重试子集（含失败）", "This Orion retry subset, including failures"), failed: media?.retry_failed });
  const local = media?.stage_timings?.["media-local"];
  if (mediaActive && local?.total > local?.observed) {
    mediaNodes[5].data.status = "running";
    mediaNodes[5].data.stateLabel = cronGraphStateLabel("running");
  }
  if (run?.selected == null && run?.started_at && ["inference", "publication", "sample_hook"].includes(run.stage)) {
    mainNodes[1].data.detail = uiText("选集已冻结", "Cohort frozen");
    mainNodes[1].data.status = "success";
    mainNodes[1].data.stateLabel = cronGraphStateLabel("success");
  }
  attach(mediaNodes[5], local?.observed, local?.total, { ...mediaOptions,
    label: uiText("已发起的本地尝试；后续尝试会增加总数", "Launched local attempts; later attempts increase the total") });
  attach(mediaNodes[6], media?.verified, media?.selected, { ...mediaOptions, label: uiText("本批双媒体最终验证", "Final dual-media validation for this cohort") });
  attach(mediaNodes[7], media?.verified, media?.selected, { ...mediaOptions, label: uiText("双媒体验证覆盖；平台就绪还需完成分配", "Dual-media coverage; readiness also requires completed assignment") });
  for (const item of [...mainNodes, ...mediaNodes]) {
    if (item.data.progress?.mode === "waiting" && item.data.status === "unknown") {
      item.data.status = "pending";
      item.data.stateLabel = cronGraphStateLabel("pending");
    }
    if (item.data.status === "skipped" && item.data.progress?.mode !== "count") item.data.progress = { ...item.data.progress, text: noMedia || empty ? uiText("无待处理项", "No work items") : uiText("无需执行", "Not required") };
  }
  if (terminal && run.skipped > 0) mainNodes[2].data.stateLabel = uiText(`跳过 ${run.skipped}`, `${run.skipped} skipped`);
  if (allMedia && media.original_orion_failed > 0) mediaNodes[3].data.stateLabel = uiText("最终已补齐", "Finally recovered");
  if (mainStale) mainNodes.forEach(n => { if (n.data.status === "running") n.data.status = "unknown"; n.data.stateLabel = cronGraphStateLabel(n.data.status); });
  if (mediaStale) mediaNodes.forEach(n => { if (n.data.status === "running") n.data.status = "unknown"; n.data.stateLabel = cronGraphStateLabel(n.data.status); });
  for (const n of mainNodes) {
    n.data.timing = run?.stage_timings?.[n.id];
    n.data.timingText = n.id === "main-schedule" ? uiText("定时触发", "Scheduled event") : cronTimingText(n.data.timing, { compact: true, stale: mainStale });
    n.data.rows.push(...cronTimingRows(n.data.timing, { stale: mainStale }));
  }
  for (const n of mediaNodes) {
    n.data.timing = n.id === "media-ready" ? media?.timing : media?.stage_timings?.[n.id];
    n.data.timingText = cronTimingText(n.data.timing, { compact: true, stale: mediaStale });
    n.data.rows.push(...cronTimingRows(n.data.timing, { stale: mediaStale }));
  }
  const edge = (source, target, label = "", optional = false) => ({ id: `${source}:${target}`, source, target, label, optional });
  const mainEdges = mainNodes.slice(1).map((n, i) => edge(mainNodes[i].id, n.id));
  const mediaEdges = [edge("media-source", "media-import"), edge("media-import", "media-camera"), edge("media-import", "media-orion"), edge("media-camera", "media-verify"), edge("media-orion", "media-verify"), edge("media-orion", "media-retry", uiText("失败", "Failed"), true), edge("media-retry", "media-verify", uiText("成功", "Success"), true), edge("media-retry", "media-local", uiText("仍失败", "Still failed"), true), edge("media-local", "media-verify", "", true), edge("media-verify", "media-ready")];
  let lanes = [{ id: "main-lane", label: uiText("推理回刷", "Inference / publication"), nodes: mainNodes }, { id: "media-lane", label: uiText("平台与媒体", "Platform / media"), nodes: mediaNodes }];
  let edges = [...mainEdges, ...mediaEdges, edge("main-verify", "media-source", uiText("完成回执 · 旁路不反向阻塞", "Completion receipt · No reverse blocking"), true)];
  if (definitionLane) {
    lanes = lanes.filter(lane => lane.id === `${definitionLane}-lane`);
    const ids = new Set(lanes.flatMap(lane => lane.nodes.map(n => n.id)));
    edges = edges.filter(e => ids.has(e.source) && ids.has(e.target));
    lanes.forEach(lane => lane.nodes.forEach(n => { n.data = { ...n.data, status: "definition", stateLabel: cronGraphStateLabel("definition"), timingText: "", progress: null, detail: n.id === "main-infer" ? uiText("缺失 ≤5 且 ≤2% 可继续", "Continue if gaps ≤5 AND ≤2%") : n.id === "media-ready" ? uiText("少量缺失单独记录", "Small gaps recorded separately") : "" }; }));
  }
  return { lanes, edges, selectedNode: dailyCronState.selectedNode || "", definition: Boolean(definitionLane), active: dailyCronState.active && !dailyCronState.error, theme: state.colorTheme || "dark", ui: { minimap: uiText("流程缩略图", "Flow overview"), loading: uiText("正在加载运行图…", "Loading run graph…"), error: uiText("运行图加载失败，可刷新重试。", "Graph unavailable; refresh to retry.") } };
}

function ensureCronGraphLibrary() {
  if (window.RACronGraph) return Promise.resolve(window.RACronGraph);
  if (cronGraphLibrary) return cronGraphLibrary;
  cronGraphLibrary = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = withBase("/static/vendor/cron-graph/graph.js?v=manual-triage-611");
    script.onload = () => resolve(window.RACronGraph);
    script.onerror = () => { cronGraphLibrary = null; script.remove(); reject(Error("graph load failed")); };
    document.body.appendChild(script);
  });
  return cronGraphLibrary;
}

async function renderDailyCronGraph() {
  if (!dailyCronState.active) return;
  const root = $("#dailyCronGraph");
  if (!root) return;
  try {
    const graph = await ensureCronGraphLibrary();
    if (!dailyCronState.active) return;
    const model = buildDailyCronGraph(dailyCronState.data);
    graph.render(root, model, id => {
      dailyCronState.selectedNode = id;
      renderCronGraphDetails(model, id);
      if (id && window.matchMedia?.("(max-width: 639px)").matches) $("#dailyCronNodeDetails")?.scrollIntoView({ block: "start", behavior: "auto" });
      void renderDailyCronGraph();
    });
    if (dailyCronState.selectedNode) renderCronGraphDetails(model, dailyCronState.selectedNode);
  } catch (_error) { root.textContent = uiText("运行图加载失败，刷新重试。", "Graph unavailable; refresh to retry."); }
}

function renderCronGraphDetails(model, id) {
  const panel = $("#dailyCronNodeDetails"), workspace = $("#dailyCronGraphWorkspace");
  const node = model.lanes.flatMap(l => l.nodes).find(n => n.id === id);
  panel.hidden = !node;
  workspace.classList.toggle("has-selection", Boolean(node));
  if (!node) return;
  panel.innerHTML = `<div class="cron-section-heading"><strong>${escapeHtml(node.data.label)}</strong><button type="button" class="button button-quiet" data-close-cron-node aria-label="${escapeHtml(uiText("关闭详情", "Close details"))}">×</button></div><span class="cron-chip" data-tone="${node.data.status === "success" ? "ok" : node.data.status === "failed" ? "fail" : node.data.status === "warn" ? "warn" : "neutral"}">${escapeHtml(node.data.stateLabel)}</span>${cronTaskProgressMarkup(node.data.progress)}<dl>${(node.data.rows || []).map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join("")}</dl>${node.data.issues.length ? `<ul class="cron-case-list">${[...new Set(node.data.issues)].map(issue => `<li><a href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(issue)}?view_id=2410" target="_blank" rel="noopener noreferrer">${escapeHtml(issue)} ↗</a></li>`).join("")}</ul>` : ""}`;
  panel.querySelector("[data-close-cron-node]").onclick = () => { dailyCronState.selectedNode = ""; renderCronGraphDetails(model, ""); void renderDailyCronGraph();
    if (window.matchMedia?.("(max-width: 639px)").matches) document.querySelector(`.cron-mobile-stage-button[data-cron-node="${id}"]`)?.focus();
  };
}

async function openCronGraphHelp(lane) {
  const dialog = $("#dailyCronHelpDialog");
  $("#dailyCronHelpTitle").textContent = lane === "main" ? uiText("推理回刷 · 流程说明", "Daily inference · Definition") : uiText("平台与媒体 · 流程说明", "Media sidecar · Definition");
  $("#dailyCronHelpNote").textContent = lane === "main" ? uiText("09:00 CST，处理 T−2；周末照常查询。少量采集缺失 ≤5 且 ≤2% 可继续并记录，超限阻塞。空数据正常结束。", "09:00 CST, T−2 data; weekends queried normally. Acquisition gaps ≤5 AND ≤2% may continue with records; larger gaps block. Empty data completes normally.") : uiText("每天低置信度＋抽样，均分给 jasperchen / liangxianghui 联合复核。Orion 重试1次，本地最多2次；少量缺失单独记录，不影响主任务。发布1小时后清理 Camera 原始 bag。", "Daily low confidence + sampling, balanced joint-review assignments. One Orion retry, at most two local attempts. Gaps recorded independently of the main task; Camera source bags cleaned 1h after publication.");
  if (dailyCronState.data?.incremental?.enabled && lane === "main") $("#dailyCronHelpNote").textContent = uiText("每5分钟按版本发现新增和后补；固定版本级10%概率抽样，缺源等待，其他案例继续。", "Version-scoped discovery every five minutes; stable probability sampling; missing sources wait independently.");
  dialog.showModal();
  const graph = await ensureCronGraphLibrary();
  if (dialog.open) graph.render($("#dailyCronHelpGraph"), buildDailyCronGraph(dailyCronState.data, lane));
}

function renderCronRunSelector() {
  const select = $("#dailyCronRunDate");
  if (!select) return;
  const runs = (dailyCronState.data?.overview?.daily?.runs || []).filter(run => /^daily-\d{4}-\d{2}-\d{2}$/.test(run.id));
  const value = dailyCronState.selectedDay || "";
  const latest = dailyCronState.data?.incremental?.enabled ? uiText("当前版本增量", "Current version incremental") : [uiText("最新运行", "Latest run"), runs[0]?.target_date_cst].filter(Boolean).join(" · ");
  select.innerHTML = `<option value="">${escapeHtml(latest)}</option>` + runs.map(run => {
    const status = ["partial", "complete_with_gaps"].includes(run.health) ? uiText("已完成（有缺失）", "Complete with gaps") : cronLabel(run.health);
    return `<option value="${escapeHtml(run.target_date_cst)}">${escapeHtml(run.target_date_cst)} · ${escapeHtml(status)}</option>`;
  }).join("");
  select.value = value;
  const picker = enhanceNativeUiSelect(select);
  picker?.querySelector(".ui-select-trigger")?.setAttribute("aria-label", uiText("选择运行日期", "Select run date"));
}

function bindCronGraphEvents() {
  $("#dailyCronRunDate")?.addEventListener("change", event => { dailyCronState.selectedDay = event.target.value; dailyCronState.selectedNode = ""; renderCronGraphDetails({ lanes: [] }, ""); renderDailyCron(); });
  document.querySelectorAll("[data-cron-help]").forEach(button => button.addEventListener("click", () => { void openCronGraphHelp(button.dataset.cronHelp); }));
  $("#dailyCronHelpClose")?.addEventListener("click", () => $("#dailyCronHelpDialog").close());
  $("#dailyCronHelpDialog")?.addEventListener("close", () => window.RACronGraph?.unmount($("#dailyCronHelpGraph")));
  $("#dailyCronFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); else void $("#dailyCronGraphWorkspace").requestFullscreen(); });
  $("#dailyCronExitFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); });
}


function buildIncrementalCronGraph(v,definitionLane='') {
  const c=v.states||{},m=v.media||{},active=!v.stale;
  const node=(id,label,detail,status)=>({id,data:{label,detail,status,stateLabel:cronGraphStateLabel(status),rows:[],issues:[]}});
  const nodes=[node('main-schedule','增量发现','每5分钟 · T−0及迟到数据',active?'success':'unknown'),node('main-query','版本分流',(v.families||[]).map(x=>x.slice(4)).join(' / '),'success'),node('main-wait','等待源信息',String(c.waiting_metadata||0),'pending'),node('main-verify','版本统一抽样','固定种子 · 每 case 约10%','success'),node('main-infer','采集与推理',String((c.inferred||0)+(c.published||0)),(c.running||c.ready||c.retry_wait)?'running':'success'),node('main-publish','Trail 回刷',String(c.published||0),c.inferred?'running':'success')];
  const media=[node('media-source','低置信＋抽样',String(m.selected||0),'success'),node('media-import','统一 Run 与数据集','仅追加新成员与分配','success'),node('media-camera','Camera','全局4并发',m.queued?'running':'success'),node('media-orion','Orion BEV','全局≤1000并发',m.queued?'running':'success'),node('media-retry','Orion 重试','仅失败子集 · 1次',m.queued?'pending':'skipped'),node('media-local','本地兜底','全局2并发 · 最多2次',m.failure_count?'warn':'pending'),node('media-verify','双媒体验证',`${m.verified||0} / ${m.selected||0}`,m.failure_count?'warn':m.verified===m.selected?'success':'running'),node('media-ready','发布与清理','Camera源bag发布1小时后清理',m.verified?'success':'pending')];
  const edge=(a,b,optional=false)=>({id:a+':'+b,source:a,target:b,optional});
  let lanes=[{id:'main-lane',label:'按版本增量处理',nodes},{id:'media-lane',label:'平台与独立媒体',nodes:media}];
  let edges=[edge('main-schedule','main-query'),edge('main-query','main-wait',true),edge('main-wait','main-verify',true),edge('main-query','main-verify'),edge('main-verify','main-infer'),edge('main-infer','main-publish'),edge('main-infer','media-source',true),edge('media-source','media-import'),edge('media-import','media-camera'),edge('media-import','media-orion'),edge('media-camera','media-verify'),edge('media-orion','media-verify'),edge('media-orion','media-retry',true),edge('media-retry','media-local',true),edge('media-local','media-verify',true),edge('media-verify','media-ready')];
  if(definitionLane){lanes=lanes.filter(x=>x.id===definitionLane+'-lane');const ids=new Set(lanes.flatMap(x=>x.nodes.map(n=>n.id)));edges=edges.filter(x=>ids.has(x.source)&&ids.has(x.target));}
  return {lanes,edges,selectedNode:dailyCronState.selectedNode||'',definition:Boolean(definitionLane),active,theme:state.colorTheme||'dark',ui:{minimap:'流程缩略图',loading:'加载运行图…',error:'运行图暂不可用'}};
}
