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
      <textarea data-trail-issue-entry-comment data-mention-composer rows="2" placeholder="留空时使用默认说明；输入 @ 可通知同事；提交后写入 info.ra_triage_dashboard.should_exclude_comment。">${comment}</textarea>
      <div class="review-mention-composer" data-mention-composer-root aria-live="polite"></div>
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
  bindReviewMentionComposer(
    row?.querySelector("[data-trail-issue-entry-comment]"),
    row?.querySelector("[data-mention-composer-root]")
  );
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
      <td data-label="Issue"><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong><div class="trail-update-issue-meta"><small>${escapeHtml(item.title || item.scenario || "")}</small><button class="analysis-discussion-link trail-update-discussion-link" type="button" data-trail-update-discussion="${escapeHtml(item.issue_id || "")}" data-model-run-id="${escapeHtml(review.model_run_id || model.run_id || "")}">评论</button></div></td>
      <td data-label="GT">${labelBadge(item.gt_label, "—")}</td>
      <td data-label="模型 label">${labelBadge(model.label, "未输出")}<small>${ready ? "" : uiText("label 不在三分类契约内", "label is outside the contract")}</small></td>
      <td data-label="模型 reason"><div class="trail-update-reason" title="${escapeHtml(model.reason || "模型未返回 reason")}">${escapeHtml(model.reason || "模型未返回 reason")}</div><small>${escapeHtml(formatModelConfidence(model.confidence))} confidence</small></td>
      <td data-label="Review"><div>${escapeHtml(review.reviewer || "未记录")}</div><small>${escapeHtml(review.status || "pending")} · ${escapeHtml(formatTime(review.reviewed_at))}</small></td>
      <td data-label="Comment"><div class="trail-update-comment" title="${escapeHtml(comment || uiText("未填写 Comment", "No Comment"))}">${escapeHtml(comment || "未填写")}</div><small class="trail-update-comment-target" title="${escapeHtml(comment ? uiText("提交时写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment on commit") : uiText("不会写入排除说明", "No exclusion note will be written"))}">${comment ? uiText("提交时写入 info.ra_triage_dashboard.should_exclude_comment", "Saved in info.ra_triage_dashboard.should_exclude_comment on commit") : uiText("不会写入排除说明", "No exclusion note will be written")}</small></td>
      <td data-label="数据集版本" class="trail-update-source-cell" title="${escapeHtml(sourceRun.title)}"><strong>${escapeHtml(sourceRun.label)}</strong></td>
      <td data-label="Trail 更新状态" data-trail-update-status-issue="${escapeHtml(item.issue_id || "")}">${trailUpdateStatusCellMarkup(status.key)}</td>
    </tr>`;
  }).join("");
  body.querySelectorAll("[data-trail-update-discussion]").forEach((button) => {
    button.addEventListener("click", () => {
      openAnalysisDiscussion(button.dataset.trailUpdateDiscussion, {
        runId: button.dataset.modelRunId || "",
        source: "trail-update",
      }).catch((error) => showToast(error.message, true));
    });
  });
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

