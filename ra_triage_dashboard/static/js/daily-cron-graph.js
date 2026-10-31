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

function cronApplyThirdMedia(nodes, media, stale) {
  const closeup = media?.closeup;
  const known = closeup?.receipt_status === 'ready';
  const complete = known && media.selected > 0 && closeup.verified === media.selected;
  const status = complete ? 'success' : !known ? 'unknown' : closeup.attention ? 'warn' : 'pending';
  const progress = cronTaskProgress(closeup?.verified, media?.selected, {
    stale: Boolean(stale), empty: media?.selected === 0,
    label: uiText('同批目标的局部 BEV 发布验收', 'Closeup BEV publication receipts for the same cohort'),
  });
  nodes.push({id:'media-closeup',data:{
    label:uiText('局部 BEV · Orion', 'Closeup BEV · Orion'), detail:uiText('40秒 · 400帧 · t0=20秒', '40s · 400 frames · t0=20s'),
    status:stale?'unknown':status,
    stateLabel:stale?cronGraphStateLabel('unknown'):closeup?.attention?uiText('待排查 / 验收', 'Needs review / verification'):cronGraphStateLabel(status), progress,
    timingText:uiText('独立验收 / 发布', 'Verify / Publish independently'),
    issues:closeup?.attention_ids || [],
    rows:[...cronTaskProgressRows(progress),
      [uiText('待队列处理', 'Queued'),cronCount(closeup?.queued)],
      [uiText('待排查 / 验收', 'Needs review / verification'),cronCount(closeup?.attention)],
      [uiText('身份或范围待核实', 'Identity / scope unconfirmed'),cronCount(closeup?.unknown)],
      [uiText('恢复路径', 'Recovery path'),uiText('失败子集 Orion 重试1次 → 仍失败则本地最多2次 → 验收发布', 'Failed subset: one Orion retry → Still failed: up to two local attempts → Verify / Publish')],
      [uiText('计数包含', 'Counts include'),uiText('Orion 与本地恢复后的有效发布回执', 'Valid publications from Orion and local recovery')],
      [uiText('发布条件', 'Publication gate'),uiText('同 Issue / trip / 锚点 / 配方；完整时序与解码验收', 'Same Issue / trip / anchor / recipe; full timing and decode validation')],
      [uiText('队列口径', 'Queue scope'),uiText('历史 running 不作为正在录制的证据', 'Historical running entries do not prove active recording')]],
  }});
  const retry = closeup?.retry;
  const retryStatus = stale ? 'unknown' : retry?.status === 'completed' ? 'success'
    : retry?.status === 'partial_failed' ? 'warn' : 'unknown';
  const retryProgress = cronTaskProgress(retry?.processed, retry?.total, {stale:Boolean(stale),
    failed:retry?.failed, label:uiText('局部 BEV 的 Orion 重试子集（含失败）', 'Closeup BEV Orion retry subset, including failures')});
  nodes.push({id:'media-closeup-retry',data:{
    label:uiText('局部 Orion 重试', 'Closeup Orion retry'),
    detail:uiText('仅失败子集 · 1次', 'Failed subset only · Once'),
    status:retryStatus,stateLabel:cronGraphStateLabel(retryStatus),progress:retryProgress,
    timingText:uiText('与 BEV 相同策略', 'Same policy as BEV'),issues:[],
    rows:[...cronTaskProgressRows(retryProgress),
      [uiText('重试次数上限', 'Retry limit'),uiText('Orion 重试1次', 'One Orion retry')],
      [uiText('原生完成 / 失败', 'Native completed / failed'),cronFraction(retry?.completed,retry?.failed)],
      [uiText('重试证据 · CST', 'Retry evidence · CST'),cronTime(retry?.evidence_at)],
      [uiText('后续恢复', 'Next recovery'),uiText('重试终态仍失败或验收不通过 → 本地兜底', 'Retry ends with failure or invalid output → Local fallback')],
      [uiText('计数口径', 'Count scope'),uiText('仅本批、同身份的第二次 Orion 尝试；原生完成不等于发布', 'Same-cohort, same-identity second Orion attempt only; native completion is not publication')],
    ],
  }});
  const fallback = closeup?.fallback;
  const recovered = fallback?.verified;
  const fallbackStatus = stale ? 'unknown' : fallback?.source_blocked > 0 ? 'warn'
    : recovered > 0 ? 'success' : 'unknown';
  nodes.push({id:'media-closeup-local',data:{
    label:uiText('局部本地兜底', 'Closeup fallback'),
    detail:uiText('全局2并发 · 最多2次', 'Global concurrency 2 · Up to 2 attempts'),
    status:fallbackStatus, stateLabel:stale?cronGraphStateLabel('unknown')
      :fallback?.source_blocked > 0?uiText('源异常待处理', 'Source failures pending')
      :recovered > 0?uiText('本地恢复已发布', 'Local recovery published'):cronGraphStateLabel(fallbackStatus),
    timingText:uiText('与 BEV 相同策略', 'Same policy as BEV'),
    issues:fallback?.source_blocked_ids || [],
    rows:[
      [uiText('本地恢复发布', 'Published via local recovery'),cronCount(recovered)],
      [uiText('已有执行证据的案例', 'Cases with execution evidence'),cronCount(fallback?.attempted_cases)],
      [uiText('已登记恢复子集', 'Registered recovery subset'),cronCount(fallback?.registered)],
      [uiText('源异常 / 缺口', 'Source errors / gaps'),cronCount(fallback?.source_blocked)],
      [uiText('回执时间 · CST', 'Evidence time · CST'),cronTime(fallback?.evidence_at)],
      [uiText('触发条件', 'Trigger'),uiText('Orion 重试终态仍失败或验收不通过', 'Orion retry ends with failure or invalid output')],
      [uiText('尝试预算', 'Attempt budget'),uiText('本地最多2次；与原 BEV 共享全局2个名额', 'At most 2 local attempts; share 2 global slots with original BEV')],
      [uiText('局部布局', 'Closeup layout'),'layout.json · ego30-forward4-1080p-10fps-v1'],
      [uiText('源异常处理', 'Source failure handling'),uiText('保留证据待处理；不反复盲重试', 'Retain evidence for resolution; no blind retries')],
      [uiText('发布条件', 'Publication gate'),uiText('同一局部配方、400帧、精确时序和完整解码验收', 'Same closeup recipe, 400 frames, exact timing and full decode validation')],
    ],
  }});
  // The mobile view reads this same array in order; recovery precedes verification.
  const closeupNodes = nodes.splice(-3);
  const verificationIndex = nodes.findIndex(n=>n.id==='media-verify');
  nodes.splice(verificationIndex < 0 ? nodes.length : verificationIndex, 0, ...closeupNodes);
  const all = media?.selected > 0 && media?.triple_verified === media?.selected;
  for (const n of nodes.filter(n=>['media-verify','media-ready'].includes(n.id))) {
    if(n.id==='media-verify')n.data.label=uiText('三媒体验证', 'Verify three videos');
    n.data.detail=cronFraction(media?.triple_verified,media?.selected);
    n.data.progress=cronTaskProgress(media?.triple_verified,media?.selected,{stale:Boolean(stale),empty:media?.selected===0,
      label:uiText('同批 Camera ∩ BEV ∩ 局部 BEV', 'Same cohort: Camera ∩ BEV ∩ Closeup BEV')});
    n.data.rows=[...cronTaskProgressRows(n.data.progress),
      [uiText('原双媒体已验证', 'Original two videos verified'),cronFraction(media?.verified,media?.selected)],
      [uiText('分别发布', 'Independent publication'),uiText('各项验收后即发布；不等待三项齐全', 'Each verified track publishes without waiting for the others')],
      [uiText('Camera 清理', 'Camera cleanup'),uiText('沿用原发布回执与1小时策略', 'Existing publication receipt and 1h policy')],
      [uiText('统计口径', 'Count scope'),uiText('同批目标的发布回执交集；不计原生 completed', 'Intersection of publication receipts in this cohort; native completed is excluded')]];
    if(!all)n.data.status=!known?'unknown':closeup.attention||media?.failure_count?'warn':'pending';
    else if(n.id==='media-verify')n.data.status='success';
    if(stale)n.data.status='unknown';
    n.data.stateLabel=cronGraphStateLabel(n.data.status);
    if(n.id==='media-verify' && known && !all && !stale)n.data.stateLabel=uiText('待补齐', 'Incomplete');
    if(n.id==='media-ready') {
      n.data.status='unknown';
      n.data.stateLabel=uiText('按单项回执发布', 'Per-track publication');
    }
  }
}

