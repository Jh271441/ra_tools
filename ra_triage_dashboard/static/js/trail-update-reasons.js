/* Reason comparisons and explicit selection share the existing Trail workflow. */
function trailReasonState(item = {}) {
  if (item.readonly && item.trail_detail && !["querying", "query_failed", "not_checked", "not_found"].includes(item.trail_detail.state)) {
    return item.trail_detail.trail_should_exclude === true ? "reconcile_excluded" : "reconcile_not_excluded";
  }
  return String(item.trail_detail?.state || item.trail_update_status || "not_checked");
}
function trailSelectedIssues() {
  if (!(state.trailUpdate.selectedIssues instanceof Set)) state.trailUpdate.selectedIssues = new Set();
  return state.trailUpdate.selectedIssues;
}
function trailReasonEligible(item) {
  if (item?.readonly || state.trailUpdate.view === "reconciliation") return false;
  const detail = item?.trail_detail || {};
  return (state.trailUpdate.selectionIntent || "reason_only") === "reason_only"
    ? detail.trail_should_exclude === true && detail.needs_reason_update === true
    : detail.needs_exclusion_update === true;
}
function trailSelectionReady(data) {
  const selected = trailSelectedIssues();
  const byId = new Map((data?.items || []).map(item => [item.issue_id, item]));
  return trailUpdateWriteReady(data) && selected.size > 0 && selected.size <= 200
    && [...selected].every(id => byId.has(id) && trailReasonEligible(byId.get(id)));
}
function trailSelectionCheckbox(item) {
  if (item.readonly || state.trailUpdate.view === "reconciliation") return "";
  const id = String(item.issue_id || "");
  return `<label class="trail-reason-check"><input type="checkbox" data-trail-reason-select="${escapeHtml(id)}" ${trailSelectedIssues().has(id) ? "checked" : ""} ${trailReasonEligible(item) ? "" : "disabled"} aria-label="${escapeHtml(uiText(`选择 ${id}`, `Select ${id}`))}"></label>`;
}
function trailReasonScopeSummary(items) {
  const excluded = items.filter(item => item.trail_detail?.trail_should_exclude === true).length;
  const pending = items.filter(item => item.trail_detail?.needs_exclusion_update === true).length;
  const changed = items.filter(item => trailReasonState(item) === "reason_changed").length;
  const missing = items.filter(item => trailReasonState(item) === "reason_missing").length;
  const unknown = items.length - excluded - pending;
  return `<p class="trail-reason-scope"><strong>${escapeHtml(uiText(`Trail 已排除 ${excluded} · 待排除 ${pending}`, `Trail excluded ${excluded} · awaiting exclusion ${pending}`))}</strong><small>${escapeHtml(uiText(`已排除中：理由待更新 ${changed}，待补充 ${missing}；无法确认 ${unknown}`, `Among excluded: ${changed} changed reasons, ${missing} missing reasons; ${unknown} unconfirmed`))}</small></p>`;
}
function trailReasonComparisonMarkup(item, expanded = false) {
  const detail = item.trail_detail || {};
  const source = item.reason_source || {};
  const local = String(detail.local_comment ?? item.comment ?? "");
  const remote = detail.trail_comment;
  const known = !["querying", "query_failed", "not_checked", "not_found", "pending"].includes(trailReasonState(item));
  const restored = source.kind === "historical_restore";
  const sourceLabel = item.readonly ? uiText("无本地排除理由", "No local exclusion reason") : restored ? uiText("历史理由恢复", "Restored historical reason")
    : source.kind === "case_label" ? uiText("Issue 标注", "Issue annotation") : uiText("模型复核（旧记录）", "Model review (legacy)");
  const originalTime = source.original_created_at || (!restored ? source.created_at : "");
  const meta = [sourceLabel, source.author || uiText("作者未知", "Unknown author"),
    originalTime ? formatTime(originalTime) : uiText("原始时间未知", "Original time unknown"),
    source.revision_id ? uiText(`版本 #${source.revision_id}`, `Revision #${source.revision_id}`) : "",
    restored && source.created_at ? uiText(`恢复时间 ${formatTime(source.created_at)}`, `Restored ${formatTime(source.created_at)}`) : ""].filter(Boolean).join(" · ");
  const remoteHint = known ? uiText("Trail 未填写理由", "No reason in Trail") : uiText("尚未确认，请刷新查询", "Unconfirmed; refresh to check");
  const localHint = uiText("未提供新理由，保留 Trail 原文", "No new reason; keep the Trail text");
  const markerLabel = ({true:uiText("Trail 已排除", "Excluded in Trail"), false:uiText("Trail 未排除（false）", "Not excluded in Trail (false)"), unset:uiText("Trail 排除标记未设置", "Trail exclusion is unset"), unknown:uiText("Trail 状态无法确认", "Trail state unconfirmed")})[trailRemoteState(item)];
  const panel = `<div class="trail-reason-comparison"><section><strong>${uiText("Trail 当前理由", "Current Trail reason")}</strong><p data-trail-reason-text="remote">${escapeHtml(remote || remoteHint)}</p><small>${escapeHtml(markerLabel)} · ${uiText("远端修改时间未知", "Remote modification time unknown")}</small>${remote ? `<button type="button" class="button button-quiet" data-trail-copy-reason="remote">${uiText("复制", "Copy")}</button>` : ""}</section><section><strong>${uiText("本地最新理由", "Latest local reason")}</strong><p data-trail-reason-text="local">${escapeHtml(local || localHint)}</p><small>${escapeHtml(meta)}</small>${local ? `<button type="button" class="button button-quiet" data-trail-copy-reason="local">${uiText("复制", "Copy")}</button>` : ""}</section></div>`;
  if (expanded) return panel + trailEvidenceMarkup(item);
  const open = Boolean(state.trailUpdate.expandedReasons?.has(trailRowKey(item)));
  return `<button class="button button-quiet trail-reason-toggle" type="button" data-trail-reason-toggle="${escapeHtml(trailRowKey(item))}" aria-expanded="${open}">${uiText("查看理由与来源", "Reasons and source")}</button>`;
}
function syncTrailSelectionControls(data = state.trailUpdate?.data) {
  const count = $("#trailReasonSelectionCount");
  const chosen = trailSelectedIssues();
  const visible = new Set([...document.querySelectorAll("#trailUpdateTableBody [data-trail-reason-select]")].map(node => node.dataset.trailReasonSelect));
  const hidden = [...chosen].filter(id => !visible.has(id)).length;
  if (count) count.textContent = uiText(`已选可提交 ${chosen.size} 条，其中 ${hidden} 条不在本页；筛选不改变选择`, `${chosen.size} selected for submission, ${hidden} outside this page; filters preserve selection`);
  const bar = document.querySelector(".trail-reason-selection-bar");
  if (bar) bar.hidden = state.trailUpdate.view === "reconciliation";
  const select = $("#trailReasonIntent");
  if (select) {
    select.value = state.trailUpdate.selectionIntent || "reason_only";
    for (const option of select.options) option.textContent = uiText(option.dataset.labelZh, option.dataset.labelEn);
    select.disabled = Boolean(state.trailUpdate.selectionBusy);
    enhanceNativeUiSelect(select);
  }
  $("#trailReasonClear")?.toggleAttribute("disabled", !chosen.size || Boolean(state.trailUpdate.selectionBusy));
  $("#trailReasonSelectVisible")?.toggleAttribute("disabled", Boolean(state.trailUpdate.selectionBusy) || !(data?.items || []).some(trailReasonEligible));
}
function patchTrailReasonCells(data) {
  const byId = new Map((data?.items || []).map(item => [trailRowKey(item), item]));
  document.querySelectorAll("[data-trail-reason-row]").forEach(row => {
    const item = byId.get(row.dataset.trailReasonRow);
    if (!item) return;
    const status = row.querySelector("[data-trail-update-status-issue]");
    if (status) status.innerHTML = trailUpdateStatusCellMarkup(trailReasonState(item));
    const check = row.querySelector("[data-trail-reason-select]");
    if (check) { check.disabled = !trailReasonEligible(item); check.checked = trailSelectedIssues().has(item.issue_id); }
    const summary = row.querySelector("[data-trail-reason-summary]");
    if (summary) summary.innerHTML = trailReasonSummaryMarkup(item);
    const toggle = row.querySelector("[data-trail-reason-toggle]");
    if (toggle) toggle.textContent = uiText("查看理由与来源", "Reasons and source");
    const expanded = document.querySelector(`[data-trail-reason-expansion="${CSS.escape(trailRowKey(item))}"] td`);
    if (expanded) {
      const markup = trailReasonComparisonMarkup(item, true);
      if (expanded.innerHTML !== markup) expanded.innerHTML = markup;
    }
  });
}
function reconcileTrailReasonRows(body, markup, preserveRows) {
  const old = new Map([...body.querySelectorAll("[data-trail-reason-row]")].map(row => [row.dataset.trailReasonRow, row]));
  const template = document.createElement("template");
  template.innerHTML = markup;
  const desired = [...template.content.children].map(row => {
    const existing = old.get(row.dataset.trailReasonRow);
    if (preserveRows && existing) return existing;
    if (existing?.querySelector("details")?.open && row.querySelector("details")) row.querySelector("details").open = true;
    return row;
  });
  const keep = new Set(desired);
  [...body.children].forEach(row => { if (!keep.has(row)) row.remove(); });
  desired.forEach((row, index) => { if (body.children[index] !== row) body.insertBefore(row, body.children[index] || null); });
}
function bindTrailReasonEvents() {
  $("#trailReasonIntent")?.addEventListener("change", event => {
    state.trailUpdate.selectionIntent = event.target.value;
    trailSelectedIssues().clear();
    patchTrailReasonCells(state.trailUpdate.data);
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
  $("#trailReasonClear")?.addEventListener("click", () => {
    trailSelectedIssues().clear(); patchTrailReasonCells(state.trailUpdate.data);
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
  $("#trailReasonSelectVisible")?.addEventListener("click", () => {
    document.querySelectorAll("#trailUpdateTableBody [data-trail-reason-select]:not(:disabled)").forEach(check => { trailSelectedIssues().add(check.dataset.trailReasonSelect); check.checked = true; });
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
  $("#trailUpdateTableBody")?.addEventListener("click", event => {
    const toggle = event.target.closest("[data-trail-reason-toggle]");
    if (!toggle) return;
    const id = toggle.dataset.trailReasonToggle;
    if (!(state.trailUpdate.expandedReasons instanceof Set)) state.trailUpdate.expandedReasons = new Set();
    const open = !state.trailUpdate.expandedReasons.has(id);
    if (open) state.trailUpdate.expandedReasons.add(id); else state.trailUpdate.expandedReasons.delete(id);
    toggle.setAttribute("aria-expanded", String(open));
    const row = document.querySelector(`[data-trail-reason-expansion="${CSS.escape(id)}"]`);
    if (row) row.hidden = !open;
  });
  $("#trailUpdateTableBody")?.addEventListener("change", event => {
    const check = event.target.closest("[data-trail-reason-select]");
    if (!check) return;
    if (check.checked) trailSelectedIssues().add(check.dataset.trailReasonSelect);
    else trailSelectedIssues().delete(check.dataset.trailReasonSelect);
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
  for (const root of [$("#trailUpdateTableBody"), $("#trailUpdateConfirmList")]) root?.addEventListener("click", event => {
    const button = event.target.closest("[data-trail-copy-reason]");
    if (!button) return;
    const text = button.closest("section")?.querySelector("[data-trail-reason-text]")?.textContent || "";
    navigator.clipboard.writeText(text).then(() => showToast(uiText("已复制理由", "Reason copied"))).catch(() => showToast(uiText("无法复制，请选择文本复制", "Could not copy; select the text to copy"), true));
  });
  syncTrailSelectionControls();
}

function refreshTrailReasonLanguage() {
  if (!state.trailUpdate?.data) return;
  renderTrailAttributePreview(state.trailUpdate.data);
  syncTrailSelectionControls();
}

function trailRowKey(item) { return item.row_key || `${item.baseline_id || ""}|${item.issue_id}`; }
function trailLocalState(item) { return item.local_selected === true ? "true" : item.local_selected === false ? "false" : "unknown"; }
function trailLocalLabel(item) {
  return ({true:uiText("已勾选排除", "Exclusion selected"), false:uiText("本地未勾选", "Not selected locally"), unknown:uiText("本地状态未知", "Local state unknown")})[trailLocalState(item)];
}
function trailRemoteState(item) {
  const detail = item.trail_detail;
  if (!detail || ["querying", "query_failed", "not_checked", "not_found"].includes(detail.state)) return "unknown";
  return detail.trail_should_exclude === true ? "true" : detail.trail_should_exclude === false ? "false" : "unset";
}
function trailSourceLabel(source) {
  return ({local:uiText("本地候选", "Local candidate"), historical:uiText("历史排除", "Historical exclusion"), both:uiText("两者都有", "Both")})[source] || source;
}
function trailReasonSummaryMarkup(item) {
  const detail = item.trail_detail || {};
  const remote = trailRemoteState(item) === "unknown" ? uiText("尚未确认", "Unconfirmed") : detail.trail_comment || uiText("理由未填写", "No reason provided");
  const local = detail.local_comment || item.comment || uiText("无新理由，保留远端原文", "No new reason; keep remote text");
  return `<div class="trail-reason-summary"><p><strong>${uiText("Trail 当前", "Current Trail")}</strong> ${escapeHtml(remote)}</p><p><strong>${uiText(item.readonly ? "本地理由" : "本地拟更新", item.readonly ? "Local reason" : "Proposed locally")}</strong> ${escapeHtml(local)}</p></div>`;
}
function trailEvidenceMarkup(item) {
  const source = item.historical_source;
  const evidence = item.local_evidence || {};
  const parts = [];
  if (source) parts.push(`<section><strong>${uiText("历史来源（仅检索依据）", "Historical source (search membership only)")}</strong><p>${escapeHtml(source.filename)} · ${escapeHtml(formatTime(source.captured_at))}</p><small>SHA-256: ${escapeHtml(source.sha256 || "—")}</small><small>${escapeHtml(source.snapshot_filename || "")} · SHA-256: ${escapeHtml(source.snapshot_sha256 || "—")}</small></section>`);
  const legacy = evidence.legacy_reviews || [];
  const migrated = evidence.migrated_revisions || [];
  const flag = value => value ? uiText("已勾选", "Selected") : uiText("未勾选", "Not selected");
  for (const row of legacy) parts.push(`<section><strong>${escapeHtml(uiText(`历史 Review #${row.id} · ${flag(row.is_excluded)}`, `Historical Review #${row.id} · ${flag(row.is_excluded)}`))}</strong><small>${escapeHtml(row.author || "")} · ${escapeHtml(formatTime(row.created_at))}</small><p>${uiText("历史 Review 备注（非排除理由）", "Historical Review note (not an exclusion reason)")}: ${escapeHtml(row.note || uiText("未填写", "Empty"))}</p></section>`);
  for (const row of migrated) parts.push(`<section><strong>${escapeHtml(uiText(`迁移版本 #${row.id} · ${flag(row.is_excluded)}`, `Migrated revision #${row.id} · ${flag(row.is_excluded)}`))}</strong><small>${escapeHtml(uiText(`原 Review #${row.source_annotation_id}`, `Original Review #${row.source_annotation_id}`))} · ${escapeHtml(formatTime(row.created_at))}</small></section>`);
  const paired = migrated.filter(row => legacy.some(old => old.id === row.source_annotation_id));
  const unchanged = paired.length > 0 && paired.every(row => legacy.find(old => old.id === row.source_annotation_id)?.is_excluded === row.is_excluded);
  if (item.readonly) parts.unshift(`<p class="trail-reconcile-note">${escapeHtml(uiText(
    `${unchanged ? "已匹配的原始与迁移记录中，没有发现迁移改变排除标记的证据。" : "原始与迁移记录需进一步核对。"}远端排除来源待核对，需要请求级证据和人工裁决；此处只读。`,
    `${unchanged ? "Matched original and migrated records show no evidence that migration changed exclusion." : "Original and migrated records need further reconciliation."} The remote exclusion source requires request-level evidence and human adjudication. This view is read-only.`))}</p>`);
  return parts.length ? `<div class="trail-reconcile-evidence">${parts.join("")}</div>` : "";
}
function renderTrailReconcileCoverage(data) {
  const target = $("#trailReconcileCoverage");
  if (!target) return;
  const items = data.items || [];
  const known = items.filter(item => trailRemoteState(item) !== "unknown").length;
  const queried = items.filter(item => item.trail_detail && item.trail_detail.state !== "querying").length;
  const scope = (data.baselines || []).join(", ") || selectedBaselineQueryValue();
  const localCount = data.local_candidate_count ?? items.filter(item => !item.readonly).length;
  const lines = [uiText(`数据集 ${scope} · 本地候选 ${localCount}`, `Datasets ${scope} · ${localCount} local candidates`)];
  if (data.reconciliation) {
    const historical = items.filter(item => item.historical_source);
    const historicalExcluded = historical.filter(item => trailRemoteState(item) === "true").length;
    const mismatches = items.filter(item => item.readonly && trailRemoteState(item) === "true").length;
    lines.push(uiText(`历史覆盖 ${historical.length}（当前已排除 ${historicalExcluded}）· 去重总数 ${items.length} · 只读待核对 ${mismatches}`, `Historical coverage ${historical.length} (${historicalExcluded} currently excluded) · ${items.length} unique cases · ${mismatches} read-only differences`));
    const sources = data.historical_sources || [];
    lines.push(sources.some(s => s.available) ? uiText("基于来源快照检索，不是完整数据集的实时扫描", "Snapshot-based membership, not a live scan of the full dataset") : uiText("历史来源未加载；当前仅展示本地候选，可刷新重试", "Historical source unavailable; showing local candidates only. Refresh to retry"));
    for (const source of sources.filter(s => s.available)) lines.push(uiText(`历史快照 ${source.baseline_id} · ${formatTime(source.captured_at)}`, `Historical snapshot ${source.baseline_id} · ${formatTime(source.captured_at)}`));
  }
  lines.push(uiText(`已确认 ${known} / 已查询 ${queried} / 共 ${items.length} · 最近核验 ${data.checked_at ? formatTime(data.checked_at) : "尚未完成"}`, `Confirmed ${known} / queried ${queried} / total ${items.length} · checked ${data.checked_at ? formatTime(data.checked_at) : "not yet completed"}`));
  target.textContent = lines.join("\n");
}
function syncTrailReconcileFilters() {
  const values = {trailReconcileView:state.trailUpdate.view || "local", trailReconcileSource:state.trailUpdate.filters.sourceKind || "", trailReconcileLocal:state.trailUpdate.filters.localState || "", trailReconcileRemote:state.trailUpdate.filters.remoteState || ""};
  for (const [id,value] of Object.entries(values)) {
    const select = $(`#${id}`);
    if (!select) continue;
    select.value = value;
    for (const option of select.options) option.textContent = uiText(option.dataset.zh, option.dataset.en);
    enhanceNativeUiSelect(select);
  }
}
function bindTrailReconcileEvents() {
  $("#trailReconcileView")?.addEventListener("change", event => {
    state.trailUpdate.view = event.target.value;
    state.trailUpdate.page = 1;
    trailSelectedIssues().clear();
    trailUpdatePersistRoute();
    loadTrailAttributePreview(true).catch(error => showToast(error.message, true));
  });
  for (const [id,key] of [["trailReconcileSource","sourceKind"],["trailReconcileLocal","localState"],["trailReconcileRemote","remoteState"]]) {
    $(`#${id}`)?.addEventListener("change", event => { state.trailUpdate.filters[key] = event.target.value; applyTrailUpdateFilters(); });
  }
  syncTrailReconcileFilters();
}
