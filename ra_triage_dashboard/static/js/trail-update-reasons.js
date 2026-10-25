/* Reason comparisons and explicit selection share the existing Trail workflow. */
function trailReasonState(item = {}) {
  if (item.readonly && item.trail_detail && !["querying", "query_failed", "not_checked", "not_found", "pending"].includes(item.trail_detail.state)) {
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
  const eligible = trailReasonEligible(item);
  const hint = eligible ? uiText("可加入本次更新", "Eligible for this update") : trailUpdateStatusMeta(trailReasonState(item)).detail;
  return `<label class="trail-reason-check" title="${escapeHtml(hint)}" ${state.trailUpdate.selectionMode ? "" : "hidden"}><input type="checkbox" data-trail-reason-select="${escapeHtml(id)}" ${trailSelectedIssues().has(id) ? "checked" : ""} ${eligible ? "" : "disabled"} aria-label="${escapeHtml(uiText(`选择 ${id}`, `Select ${id}`))}"></label>`;
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
  const restored = ["historical_restore", "legacy_exclusion_note"].includes(source.kind);
  const sourceLabel = item.readonly ? uiText("无本地排除理由", "No local exclusion reason") : source.kind === "legacy_exclusion_note" ? uiText("迁移前排除备注", "Original exclusion note") : restored ? uiText("历史理由恢复", "Restored historical reason")
    : source.kind === "case_label" ? uiText("Issue 标注", "Issue annotation") : uiText("模型复核（旧记录）", "Model review (legacy)");
  const originalTime = source.original_created_at || (!restored ? source.created_at : "");
  const meta = [sourceLabel, source.author || uiText("作者未知", "Unknown author"),
    originalTime ? formatTime(originalTime) : uiText("原始时间未知", "Original time unknown"),
    source.source_annotation_id ? uiText(`原 Review #${source.source_annotation_id}`, `Original Review #${source.source_annotation_id}`) : "",
    source.revision_id ? uiText(`版本 #${source.revision_id}`, `Revision #${source.revision_id}`) : "",
    source.kind === "historical_restore" && source.created_at ? uiText(`恢复时间 ${formatTime(source.created_at)}`, `Restored ${formatTime(source.created_at)}`) : ""].filter(Boolean).join(" · ");
  const remoteHint = known ? uiText("Trail 未填写理由", "No reason in Trail") : uiText("尚未确认，请刷新查询", "Unconfirmed; refresh to check");
  const localHint = uiText("本地理由待补充；保留 Trail 原文", "Local reason needed; the Trail text is preserved");
  const markerLabel = ({true:uiText("Trail 已排除", "Excluded in Trail"), false:uiText("Trail 未排除（false）", "Not excluded in Trail (false)"), unset:uiText("Trail 排除标记未设置", "Trail exclusion is unset"), unknown:uiText("Trail 状态无法确认", "Trail state unconfirmed")})[trailRemoteState(item)];
  const panel = `<div class="trail-reason-comparison"><section><strong>${uiText("Trail 当前理由", "Current Trail reason")}</strong><p data-trail-reason-text="remote">${escapeHtml(remote || remoteHint)}</p><small>${escapeHtml(markerLabel)} · ${uiText("远端修改时间未知", "Remote modification time unknown")}</small>${remote ? `<button type="button" class="button button-quiet" data-trail-copy-reason="remote">${uiText("复制", "Copy")}</button>` : ""}</section><section><strong>${uiText("本地最新理由", "Latest local reason")}</strong><p data-trail-reason-text="local">${escapeHtml(local || localHint)}</p><small>${escapeHtml(meta)}</small>${local ? `<button type="button" class="button button-quiet" data-trail-copy-reason="local">${uiText("复制", "Copy")}</button>` : ""}</section></div>`;
  if (expanded) return panel + trailEvidenceMarkup(item);
  const open = Boolean(state.trailUpdate.expandedReasons?.has(trailRowKey(item)));
  return `<button class="text-link trail-reason-toggle" type="button" data-trail-reason-toggle="${escapeHtml(trailRowKey(item))}" aria-haspopup="dialog">${uiText("详情", "Details")}</button>`;
}
function trailSelectionPageStats(data = state.trailUpdate?.data) {
  const items = trailUpdateFilteredItems(data);
  const size = Number(state.trailUpdate.pageSize) || DEFAULT_CASE_PAGE_SIZE;
  const start = (Math.max(1, Number(state.trailUpdate.page) || 1) - 1) * size;
  const pageItems = items.slice(start, start + size);
  return {
    visible: new Set(pageItems.map(item => item.issue_id)),
    eligible: new Set(pageItems.filter(trailReasonEligible).map(item => item.issue_id)),
    reasonNeeded: pageItems.filter(item => trailStatusGroup(trailReasonState(item)) === "reason_needed").length,
  };
}
function syncTrailSelectionControls(data = state.trailUpdate?.data) {
  const count = $("#trailReasonSelectionCount");
  const chosen = trailSelectedIssues();
  const { visible, eligible, reasonNeeded } = trailSelectionPageStats(data);
  const hidden = [...chosen].filter(id => !visible.has(id)).length;
  const byId = new Map((data?.items || []).map(item => [item.issue_id, item]));
  const invalid = [...chosen].filter(id => !byId.has(id) || !trailReasonEligible(byId.get(id))).length;
  if (count) count.textContent = [
    uiText(`已选 ${chosen.size} 条`, `${chosen.size} selected`),
    hidden ? uiText(`${hidden} 条不在本页`, `${hidden} outside this page`) : "",
    invalid ? uiText(`${invalid} 条已不可更新，请清空后重选`, `${invalid} no longer eligible; clear and reselect`) : "",
    reasonNeeded ? uiText(`本页 ${reasonNeeded} 条需先补充本地理由`, `${reasonNeeded} on this page need a local reason first`) : "",
  ].filter(Boolean).join(" · ");
  const bar = document.querySelector(".trail-reason-selection-bar");
  const selecting = Boolean(state.trailUpdate.selectionMode) && state.trailUpdate.view !== "reconciliation";
  if (bar) bar.hidden = !selecting;
  document.querySelectorAll("#trailUpdateTableBody .trail-reason-check").forEach(label => { label.hidden = !selecting; });
  const toggle = $("#trailReasonBatchToggle");
  if (toggle) {
    toggle.hidden = state.trailUpdate.view === "reconciliation";
    toggle.disabled = Boolean(state.trailUpdate.selectionBusy);
    toggle.textContent = selecting ? uiText("完成选择", "Done selecting") : uiText("批量更新", "Batch update");
    toggle.setAttribute("aria-expanded", String(selecting));
  }
  const select = $("#trailReasonIntent");
  if (select) {
    select.value = state.trailUpdate.selectionIntent || "reason_only";
    for (const option of select.options) option.textContent = uiText(option.dataset.labelZh, option.dataset.labelEn);
    select.disabled = Boolean(state.trailUpdate.selectionBusy);
    enhanceNativeUiSelect(select);
  }
  $("#trailReasonClear")?.toggleAttribute("disabled", !chosen.size || Boolean(state.trailUpdate.selectionBusy));
  const selectVisible = $("#trailReasonSelectVisible");
  if (selectVisible) {
    selectVisible.textContent = uiText(`选择本页可更新项（${eligible.size}）`, `Select eligible on page (${eligible.size})`);
    selectVisible.toggleAttribute("disabled", Boolean(state.trailUpdate.selectionBusy) || !eligible.size);
  }
}
function patchTrailReasonCells(data) {
  refreshTrailReasonDetails();
  const byId = new Map((data?.items || []).map(item => [trailRowKey(item), item]));
  document.querySelectorAll("[data-trail-reason-row]").forEach(row => {
    const item = byId.get(row.dataset.trailReasonRow);
    if (!item) return;
    const status = row.querySelector("[data-trail-update-status-issue]");
    if (status) status.innerHTML = trailUpdateStatusCellMarkup(trailReasonState(item));
    const check = row.querySelector("[data-trail-reason-select]");
    if (check) { check.disabled = !trailReasonEligible(item); check.checked = trailSelectedIssues().has(item.issue_id);
      check.closest("label").title = trailReasonEligible(item) ? uiText("可加入本次更新", "Eligible for this update") : trailUpdateStatusMeta(trailReasonState(item)).detail;
    }
    const summary = row.querySelector("[data-trail-reason-summary]");
    if (summary) summary.innerHTML = trailReasonSummaryMarkup(item);
    const toggle = row.querySelector("[data-trail-reason-toggle]");
    if (toggle) toggle.textContent = uiText("详情", "Details");
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
  $("#trailReasonBatchToggle")?.addEventListener("click", () => {
    if (state.trailUpdate.selectionBusy) return;
    state.trailUpdate.selectionMode = !state.trailUpdate.selectionMode;
    if (!state.trailUpdate.selectionMode) trailSelectedIssues().clear();
    patchTrailReasonCells(state.trailUpdate.data);
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
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
    if (state.trailUpdate.selectionBusy) return;
    trailSelectionPageStats().eligible.forEach(id => trailSelectedIssues().add(id));
    patchTrailReasonCells(state.trailUpdate.data);
    syncTrailSelectionControls(); syncTrailAttributeActions();
  });
  $("#trailUpdateTableBody")?.addEventListener("click", event => {
    const toggle = event.target.closest("[data-trail-reason-toggle]");
    if (!toggle) return;
    const item = (state.trailUpdate.data?.items || []).find(item => trailRowKey(item) === toggle.dataset.trailReasonToggle);
    if (item) openTrailReasonDetails(item);

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
  refreshTrailReasonDetails();
}

function trailRowKey(item) { return item.row_key || `${item.baseline_id || ""}|${item.issue_id}`; }
function trailLocalState(item) { return item.local_selected === true ? "true" : item.local_selected === false ? "false" : "unknown"; }
function trailLocalLabel(item) {
  return ({true:uiText("已勾选排除", "Exclusion selected"), false:uiText("本地未勾选", "Not selected locally"), unknown:uiText("本地状态未知", "Local state unknown")})[trailLocalState(item)];
}
function trailRemoteState(item) {
  const detail = item.trail_detail;
  if (!detail || ["querying", "query_failed", "not_checked", "not_found", "pending"].includes(detail.state)) return "unknown";
  return detail.trail_should_exclude === true ? "true" : detail.trail_should_exclude === false ? "false" : "unset";
}
function trailSourceLabel(source) {
  return ({local:uiText("本地候选", "Local candidate"), historical:uiText("历史排除", "Historical exclusion"), both:uiText("两者都有", "Both")})[source] || source;
}
function trailReasonSummaryMarkup(item) {
  const detail = item.trail_detail || {};
  const remote = trailRemoteState(item) === "unknown" ? uiText("尚未确认", "Unconfirmed") : detail.trail_comment || uiText("理由未填写", "No reason provided");
  const local = detail.local_comment || item.comment || uiText("理由待补充", "Reason needed");
  return `<div class="trail-reason-summary"><p title="${escapeHtml(remote)}"><span>${uiText("Trail", "Trail")}</span>${escapeHtml(remote)}</p><p title="${escapeHtml(local)}"><span>${uiText("本地", "Local")}</span>${escapeHtml(local)}</p></div>`;
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
  target.hidden = !data.reconciliation;
  if (target.hidden) { target.textContent = ""; return; }
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
    state.trailUpdate.selectionMode = false;
    trailSelectedIssues().clear();
    trailUpdatePersistRoute();
    loadTrailAttributePreview(true).catch(error => showToast(error.message, true));
  });
  for (const [id,key] of [["trailReconcileSource","sourceKind"],["trailReconcileLocal","localState"],["trailReconcileRemote","remoteState"]]) {
    $(`#${id}`)?.addEventListener("change", event => { state.trailUpdate.filters[key] = event.target.value; applyTrailUpdateFilters(); });
  }
  syncTrailReconcileFilters();
}

function openTrailReasonDetails(item) {
  let dialog = $("#trailReasonDetailsDialog");
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = "trailReasonDetailsDialog";
    dialog.className = "dialog case-label-decision-dialog";
    dialog.setAttribute("aria-labelledby", "trailReasonDetailsTitle");
    document.body.appendChild(dialog);
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-trail-reasons]")) dialog.close();
      const copy = event.target.closest("[data-trail-copy-reason]");
      if (copy) navigator.clipboard.writeText(copy.closest("section").querySelector("[data-trail-reason-text]").textContent).then(() => showToast(uiText("已复制理由", "Reason copied"))).catch(() => showToast(uiText("无法复制，请选择文本复制", "Could not copy; select text to copy"), true));
    });
    dialog.addEventListener("close", () => document.querySelector(`[data-trail-reason-toggle="${CSS.escape(dialog.dataset.rowKey || "")}"]`)?.focus({preventScroll:true}));
  }
  dialog.dataset.rowKey = trailRowKey(item);
  dialog.innerHTML = "";
  renderTrailReasonDetails(dialog, item);
  dialog.showModal();
}
function renderTrailReasonDetails(dialog, item) {
  const scroll = dialog.querySelector(".case-label-decision-body")?.scrollTop || 0;
  const focus = dialog.contains(document.activeElement) ? document.activeElement?.dataset.trailCopyReason : null;
  dialog.innerHTML = `<div class="dialog-card"><div class="dialog-heading"><div><small>${escapeHtml(item.issue_id)}</small><h2 id="trailReasonDetailsTitle">${uiText("排除理由与来源", "Exclusion reasons and source")}</h2></div><button type="button" class="icon-button" data-close-trail-reasons aria-label="${uiText("关闭", "Close")}">×</button></div><div class="case-label-decision-body">${trailUpdateStatusCellMarkup(trailReasonState(item))}${trailReasonComparisonMarkup(item, true)}</div><div class="dialog-actions"><button type="button" class="button button-quiet" data-close-trail-reasons>${uiText("关闭", "Close")}</button></div></div>`;
  dialog.querySelector(".case-label-decision-body").scrollTop = scroll;
  if (focus) dialog.querySelector(`[data-trail-copy-reason="${CSS.escape(focus)}"]`)?.focus({preventScroll:true});
}
function refreshTrailReasonDetails() {
  const dialog = $("#trailReasonDetailsDialog");
  if (!dialog?.open) return;
  const item = (state.trailUpdate.data?.items || []).find(item => trailRowKey(item) === dialog.dataset.rowKey);
  if (!item) { dialog.close(); return; }
  renderTrailReasonDetails(dialog, item);
}