// Both the live and definition graphs use the same real recovery branch.
function cronCloseupEdges() {
  return [
    {id:'media-import:media-closeup',source:'media-import',target:'media-closeup'},
    ...cronBevRecoveryEdges('media-closeup','media-closeup-retry','media-closeup-local'),
  ];
}

// Original and closeup BEV use exactly the same recovery topology.
function cronBevRecoveryEdges(source, retry, local) {
  const edge=(a,b,label='',optional=false)=>({id:a+':'+b,source:a,target:b,label,optional});
  return [edge(source,'media-verify'),edge(source,retry,uiText('失败','Failed'),true),
    edge(retry,'media-verify',uiText('成功','Success'),true),
    edge(retry,local,uiText('仍失败','Still failed'),true),
    edge(local,'media-verify','',true)];
}

function buildDailyCronGraph(data, definitionLane = "") {
  if (cronIncrementalEnabled(data) && !dailyCronState.selectedDay) return buildIncrementalCronGraph(cronSelectedIncremental(data), definitionLane);
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
  cronApplyThirdMedia(mediaNodes, media, mediaStale);
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
    if (['media-closeup', 'media-closeup-retry', 'media-closeup-local', 'media-verify', 'media-ready'].includes(n.id)) continue;
    n.data.timing = n.id === "media-ready" ? media?.timing : media?.stage_timings?.[n.id];
    n.data.timingText = cronTimingText(n.data.timing, { compact: true, stale: mediaStale });
    n.data.rows.push(...cronTimingRows(n.data.timing, { stale: mediaStale }));
  }
  const edge = (source, target, label = "", optional = false) => ({ id: `${source}:${target}`, source, target, label, optional });
  const mainEdges = mainNodes.slice(1).map((n, i) => edge(mainNodes[i].id, n.id));
  const mediaEdges = [...cronCloseupEdges(), edge("media-source", "media-import"), edge("media-import", "media-camera"), edge("media-import", "media-orion"), edge("media-camera", "media-verify"), ...cronBevRecoveryEdges("media-orion", "media-retry", "media-local"), edge("media-verify", "media-ready")];
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
    const help = $("#dailyCronHelpDialog");
    if (help?.open) void openCronGraphHelp(help.dataset.lane);
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
  dialog.dataset.lane = lane;
  $("#dailyCronHelpTitle").textContent = lane === "main" ? uiText("推理回刷 · 流程说明", "Daily inference · Definition") : uiText("平台与媒体 · 流程说明", "Media sidecar · Definition");
  $("#dailyCronHelpNote").textContent = lane === "main" ? uiText("09:00 CST，处理 T−2；周末照常查询。少量采集缺失 ≤5 且 ≤2% 可继续并记录，超限阻塞。空数据正常结束。", "09:00 CST, T−2 data; weekends queried normally. Acquisition gaps ≤5 AND ≤2% may continue with records; larger gaps block. Empty data completes normally.") : uiText("同批目标生成 Camera、BEV、局部 BEV，分别验收发布，三项交集计为齐全。两种 BEV 均先 Orion 重试1次，仍失败或验收不通过则本地最多2次，共享全局2个本地名额。源异常保留待查。Camera 清理沿用原发布回执与1小时策略。", "Camera, BEV and closeup BEV share the target cohort and publish independently. Complete coverage is their intersection. Both BEV tracks retry Orion once, then use up to two local attempts for failures or invalid output, sharing two global local slots. Source failures retain evidence. Camera cleanup keeps its existing publication receipt and 1h policy.");
  if (dailyCronState.data?.incremental?.enabled && lane === "main") $("#dailyCronHelpNote").textContent = uiText("每天07:00、19:00 CST按版本全量发现和补查；队列4并发全量处理，固定版本级10%概率抽样。缺源独立等待，每轮增量分开记录。", "Version discovery and source checks at07:00/19:00 CST; four workers process all eligible queued cases with stable10% probability sampling. Missing sources wait independently; increments are recorded per round.");
  if (!dialog.open) dialog.showModal();
  const graph = await ensureCronGraphLibrary();
  if (dialog.open) graph.render($("#dailyCronHelpGraph"), buildDailyCronGraph(dailyCronState.data, lane));
}

