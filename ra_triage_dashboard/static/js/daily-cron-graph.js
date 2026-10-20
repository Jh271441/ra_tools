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

function buildDailyCronGraph(data, definitionLane = "") {
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
    node("media-source", uiText("低置信度 / 抽样", "Low confidence / Sample"), `${day || "—"} · ${cronCount(media?.selected)}`, media ? "success" : runtime ? "pending" : "unknown", [[uiText("所选日期", "Selected day"), day || "—"], [uiText("目标案例", "Target cases"), cronCount(media?.selected)]]),
    node("media-import", uiText("Run 导入 / 分配", "Import / Assign"), `${cronCount(media?.imported)} / ${cronCount(media?.assigned)}`, noMedia ? "skipped" : media?.imported === media?.selected && media?.assigned === media?.selected && media?.selected > 0 ? "success" : media ? "pending" : "unknown", [[uiText("导入", "Imported"), cronCount(media?.imported)], [uiText("已分配", "Assigned"), cronCount(media?.assigned)], ["Run", media?.run_id || "—"]]),
    node("media-camera", "Camera · ±20s", cronFraction(media?.camera_verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : mediaActive ? "running" : "unknown", [[uiText("已验证", "Verified"), cronFraction(media?.camera_verified, media?.selected)]]),
    node("media-orion", "BEV · Orion", `${uiText("验证", "Verified")} ${cronCount(media?.bev_verified)}`, noMedia ? "skipped" : allMedia ? media.original_orion_failed > 0 ? "warn" : "success" : mediaActive ? "running" : "unknown", [[uiText("最终已验证", "Final verified"), cronCount(media?.bev_verified)], [uiText("可见原始队列范围", "Observed original queue scope"), cronFraction(media?.original_orion_total, media?.selected)], [uiText("队列完成 / 失败", "Queue completed / failed"), cronFraction(media?.original_orion_completed, media?.original_orion_failed)]]),
    node("media-retry", uiText("Orion 重试 ×1", "Orion retry ×1"), retryObserved ? `${cronCount(media?.retry_completed)} ${uiText("完成", "completed")}` : uiText("未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : retryObserved ? media.retry_state === "completed" ? "success" : media.retry_state === "partial_failed" ? "warn" : mediaActive ? "running" : "unknown" : "unknown", [[uiText("重试状态", "Retry state"), media?.retry_state || "—"], [uiText("完成 / 失败", "Complete / Failed"), cronFraction(media?.retry_completed, media?.retry_failed)]]),
    node("media-local", uiText("本地兜底 · 最多2次", "Local · At most 2 tries"), media?.local_attempts ? `${media.local_attempts} ${uiText("次回执", "receipts")}` : uiText("未观测到执行", "No execution observed"), recoveryUnneeded ? "skipped" : media?.local_attempts ? media.local_verified > 0 ? "success" : "warn" : "unknown", [[uiText("尝试回执", "Attempt receipts"), cronCount(media?.local_attempts)], [uiText("本地验证", "Local verified"), cronCount(media?.local_verified)]]),
    node("media-verify", uiText("双媒体验证", "Verify both videos"), cronFraction(media?.verified, media?.selected), noMedia ? "skipped" : allMedia ? "success" : media?.state === "media_failed" ? "failed" : mediaActive ? "running" : "unknown", [[uiText("已验证", "Verified"), cronFraction(media?.verified, media?.selected)], [uiText("终态失败", "Terminal failures"), cronCount(media?.failure_count)]], media?.failure_ids || []),
    node("media-ready", uiText("平台就绪", "Platform ready"), media ? cronLabel(media.state) : uiText("等待当日回执", "Awaiting daily receipt"), noMedia ? "skipped" : allMedia && media.assigned === media.selected ? "success" : media?.state === "complete_with_gaps" ? "warn" : media?.state === "media_failed" ? "failed" : "pending", [[uiText("目标日期", "Target day"), day || "—"], [uiText("更新 · CST", "Updated · CST"), cronTime(media?.updated_at)], [uiText("主任务影响", "Main pipeline impact"), uiText("独立判定", "Independent outcome")]]),
  ];
  if (terminal && run.skipped > 0) mainNodes[2].data.stateLabel = uiText(`跳过 ${run.skipped}`, `${run.skipped} skipped`);
  if (allMedia && media.original_orion_failed > 0) mediaNodes[3].data.stateLabel = uiText("最终已补齐", "Finally recovered");
  if (mainStale) mainNodes.forEach(n => { if (n.data.status === "running") n.data.status = "unknown"; n.data.stateLabel = cronGraphStateLabel(n.data.status); });
  if (mediaStale) mediaNodes.forEach(n => { if (n.data.status === "running") n.data.status = "unknown"; n.data.stateLabel = cronGraphStateLabel(n.data.status); });
  const edge = (source, target, label = "", optional = false) => ({ id: `${source}:${target}`, source, target, label, optional });
  const mainEdges = mainNodes.slice(1).map((n, i) => edge(mainNodes[i].id, n.id));
  const mediaEdges = [edge("media-source", "media-import"), edge("media-import", "media-camera"), edge("media-import", "media-orion"), edge("media-camera", "media-verify"), edge("media-orion", "media-verify"), edge("media-orion", "media-retry", uiText("失败", "Failed"), true), edge("media-retry", "media-verify", uiText("成功", "Success"), true), edge("media-retry", "media-local", uiText("仍失败", "Still failed"), true), edge("media-local", "media-verify", "", true), edge("media-verify", "media-ready")];
  let lanes = [{ id: "main-lane", label: uiText("推理回刷", "Inference / publication"), nodes: mainNodes }, { id: "media-lane", label: uiText("平台与媒体", "Platform / media"), nodes: mediaNodes }];
  let edges = [...mainEdges, ...mediaEdges, edge("main-verify", "media-source", uiText("完成回执 · 旁路不反向阻塞", "Completion receipt · No reverse blocking"), true)];
  if (definitionLane) {
    lanes = lanes.filter(lane => lane.id === `${definitionLane}-lane`);
    const ids = new Set(lanes.flatMap(lane => lane.nodes.map(n => n.id)));
    edges = edges.filter(e => ids.has(e.source) && ids.has(e.target));
    lanes.forEach(lane => lane.nodes.forEach(n => { n.data = { ...n.data, status: "definition", stateLabel: cronGraphStateLabel("definition"), detail: n.id === "main-infer" ? uiText("缺失 ≤5 且 ≤2% 可继续", "Continue if gaps ≤5 AND ≤2%") : n.id === "media-ready" ? uiText("少量缺失单独记录", "Small gaps recorded separately") : "" }; }));
  }
  return { lanes, edges, selectedNode: dailyCronState.selectedNode || "", definition: Boolean(definitionLane), active: dailyCronState.active && !dailyCronState.error, theme: state.colorTheme || "dark", ui: { loading: uiText("正在加载运行图…", "Loading run graph…"), error: uiText("运行图加载失败，可刷新重试。", "Graph unavailable; refresh to retry.") } };
}

function ensureCronGraphLibrary() {
  if (window.RACronGraph) return Promise.resolve(window.RACronGraph);
  if (cronGraphLibrary) return cronGraphLibrary;
  cronGraphLibrary = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = withBase("/static/vendor/cron-graph/graph.js?v=manual-triage-580");
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
    graph.render(root, model, id => { dailyCronState.selectedNode = id; renderCronGraphDetails(model, id); void renderDailyCronGraph(); });
    if (dailyCronState.selectedNode) renderCronGraphDetails(model, dailyCronState.selectedNode);
  } catch (_error) { root.textContent = uiText("运行图加载失败，刷新重试。", "Graph unavailable; refresh to retry."); }
}

function renderCronGraphDetails(model, id) {
  const panel = $("#dailyCronNodeDetails"), workspace = $("#dailyCronGraphWorkspace");
  const node = model.lanes.flatMap(l => l.nodes).find(n => n.id === id);
  panel.hidden = !node;
  workspace.classList.toggle("has-selection", Boolean(node));
  if (!node) return;
  panel.innerHTML = `<div class="cron-section-heading"><strong>${escapeHtml(node.data.label)}</strong><button type="button" class="button button-quiet" data-close-cron-node aria-label="${escapeHtml(uiText("关闭详情", "Close details"))}">×</button></div><span class="cron-chip" data-tone="${node.data.status === "success" ? "ok" : node.data.status === "failed" ? "fail" : node.data.status === "warn" ? "warn" : "neutral"}">${escapeHtml(node.data.stateLabel)}</span><dl>${(node.data.rows || []).map(([k, v]) => `<div><dt>${escapeHtml(k)}</dt><dd>${escapeHtml(v)}</dd></div>`).join("")}</dl>${node.data.issues.length ? `<ul class="cron-case-list">${[...new Set(node.data.issues)].map(issue => `<li><a href="https://voyager.intra.xiaojukeji.com/static/management/#/issue/${encodeURIComponent(issue)}?view_id=2410" target="_blank" rel="noopener noreferrer">${escapeHtml(issue)} ↗</a></li>`).join("")}</ul>` : ""}`;
  panel.querySelector("[data-close-cron-node]").onclick = () => { dailyCronState.selectedNode = ""; renderCronGraphDetails(model, ""); void renderDailyCronGraph(); };
}

async function openCronGraphHelp(lane) {
  const dialog = $("#dailyCronHelpDialog");
  $("#dailyCronHelpTitle").textContent = lane === "main" ? uiText("推理回刷 · 流程说明", "Daily inference · Definition") : uiText("平台与媒体 · 流程说明", "Media sidecar · Definition");
  $("#dailyCronHelpNote").textContent = lane === "main" ? uiText("09:00 CST，处理 T−2；周末照常查询。少量采集缺失 ≤5 且 ≤2% 可继续并记录，超限阻塞。空数据正常结束。", "09:00 CST, T−2 data; weekends queried normally. Acquisition gaps ≤5 AND ≤2% may continue with records; larger gaps block. Empty data completes normally.") : uiText("每天低置信度＋抽样，均分给 jasperchen / liangxianghui 联合复核。Orion 重试1次，本地最多2次；少量缺失单独记录，不影响主任务。发布1小时后清理 Camera 原始 bag。", "Daily low confidence + sampling, balanced joint-review assignments. One Orion retry, at most two local attempts. Gaps recorded independently of the main task; Camera source bags cleaned 1h after publication.");
  dialog.showModal();
  const graph = await ensureCronGraphLibrary();
  if (dialog.open) graph.render($("#dailyCronHelpGraph"), buildDailyCronGraph(dailyCronState.data, lane));
}

function renderCronRunSelector() {
  const select = $("#dailyCronRunDate");
  if (!select) return;
  const runs = (dailyCronState.data?.overview?.daily?.runs || []).filter(run => /^daily-\d{4}-\d{2}-\d{2}$/.test(run.id));
  const value = dailyCronState.selectedDay || "";
  select.innerHTML = `<option value="">${escapeHtml(uiText("最新运行", "Latest run"))}</option>` + runs.map(run => `<option value="${escapeHtml(run.target_date_cst)}">${escapeHtml(run.target_date_cst)} · ${escapeHtml(cronLabel(run.health))}</option>`).join("");
  select.value = value;
}

function bindCronGraphEvents() {
  $("#dailyCronRunDate")?.addEventListener("change", event => { dailyCronState.selectedDay = event.target.value; dailyCronState.selectedNode = ""; renderCronGraphDetails({ lanes: [] }, ""); renderDailyCron(); });
  document.querySelectorAll("[data-cron-help]").forEach(button => button.addEventListener("click", () => { void openCronGraphHelp(button.dataset.cronHelp); }));
  $("#dailyCronHelpClose")?.addEventListener("click", () => $("#dailyCronHelpDialog").close());
  $("#dailyCronHelpDialog")?.addEventListener("close", () => window.RACronGraph?.unmount($("#dailyCronHelpGraph")));
  $("#dailyCronFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); else void $("#dailyCronGraphWorkspace").requestFullscreen(); });
  $("#dailyCronExitFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); });
}
