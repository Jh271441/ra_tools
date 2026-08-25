/* Trail 属性更新：Review 汇总 / Issue ID 屏蔽两个独立的预览→提交工作流。 */

function setTrailUpdateTab(tab = "review") {
  const nextTab = tab === "issue" ? "issue" : "review";
  state.trailUpdate.tab = nextTab;
  document.querySelectorAll("[data-trail-update-tab]").forEach((button) => {
    const active = button.dataset.trailUpdateTab === nextTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll("[data-trail-update-panel]").forEach((panel) => {
    const active = panel.dataset.trailUpdatePanel === nextTab;
    panel.classList.toggle("hidden", !active);
    panel.setAttribute("aria-hidden", active ? "false" : "true");
  });
  // A tab may be revisited after a route render while its preview is already
  // cached.  Re-apply the action state here instead of leaving the initial
  // disabled HTML attribute in place until another network request happens.
  if (nextTab === "issue") syncTrailIssueActions();
  else syncTrailAttributeActions();
}

function setTrailIssueStatus(message = "") {
  const status = $("#trailUpdateIssueStatus");
  if (!status) return;
  status.hidden = !message;
  status.textContent = message;
}

function trailIssueIdsFeedback(parsed) {
  const ids = parsed?.ids || [];
  const invalid = parsed?.invalid || [];
  if (invalid.length) {
    return uiText(
      `已识别 ${ids.length} 个 Issue；请修正：${invalid.slice(0, 4).join("、")}${invalid.length > 4 ? "…" : ""}`,
      `${ids.length} Issues recognized; fix: ${invalid.slice(0, 4).join(", ")}${invalid.length > 4 ? "…" : ""}`
    );
  }
  return uiText(
    ids.length ? `已识别 ${ids.length} 个 Issue（每行可填多个，可分别填写说明）` : "请输入 Issue ID",
    ids.length ? `${ids.length} Issues recognized (multiple per row; notes can differ)` : "Enter at least one Issue ID"
  );
}

function trailIssueEntryRows() {
  return Array.from(document.querySelectorAll("[data-trail-issue-entry-row]"));
}

function historicalExclusionSource(source) {
  if (!source || typeof source !== "object") return null;
  return String(source.kind || "") === "historical_spotcheck_xlsx" ? source : null;
}

function historicalExclusionSourceText(source) {
  const record = historicalExclusionSource(source);
  if (!record) return "";
  const label = String(record.label || record.source_id || uiText("历史抽检", "Historical spot check"));
  const row = Number(record.row_number || 0);
  return uiText(
    `历史抽检 · ${label}${row ? ` · Excel 第 ${row} 行` : ""}`,
    `Historical spot check · ${label}${row ? ` · Excel row ${row}` : ""}`
  );
}

function historicalExclusionSourceTitle(source) {
  const record = historicalExclusionSource(source);
  if (!record) return "";
  const filename = String(record.filename || "—");
  const column = String(record.column || "是否排除");
  const value = String(record.value || "—");
  const sha = String(record.sha256 || "—");
  return `${filename}\nExcel「${column}」=「${value}」\nSHA-256: ${sha}`;
}

function historicalExclusionSourceMarkup(source, className = "") {
  const text = historicalExclusionSourceText(source);
  if (!text) return "";
  const title = historicalExclusionSourceTitle(source);
  return `<small class="trail-update-historical-source ${escapeHtml(className)}" title="${escapeHtml(title)}">${escapeHtml(text)}</small>`;
}

function trailIssueEntrySource(row) {
  const raw = String(row?.dataset?.trailIssueEntrySource || "").trim();
  if (!raw) return null;
  try {
    return historicalExclusionSource(JSON.parse(raw));
  } catch (_error) {
    return null;
  }
}

function clearTrailIssueEntrySource(row) {
  if (!row) return;
  delete row.dataset.trailIssueEntrySource;
  row.querySelectorAll("[data-trail-issue-entry-source-label]").forEach((node) => node.remove());
}

function renderTrailIssueEntryRow(entry = {}) {
  const issueId = escapeHtml(String(entry.issue_id || ""));
  const comment = escapeHtml(String(entry.comment || ""));
  const source = historicalExclusionSource(entry.source);
  let sourceAttribute = "";
  if (source) {
    try {
      sourceAttribute = ` data-trail-issue-entry-source="${escapeHtml(JSON.stringify(source))}"`;
    } catch (_error) {
      sourceAttribute = "";
    }
  }
  const sourceMarkup = source
    ? `<div class="trail-update-entry-source" data-trail-issue-entry-source-label>${historicalExclusionSourceMarkup(source)}</div>`
    : "";
  return `<div class="trail-update-entry-row" data-trail-issue-entry-row${sourceAttribute}>
    <label>
      <span class="ui-lang-zh">Issue ID（可多个）</span><span class="ui-lang-en">Issue IDs (multiple)</span>
      <textarea data-trail-issue-entry-id rows="2" inputmode="text" autocomplete="off" placeholder="cn32171803, cn31994663" spellcheck="false">${issueId}</textarea>
    </label>
    <label>
      <span class="ui-lang-zh">排除说明（可选，写入 info）</span><span class="ui-lang-en">Exclusion note (optional; saved in info)</span>
      <textarea data-trail-issue-entry-comment rows="2" placeholder="留空时使用默认说明；会写入 info.ra_triage_dashboard.should_exclude_comment。">${comment}</textarea>
    </label>
    <button class="button button-quiet trail-update-entry-remove" data-trail-issue-entry-remove type="button" aria-label="删除此行" title="删除此行">×</button>
    ${sourceMarkup}
  </div>`;
}

function syncTrailIssueEntryRemoveButtons() {
  const rows = trailIssueEntryRows();
  rows.forEach((row) => {
    const button = row.querySelector("[data-trail-issue-entry-remove]");
    if (button) button.toggleAttribute("disabled", rows.length <= 1);
  });
}

function addTrailIssueEntryRow(entry = {}, { focus = true } = {}) {
  const list = $("#trailUpdateIssueEntries");
  if (!list) return null;
  list.insertAdjacentHTML("beforeend", renderTrailIssueEntryRow(entry));
  syncTrailIssueEntryRemoveButtons();
  const row = list.lastElementChild;
  if (focus) row?.querySelector("[data-trail-issue-entry-id]")?.focus();
  return row;
}

function clearTrailIssueEntries() {
  const list = $("#trailUpdateIssueEntries");
  if (!list) return;
  list.innerHTML = renderTrailIssueEntryRow();
  syncTrailIssueEntryRemoveButtons();
  parseTrailIssueIds();
  clearTrailIssuePreview();
  setTrailIssueStatus(uiText(
    "已清空所有屏蔽草稿行；尚未写入 Trail。",
    "All shielding draft rows were cleared; Trail has not been written."
  ));
  list.querySelector("[data-trail-issue-entry-id]")?.focus();
}

function collectTrailIssueEntries() {
  const entries = [];
  const ids = [];
  const invalid = [];
  const seen = new Set();
  trailIssueEntryRows().forEach((row, index) => {
    const idInput = row.querySelector("[data-trail-issue-entry-id]");
    const commentInput = row.querySelector("[data-trail-issue-entry-comment]");
    const raw = String(idInput?.value || "").trim();
    const comment = String(commentInput?.value || "").trim().slice(0, 4000);
    const source = trailIssueEntrySource(row);
    if (!raw && !comment) return;
    const parsed = typeof parseIssueIdsInput === "function"
      ? parseIssueIdsInput(raw)
      : { ids: [], invalid: [raw || `row ${index + 1}`] };
    if (parsed.invalid.length) {
      invalid.push(...parsed.invalid.map((item) => `${item}（第 ${index + 1} 行）`));
    }
    if (!parsed.ids.length) {
      invalid.push(`${raw || `第 ${index + 1} 行`}（未识别到 Issue ID）`);
      return;
    }
    parsed.ids.forEach((value) => {
      const issueId = String(value || "").trim();
      if (!issueId) return;
      if (seen.has(issueId)) {
        invalid.push(`${issueId}（重复）`);
        return;
      }
      seen.add(issueId);
      ids.push(issueId);
      const sourceMatchesRow = source
        && parsed.ids.length === 1
        && String(source.issue_id || "") === issueId;
      entries.push({
        issue_id: issueId,
        comment,
        ...(sourceMatchesRow ? { source } : {}),
      });
    });
  });
  entries.sort((left, right) => left.issue_id.localeCompare(right.issue_id));
  ids.splice(0, ids.length, ...entries.map((entry) => entry.issue_id));
  return { ids, invalid, entries };
}

function parseTrailIssueIds() {
  const feedback = $("#trailUpdateIssueIdsFeedback");
  const parsed = collectTrailIssueEntries();
  if (feedback) {
    feedback.textContent = trailIssueIdsFeedback(parsed);
    feedback.classList.toggle("is-error", parsed.invalid.length > 0);
    feedback.classList.toggle("is-ready", !parsed.invalid.length && parsed.ids.length > 0);
  }
  syncTrailIssueEntryRemoveButtons();
  return parsed;
}

function trailIssueHistoryStatusMeta(status = "pending") {
  const key = String(status || "pending");
  const values = {
    pending: ["待提交", "Pending", "is-pending"],
    completed: ["已同步", "Synced", "is-success"],
    partial: ["部分成功", "Partial", "is-warning"],
    failed: ["失败", "Failed", "is-error"],
    trail_synced_not_in_dashboard: ["Trail 已同步（看板外）", "Trail synced (outside dashboard)", "is-warning"],
  };
  const value = values[key] || values.pending;
  return { label: uiText(value[0], value[1]), className: value[2] };
}

function renderTrailIssueHistory(data = {}) {
  const list = $("#trailUpdateIssueHistoryList");
  if (!list) return;
  const items = Array.isArray(data?.items) ? data.items : [];
  if (!items.length) {
    list.innerHTML = `<div class="trail-update-history-empty">${escapeHtml(uiText("暂无 Issue ID 屏蔽上传记录。", "No Issue shielding uploads yet."))}</div>`;
    return;
  }
  list.innerHTML = items.map((item) => {
    const meta = trailIssueHistoryStatusMeta(item.status);
    const entries = Array.isArray(item.entries) ? item.entries : [];
    const total = Number(item.requested_count || entries.length || 0);
    const synced = Number(item.synced_count || 0);
    const failed = Number(item.failed_count || 0);
    const actor = String(item.actor || uiText("未记录", "Unknown"));
    const operation = String(item.operation_id || "");
    const detailRows = entries.length
      ? entries.map((entry) => {
        const entryMeta = trailIssueHistoryStatusMeta(entry.status);
        return `<tr><td data-label="Issue"><strong>${escapeHtml(entry.issue_id || "—")}</strong></td><td data-label="排除说明"><div class="trail-update-history-comment">${escapeHtml(entry.comment || "—")}</div>${historicalExclusionSourceMarkup(entry.source)}</td><td data-label="结果"><span class="trail-update-history-entry-status ${entryMeta.className}">${escapeHtml(entryMeta.label)}</span><small>${escapeHtml(entry.detail || "")}</small></td></tr>`;
      }).join("")
      : `<tr><td colspan="3" class="trail-update-history-empty">${escapeHtml(uiText("没有逐条明细。", "No per-Issue details."))}</td></tr>`;
    return `<details class="trail-update-history-item">
      <summary>
        <div class="trail-update-history-summary-main"><span class="trail-update-history-status ${meta.className}">${escapeHtml(meta.label)}</span><strong>${escapeHtml(`${total} ${uiText("个 Issue", "Issues")}`)}</strong><small>${escapeHtml(formatTime(item.created_at))} · ${escapeHtml(actor)}</small></div>
        <div class="trail-update-history-summary-count"><strong>${escapeHtml(`${synced}/${total}`)}</strong><small>${escapeHtml(failed ? `${failed} ${uiText("失败", "failed")}` : uiText("全部回读成功", "readback complete"))}</small></div>
      </summary>
      <div class="trail-update-history-details"><div class="trail-update-history-operation"><span>${escapeHtml(item.message || uiText("Issue 屏蔽提交记录。", "Issue shielding submission."))}</span><code title="${escapeHtml(operation)}">${escapeHtml(operation ? `${operation.slice(0, 12)}…` : "—")}</code></div><div class="trail-update-history-table-wrap"><table><thead><tr><th>Issue</th><th>${escapeHtml(uiText("排除说明", "Exclusion note"))}</th><th>${escapeHtml(uiText("结果", "Result"))}</th></tr></thead><tbody>${detailRows}</tbody></table></div></div>
    </details>`;
  }).join("");
}

async function loadTrailIssueHistory() {
  const list = $("#trailUpdateIssueHistoryList");
  if (!list) return null;
  const requestSeq = ++state.trailUpdate.issueHistoryRequestSeq;
  list.innerHTML = `<div class="trail-update-history-empty">${escapeHtml(uiText("正在加载屏蔽历史…", "Loading shielding history…"))}</div>`;
  try {
    const data = await api("/api/trail-attribute-update/issue-history?limit=20");
    if (requestSeq !== state.trailUpdate.issueHistoryRequestSeq) return data;
    state.trailUpdate.issueHistory = data;
    renderTrailIssueHistory(data);
    return data;
  } catch (error) {
    if (requestSeq === state.trailUpdate.issueHistoryRequestSeq) {
      list.innerHTML = `<div class="trail-update-history-empty is-error">${escapeHtml(error?.message || uiText("屏蔽历史加载失败。", "Shielding history failed to load."))}</div>`;
    }
    return null;
  }
}

function trailUpdateRunLabel(run) {
  if (!run) return "";
  const count = Number(run.baseline_prediction_count || 0);
  const failures = Number(run.failure_count || 0);
  const source = run.source_name ? ` · ${run.source_name}` : "";
  return `${run.name || run.id}${source} · ${count} 条 · 错 ${failures}`;
}
function renderTrailAttributeRunPicker() {
  const select = $("#trailUpdateRunSelect");
  const picker = $("#trailUpdateRunPicker");
  if (!select) return;
  // Trail drafts must be explicit.  Do not inherit the Review gallery's
  // global/default Run when the user merely opens this page.
  const selected = state.trailUpdate?.runId || "";
  const hasRuns = Array.isArray(state.modelRuns) && state.modelRuns.length > 0;
  const options = [
    {
      value: "",
      label: hasRuns
        ? uiText("未选择模型 Run（合并全部）", "No model Run selected (all Runs)")
        : uiText("当前环境没有模型 Run", "No model Run in this environment"),
    },
    ...(state.modelRuns || []).map((run) => ({ value: run.id, label: trailUpdateRunLabel(run) })),
  ];
  select.disabled = !hasRuns;
  const selectedValue = (state.modelRuns || []).some((run) => run.id === selected) ? selected : "";
  if (picker && typeof populateUiSelect === "function") {
    populateUiSelect(picker, options, selectedValue);
    bindUiSelect(picker, { maxHeight: 360, maxWidth: 720 });
  } else {
    select.innerHTML = options
      .map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`)
      .join("");
    select.value = selectedValue;
  }
  const hint = $("#trailUpdateRunHint");
  if (hint) {
    hint.hidden = hasRuns;
    if (!hasRuns) {
      const isGray = window.location.port === "8786";
      hint.innerHTML = uiText(
        isGray
          ? "当前 8786 灰度只有基线数据，尚无 Model Run。它使用独立空库，不会自动共享 8785 生产 Run；请先到“模型结果”导入结果。"
          : "当前环境只有基线数据，尚无 Model Run；请先到“模型结果”导入结果。",
        isGray
          ? "Gray 8786 has baselines but no Model Run. It uses an isolated empty database and does not share Runs with production 8785; import a result from Model Runs first."
          : "This environment has baselines but no Model Run; import a result from Model Runs first."
      );
    }
  }
  const baseline = normalizeBaselineIds(state.selectedBaselineIds);
  const summary = $("#trailUpdateBaselineSummary");
  if (summary) summary.textContent = baseline.join(" + ") || uiText("当前数据集", "Selected dataset");
}

function setTrailAttributeStatus(message = "") {
  const status = $("#trailUpdateStatus");
  if (!status) return;
  status.hidden = !message;
  status.textContent = message;
}

function setTrailAttributeLoading(loading = false) {
  const active = Boolean(loading);
  state.trailUpdate.loading = active;
  const page = $("#trailAttributeUpdatePage");
  page?.classList.toggle("is-loading", active);
  [
    ...document.querySelectorAll("[data-trail-json-preview]"),
    $("#trailUpdateCommitButton"),
  ].filter(Boolean).forEach((button) => {
    if (!button) return;
    button.toggleAttribute("aria-busy", active);
    if (active) button.disabled = true;
  });
}

function trailUpdateWriteReady(data = null) {
  // `write_ready` is retained as a compatibility fallback for a preview that
  // was produced while a rolling server update was in progress.  The server
  // still owns the final write gate and validates the preview fingerprint.
  return Boolean(data && (data.write_status === "ready" || data.write_ready === true));
}

function syncTrailAttributeActions(data = state.trailUpdate?.data) {
  const loading = Boolean(state.trailUpdate?.loading);
  document.querySelectorAll('[data-trail-json-preview="review"]').forEach((button) => {
    button.toggleAttribute("disabled", loading || !data?.draft);
  });
  $("#trailUpdateCommitButton")?.toggleAttribute("disabled", loading || !trailUpdateWriteReady(data));
}

function syncTrailIssueActions(data = state.trailUpdate?.directData) {
  const ready = trailUpdateWriteReady(data);
  document.querySelectorAll('[data-trail-json-preview="issue"]').forEach((button) => {
    button.toggleAttribute("disabled", !data?.draft);
  });
  $("#trailUpdateIssueCommitButton")?.toggleAttribute("disabled", !ready);
}

function setTrailAttributeUpdatePreviewVisible(visible) {
  const page = $("#trailAttributeUpdatePage");
  const results = $("#trailUpdateResults");
  page?.classList.toggle("has-preview", visible);
  if (results) results.hidden = !visible;
}

function setTrailAttributeCapability(data = null) {
  const capability = data?.trail_capability || {};
  const directMode = data?.mode === "direct_issue_ids";
  const hasPreview = Boolean(data);
  // The deployment flag is an independent safety gate from Trail field
  // visibility.  Surface it first so a field-ready preview in a read-only
  // environment cannot look like it is commit-ready.
  const status = data?.write_status === "disabled" || !data
    ? "disabled"
    : String(capability.status || "not_checked");
  const panel = $("#trailUpdateCapability");
  const title = $("#trailUpdateCapabilityTitle");
  const message = $("#trailUpdateCapabilityMessage");
  const fields = $("#trailUpdateVisibleFields");
  const commitButton = $("#trailUpdateCommitButton");
  const infoOnly = data?.write_mode === "info_only";
  const resultField = data?.model_result_field || data?.target_fields?.[0] || "ra_stuck_auto_result";
  const infoField = directMode || infoOnly
    ? data?.target_field || data?.target_fields?.[0] || "ra_stuck_auto_result_info"
    : data?.target_fields?.[1] || "ra_stuck_auto_result_info";
  if (panel) panel.dataset.status = status;
  if (title) title.textContent = uiText(
    !hasPreview ? "尚未生成预览" : status === "ready" ? "可以提交到 Trail" : status === "missing_fields" ? "当前 view 不能安全写入" : status === "disabled" ? "当前环境只允许预览" : "Trail 字段能力尚未确认",
    !hasPreview ? "Preview not generated" : status === "ready" ? "Ready to commit to Trail" : status === "missing_fields" ? "The current view is not safe to write" : status === "disabled" ? "Preview only in this environment" : "Trail field capability is not confirmed"
  );
  if (message) {
    const capabilityMessage = capability.message || uiText(
      infoOnly || directMode
        ? "生成预览后检查 2410 view 的 info 字段；提交只会 deep_merge info，不改模型 label。"
        : "选择 Run 后生成预览，页面会检查 2410 view 是否同时暴露两个目标字段。",
      infoOnly || directMode
        ? "Build a preview to check the info field in view 2410; commit deep-merges info only and leaves the model label unchanged."
        : "Choose a Run and build a preview to check whether view 2410 exposes both target fields."
    );
    message.textContent = status === "disabled"
      ? uiText(`当前环境只允许预览；${capabilityMessage}`, `This environment is preview-only; ${capabilityMessage}`)
      : capabilityMessage;
  }
  if (fields) {
    const visible = Array.isArray(capability.fields_visible) ? capability.fields_visible : [];
    fields.textContent = uiText(
      directMode
        ? `目标：仅更新 ${infoField} 的 Dashboard 排除标记；当前 view 可见：${visible.join(", ") || "无"}`
        : infoOnly
          ? `目标：仅 deep_merge ${infoField}，不改 ${resultField}；当前 view 可见：${visible.join(", ") || "无"}`
        : `目标：${resultField} + ${infoField}；当前 view 可见：${visible.join(", ") || "无"}`,
      directMode
        ? `Target: Dashboard exclusion marker in ${infoField}; visible in view: ${visible.join(", ") || "none"}`
        : infoOnly
          ? `Target: deep-merge ${infoField} only; ${resultField} remains unchanged; visible in view: ${visible.join(", ") || "none"}`
        : `Target: ${resultField} + ${infoField}; visible in view: ${visible.join(", ") || "none"}`
    );
  }
  if (commitButton) {
    commitButton.title = uiText(
      status === "disabled"
        ? "当前环境未开启 Trail 属性写入；可以预览、下载和复制草稿。"
        : status === "ready"
          ? "已通过字段检查；点击后会再次确认并写入 Trail。"
          : "当前预览尚未通过 Trail 字段检查。",
      status === "disabled"
        ? "Trail attribute writing is disabled here; preview, download, and copy remain available."
        : status === "ready"
          ? "Field check passed; click to confirm and write to Trail."
          : "The current preview has not passed Trail field validation."
    );
  }
}

function trailUpdateTargetSpec(data = {}) {
  const field = String(
    data?.target_field
      || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1])
      || "ra_stuck_auto_result_info"
  ).trim() || "ra_stuck_auto_result_info";
  const path = String(data?.target_path || "ra_triage_dashboard.should_exclude").trim().replace(/^\.+|\.+$/g, "");
  const commentPath = String(data?.comment_target_path || "ra_triage_dashboard.should_exclude_comment").trim().replace(/^\.+|\.+$/g, "");
  return {
    field,
    path,
    commentPath,
    fullPath: path ? `${field}.${path}` : field,
    commentFullPath: commentPath ? `${field}.${commentPath}` : field,
  };
}

function renderTrailUpdateTargetField(data = {}, fieldId = "trailUpdateInfoField") {
  const spec = trailUpdateTargetSpec(data);
  const field = $(`#${fieldId}`);
  if (field) {
    field.textContent = spec.fullPath;
    field.setAttribute("title", `${spec.fullPath}\n排除说明：${spec.commentFullPath}`);
  }
  return spec;
}

function trailUpdateFilterValues(key) {
  const filters = state.trailUpdate?.filters || {};
  return parseFilterList(filters[key]);
}

function currentTrailUpdateRouteOptions(overrides = {}) {
  const filters = state.trailUpdate?.filters || {};
  return {
    runId: state.trailUpdate?.runId || "",
    search: String(filters.search || "").trim(),
    gtLabel: trailUpdateFilterValues("gtLabel"),
    modelLabel: trailUpdateFilterValues("modelLabel"),
    annotationAuthor: trailUpdateFilterValues("reviewer"),
    reviewStatus: trailUpdateFilterValues("reviewStatus"),
    trailStatus: trailUpdateFilterValues("trailStatus"),
    page: Math.max(1, Number(state.trailUpdate?.page) || 1),
    pageSize: CASE_PAGE_SIZES.includes(Number(state.trailUpdate?.pageSize))
      ? Number(state.trailUpdate.pageSize)
      : DEFAULT_CASE_PAGE_SIZE,
    ...overrides,
  };
}

function applyTrailUpdateRouteControls(filters = {}) {
  const source = filters || {};
  state.trailUpdate.filters = {
    search: String(source.search || ""),
    gtLabel: parseFilterList(source.gtLabel).filter((value) => LABELS.includes(value)),
    modelLabel: parseFilterList(source.modelLabel),
    reviewer: parseFilterList(source.annotationAuthor || source.reviewer),
    reviewStatus: parseFilterList(source.reviewStatus).filter((value) =>
      ["pending", "reviewed", "needs_gt_review"].includes(value)
    ),
    trailStatus: parseFilterList(source.trailStatus).filter((value) =>
      ["querying", "synced", "pending", "not_found", "query_failed", "not_checked"].includes(value)
    ),
  };
  state.trailUpdate.page = Math.max(1, Number(source.page) || 1);
  state.trailUpdate.pageSize = CASE_PAGE_SIZES.includes(Number(source.pageSize))
    ? Number(source.pageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  const search = $("#trailUpdateSearchInput");
  if (search && document.activeElement !== search) search.value = state.trailUpdate.filters.search;
  const pageSize = $("#trailUpdatePageSize");
  if (pageSize) pageSize.value = String(state.trailUpdate.pageSize);
  if (state.trailUpdate?.data) renderTrailAttributePreview(state.trailUpdate.data);
}

function trailUpdatePersistRoute() {
  if (typeof pageUrl !== "function") return;
  history.replaceState(
    { page: "trail-update" },
    "",
    pageUrl("trail-update", currentTrailUpdateRouteOptions())
  );
}

function trailUpdateModelValue(item = {}) {
  return String(item?.model?.label || "").trim() || "__none__";
}

function trailUpdateSearchText(item = {}) {
  const review = item.review || {};
  const model = item.model || {};
  return [
    item.issue_id,
    item.title,
    item.scenario,
    item.gt_label,
    model.label,
    model.reason,
    review.reviewer,
    review.status,
    review.note,
    item.comment,
    item.baseline_id,
    item.baseline_scope,
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function trailUpdateFilteredItems(data = state.trailUpdate?.data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const filters = state.trailUpdate?.filters || {};
  const search = String(filters.search || "").trim().toLocaleLowerCase();
  const gt = new Set(trailUpdateFilterValues("gtLabel"));
  const modelLabel = new Set(trailUpdateFilterValues("modelLabel"));
  const reviewer = new Set(trailUpdateFilterValues("reviewer"));
  const reviewStatus = new Set(trailUpdateFilterValues("reviewStatus"));
  const trailStatus = new Set(trailUpdateFilterValues("trailStatus"));
  return items.filter((item) => {
    const review = item.review || {};
    if (search && !trailUpdateSearchText(item).includes(search)) return false;
    if (gt.size && !gt.has(String(item?.gt_label || ""))) return false;
    if (modelLabel.size && !modelLabel.has(trailUpdateModelValue(item))) return false;
    if (reviewer.size && !reviewer.has(String(review.reviewer || ""))) return false;
    if (reviewStatus.size && !reviewStatus.has(String(review.status || "pending"))) return false;
    if (trailStatus.size && !trailStatus.has(String(item?.trail_update_status || "not_checked"))) return false;
    return true;
  });
}

function trailUpdateFilterOptions(items = []) {
  const distinct = (values) => [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  const modelValues = distinct(items.map(trailUpdateModelValue));
  const reviewerValues = distinct(items.map((item) => item?.review?.reviewer));
  const reviewValues = distinct(items.map((item) => item?.review?.status || "pending"));
  const statusValues = distinct(items.map((item) => item?.trail_update_status || "not_checked"));
  return {
    gt: LABELS.filter((label) => items.some((item) => item?.gt_label === label)).map((value) => ({ value, label: value })),
    model: modelValues.map((value) => ({ value, label: value === "__none__" ? uiText("未输出", "No output") : value })),
    reviewer: reviewerValues.map((value) => ({ value, label: value })),
    review: reviewValues.map((value) => ({
      value,
      label: ({ pending: uiText("待补充", "Pending"), reviewed: uiText("已复核", "Reviewed"), needs_gt_review: uiText("GT 需复核", "Needs GT review") })[value] || value,
    })),
    trail: statusValues.map((value) => ({ value, label: trailUpdateStatusMeta(value).label })),
  };
}

function applyTrailUpdateFilters({ resetPage = true, persist = true } = {}) {
  if (resetPage) state.trailUpdate.page = 1;
  if (state.trailUpdate?.data) renderTrailAttributePreview(state.trailUpdate.data);
  if (persist) trailUpdatePersistRoute();
}

function scheduleTrailUpdateFilterRender() {
  if (state.trailUpdate.filterTimer) window.clearTimeout(state.trailUpdate.filterTimer);
  state.trailUpdate.filterTimer = window.setTimeout(() => {
    state.trailUpdate.filterTimer = null;
    const search = $("#trailUpdateSearchInput");
    state.trailUpdate.filters.search = String(search?.value || "");
    applyTrailUpdateFilters();
  }, 180);
}

function renderTrailUpdateFilters(data = state.trailUpdate?.data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const options = trailUpdateFilterOptions(items);
  const filters = state.trailUpdate?.filters || {};
  const search = $("#trailUpdateSearchInput");
  if (search && document.activeElement !== search) search.value = String(filters.search || "");
  const pageSize = $("#trailUpdatePageSize");
  if (pageSize) pageSize.value = String(state.trailUpdate.pageSize || DEFAULT_CASE_PAGE_SIZE);
  const bind = (id, values, selected, onChange) => {
    const root = $(id);
    if (!root || typeof renderMultiFilter !== "function") return;
    renderMultiFilter(root, { options: values, selected, onChange });
  };
  bind("#trailUpdateGtFilter", options.gt, filters.gtLabel, (values) => {
    state.trailUpdate.filters.gtLabel = values;
    applyTrailUpdateFilters();
  });
  bind("#trailUpdateModelLabelFilter", options.model, filters.modelLabel, (values) => {
    state.trailUpdate.filters.modelLabel = values;
    applyTrailUpdateFilters();
  });
  bind("#trailUpdateReviewerFilter", options.reviewer, filters.reviewer, (values) => {
    state.trailUpdate.filters.reviewer = values;
    applyTrailUpdateFilters();
  });
  bind("#trailUpdateReviewStatusFilter", options.review, filters.reviewStatus, (values) => {
    state.trailUpdate.filters.reviewStatus = values;
    applyTrailUpdateFilters();
  });
  bind("#trailUpdateStatusFilter", options.trail, filters.trailStatus, (values) => {
    state.trailUpdate.filters.trailStatus = values;
    applyTrailUpdateFilters();
  });
}

function renderTrailUpdatePagination(filteredItems = []) {
  const total = filteredItems.length;
  const pageSize = CASE_PAGE_SIZES.includes(Number(state.trailUpdate?.pageSize))
    ? Number(state.trailUpdate.pageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  state.trailUpdate.pageSize = pageSize;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  state.trailUpdate.page = Math.min(Math.max(1, Number(state.trailUpdate?.page) || 1), totalPages);
  const page = state.trailUpdate.page;
  const start = total ? (page - 1) * pageSize + 1 : 0;
  const end = Math.min(page * pageSize, total);
  const previous = $("#trailUpdatePagePrevious");
  const next = $("#trailUpdatePageNext");
  const summary = $("#trailUpdatePageSummary");
  const result = $("#trailUpdateResultSummary");
  const jump = $("#trailUpdatePageJump");
  const jumpButton = $("#trailUpdatePageJumpButton");
  const pageSizeSelect = $("#trailUpdatePageSize");
  const pagination = $("#trailUpdatePagination");
  if (pagination) pagination.hidden = total === 0;
  if (previous) previous.disabled = page <= 1 || !total;
  if (next) next.disabled = page >= totalPages || !total;
  if (summary) summary.textContent = `${page} / ${totalPages}`;
  if (result) {
    result.textContent = total
      ? uiText(`当前显示 ${start}–${end} / 共 ${total} 条`, `Showing ${start}–${end} of ${total}`)
      : uiText("当前筛选没有匹配案例", "No cases match the current filters");
  }
  if (jump) {
    jump.min = "1";
    jump.max = String(totalPages);
    jump.disabled = totalPages <= 1;
    if (document.activeElement !== jump) jump.value = String(page);
  }
  if (jumpButton) jumpButton.disabled = totalPages <= 1;
  if (pageSizeSelect) pageSizeSelect.value = String(pageSize);
  return { start: total ? (page - 1) * pageSize : 0, end: page * pageSize, total, page, totalPages };
}

function goToTrailUpdatePage(nextPage) {
  const total = trailUpdateFilteredItems().length;
  const pageSize = CASE_PAGE_SIZES.includes(Number(state.trailUpdate?.pageSize))
    ? Number(state.trailUpdate.pageSize)
    : DEFAULT_CASE_PAGE_SIZE;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  state.trailUpdate.page = Math.min(Math.max(1, Number(nextPage) || 1), totalPages);
  applyTrailUpdateFilters({ resetPage: false });
}

function clearTrailAttributePreview(message = "") {
  state.trailUpdate.data = null;
  state.trailUpdate.jsonPreview = null;
  state.trailUpdate.previewKey = "";
  state.trailUpdate.previewLoadedAt = 0;
  state.trailUpdate.statusLoadedAt = 0;
  setTrailAttributeUpdatePreviewVisible(false);
  setTrailAttributeCapability(null);
  $("#trailUpdateCount").textContent = "—";
  $("#trailUpdateRunSummary").textContent = "—";
  $("#trailUpdateStatusSummary").textContent = "—";
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) digestElement.textContent = "—";
  const resultSummary = $("#trailUpdateResultSummary");
  if (resultSummary) resultSummary.textContent = "—";
  const pagination = $("#trailUpdatePagination");
  if (pagination) pagination.hidden = true;
  setTrailAttributeLoading(false);
  syncTrailAttributeActions(null);
  setTrailAttributeStatus(message);
  const body = $("#trailUpdateTableBody");
  if (body) {
    body.innerHTML = `<tr><td colspan="8" class="trail-update-empty">${uiText("正在加载排除案例。", "Loading excluded cases.")}</td></tr>`;
  }
}

function clearTrailIssuePreview(message = "") {
  state.trailUpdate.directData = null;
  state.trailUpdate.jsonPreview = null;
  const results = $("#trailUpdateIssueResults");
  if (results) results.hidden = true;
  $("#trailUpdateIssueCount").textContent = "—";
  $("#trailUpdateIssueMissingCount").textContent = "—";
  $("#trailUpdateIssueSummary").textContent = "—";
  document.querySelectorAll('[data-trail-json-preview="issue"]').forEach((button) => {
    button.toggleAttribute("disabled", true);
  });
  $("#trailUpdateIssueCommitButton")?.toggleAttribute("disabled", true);
  setTrailIssueStatus(message);
  const body = $("#trailUpdateIssueTableBody");
  if (body) {
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("生成预览后显示 Issue。", "Issues appear after building a preview.")}</td></tr>`;
  }
}

function renderTrailAttributePreview(data) {
  const allItems = Array.isArray(data?.items) ? data.items : [];
  renderTrailUpdateFilters(data);
  const filteredItems = trailUpdateFilteredItems(data);
  const page = renderTrailUpdatePagination(filteredItems);
  const items = filteredItems.slice(page.start, page.end);
  const run = data?.selected_run || {};
  const digest = String(data?.payload_sha256 || "");
  const capability = data?.trail_capability || {};
  setTrailAttributeUpdatePreviewVisible(true);
  setTrailAttributeCapability(data);
  $("#trailUpdateCount").textContent = String(filteredItems.length);
  const sourceLabel = run.name || run.id || uiText("全部 Model Runs", "All model Runs");
  $("#trailUpdateRunSummary").textContent = filteredItems.length === allItems.length
    ? sourceLabel
    : `${sourceLabel} · ${uiText(`筛选 ${filteredItems.length}/${allItems.length} 条`, `${filteredItems.length}/${allItems.length} filtered`)}`;
  renderTrailUpdateTargetField(data);
  trailUpdateStatusSummary(data, filteredItems);
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) {
    digestElement.textContent = digest ? `${digest.slice(0, 12)}…` : "—";
    digestElement.setAttribute("title", digest || "");
  }
  const body = $("#trailUpdateTableBody");
  if (!body) return;
  if (!allItems.length) {
    body.innerHTML = `<tr><td colspan="8" class="trail-update-empty">${uiText("当前数据集与 Run 范围没有已标记“应该排除”的 Review。", "No reviewed “should exclude” cases in the current dataset and Run.")}</td></tr>`;
    return;
  }
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="8" class="trail-update-empty">${uiText("当前筛选没有匹配的排除案例。", "No excluded cases match the current filters.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const review = item.review || {};
    const model = item.model || {};
    const comment = String(item.comment || review.note || "").trim();
    const ready = item.write_ready !== false;
    const sourceRun = trailUpdateSourceRun(model, data, item);
    const status = trailUpdateStatusMeta(item.trail_update_status || "not_checked");
    return `<tr class="${ready ? "" : "is-invalid"}">
      <td data-label="Issue"><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong><small>${escapeHtml(item.title || item.scenario || "")}</small></td>
      <td data-label="GT">${labelBadge(item.gt_label, "—")}</td>
      <td data-label="模型 label">${labelBadge(model.label, "未输出")}<small>${ready ? "" : uiText("label 不在三分类契约内", "label is outside the contract")}</small></td>
      <td data-label="模型 reason"><div class="trail-update-reason" title="${escapeHtml(model.reason || "模型未返回 reason")}">${escapeHtml(model.reason || "模型未返回 reason")}</div><small>${escapeHtml(formatModelConfidence(model.confidence))} confidence</small></td>
      <td data-label="Review"><div>${escapeHtml(review.reviewer || "未记录")}</div><small>${escapeHtml(review.status || "pending")} · ${escapeHtml(formatTime(review.reviewed_at))}</small></td>
      <td data-label="Comment"><div class="trail-update-comment" title="${escapeHtml(comment || uiText("未填写 Comment", "No Comment"))}">${escapeHtml(comment || "未填写")}</div><small class="trail-update-comment-target" title="${escapeHtml(comment ? uiText("提交时写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment on commit") : uiText("不会写入排除说明", "No exclusion note will be written"))}">${comment ? uiText("提交时写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment on commit") : uiText("不会写入排除说明", "No exclusion note will be written")}</small></td>
      <td data-label="数据集版本" class="trail-update-source-cell" title="${escapeHtml(sourceRun.title)}"><strong>${escapeHtml(sourceRun.label)}</strong></td>
      <td data-label="Trail 更新状态" data-trail-update-status-issue="${escapeHtml(item.issue_id || "")}">${trailUpdateStatusCellMarkup(status.key)}</td>
    </tr>`;
  }).join("");
}

function patchTrailAttributeStatus(statusData) {
  const data = state.trailUpdate?.data;
  if (!data || !statusData || typeof statusData !== "object") return data;
  const statuses = statusData.trail_update_statuses || {};
  data.trail_capability = statusData.trail_capability || data.trail_capability;
  data.trail_update_status_summary = statusData.trail_update_status_summary || {};
  data.pending_count = Number(statusData.pending_count || 0);
  data.pending_issue_ids = (data.items || [])
    .filter((item) => String(statuses[String(item?.issue_id || "")] || item?.trail_update_status || "") === "pending")
    .map((item) => String(item?.issue_id || "").trim())
    .filter(Boolean);
  data.write_status = statusData.write_status || data.write_status;
  data.write_ready = statusData.write_ready === true;
  data.capability_pending = false;
  (data.items || []).forEach((item) => {
    const itemIssueId = String(item?.issue_id || "");
    if (Object.prototype.hasOwnProperty.call(statuses, itemIssueId)) {
      item.trail_update_status = statuses[itemIssueId];
    }
  });
  // This remains the second-stage Trail response.  Re-rendering only this
  // local projection updates filters/pagination and visible rows without a
  // second Review aggregation or a new Trail request.
  renderTrailAttributePreview(data);
  syncTrailAttributeActions(data);
  return data;
}

async function refreshTrailAttributeStatus({ runId, previewKey, requestSeq, force = false } = {}) {
  try {
    // This is deliberately a second-stage request.  The Review aggregate has
    // already rendered from local data, so a slow Trail view must never hold
    // candidate rows hostage.
    const current = state.trailUpdate?.data;
    const items = Array.isArray(current?.items) ? current.items : [];
    if (!items.length) return current;
    const data = await api(trailUpdateStatusEndpoint(items, force), { cache: "no-store" });
    if (
      requestSeq !== state.trailUpdate.requestSeq ||
      previewKey !== trailUpdatePreviewKey(runId)
    ) return data;
    patchTrailAttributeStatus(data);
    state.trailUpdate.previewKey = previewKey;
    state.trailUpdate.statusLoadedAt = Date.now();
    setTrailAttributeStatus("");
    return data;
  } catch (error) {
    if (
      requestSeq === state.trailUpdate.requestSeq &&
      previewKey === trailUpdatePreviewKey(runId)
    ) {
      // Keep the already-rendered local candidate list usable for inspection;
      // only the remote status projection and commit readiness remain pending.
      setTrailAttributeStatus(uiText(
        "Trail 状态查询失败；案例已加载，可点击顶部刷新重试。",
        "Trail status check failed; cases are loaded. Use the top refresh to retry."
      ));
    }
    throw error;
  }
}

async function loadTrailAttributePreview(force = false, options = {}) {
  const background = Boolean(options?.background);
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  state.trailUpdate.runId = runId;
  const previewKey = trailUpdatePreviewKey(runId);
  const cachedData = state.trailUpdate?.data;
  if (!background && !force && state.trailUpdate?.loading && state.trailUpdate.previewKey === previewKey) {
    if (cachedData) {
      setTrailAttributeLoading(false);
      renderTrailAttributePreview(cachedData);
      syncTrailAttributeActions(cachedData);
    }
    return cachedData;
  }
  if (
    !background &&
    !force &&
    cachedData &&
    state.trailUpdate.previewKey === previewKey &&
    Number(state.trailUpdate.previewLoadedAt || 0) > 0
  ) {
    setTrailAttributeLoading(false);
    renderTrailAttributePreview(cachedData);
    syncTrailAttributeActions(cachedData);
    return cachedData;
  }
  const requestSeq = ++state.trailUpdate.requestSeq;
  if (background) {
    return refreshTrailAttributeStatus({ runId, previewKey, requestSeq, force });
  }
  if (!background) setTrailAttributeLoading(true);
  const applyPreview = (data, { loaded = false } = {}) => {
    if (requestSeq !== state.trailUpdate.requestSeq) return false;
    if (!background) setTrailAttributeLoading(false);
    state.trailUpdate.data = data;
    state.trailUpdate.previewKey = previewKey;
    state.trailUpdate.previewLoadedAt = loaded ? Date.now() : 0;
    renderTrailAttributePreview(data);
    syncTrailAttributeActions(data);
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId }));
    }
    return true;
  };
  try {
    // First paint reads only the local Review aggregate.  It immediately
    // presents every candidate as “查询中”, then a single batched Trail read
    // fills in per-Issue state asynchronously below.
    const data = await api(trailUpdateEndpoint(runId, false, force), { cache: "no-store" });
    if (requestSeq !== state.trailUpdate.requestSeq) return data;
    applyPreview(data, { loaded: true });
    void refreshTrailAttributeStatus({ runId, previewKey, requestSeq, force }).catch(() => {});
    return data;
  } catch (error) {
    if (requestSeq === state.trailUpdate.requestSeq) {
      if (!background) setTrailAttributeLoading(false);
      syncTrailAttributeActions(null);
      if (!background) setTrailAttributeStatus(uiText("排除案例加载失败，请稍后重试。", "Could not load excluded cases. Try again later."));
    }
    throw error;
  }
}

async function refreshTrailReviewAfterIssueCommit() {
  // The direct Issue-ID commit already persisted the Review exclusion marker
  // server-side.  Refresh the Review aggregate in the background without
  // switching tabs or putting the active Issue form into a loading state.
  try {
    await loadTrailAttributePreview(true);
    showToast(uiText("Review 排除汇总已自动刷新。", "Review exclusion summary refreshed automatically."));
  } catch (error) {
    showToast(uiText(
      "Trail 已提交，但 Review 汇总刷新失败；切换到 Review 页重试即可。",
      "Trail was committed, but the Review summary refresh failed; switch to Review and retry."
    ), true);
  }
}

function trailUpdateDraftText() {
  const draft = state.trailUpdate?.data?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

function trailIssueDraftText() {
  const draft = state.trailUpdate?.directData?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

const trailIssueImportState = {
  json: { preview: null, requestSeq: 0 },
  excel: { preview: null, requestSeq: 0 },
};

function trailIssueImportPrefix(mode) {
  return mode === "excel" ? "trailUpdateIssueExcelImport" : "trailUpdateIssueJsonImport";
}

function trailIssueImportElement(mode, suffix) {
  return $(`#${trailIssueImportPrefix(mode)}${suffix}`);
}

function trailIssueImportModeLabel(mode) {
  return mode === "excel"
    ? uiText("Excel", "Excel")
    : uiText("JSON", "JSON");
}

function setTrailIssueImportStatus(mode, message = "", error = false) {
  const status = trailIssueImportElement(mode, "Status");
  if (!status) return;
  status.textContent = message;
  status.classList.toggle("is-error", Boolean(error));
  status.classList.toggle("is-ready", Boolean(message) && !error);
}

function trailIssueImportStatusMeta(status) {
  const value = String(status || "invalid");
  if (value === "ready") {
    return { label: uiText("将导入", "Ready"), className: "is-ready" };
  }
  if (value === "skipped") {
    return { label: uiText("跳过", "Skipped"), className: "is-skipped" };
  }
  return { label: uiText("需修正", "Fix"), className: "is-invalid" };
}

function clearTrailIssueImportPreview(mode) {
  trailIssueImportState[mode].requestSeq += 1;
  trailIssueImportState[mode].preview = null;
  const preview = trailIssueImportElement(mode, "Preview");
  const summary = trailIssueImportElement(mode, "PreviewSummary");
  const rows = trailIssueImportElement(mode, "PreviewRows");
  const apply = trailIssueImportElement(mode, "Apply");
  if (preview) preview.hidden = true;
  if (summary) summary.textContent = "";
  if (rows) rows.innerHTML = "";
  if (apply) apply.disabled = true;
}

function renderTrailIssueImportPreview(mode, data) {
  const preview = trailIssueImportElement(mode, "Preview");
  const summaryNode = trailIssueImportElement(mode, "PreviewSummary");
  const rowsNode = trailIssueImportElement(mode, "PreviewRows");
  const apply = trailIssueImportElement(mode, "Apply");
  if (!preview || !summaryNode || !rowsNode || !apply) return;
  if (!data || typeof data !== "object") {
    clearTrailIssueImportPreview(mode);
    return;
  }
  const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
  const items = Array.isArray(data.items) ? data.items : [];
  const globalErrors = Array.isArray(data.global_errors) ? data.global_errors.filter(Boolean) : [];
  const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
  const sourceRows = Number(summary.source_row_count || 0);
  const ready = Number(summary.ready_count || 0);
  const skipped = Number(summary.skipped_count || 0);
  const invalid = Number(summary.invalid_count || 0);
  const message = String(summary.message || "");
  const countText = uiText(
    `源数据 ${sourceRows} 行 · 将导入 ${ready} · 跳过 ${skipped} · 需修正 ${invalid}`,
    `${sourceRows} source row(s) · ${ready} ready · ${skipped} skipped · ${invalid} to fix`
  );
  summaryNode.innerHTML = [
    `<strong>${escapeHtml(message || uiText("导入预览已生成。", "Import preview generated."))}</strong>`,
    `<small>${escapeHtml(countText)}</small>`,
    ...globalErrors.map((item) => `<small class="is-error">${escapeHtml(String(item))}</small>`),
    ...warnings.map((item) => `<small class="is-warning">${escapeHtml(String(item))}</small>`),
  ].join("");
  rowsNode.innerHTML = items.length
    ? items.map((item) => {
      const meta = trailIssueImportStatusMeta(item?.status);
      const source = historicalExclusionSource(item?.source);
      const sourceMarkup = source
        ? historicalExclusionSourceMarkup(source, "trail-update-import-preview-source")
        : `<div class="trail-update-import-preview-source" title="${escapeHtml(String(item?.source_label || ""))}">${escapeHtml(String(item?.source_label || "—"))}</div>`;
      const comment = String(item?.comment || "—");
      const shouldExclude = item?.should_exclude === true
        ? uiText("是", "Yes")
        : item?.should_exclude === false
          ? uiText("否", "No")
          : "—";
      return `<tr class="${meta.className}">
        <td>${escapeHtml(String(item?.row_number || "—"))}</td>
        <td><code>${escapeHtml(String(item?.issue_id || "—"))}</code></td>
        <td>${escapeHtml(shouldExclude)}</td>
        <td><div class="trail-update-import-preview-comment" title="${escapeHtml(comment)}">${escapeHtml(comment)}</div></td>
        <td>${sourceMarkup}</td>
        <td><span class="trail-update-import-preview-state ${meta.className}">${escapeHtml(meta.label)}</span><small class="trail-update-import-preview-message">${escapeHtml(String(item?.message || ""))}</small></td>
      </tr>`;
    }).join("")
    : `<tr><td class="trail-update-empty" colspan="6">${escapeHtml(uiText("没有可展示的导入行。", "No import rows to display."))}</td></tr>`;
  preview.hidden = false;
  apply.disabled = data.can_apply !== true;
}

function openTrailIssueImport(mode) {
  const dialog = trailIssueImportElement(mode, "Dialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    showToast(uiText(`${trailIssueImportModeLabel(mode)} 导入弹窗不可用。`, `${trailIssueImportModeLabel(mode)} import dialog is unavailable.`), true);
    return;
  }
  clearTrailIssueImportPreview(mode);
  setTrailIssueImportStatus(mode, "");
  if (!dialog.open) dialog.showModal();
  if (mode === "json") trailIssueImportElement(mode, "Text")?.focus();
  else trailIssueImportElement(mode, "ChooseFile")?.focus();
}

function closeTrailIssueImport(mode) {
  trailIssueImportElement(mode, "Dialog")?.close();
}

function applyTrailIssueImportPreview(mode) {
  const preview = trailIssueImportState[mode]?.preview;
  if (!preview?.can_apply) {
    setTrailIssueImportStatus(mode, uiText("请先生成无错误的导入预览。", "Build an error-free import preview first."), true);
    return false;
  }
  const entries = Array.isArray(preview.entries) ? preview.entries : [];
  if (!entries.length) {
    setTrailIssueImportStatus(mode, uiText("预览中没有可替换的屏蔽行。", "The preview has no shielding rows to replace."), true);
    return false;
  }
  const list = $("#trailUpdateIssueEntries");
  if (!list) {
    setTrailIssueImportStatus(mode, uiText("Issue 输入区不可用。", "Issue editor is unavailable."), true);
    return false;
  }
  list.innerHTML = entries.map((entry) => renderTrailIssueEntryRow(entry)).join("");
  syncTrailIssueEntryRemoveButtons();
  parseTrailIssueIds();
  clearTrailIssuePreview();
  closeTrailIssueImport(mode);
  setTrailIssueStatus(uiText(
    `已从 ${trailIssueImportModeLabel(mode)} 预览替换 ${entries.length} 个 Issue；尚未写入 Trail，请生成最终预览后确认。`,
    `${entries.length} Issues from the ${trailIssueImportModeLabel(mode)} preview replaced the draft; no Trail write has occurred. Build the final preview to continue.`
  ));
  showToast(uiText(
    `已替换 ${entries.length} 条屏蔽草稿；尚未写入 Trail。`,
    `${entries.length} shielding draft row(s) replaced; Trail has not been written.`
  ));
  return true;
}

async function importTrailIssueJsonFile(file) {
  if (!file) return;
  const text = typeof file.text === "function"
    ? await file.text()
    : await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result || ""));
      reader.onerror = () => reject(new Error(uiText("JSON 文件读取失败。", "Could not read the JSON file.")));
      reader.readAsText(file);
    });
  const textArea = trailIssueImportElement("json", "Text");
  if (textArea) textArea.value = text;
  const fileName = trailIssueImportElement("json", "FileName");
  if (fileName) fileName.textContent = file.name || uiText("已读取 JSON 文件。", "JSON file loaded.");
  clearTrailIssueImportPreview("json");
  setTrailIssueImportStatus("json", uiText("文件已读取，点击“生成导入预览”继续。", "File loaded; build the import preview to continue."));
}

async function previewTrailIssueJsonImport() {
  const raw = String(trailIssueImportElement("json", "Text")?.value || "").trim();
  if (!raw) {
    setTrailIssueImportStatus("json", uiText("请先粘贴 JSON 或选择文件。", "Paste JSON or choose a file first."), true);
    return null;
  }
  let body;
  try {
    body = JSON.parse(raw);
  } catch (_error) {
    setTrailIssueImportStatus("json", uiText("JSON 格式不合法，请粘贴对象或数组。", "Invalid JSON; paste an object or array."), true);
    return null;
  }
  if (!Array.isArray(body) && (!body || typeof body !== "object")) {
    setTrailIssueImportStatus("json", uiText("JSON 必须是对象或数组。", "JSON must be an object or array."), true);
    return null;
  }
  const button = trailIssueImportElement("json", "PreviewButton");
  const requestSeq = ++trailIssueImportState.json.requestSeq;
  button?.toggleAttribute("disabled", true);
  button?.setAttribute("aria-busy", "true");
  setTrailIssueImportStatus("json", uiText("正在解析 JSON 导入预览…", "Parsing JSON import preview…"));
  try {
    const data = await api("/api/trail-attribute-update/issue-import/json-preview", {
      method: "POST",
      body: JSON.stringify(body),
      allowReadOnlyMutation: true,
    });
    if (requestSeq !== trailIssueImportState.json.requestSeq) return data;
    trailIssueImportState.json.preview = data;
    renderTrailIssueImportPreview("json", data);
    const hasErrors = Boolean((data?.global_errors || []).length || Number(data?.summary?.invalid_count || 0));
    setTrailIssueImportStatus("json", String(data?.summary?.message || ""), hasErrors);
    return data;
  } catch (error) {
    if (requestSeq === trailIssueImportState.json.requestSeq) {
      setTrailIssueImportStatus("json", error?.message || uiText("JSON 导入预览失败。", "Could not preview the JSON import."), true);
    }
    return null;
  } finally {
    if (requestSeq === trailIssueImportState.json.requestSeq) {
      button?.toggleAttribute("disabled", false);
      button?.removeAttribute("aria-busy");
    }
  }
}

async function previewTrailIssueExcelImport() {
  const file = trailIssueImportElement("excel", "File")?.files?.[0];
  if (!file) {
    setTrailIssueImportStatus("excel", uiText("请先选择 .xlsx 或 .xlsm 文件。", "Choose a .xlsx or .xlsm file first."), true);
    return null;
  }
  const button = trailIssueImportElement("excel", "PreviewButton");
  const requestSeq = ++trailIssueImportState.excel.requestSeq;
  button?.toggleAttribute("disabled", true);
  button?.setAttribute("aria-busy", "true");
  setTrailIssueImportStatus("excel", uiText("正在解析 Excel 导入预览…", "Parsing Excel import preview…"));
  try {
    const form = new FormData();
    form.append("file", file, file.name || "issue-exclusions.xlsx");
    const data = await api("/api/trail-attribute-update/issue-import/excel-preview", {
      method: "POST",
      body: form,
      allowReadOnlyMutation: true,
    });
    if (requestSeq !== trailIssueImportState.excel.requestSeq) return data;
    trailIssueImportState.excel.preview = data;
    renderTrailIssueImportPreview("excel", data);
    const hasErrors = Boolean((data?.global_errors || []).length || Number(data?.summary?.invalid_count || 0));
    setTrailIssueImportStatus("excel", String(data?.summary?.message || ""), hasErrors);
    return data;
  } catch (error) {
    if (requestSeq === trailIssueImportState.excel.requestSeq) {
      setTrailIssueImportStatus("excel", error?.message || uiText("Excel 导入预览失败。", "Could not preview the Excel import."), true);
    }
    return null;
  } finally {
    if (requestSeq === trailIssueImportState.excel.requestSeq) {
      button?.toggleAttribute("disabled", false);
      button?.removeAttribute("aria-busy");
    }
  }
}

function bindTrailIssueImportEvents(mode) {
  const dialog = trailIssueImportElement(mode, "Dialog");
  trailIssueImportElement(mode, "Close")?.addEventListener("click", () => closeTrailIssueImport(mode));
  trailIssueImportElement(mode, "Cancel")?.addEventListener("click", () => closeTrailIssueImport(mode));
  dialog?.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeTrailIssueImport(mode);
  });
  trailIssueImportElement(mode, "PreviewButton")?.addEventListener("click", () => {
    void (mode === "excel" ? previewTrailIssueExcelImport() : previewTrailIssueJsonImport());
  });
  trailIssueImportElement(mode, "Apply")?.addEventListener("click", () => {
    applyTrailIssueImportPreview(mode);
  });
  trailIssueImportElement(mode, "ChooseFile")?.addEventListener("click", () => {
    trailIssueImportElement(mode, "File")?.click();
  });
  if (mode === "json") {
    trailIssueImportElement(mode, "Text")?.addEventListener("input", () => {
      clearTrailIssueImportPreview(mode);
      setTrailIssueImportStatus(mode, "");
    });
    trailIssueImportElement(mode, "File")?.addEventListener("change", (event) => {
      void importTrailIssueJsonFile(event.target?.files?.[0]).catch((error) => {
        setTrailIssueImportStatus(mode, error?.message || uiText("JSON 文件读取失败。", "Could not read the JSON file."), true);
      });
    });
    return;
  }
  trailIssueImportElement(mode, "File")?.addEventListener("change", (event) => {
    const file = event.target?.files?.[0];
    const fileName = trailIssueImportElement(mode, "FileName");
    if (fileName) {
      fileName.textContent = file?.name || uiText("尚未选择 Excel 文件。", "No Excel file selected.");
    }
    clearTrailIssueImportPreview(mode);
    setTrailIssueImportStatus(
      mode,
      file
        ? uiText("已选择文件，点击“生成导入预览”继续。", "File selected; build the import preview to continue.")
        : ""
    );
  });
}

function trailUpdateJsonContext(mode = state.trailUpdate?.tab || "review") {
  const direct = mode === "issue";
  const text = direct ? trailIssueDraftText() : trailUpdateDraftText();
  if (!text) return null;
  const run = state.trailUpdate?.data?.selected_run || {};
  const safeName = String(run.name || run.id || "run").replace(/[^A-Za-z0-9._-]+/g, "_");
  return {
    text,
    filename: direct ? "trail_issue_exclusion_update.json" : `trail_attribute_update_${safeName}.json`,
    title: direct ? uiText("Issue 屏蔽 JSON 预览", "Issue shielding JSON preview") : uiText("问题排除 JSON 预览", "Issue exclusion JSON preview"),
    subtitle: direct
      ? uiText("当前 Issue ID 屏蔽 Tab 的草稿；可复制或下载。", "Draft from the Issue shielding tab; copy or download it.")
      : uiText("当前 Review 排除汇总 Tab 的草稿；可复制或下载。", "Draft from the Review exclusion tab; copy or download it."),
  };
}

function openTrailUpdateJsonPreview() {
  const context = trailUpdateJsonContext();
  if (!context) {
    showToast(uiText("当前没有可预览的 JSON 草稿。", "There is no JSON draft to preview."), true);
    return;
  }
  const dialog = $("#trailUpdateJsonDialog");
  const preview = $("#trailUpdateJsonPreview");
  if (!dialog || !preview || typeof dialog.showModal !== "function") {
    showToast(uiText("JSON 预览弹窗不可用。", "The JSON preview dialog is unavailable."), true);
    return;
  }
  state.trailUpdate.jsonPreview = context;
  const title = $("#trailUpdateJsonTitle");
  const subtitle = $("#trailUpdateJsonSubtitle");
  if (title) title.textContent = context.title;
  if (subtitle) subtitle.textContent = context.subtitle;
  preview.textContent = context.text;
  if (!dialog.open) dialog.showModal();
}

function trailUpdateJsonForAction() {
  return state.trailUpdate?.jsonPreview || trailUpdateJsonContext();
}

function downloadTrailUpdateJson() {
  const context = trailUpdateJsonForAction();
  if (!context) return;
  const blob = new Blob([context.text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = context.filename;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyTrailUpdateJson() {
  const context = trailUpdateJsonForAction();
  if (!context) return;
  if (!navigator.clipboard?.writeText) throw new Error(uiText("当前浏览器不支持复制。", "Clipboard is unavailable in this browser."));
  await navigator.clipboard.writeText(context.text);
  showToast(uiText("已复制 JSON。", "JSON copied."));
}

let trailUpdateProgressTimer = null;
let trailUpdateProgressCloseTimer = null;

const TRAIL_UPDATE_PROGRESS_STAGES = [
  { key: "prepare", zh: "校验预览", en: "Validate preview" },
  { key: "request", zh: "连接 Trail 接口", en: "Connect to Trail" },
  { key: "write", zh: "分批写入字段与排除说明", en: "Write fields and exclusion notes in batches" },
  { key: "readback", zh: "批量回读并校验", en: "Read back and verify" },
  { key: "done", zh: "完成", en: "Complete" },
];

function trailUpdateProgressStageIndex(key) {
  const index = TRAIL_UPDATE_PROGRESS_STAGES.findIndex((item) => item.key === key);
  return index >= 0 ? index : 0;
}

function trailUpdateProgressSetStage(key, detail = "") {
  const index = trailUpdateProgressStageIndex(key);
  const progress = state.trailUpdate?.progress;
  if (progress) {
    progress.stage = key;
    progress.stageIndex = index;
    progress.detail = detail;
  }
  const dialog = $("#trailUpdateProgressDialog");
  if (!dialog) return;
  dialog.dataset.stage = key;
  const bar = $("#trailUpdateProgressBar");
  if (bar) {
    const percent = key === "done" ? 100 : Math.max(10, Math.round((index / (TRAIL_UPDATE_PROGRESS_STAGES.length - 1)) * 86));
    bar.style.width = `${percent}%`;
    bar.parentElement?.setAttribute("aria-valuenow", String(percent));
  }
  dialog.querySelectorAll("[data-trail-progress-stage]").forEach((node, nodeIndex) => {
    const active = nodeIndex === index;
    const complete = nodeIndex < index || key === "done";
    node.classList.toggle("is-active", active && key !== "done");
    node.classList.toggle("is-complete", complete);
    node.classList.toggle("is-pending", !active && !complete);
    node.setAttribute("aria-current", active ? "step" : "false");
  });
  const title = $("#trailUpdateProgressTitle");
  const message = $("#trailUpdateProgressMessage");
  if (title) title.textContent = key === "done"
    ? uiText("Trail 更新完成", "Trail update complete")
    : uiText("正在提交到 Trail", "Submitting to Trail");
  if (message) {
    message.textContent = detail || (key === "request"
      ? uiText("服务端正在分批写入；完成后会统一回读，请不要重复提交。", "The server is writing in batches; it will read back once complete. Do not submit again.")
      : uiText(TRAIL_UPDATE_PROGRESS_STAGES[index]?.zh || "正在处理…", TRAIL_UPDATE_PROGRESS_STAGES[index]?.en || "Working…"));
  }
}

function trailUpdateProgressElapsed() {
  const elapsed = $("#trailUpdateProgressElapsed");
  const startedAt = Number(state.trailUpdate?.progress?.startedAt || 0);
  if (!elapsed || !startedAt) return;
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
  elapsed.textContent = uiText(`已用时 ${seconds}s`, `${seconds}s elapsed`);
}

function openTrailUpdateProgress({ mode = "review", total = 0 } = {}) {
  const dialog = $("#trailUpdateProgressDialog");
  if (!dialog || typeof dialog.showModal !== "function") return;
  window.clearInterval(trailUpdateProgressTimer);
  window.clearTimeout(trailUpdateProgressCloseTimer);
  state.trailUpdate.progress = {
    active: true,
    mode,
    total: Number(total || 0),
    startedAt: Date.now(),
    stage: "prepare",
    stageIndex: 0,
  };
  dialog.dataset.mode = mode;
  dialog.dataset.running = "true";
  const count = $("#trailUpdateProgressCount");
  if (count) count.textContent = total ? uiText(`${total} 个 Issue`, `${total} Issues`) : "";
  const close = $("#trailUpdateProgressClose");
  if (close) close.hidden = true;
  const bar = $("#trailUpdateProgressBar");
  if (bar) bar.style.width = "10%";
  const track = bar?.parentElement;
  track?.classList.add("is-running");
  trailUpdateProgressSetStage("prepare", uiText("已确认预览指纹，准备提交。", "Preview fingerprint confirmed; preparing commit."));
  trailUpdateProgressTimer = window.setInterval(trailUpdateProgressElapsed, 500);
  trailUpdateProgressElapsed();
  if (!dialog.open) dialog.showModal();
}

function finishTrailUpdateProgress({ ok = false, warning = false, message = "" } = {}) {
  const dialog = $("#trailUpdateProgressDialog");
  const progress = state.trailUpdate?.progress;
  if (progress) {
    progress.active = false;
    progress.finishedAt = Date.now();
    progress.ok = Boolean(ok);
  }
  window.clearInterval(trailUpdateProgressTimer);
  trailUpdateProgressTimer = null;
  const bar = $("#trailUpdateProgressBar");
  bar?.parentElement?.classList.remove("is-running");
  if (bar) {
    bar.style.width = ok ? "100%" : "34%";
    bar.parentElement?.setAttribute("aria-valuenow", ok ? "100" : "34");
  }
  if (dialog) {
    dialog.dataset.running = "false";
    dialog.dataset.result = ok ? (warning ? "warning" : "success") : "error";
    trailUpdateProgressSetStage(ok ? "done" : "request", message || (ok
      ? uiText("字段和回读结果已返回。", "Field and readback results are ready.")
      : uiText("提交失败，请关闭弹窗查看错误信息。", "The commit failed; close this dialog to inspect the error.")));
    const title = $("#trailUpdateProgressTitle");
    if (title) {
      title.textContent = !ok
        ? uiText("Trail 更新失败", "Trail update failed")
        : warning
          ? uiText("Trail 更新完成（看板同步提示）", "Trail update complete (dashboard sync notice)")
          : uiText("Trail 更新完成", "Trail update complete");
    }
    const close = $("#trailUpdateProgressClose");
    if (close) close.hidden = false;
    if (ok && !warning) {
      trailUpdateProgressCloseTimer = window.setTimeout(() => {
        if (dialog.open) dialog.close();
      }, 900);
    }
  }
}

function closeTrailUpdateProgress() {
  window.clearInterval(trailUpdateProgressTimer);
  window.clearTimeout(trailUpdateProgressCloseTimer);
  trailUpdateProgressTimer = null;
  trailUpdateProgressCloseTimer = null;
  const dialog = $("#trailUpdateProgressDialog");
  if (dialog?.open) dialog.close();
  if (state.trailUpdate?.progress) state.trailUpdate.progress.active = false;
}

let trailUpdateConfirmResolver = null;

function trailUpdateConfirmClose(confirmed = false) {
  const dialog = $("#trailUpdateConfirmDialog");
  const resolve = trailUpdateConfirmResolver;
  trailUpdateConfirmResolver = null;
  if (dialog?.open) dialog.close();
  if (resolve) resolve(Boolean(confirmed));
}

function trailUpdateConfirmPatch(item, infoField) {
  const updates = item?.field_updates;
  if (updates && typeof updates === "object" && updates[infoField] && typeof updates[infoField] === "object") {
    return updates[infoField];
  }
  const update = item?.field_update || {};
  if (update.patch && typeof update.patch === "object") return update.patch;
  if (item?.target?.patch && typeof item.target.patch === "object") return item.target.patch;
  return {};
}

function trailUpdateConfirmCompact(value) {
  try {
    const text = JSON.stringify(value ?? {}, (_key, entry) => entry === undefined ? null : entry);
    return text && text !== "{}" ? text : "{}";
  } catch (_error) {
    return "{}";
  }
}

function trailUpdateConfirmSetExpanded(expanded = false) {
  const dialog = $("#trailUpdateConfirmDialog");
  const details = [...(dialog?.querySelectorAll(".trail-update-confirm-item") || [])];
  details.forEach((item) => {
    item.open = Boolean(expanded);
  });
  const button = $("#trailUpdateConfirmExpand");
  if (!button) return;
  button.hidden = details.length === 0;
  button.dataset.expanded = expanded ? "true" : "false";
  button.innerHTML = expanded
    ? '<span class="ui-lang-zh">收起全部</span><span class="ui-lang-en">Collapse all</span>'
    : '<span class="ui-lang-zh">展开全部</span><span class="ui-lang-en">Expand all</span>';
}

function openTrailUpdateConfirm({ mode = "review", data = {} } = {}) {
  const dialog = $("#trailUpdateConfirmDialog");
  if (!dialog || typeof dialog.showModal !== "function") {
    showToast(uiText("确认弹窗不可用，已取消写入。", "The confirmation dialog is unavailable; write cancelled."), true);
    return Promise.resolve(false);
  }
  if (trailUpdateConfirmResolver) trailUpdateConfirmClose(false);
  const directMode = mode === "direct_issue_ids" || data?.mode === "direct_issue_ids";
  const allItems = Array.isArray(data?.items) ? data.items : [];
  // The server rechecks this state immediately before the write, but make the
  // confirmation surface match the operation: only rows whose dashboard
  // marker *or* exclusion note differs from Trail will be submitted.
  const items = allItems.filter((item) => item?.trail_update_status === "pending");
  const skippedSyncedCount = Math.max(0, allItems.length - items.length);
  const infoField = String(
    data?.target_field
      || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1])
      || "ra_stuck_auto_result_info"
  );
  const targetSpec = trailUpdateTargetSpec(data);
  const resultField = String(data?.model_result_field || "ra_stuck_auto_result");
  const infoOnly = data?.write_mode === "info_only" || directMode;
  const count = Number(data?.pending_count ?? items.length);
  const run = data?.selected_run || {};
  const runLabel = directMode
    ? uiText("Issue ID 屏蔽", "Shield by Issue ID")
    : String(run.name || run.id || uiText("全部 Model Runs", "All model Runs"));
  const baselineLabel = Array.isArray(data?.baselines) && data.baselines.length
    ? data.baselines.join(" + ")
    : uiText("当前数据集", "Selected dataset");
  const digest = String(data?.payload_sha256 || "");

  const subtitle = $("#trailUpdateConfirmSubtitle");
  if (subtitle) subtitle.textContent = uiText(
    directMode ? "请核对要屏蔽的 Issue 和 info 标记。" : "请核对本次即将写入的 Issue、字段和预览指纹。",
    directMode ? "Review the Issues and info marker before shielding." : "Review the Issues, fields, and preview fingerprint before committing."
  );
  const bannerTitle = $("#trailUpdateConfirmBannerTitle");
  const bannerText = $("#trailUpdateConfirmBannerText");
  if (bannerTitle) bannerTitle.textContent = infoOnly
    ? uiText(`仅写 ${targetSpec.fullPath}`, `Info only · ${targetSpec.fullPath}`)
    : uiText(`写入 ${resultField} + ${targetSpec.fullPath}`, `Write ${resultField} + ${targetSpec.fullPath}`);
  if (bannerText) bannerText.textContent = infoOnly
    ? uiText(
      directMode
        ? "模型 label 保持不变；info 使用 deep_merge；Trail 回读成功后同步判错复核“应该排除”。"
        : "模型 label 保持不变；info 使用 deep_merge。",
      directMode
        ? "Model label stays unchanged; info is deep-merged; after Trail readback, Review ‘Exclude’ is synchronized."
        : "Model label stays unchanged; info is deep-merged."
    )
    : uiText("模型 label 和 info 将按预览写入。", "Model label and info will be written as previewed.");

  const summary = $("#trailUpdateConfirmSummary");
  if (summary) {
    const cards = [
      [uiText("提交模式", "Mode"), directMode ? uiText("Issue ID 屏蔽", "Issue shielding") : uiText("Review 排除汇总", "Review summary")],
      [uiText("Issue 数量", "Issues"), String(count)],
      [directMode ? uiText("目标字段", "Target field") : uiText("Run / 数据集", "Run / dataset"), directMode ? targetSpec.fullPath : `${runLabel} · ${baselineLabel}`],
    ];
    summary.innerHTML = cards.map(([label, value]) => `<div><small>${escapeHtml(label)}</small><strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong></div>`).join("");
  }

  const list = $("#trailUpdateConfirmList");
  const listCount = $("#trailUpdateConfirmListCount");
  const shownItems = items.slice(0, 12);
  if (listCount) listCount.textContent = uiText(
    `${count > shownItems.length ? `共 ${count} 条，展示前 ${shownItems.length} 条` : `共 ${count} 条`}${skippedSyncedCount ? `；已同步跳过 ${skippedSyncedCount} 条` : ""}`,
    `${count > shownItems.length ? `${count} total · first ${shownItems.length} shown` : `${count} item(s)`}${skippedSyncedCount ? `; ${skippedSyncedCount} synced item(s) skipped` : ""}`
  );
  if (list) {
    list.innerHTML = shownItems.length
      ? shownItems.map((item) => {
        const issueId = String(item?.issue_id || "—");
        const currentLabel = directMode
          ? (item?.current_should_exclude ? uiText("已屏蔽", "Already shielded") : uiText("未屏蔽", "Not shielded"))
          : String(item?.model?.label || item?.review?.status || uiText("排除候选", "Excluded candidate"));
        const patch = trailUpdateConfirmCompact(trailUpdateConfirmPatch(item, infoField));
        const clippedPatch = patch.length > 420 ? `${patch.slice(0, 417)}…` : patch;
        const sourceMarkup = directMode ? historicalExclusionSourceMarkup(item?.source) : "";
        return `<details class="trail-update-confirm-item"><summary><div><strong>${escapeHtml(issueId)}</strong><small>${escapeHtml(currentLabel)}</small></div><div><code title="${escapeHtml(patch)}">${escapeHtml(`${infoField} = ${clippedPatch}`)}</code><small>${escapeHtml(uiText("点击展开完整 patch · deep_merge · label 不变", "Click to expand full patch · deep_merge · label unchanged"))}</small></div></summary><div class="trail-update-confirm-item-details"><small>${escapeHtml(uiText("完整字段 patch", "Full field patch"))}</small><pre>${escapeHtml(`${infoField} = ${patch}`)}</pre>${sourceMarkup}</div></details>`;
      }).join("")
      : `<div class="trail-update-confirm-empty">${escapeHtml(uiText("没有可提交的 Issue。", "No Issues are ready to commit."))}</div>`;
    trailUpdateConfirmSetExpanded(false);
  }

  const note = $("#trailUpdateConfirmNote");
  if (note) note.textContent = uiText(
    `${infoOnly ? `仅更新 ${targetSpec.fullPath}，不改模型 label。${directMode ? ` Trail 回读成功后同步判错复核“应该排除”。` : ""}` : `将更新 ${resultField} 和 ${targetSpec.fullPath}。`}提交前会再次校验预览指纹${digest ? `（${digest.slice(0, 12)}…）` : ""}。`,
    `${infoOnly ? `Only ${targetSpec.fullPath} will be updated; model labels stay unchanged.${directMode ? " Review ‘Exclude’ will be synchronized after Trail readback. " : " "}` : `Both ${resultField} and ${targetSpec.fullPath} will be updated. `}The preview fingerprint will be checked again before commit${digest ? ` (${digest.slice(0, 12)}…)` : ""}.`
  );
  dialog.dataset.confirmMode = directMode ? "direct_issue_ids" : "review";
  return new Promise((resolve) => {
    trailUpdateConfirmResolver = resolve;
    dialog.showModal();
  });
}

function renderTrailIssuePreview(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const missing = Array.isArray(data?.missing_issue_ids) ? data.missing_issue_ids : [];
  const invalid = Array.isArray(data?.invalid_issue_ids) ? data.invalid_issue_ids : [];
  const capability = data?.trail_capability || {};
  setTrailAttributeCapability(data);
  const results = $("#trailUpdateIssueResults");
  if (results) results.hidden = false;
  $("#trailUpdateIssueCount").textContent = String(items.length);
  $("#trailUpdateIssueMissingCount").textContent = String(missing.length + invalid.length);
  $("#trailUpdateIssueSummary").textContent = uiText(
    `${data?.requested_issue_ids?.length || 0} 条请求；${items.length} 条可写`,
    `${data?.requested_issue_ids?.length || 0} requested; ${items.length} writable`
  );
  const targetSpec = renderTrailUpdateTargetField(data, "trailUpdateIssueField");
  const statusText = data?.write_status === "ready"
    ? uiText(`已生成屏蔽预览：${items.length} 条，可提交。`, `Shield preview ready: ${items.length} item(s); commit is available.`)
    : uiText(
      `已生成预览：${items.length} 条；${missing.length ? `未找到 ${missing.length} 条。` : ""}${capability.message || "当前不可写入 Trail"}`,
      `Preview ready: ${items.length} item(s); ${missing.length ? `${missing.length} missing. ` : ""}${capability.message || "Trail is not writable yet."}`
    );
  setTrailIssueStatus(statusText);
  const body = $("#trailUpdateIssueTableBody");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("没有可写的 Issue，请检查 ID 和 Trail view。", "No writable Issues; check IDs and the Trail view.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const target = item.target || {};
    const patchPath = target.path || "ra_triage_dashboard.should_exclude";
    const currentState = item.current_should_exclude
      ? uiText("已屏蔽", "Shielded")
      : uiText("未屏蔽", "Not shielded");
    const shortPath = patchPath.split(".").filter(Boolean).pop() || patchPath;
    const release = String(
      item.baseline_id
        || (typeof baselineLabelForScope === "function" ? baselineLabelForScope(item.baseline_scope) : "")
        || item.baseline_scope
        || "—"
    );
    const comment = String(item.comment || "").trim();
    const commentHint = item.comment_defaulted
      ? uiText("自动说明 · 写入 info.ra_triage_dashboard.should_exclude_comment", "Auto note · saved in info.ra_triage_dashboard.should_exclude_comment")
      : uiText("写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment");
    const dashboardPatch = target.patch?.ra_triage_dashboard || {};
    const commentPatch = String(dashboardPatch.should_exclude_comment || "").trim();
    const infoPreview = [
      `${shortPath} = true`,
      commentPatch ? `should_exclude_comment = ${commentPatch}` : "",
    ].filter(Boolean).join("; ");
    return `<tr>
      <td data-label="Issue"><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong></td>
      <td data-label="数据集版本" class="trail-update-release-cell" title="${escapeHtml(item.baseline_scope || release)}"><strong>${escapeHtml(release)}</strong></td>
      <td data-label="当前模型 label">${labelBadge(item.current_label, "未输出")}</td>
      <td data-label="当前屏蔽状态"><span class="trail-update-state-badge ${item.current_should_exclude ? "is-on" : ""}">${escapeHtml(currentState)}</span></td>
      <td data-label="预计写入 info" class="trail-update-info-cell"><strong title="${escapeHtml(targetSpec.fullPath)}">${escapeHtml(shortPath)}</strong><small>${uiText("info-only · label 不变", "info-only · label unchanged")}</small><code title="${escapeHtml(infoPreview)}">${escapeHtml(infoPreview)}</code></td>
      <td data-label="Comment"><div class="trail-update-comment" title="${escapeHtml(comment)}">${escapeHtml(comment || "—")}</div>${historicalExclusionSourceMarkup(item.source)}<small>${commentHint}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailIssuePreview() {
  const parsed = parseTrailIssueIds();
  if (parsed.invalid.length || !parsed.ids.length) {
    clearTrailIssuePreview(uiText("请先填写合法的 Issue ID（每行可填多个）。", "Enter valid Issue IDs first (multiple per row are supported)."));
    return null;
  }
  const requestSeq = ++state.trailUpdate.directRequestSeq;
  setTrailIssueStatus(uiText("正在检查 Issue 和 Trail 字段…", "Checking Issues and Trail fields…"));
  $("#trailUpdateIssuePreviewButton")?.toggleAttribute("disabled", true);
  try {
    const data = await api("/api/trail-attribute-update/issue-preview", {
      method: "POST",
      allowReadOnlyMutation: true,
      body: JSON.stringify({ entries: parsed.entries }),
    });
    if (requestSeq !== state.trailUpdate.directRequestSeq) return data;
    state.trailUpdate.directData = data;
    renderTrailIssuePreview(data);
    syncTrailIssueActions(data);
    return data;
  } catch (error) {
    if (requestSeq === state.trailUpdate.directRequestSeq) {
      setTrailIssueStatus(error?.message || uiText("屏蔽预览失败。", "Shield preview failed."));
    }
    throw error;
  } finally {
    if (requestSeq === state.trailUpdate.directRequestSeq) $("#trailUpdateIssuePreviewButton")?.toggleAttribute("disabled", false);
  }
}

async function commitTrailIssueExclusion() {
  const data = state.trailUpdate?.directData;
  if (!trailUpdateWriteReady(data)) return;
  const ids = Array.isArray(data.requested_issue_ids) ? data.requested_issue_ids : [];
  const entries = Array.isArray(data.requested_entries)
    ? data.requested_entries
    : ids.map((issueId) => ({ issue_id: issueId, comment: data.comment || "" }));
  const pendingCount = Number(data?.pending_count ?? data?.items?.filter(
    (item) => item?.trail_update_status === "pending"
  ).length ?? ids.length);
  if (!await openTrailUpdateConfirm({ mode: "direct_issue_ids", data })) return;
  const button = $("#trailUpdateIssueCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailIssueStatus(uiText("正在写入 Trail 字段和 info 排除说明…", "Writing Trail fields and info notes…"));
  openTrailUpdateProgress({ mode: "issue", total: pendingCount });
  trailUpdateProgressSetStage("request");
  try {
    const result = await api("/api/trail-attribute-update/issue-commit", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        entries,
        payload_sha256: data.payload_sha256,
      }),
    });
    const stats = result?.stats || {};
    const readback = result?.readback || {};
    const localReview = result?.local_review || {};
    const trailOk = typeof result?.trail_ok === "boolean" ? result.trail_ok : Boolean(result?.ok);
    const outsideDashboard = Array.isArray(localReview.not_in_dashboard_issue_ids)
      ? localReview.not_in_dashboard_issue_ids
      : [];
    const localFailures = Array.isArray(localReview.failed_issue_ids)
      ? localReview.failed_issue_ids
      : [];
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    const localMarked = Number(localReview.marked_count || 0) + Number(localReview.already_excluded_count || 0);
    const localTargetCount = Math.max(0, Number(localReview.requested_count || 0) - outsideDashboard.length);
    const localReviewText = outsideDashboard.length
      ? uiText(
        `看板“应该排除” ${localMarked}/${localTargetCount}；${outsideDashboard.length} 条不在当前看板`,
        `Review “Exclude” ${localMarked}/${localTargetCount}; ${outsideDashboard.length} outside this dashboard`
      )
      : uiText(
        `看板“应该排除” ${localMarked}/${localReview.requested_count || 0}`,
        `Review “Exclude” ${localMarked}/${localReview.requested_count || 0}`
      );
    const localReviewWithFailures = localFailures.length
      ? `${localReviewText}${uiText(`；本地标记失败 ${localFailures.length} 条`, `; ${localFailures.length} local mark failures`)}`
      : localReviewText;
    const progressMessage = uiText(
      `字段与 info 排除说明 ${stats.success_count || 0}/${stats.total || pendingCount}；${readbackText}；${localReviewWithFailures}。`,
      `Trail fields and info notes ${stats.success_count || 0}/${stats.total || pendingCount}; ${readbackText}; ${localReviewWithFailures}.`
    );
    const localSyncWarning = outsideDashboard.length > 0 || localFailures.length > 0;
    finishTrailUpdateProgress({ ok: trailOk, warning: trailOk && localSyncWarning, message: progressMessage });
    setTrailIssueStatus(uiText(
      `屏蔽完成：字段与 info 排除说明成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}；${readbackText}；${localReviewWithFailures}。`,
      `Shield finished: fields and info notes ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; ${readbackText}; ${localReviewWithFailures}.`
    ));
    showToast(
      !trailOk
        ? uiText("Issue 屏蔽未完整写入，请查看 Trail 回读明细。", "Issue shielding is incomplete; inspect Trail readback.")
        : localSyncWarning
          ? outsideDashboard.length
            ? uiText(`Trail 已完成；${outsideDashboard.length} 条不在当前看板，未创建本地 Review 排除标记。`, `Trail completed; ${outsideDashboard.length} Issues are outside this dashboard and have no local Review mark.`)
            : uiText(`Trail 已完成；本地 Review 排除标记失败 ${localFailures.length} 条。`, `Trail completed; ${localFailures.length} local Review exclusion marks failed.`)
          : uiText("Issue 屏蔽已提交，Trail 与判错复核排除标记均已更新。", "Issue shielding and Review exclusion marks were updated."),
      !trailOk
    );
    if (readback.complete && Number(localReview.requested_count || 0) > 0) {
      void refreshTrailReviewAfterIssueCommit();
    }
    void loadTrailIssueHistory();
  } catch (error) {
    finishTrailUpdateProgress({ ok: false, message: error?.message || uiText("屏蔽失败，请稍后重试。", "Shielding failed; try again later.") });
    setTrailIssueStatus(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."));
    showToast(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."), true);
  } finally {
    syncTrailIssueActions(data);
  }
}

async function commitTrailAttributeUpdate() {
  const data = state.trailUpdate?.data;
  if (!trailUpdateWriteReady(data)) return;
  if (!await openTrailUpdateConfirm({ mode: "review", data })) return;
  const button = $("#trailUpdateCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailAttributeStatus(uiText("正在提交 Trail 属性…", "Committing Trail info…"));
  openTrailUpdateProgress({ mode: "review", total: Number(data?.pending_count ?? data?.count ?? data?.items?.length ?? 0) });
  trailUpdateProgressSetStage("request");
  try {
    const result = await api("/api/trail-attribute-update/commit", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        model_run_id: data.selected_run?.id || state.trailUpdate.runId,
        baselines: data.baselines || [],
        payload_sha256: data.payload_sha256,
      }),
    });
    const stats = result?.stats || {};
    const readback = result?.readback || {};
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    const progressMessage = uiText(
      `字段与 info 排除说明 ${stats.success_count || 0}/${stats.total || data?.items?.length || 0}；${readbackText}。`,
      `Trail fields and info notes ${stats.success_count || 0}/${stats.total || data?.items?.length || 0}; ${readbackText}.`
    );
    finishTrailUpdateProgress({ ok: Boolean(result?.ok), message: progressMessage });
    setTrailAttributeStatus(uiText(
      `Trail 更新完成：字段与 info 排除说明成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}；${readbackText}。`,
      `Trail update finished: fields and info notes ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; ${readbackText}.`
    ));
    showToast(
      result?.ok
        ? uiText("Trail 属性更新已完成并回读确认。", "Trail attributes updated and read back.")
        : uiText("Trail 属性更新部分失败，请查看回读和失败明细。", "Trail attribute update is incomplete; inspect readback and failures."),
      !result?.ok
    );
    if (result?.ok) {
      const runId = String(data?.selected_run?.id || state.trailUpdate?.runId || "").trim();
      void refreshTrailAttributeStatus({
        runId,
        previewKey: trailUpdatePreviewKey(runId),
        requestSeq: state.trailUpdate.requestSeq,
        force: true,
      }).catch(() => {});
    }
  } catch (error) {
    finishTrailUpdateProgress({ ok: false, message: error?.message || uiText("提交失败，请稍后重试。", "Commit failed; try again later.") });
    setTrailAttributeStatus(error?.message || uiText("Trail 更新失败。", "Trail update failed."));
    showToast(error?.message || uiText("Trail 更新失败。", "Trail update failed."), true);
  } finally {
    syncTrailAttributeActions(data);
  }
}

function bindTrailAttributeUpdateEvents() {
  $("#trailUpdateProgressClose")?.addEventListener("click", closeTrailUpdateProgress);
  $("#trailUpdateProgressDialog")?.addEventListener("cancel", (event) => {
    const dialog = $("#trailUpdateProgressDialog");
    if (dialog?.dataset.running === "true") {
      event.preventDefault();
      return;
    }
    closeTrailUpdateProgress();
  });
  $("#trailUpdateProgressDialog")?.addEventListener("close", () => {
    window.clearInterval(trailUpdateProgressTimer);
    window.clearTimeout(trailUpdateProgressCloseTimer);
    trailUpdateProgressTimer = null;
    trailUpdateProgressCloseTimer = null;
    if (state.trailUpdate?.progress) state.trailUpdate.progress.active = false;
  });
  $("#trailUpdateConfirmClose")?.addEventListener("click", () => trailUpdateConfirmClose(false));
  $("#trailUpdateConfirmCancel")?.addEventListener("click", () => trailUpdateConfirmClose(false));
  $("#trailUpdateConfirmSubmit")?.addEventListener("click", () => trailUpdateConfirmClose(true));
  $("#trailUpdateConfirmExpand")?.addEventListener("click", () => {
    const button = $("#trailUpdateConfirmExpand");
    trailUpdateConfirmSetExpanded(button?.dataset.expanded !== "true");
  });
  $("#trailUpdateConfirmDialog")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    trailUpdateConfirmClose(false);
  });
  $("#trailUpdateConfirmDialog")?.addEventListener("close", () => {
    if (trailUpdateConfirmResolver) trailUpdateConfirmClose(false);
  });
  document.querySelectorAll("[data-trail-update-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTab = button.dataset.trailUpdateTab || "review";
      setTrailUpdateTab(nextTab);
      if (nextTab === "issue") void loadTrailIssueHistory();
      if (typeof pageUrl === "function") {
        history.replaceState(
          { page: "trail-update" },
          "",
          pageUrl("trail-update", { runId: state.trailUpdate?.runId || "" })
        );
      }
    });
  });
  const select = $("#trailUpdateRunSelect");
  select?.addEventListener("change", () => {
    state.trailUpdate.runId = String(select.value || "");
    state.trailUpdate.page = 1;
    clearTrailAttributePreview();
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId: state.trailUpdate.runId }));
    }
    loadTrailAttributePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateFilterForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    state.trailUpdate.filters.search = String($("#trailUpdateSearchInput")?.value || "");
    applyTrailUpdateFilters();
  });
  $("#trailUpdateSearchInput")?.addEventListener("input", scheduleTrailUpdateFilterRender);
  $("#trailUpdateResetFiltersButton")?.addEventListener("click", () => {
    state.trailUpdate.filters = {
      search: "",
      gtLabel: [],
      modelLabel: [],
      reviewer: [],
      reviewStatus: [],
      trailStatus: [],
    };
    const search = $("#trailUpdateSearchInput");
    if (search) search.value = "";
    applyTrailUpdateFilters();
  });
  $("#trailUpdatePagePrevious")?.addEventListener("click", () => {
    goToTrailUpdatePage((Number(state.trailUpdate?.page) || 1) - 1);
  });
  $("#trailUpdatePageNext")?.addEventListener("click", () => {
    goToTrailUpdatePage((Number(state.trailUpdate?.page) || 1) + 1);
  });
  const pageJump = $("#trailUpdatePageJump");
  const jumpTrailUpdatePage = () => goToTrailUpdatePage(pageJump?.value);
  $("#trailUpdatePageJumpButton")?.addEventListener("click", jumpTrailUpdatePage);
  pageJump?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      jumpTrailUpdatePage();
    }
  });
  $("#trailUpdatePageSize")?.addEventListener("change", (event) => {
    const nextSize = Number(event.currentTarget?.value);
    state.trailUpdate.pageSize = CASE_PAGE_SIZES.includes(nextSize)
      ? nextSize
      : DEFAULT_CASE_PAGE_SIZE;
    applyTrailUpdateFilters();
  });
  $("#trailUpdateCommitButton")?.addEventListener("click", () => {
    commitTrailAttributeUpdate().catch((error) => showToast(error.message, true));
  });
  document.querySelectorAll("[data-trail-json-preview]").forEach((button) => {
    button.addEventListener("click", openTrailUpdateJsonPreview);
  });
  $("#trailUpdateJsonClose")?.addEventListener("click", () => $("#trailUpdateJsonDialog")?.close());
  $("#trailUpdateJsonCancel")?.addEventListener("click", () => $("#trailUpdateJsonDialog")?.close());
  $("#trailUpdateJsonDownload")?.addEventListener("click", downloadTrailUpdateJson);
  $("#trailUpdateJsonCopy")?.addEventListener("click", () => {
    copyTrailUpdateJson().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateJsonDialog")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    $("#trailUpdateJsonDialog")?.close();
  });
  $("#trailUpdateIssueAddButton")?.addEventListener("click", () => {
    addTrailIssueEntryRow();
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssueClearAllButton")?.addEventListener("click", clearTrailIssueEntries);
  $("#trailUpdateIssueJsonImportButton")?.addEventListener("click", () => openTrailIssueImport("json"));
  $("#trailUpdateIssueExcelImportButton")?.addEventListener("click", () => openTrailIssueImport("excel"));
  bindTrailIssueImportEvents("json");
  bindTrailIssueImportEvents("excel");
  $("#trailUpdateIssueEntries")?.addEventListener("input", (event) => {
    const target = event.target;
    const row = target?.closest?.("[data-trail-issue-entry-row]");
    if (row && target?.matches?.("[data-trail-issue-entry-id], [data-trail-issue-entry-comment]")) {
      // Editing a source-loaded row deliberately turns it into a manual row;
      // server-side validation then cannot attribute user-edited text to the
      // historical workbook.
      clearTrailIssueEntrySource(row);
    }
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssueEntries")?.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-trail-issue-entry-remove]");
    if (!remove || remove.disabled) return;
    remove.closest("[data-trail-issue-entry-row]")?.remove();
    syncTrailIssueEntryRemoveButtons();
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssuePreviewButton")?.addEventListener("click", () => {
    loadTrailIssuePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateIssueCommitButton")?.addEventListener("click", () => {
    commitTrailIssueExclusion().catch((error) => showToast(error.message, true));
  });
  setTrailUpdateTab(state.trailUpdate?.tab || "review");
  void loadTrailIssueHistory();
  $("#trailUpdateIssueHistoryRefresh")?.addEventListener("click", () => {
    void loadTrailIssueHistory();
  });
  parseTrailIssueIds();
  setTrailAttributeCapability(null);
  renderTrailAttributeRunPicker();
}