function renderCronRunSelector() {
  const select = $("#dailyCronRunDate");
  if (!select) return;
  const runs = (dailyCronState.data?.overview?.daily?.runs || []).filter(run => /^daily-\d{4}-\d{2}-\d{2}$/.test(run.id));
  const incremental = dailyCronState.data?.incremental?.enabled ? dailyCronState.data.incremental : { enabled: Boolean(dailyCronState.selectedVersion) };
  const families = cronVersionFamilies(incremental);
  const family = dailyCronState.selectedVersion;
  // Keep a temporarily missing selected version visible, with unknown counts, rather than switching scope.
  if (/^\d{8}$/.test(family) && !families.includes(family)) families.push(family);
  const value = dailyCronState.selectedDay || (incremental?.enabled ? family === 'all' ? 'all' : `version:${family}` : '');
  const options = incremental?.enabled
    ? families.map(f => `<option value="version:${f}">${escapeHtml(uiText('版本', 'Version'))} ${f.slice(4)} · ${f.slice(0,4)}</option>`).join('') + `<option value="all">${escapeHtml(uiText('全部版本汇总', 'All versions'))}</option>`
    : `<option value="">${escapeHtml([uiText('最新运行', 'Latest run'), runs[0]?.target_date_cst].filter(Boolean).join(' · '))}</option>`;
  const markup = options + runs.map(run => {
    const status = ["partial", "complete_with_gaps"].includes(run.health) ? uiText("已完成（有缺失）", "Complete with gaps") : cronLabel(run.health);
    return `<option value="${escapeHtml(run.target_date_cst)}">${escapeHtml(uiText('旧日期批次', 'Legacy daily run'))} · ${escapeHtml(run.target_date_cst)} · ${escapeHtml(status)}</option>`;
  }).join("");
  if (select.innerHTML !== markup) select.innerHTML = markup;
  select.value = value;
  select.setAttribute('aria-label', uiText('选择版本或旧日期批次', 'Select version or legacy daily run'));
  const picker = enhanceNativeUiSelect(select);
  picker?.querySelector(".ui-select-trigger")?.setAttribute("aria-label", uiText('选择版本或旧日期批次', 'Select version or legacy daily run'));
}

function bindCronGraphEvents() {
  $("#dailyCronRunDate")?.addEventListener("change", event => {
    const value = event.target.value;
    dailyCronState.selectedDay = /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : '';
    if (value === 'all' || /^version:\d{8}$/.test(value)) dailyCronState.selectedVersion = value.replace('version:', '');
    dailyCronState.selectedNode = "";
    const url = new URL(window.location.href); writeCronScope(url);
    window.history.replaceState(window.history.state, '', url);
    renderCronGraphDetails({ lanes: [] }, ""); renderDailyCron();
  });
  document.querySelectorAll("[data-cron-help]").forEach(button => button.addEventListener("click", () => { void openCronGraphHelp(button.dataset.cronHelp); }));
  $("#dailyCronHelpClose")?.addEventListener("click", () => $("#dailyCronHelpDialog").close());
  $("#dailyCronHelpDialog")?.addEventListener("close", () => window.RACronGraph?.unmount($("#dailyCronHelpGraph")));
  $("#dailyCronFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); else void $("#dailyCronGraphWorkspace").requestFullscreen(); });
  $("#dailyCronExitFullscreen")?.addEventListener("click", () => { if (document.fullscreenElement) void document.exitFullscreen(); });
}


function buildIncrementalCronGraph(v,definitionLane='') {
  const c=v.states||{},m=v.media||{},active=!v.stale;
  const done=(c.inferred||0)+(c.published||0);
  const pending=(c.ready||0)+(c.running||0)+(c.retry_wait||0);
  const attention=(c.needs_attention||0)+(c.identity_conflict||0);
  const total=done+pending+attention;
  const continuing=pending>0||attention>0||(c.inferred||0)>0;
  const admitted=(v.datasets||[]).reduce((n,d)=>n+(d.targets||0),0);
  const assigned=(v.datasets||[]).reduce((n,d)=>n+Object.values(d.assigned||{}).reduce((a,b)=>a+b,0),0);
  const node=(id,label,detail,status,stateLabel,rows=[])=>({id,data:{label,detail,status:active?status:'unknown',stateLabel:active?stateLabel:uiText('观测过期','Stale observation'),rows,issues:[]}});
  const rolling=uiText('分批持续处理','Streaming per case');
  const nodes=[
    node('main-schedule',uiText('增量发现','Discover'),'07:00 / 19:00 CST','success',uiText('周期调度','Scheduled polling')),
    node('main-query',uiText('版本分流','Route by version'),(v.families||[]).map(x=>x.slice(4)).join(' / '),'success',uiText('独立归集','Separate worksets')),
    node('main-wait',uiText('等待源信息','Await source'),String(c.waiting_metadata||0),'pending',uiText('不阻塞其他 case','Other cases continue')),
    node('main-verify',uiText('版本统一抽样','Version sampling'),uiText('固定种子 · 每 case 约10%','Frozen seed · 10% probability per case'),'success',uiText('固定策略','Frozen policy')),
    node('main-infer',uiText('采集与推理','Collect / Infer'),`${done} / ${total}`,attention?'warn':pending?'running':'success',pending?uiText('仍有待处理','Cases still pending'):uiText('当前已处理','Current cases processed'),[[uiText('已推理','Inferred'),done],[uiText('待推理 / 重试','Queued / Retry'),pending],[uiText('待核实','Needs attention'),attention]]),
    node('main-publish',uiText('Trail 回刷','Trail publication'),`${c.published||0} / ${done}`,continuing?'running':'success',continuing?uiText('已完成结果持续回刷','Streaming finished results'):uiText('已有结果已回刷','Existing results published'),[[uiText('已完成推理','Finished inference'),done],[uiText('已回刷','Published'),c.published||0],[uiText('依赖范围','Dependency scope'),uiText('每个 case 完成后推进，不等待整批','Each completed case advances independently')]])
  ];
  nodes[4].data.progress=cronTaskProgress(done,total,{stale:!active,label:uiText('当前准入队列','Current admitted queue')});
  nodes[5].data.progress=cronTaskProgress(c.published||0,done,{stale:!active,label:uiText('已完成推理的结果','Finished inference results')});
  const mediaPending=(m.verified||0)<(m.selected||0);
  const media=[
    node('media-source',uiText('低置信＋抽样','Low confidence + sample'),String(m.selected||0),continuing?'running':'success',continuing?uiText('持续纳入','Continuing admissions'):uiText('当前目标','Current targets')),
    node('media-import',uiText('统一 Run 与数据集','Unified Run / Dataset'),`${assigned} / ${admitted}`,assigned<admitted||continuing?'running':'success',continuing?uiText('分批导入与分配','Incremental import / assignment'):uiText('当前成员已分配','Current members assigned')),
    node('media-camera','Camera',uiText('全局4并发','Global concurrency4'),mediaPending?'running':'success',mediaPending?rolling:uiText('当前媒体已验证','Current media verified')),
    node('media-orion','Orion BEV',uiText('全局≤1000并发','Global concurrency ≤1000'),mediaPending?'running':'success',mediaPending?rolling:uiText('当前媒体已验证','Current media verified')),
    node('media-retry',uiText('Orion 重试','Orion retry'),uiText('仅失败子集 · 1次','Failed subset only · Once'),'unknown',uiText('按单项回执判定','Requires attempt receipts')),
    node('media-local',uiText('本地兜底','Local fallback'),uiText('全局2并发 · 最多2次','Global concurrency2 · Up to2 attempts'),'unknown',uiText('按单项回执判定','Requires attempt receipts')),
    node('media-verify',uiText('双媒体验证','Dual media verification'),`${m.verified||0} / ${m.selected||0}`,m.failure_count?'warn':mediaPending?'running':'success',mediaPending?uiText('逐条验证中','Verifying per case'):uiText('当前目标已验证','Current targets verified')),
    node('media-ready',uiText('逐条发布 / 清理','Publish / Clean per case'),uiText(`累计验证 ${m.verified||0} · 满1小时后清理`,`Verified so far ${m.verified||0} · Cleanup after1h`),mediaPending||continuing?'running':'unknown',mediaPending||continuing?rolling:uiText('清理回执未观测','Cleanup receipt not observed'),[[uiText('判定范围','Scope'),uiText('已验证 case 可先发布；清理独立记录','Verified cases publish first; cleanup has separate receipts')]])
  ];
  media[6].data.progress=cronTaskProgress(m.verified||0,m.selected||0,{stale:!active,label:uiText('当前媒体目标','Current media targets')});
  cronApplyThirdMedia(media, m, !active);
  for (const [id, count] of [['media-camera', m.camera_verified], ['media-orion', m.bev_verified]]) {
    const n=media.find(n=>n.id===id);
    n.data.progress=cronTaskProgress(count,m.selected,{stale:!active,label:uiText('同批发布验收（双媒体回执确认的覆盖）','Same-cohort publication coverage confirmed by paired receipts')});
    n.data.detail=cronFraction(count,m.selected);
    n.data.status=!active||count==null?'unknown':count===m.selected&&m.selected>0?'success':'pending';
    n.data.stateLabel=cronGraphStateLabel(n.data.status);
  }
  if (v.statesUnavailable || v.unavailable) {
    for (const n of nodes.filter(n => ['main-wait','main-infer','main-publish'].includes(n.id))) {
      n.data.status='unknown'; n.data.stateLabel=uiText('状态暂不可用','Status unavailable');
      n.data.detail='—'; n.data.rows=[];
      n.data.progress=cronTaskProgress(null,null,{label:uiText('所选版本队列','Selected version queue')});
    }
  }
  if (v.unavailable) for (const n of media) {
    n.data.status='unknown'; n.data.stateLabel=uiText('状态暂不可用','Status unavailable');
    n.data.detail='—'; n.data.rows=[]; n.data.progress=null;
  }
  const edge=(a,b,optional=false)=>({id:a+':'+b,source:a,target:b,optional});
  let lanes=[{id:'main-lane',label:uiText('按版本增量处理','Version incremental processing'),nodes},{id:'media-lane',label:uiText('平台与独立媒体','Platform and independent media'),nodes:media}];
  let edges=[edge('main-schedule','main-query'),edge('main-query','main-wait',true),edge('main-wait','main-verify',true),edge('main-query','main-verify'),edge('main-verify','main-infer'),edge('main-infer','main-publish'),edge('main-infer','media-source',true),edge('media-source','media-import'),...cronCloseupEdges(),edge('media-import','media-camera'),edge('media-import','media-orion'),edge('media-camera','media-verify'),...cronBevRecoveryEdges('media-orion','media-retry','media-local'),edge('media-verify','media-ready')];
  if(definitionLane){lanes=lanes.filter(x=>x.id===definitionLane+'-lane');const ids=new Set(lanes.flatMap(x=>x.nodes.map(n=>n.id)));edges=edges.filter(x=>ids.has(x.source)&&ids.has(x.target));lanes.forEach(l=>l.nodes.forEach(n=>{n.data.status='definition';n.data.stateLabel=cronGraphStateLabel('definition');n.data.progress=null;}));}
  return {lanes,edges,selectedNode:dailyCronState.selectedNode||'',definition:Boolean(definitionLane),active,theme:state.colorTheme||'dark',ui:{minimap:uiText('流程缩略图','Workflow minimap'),loading:uiText('加载运行图…','Loading graph…'),error:uiText('运行图暂不可用','Graph unavailable')}};
}
