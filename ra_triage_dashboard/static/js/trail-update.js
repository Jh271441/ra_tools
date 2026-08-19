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
    ids.length ? `已识别 ${ids.length} 个 Issue（每行一个，可分别填写说明）` : "请输入 Issue ID",
    ids.length ? `${ids.length} Issues recognized (one per row; notes can differ)` : "Enter at least one Issue ID"
  );
}

function trailIssueEntryRows() {
  return Array.from(document.querySelectorAll("[data-trail-issue-entry-row]"));
}

function renderTrailIssueEntryRow(entry = {}) {
  const issueId = escapeHtml(String(entry.issue_id || ""));
  const comment = escapeHtml(String(entry.comment || ""));
  return `<div class="trail-update-entry-row" data-trail-issue-entry-row>
    <label>
      <span class="ui-lang-zh">Issue ID</span><span class="ui-lang-en">Issue ID</span>
      <input data-trail-issue-entry-id type="text" inputmode="text" autocomplete="off" placeholder="cn32171803" value="${issueId}" />
    </label>
    <label>
      <span class="ui-lang-zh">排除说明（可选，写入 info）</span><span class="ui-lang-en">Exclusion note (optional; saved in info)</span>
      <textarea data-trail-issue-entry-comment rows="2" placeholder="留空时使用默认说明；会写入 info.ra_triage_dashboard.should_exclude_comment。">${comment}</textarea>
    </label>
    <button class="button button-quiet trail-update-entry-remove" data-trail-issue-entry-remove type="button" aria-label="删除此行" title="删除此行">×</button>
  </div>`;
}

function syncTrailIssueEntryRemoveButtons() {
  const rows = trailIssueEntryRows();
  rows.forEach((row) => {
    const button = row.querySelector("[data-trail-issue-entry-remove]");
    if (button) button.toggleAttribute("disabled", rows.length <= 1);
  });
}

function addTrailIssueEntryRow(entry = {}) {
  const list = $("#trailUpdateIssueEntries");
  if (!list) return null;
  list.insertAdjacentHTML("beforeend", renderTrailIssueEntryRow(entry));
  syncTrailIssueEntryRemoveButtons();
  const row = list.lastElementChild;
  row?.querySelector("[data-trail-issue-entry-id]")?.focus();
  return row;
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
    if (!raw && !comment) return;
    const parsed = typeof parseIssueIdsInput === "function"
      ? parseIssueIdsInput(raw)
      : { ids: [], invalid: [raw || `row ${index + 1}`] };
    if (parsed.invalid.length || parsed.ids.length !== 1) {
      invalid.push(parsed.invalid[0] || `${raw || `第 ${index + 1} 行`}（每行只能填一个 Issue ID）`);
      return;
    }
    const issueId = String(parsed.ids[0] || "").trim();
    if (seen.has(issueId)) {
      invalid.push(`${issueId}（重复）`);
      return;
    }
    seen.add(issueId);
    ids.push(issueId);
    entries.push({ issue_id: issueId, comment });
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
        return `<tr><td data-label="Issue"><strong>${escapeHtml(entry.issue_id || "—")}</strong></td><td data-label="排除说明"><div class="trail-update-history-comment">${escapeHtml(entry.comment || "—")}</div></td><td data-label="结果"><span class="trail-update-history-entry-status ${entryMeta.className}">${escapeHtml(entryMeta.label)}</span><small>${escapeHtml(entry.detail || "")}</small></td></tr>`;
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

function syncTrailAttributeActions(data = state.trailUpdate?.data) {
  const loading = Boolean(state.trailUpdate?.loading);
  document.querySelectorAll('[data-trail-json-preview="review"]').forEach((button) => {
    button.toggleAttribute("disabled", loading || !data?.draft);
  });
  $("#trailUpdateCommitButton")?.toggleAttribute("disabled", loading || data?.write_status !== "ready");
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

function clearTrailAttributePreview(message = "") {
  state.trailUpdate.data = null;
  state.trailUpdate.jsonPreview = null;
  state.trailUpdate.previewKey = "";
  state.trailUpdate.previewLoadedAt = 0;
  setTrailAttributeUpdatePreviewVisible(false);
  setTrailAttributeCapability(null);
  $("#trailUpdateCount").textContent = "—";
  $("#trailUpdateRunSummary").textContent = "—";
  $("#trailUpdateStatusSummary").textContent = "—";
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) digestElement.textContent = "—";
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

function trailUpdatePreviewKey(runId = state.trailUpdate?.runId || "") {
  return `${String(runId || "").trim()}|${selectedBaselineQueryValue()}`;
}

function trailAttributePreviewNeedsLoad(runId = state.trailUpdate?.runId || "") {
  const key = trailUpdatePreviewKey(runId);
  return !state.trailUpdate?.data || state.trailUpdate.previewKey !== key;
}

function trailUpdateEndpoint(runId, probeTrail = true, refresh = false) {
  const params = new URLSearchParams();
  if (runId) params.set("model_run_id", runId);
  const baselines = selectedBaselineQueryValue();
  if (baselines) params.set("baselines", baselines);
  if (!probeTrail) params.set("probe_trail", "false");
  if (refresh) params.set("refresh", "true");
  return `/api/trail-attribute-update/preview?${params.toString()}`;
}

function trailUpdateStatusMeta(status = "not_checked") {
  const key = String(status || "not_checked");
  const labels = {
    querying: ["查询中", "Checking", "is-querying", "Trail 查询尚未完成"],
    synced: ["已同步", "Synced", "is-synced", "已读到 should_exclude=true"],
    pending: ["待同步", "Pending", "is-pending", "尚未读到 should_exclude=true"],
    not_found: ["未找到", "Not found", "is-not-found", "Trail 未返回该 Issue"],
    query_failed: ["查询失败", "Query failed", "is-failed", "请刷新后重试"],
    not_checked: ["未检查", "Not checked", "is-not-checked", "当前环境未执行 Trail 查询"],
  };
  const [zh, en, className, detail] = labels[key] || labels.not_checked;
  return { key, label: uiText(zh, en), className, detail: uiText(detail, detail) };
}

function trailUpdateStatusSummary(data, items) {
  const counts = {};
  const provided = data?.trail_update_status_summary;
  if (provided && typeof provided === "object") {
    Object.entries(provided).forEach(([key, value]) => {
      const count = Number(value || 0);
      if (count > 0) counts[key] = count;
    });
  }
  if (!Object.keys(counts).length) {
    (items || []).forEach((item) => {
      const key = String(item?.trail_update_status || "not_checked");
      counts[key] = Number(counts[key] || 0) + 1;
    });
  }
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  const priority = ["querying", "query_failed", "pending", "not_found", "not_checked", "synced"];
  const primaryKey = priority.find((key) => counts[key]) || "not_checked";
  const primary = trailUpdateStatusMeta(primaryKey);
  const total = Object.values(counts).reduce((sum, count) => sum + Number(count || 0), 0);
  const detail = entries
    .sort(([a], [b]) => priority.indexOf(a) - priority.indexOf(b))
    .map(([key, count]) => `${count} ${trailUpdateStatusMeta(key).label}`)
    .join(" · ");
  const statusElement = $("#trailUpdateStatusSummary");
  if (statusElement) {
    const visualEntries = entries.length
      ? entries
      : [["not_checked", 0]];
    const segments = visualEntries.map(([key, count]) => {
      const meta = trailUpdateStatusMeta(key);
      const percent = total ? Math.round((Number(count) / total) * 1000) / 10 : 100;
      return `<span class="analysis-review-status-segment trail-status-${escapeHtml(meta.key)}" data-trail-update-status-key="${escapeHtml(meta.key)}" style="width:${percent}%" title="${escapeHtml(`${meta.label} · ${count} · ${percent}%`)}"></span>`;
    }).join("");
    const legend = visualEntries.map(([key, count]) => {
      const meta = trailUpdateStatusMeta(key);
      const percent = total ? Math.round((Number(count) / total) * 1000) / 10 : 0;
      return `<div class="analysis-review-status-legend-item trail-status-${escapeHtml(meta.key)}" data-trail-update-status-key="${escapeHtml(meta.key)}" role="listitem" tabindex="0" aria-label="${escapeHtml(`${meta.label}: ${count}, ${percent}%. ${meta.detail}`)}" title="${escapeHtml(meta.detail)}"><span class="analysis-review-status-swatch"></span><span class="analysis-review-status-legend-copy"><strong>${escapeHtml(meta.label)}</strong><small>${count} · ${percent}%</small></span></div>`;
    }).join("");
    statusElement.innerHTML = `<div class="analysis-review-status-bar" role="img" aria-label="${escapeHtml(detail || primary.label)}">${segments}</div><div class="analysis-review-status-legend" role="list">${legend}</div>`;
    statusElement.className = "analysis-review-status-chart analysis-review-status-visual trail-update-status-chart trail-update-status-visual trail-update-status-summary";
    statusElement.title = detail;
    statusElement.setAttribute("aria-label", detail || primary.label);
    const visual = statusElement;
    if (visual && !visual.dataset.hoverBound) {
      visual.dataset.hoverBound = "true";
      if (typeof bindAnalysisLinkedHover === "function") {
        bindAnalysisLinkedHover(visual, "[data-trail-update-status-key]", (node) => {
          const key = node.dataset.trailUpdateStatusKey;
          visual.querySelectorAll(`[data-trail-update-status-key="${CSS.escape(key)}"]`).forEach((peer) => peer.classList.add("is-hover"));
        });
      }
    }
  }
  return counts;
}

function trailUpdateSourceRun(model = {}, data = {}, item = {}) {
  const runId = String(model?.run_id || "").trim();
  const selectedRun = data?.selected_run || {};
  const knownRun = (state.modelRuns || []).find((run) => String(run?.id || "") === runId) || {};
  const selected = String(selectedRun.id || "") === runId ? selectedRun : {};
  const selectedBaselineIds = Array.isArray(data?.baseline_ids)
    ? data.baseline_ids
    : (Array.isArray(data?.baselines) ? data.baselines : []);
  const baselineId = String(item?.baseline_id || "").trim()
    || (selectedBaselineIds.length === 1 ? String(selectedBaselineIds[0]) : "");
  const name = knownRun.name || selected.name || runId || uiText("未绑定 Run", "Unbound Run");
  const source = knownRun.source_name || selected.source_name || "";
  const version = knownRun.source_sha256
    ? `v${String(knownRun.source_sha256).slice(0, 10)}`
    : (knownRun.schema_version || selected.schema_version || "");
  const label = baselineId || uiText("未标记", "Unassigned");
  const title = [label, name, source, version, item?.baseline_scope].filter(Boolean).join(" · ");
  return { label, name, source, version, runId, title };
}

function renderTrailAttributePreview(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const run = data?.selected_run || {};
  const digest = String(data?.payload_sha256 || "");
  const capability = data?.trail_capability || {};
  setTrailAttributeUpdatePreviewVisible(true);
  setTrailAttributeCapability(data);
  $("#trailUpdateCount").textContent = String(items.length);
  $("#trailUpdateRunSummary").textContent = run.name || run.id || uiText("全部 Model Runs", "All model Runs");
  renderTrailUpdateTargetField(data);
  trailUpdateStatusSummary(data, items);
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) {
    digestElement.textContent = digest ? `${digest.slice(0, 12)}…` : "—";
    digestElement.setAttribute("title", digest || "");
  }
  const body = $("#trailUpdateTableBody");
  if (!body) return;
  if (!items.length) {
    trailUpdateStatusSummary(data, []);
    body.innerHTML = `<tr><td colspan="8" class="trail-update-empty">${uiText("当前筛选范围没有已标记“应该排除”的 Review。", "No reviewed “should exclude” cases in the current filter.")}</td></tr>`;
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
      <td data-label="Trail 更新状态"><span class="trail-update-state-badge ${status.className}" title="${escapeHtml(status.detail)}">${escapeHtml(status.label)}</span><small>${escapeHtml(status.detail)}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailAttributePreview(force = false, options = {}) {
  const background = Boolean(options?.background);
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  state.trailUpdate.runId = runId;
  const previewKey = trailUpdatePreviewKey(runId);
  const cachedData = state.trailUpdate?.data;
  if (!force && state.trailUpdate?.loading && state.trailUpdate.previewKey === previewKey) {
    if (cachedData) {
      renderTrailAttributePreview(cachedData);
      syncTrailAttributeActions(cachedData);
    }
    return cachedData;
  }
  if (
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
  if (!background) setTrailAttributeLoading(true);
  const applyPreview = (data, { loaded = false } = {}) => {
    if (requestSeq !== state.trailUpdate.requestSeq) return false;
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
    // Render the local Review projection first.  The remote Trail capability
    // probe is intentionally a second, background request because it is the
    // slowest part of entering this page.
    const data = await api(trailUpdateEndpoint(runId, false));
    if (requestSeq !== state.trailUpdate.requestSeq) return data;
    applyPreview(data);
    if (!data?.capability_pending) {
      if (!background) setTrailAttributeLoading(false);
      applyPreview(data, { loaded: true });
      return data;
    }
    if (!background) {
      setTrailAttributeStatus(uiText(
        "排除案例已加载，正在后台检查 Trail 字段…",
        "Excluded cases loaded; checking Trail fields in the background…"
      ));
    }
    try {
      const checked = await api(trailUpdateEndpoint(runId, true, force));
      if (requestSeq !== state.trailUpdate.requestSeq) return checked;
      if (!background) setTrailAttributeLoading(false);
      applyPreview(checked, { loaded: true });
      return checked;
    } catch (error) {
      if (requestSeq === state.trailUpdate.requestSeq) {
        if (!background) setTrailAttributeLoading(false);
        const failedItems = Array.isArray(data?.items)
          ? data.items.map((item) => ({ ...item, trail_update_status: "query_failed" }))
          : [];
        // Keep the fast local payload available for download/retry, but make
        // the per-row state truthful instead of leaving every row stuck at
        // “查询中” after the background request fails.
        renderTrailAttributePreview({
          ...data,
          items: failedItems,
          trail_update_status_summary: failedItems.length ? { query_failed: failedItems.length } : {},
        });
        syncTrailAttributeActions(data);
        if (!background) {
          setTrailAttributeStatus(uiText(
            "排除案例已加载，但 Trail 字段检查失败；可稍后刷新重试。",
            "Excluded cases loaded, but the Trail field check failed; refresh to retry."
          ));
        }
      }
      if (background) throw error;
      return data;
    }
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
    await loadTrailAttributePreview(true, { background: true });
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

function finishTrailUpdateProgress({ ok = false, message = "" } = {}) {
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
    dialog.dataset.result = ok ? "success" : "error";
    trailUpdateProgressSetStage(ok ? "done" : "request", message || (ok
      ? uiText("字段和回读结果已返回。", "Field and readback results are ready.")
      : uiText("提交失败，请关闭弹窗查看错误信息。", "The commit failed; close this dialog to inspect the error.")));
    const title = $("#trailUpdateProgressTitle");
    if (title && !ok) title.textContent = uiText("Trail 更新失败", "Trail update failed");
    const close = $("#trailUpdateProgressClose");
    if (close) close.hidden = false;
    if (ok) {
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
  const items = Array.isArray(data?.items) ? data.items : [];
  const infoField = String(
    data?.target_field
      || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1])
      || "ra_stuck_auto_result_info"
  );
  const targetSpec = trailUpdateTargetSpec(data);
  const resultField = String(data?.model_result_field || "ra_stuck_auto_result");
  const infoOnly = data?.write_mode === "info_only" || directMode;
  const count = Number(data?.count || items.length);
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
    count > shownItems.length ? `共 ${count} 条，展示前 ${shownItems.length} 条` : `共 ${count} 条`,
    count > shownItems.length ? `${count} total · first ${shownItems.length} shown` : `${count} item(s)`
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
        return `<details class="trail-update-confirm-item"><summary><div><strong>${escapeHtml(issueId)}</strong><small>${escapeHtml(currentLabel)}</small></div><div><code title="${escapeHtml(patch)}">${escapeHtml(`${infoField} = ${clippedPatch}`)}</code><small>${escapeHtml(uiText("点击展开完整 patch · deep_merge · label 不变", "Click to expand full patch · deep_merge · label unchanged"))}</small></div></summary><div class="trail-update-confirm-item-details"><small>${escapeHtml(uiText("完整字段 patch", "Full field patch"))}</small><pre>${escapeHtml(`${infoField} = ${patch}`)}</pre></div></details>`;
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
      <td data-label="Comment"><div class="trail-update-comment" title="${escapeHtml(comment)}">${escapeHtml(comment || "—")}</div><small>${commentHint}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailIssuePreview() {
  const parsed = parseTrailIssueIds();
  if (parsed.invalid.length || !parsed.ids.length) {
    clearTrailIssuePreview(uiText("请先填写合法的 Issue ID（每行一个）。", "Enter valid Issue IDs first (one per row)."));
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
    document.querySelectorAll('[data-trail-json-preview="issue"]').forEach((button) => {
      button.toggleAttribute("disabled", !data?.draft);
    });
    $("#trailUpdateIssueCommitButton")?.toggleAttribute("disabled", data?.write_status !== "ready");
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
  if (!data || data.write_status !== "ready") return;
  const ids = Array.isArray(data.requested_issue_ids) ? data.requested_issue_ids : [];
  const entries = Array.isArray(data.requested_entries)
    ? data.requested_entries
    : ids.map((issueId) => ({ issue_id: issueId, comment: data.comment || "" }));
  if (!await openTrailUpdateConfirm({ mode: "direct_issue_ids", data })) return;
  const button = $("#trailUpdateIssueCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailIssueStatus(uiText("正在写入 Trail 字段和 info 排除说明…", "Writing Trail fields and info notes…"));
  openTrailUpdateProgress({ mode: "issue", total: ids.length });
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
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    const localReviewText = uiText(
      `看板“应该排除” ${Number(localReview.marked_count || 0) + Number(localReview.already_excluded_count || 0)}/${localReview.requested_count || 0}`,
      `Review “Exclude” ${Number(localReview.marked_count || 0) + Number(localReview.already_excluded_count || 0)}/${localReview.requested_count || 0}`
    );
    const progressMessage = uiText(
      `字段与 info 排除说明 ${stats.success_count || 0}/${stats.total || ids.length}；${readbackText}；${localReviewText}。`,
      `Trail fields and info notes ${stats.success_count || 0}/${stats.total || ids.length}; ${readbackText}; ${localReviewText}.`
    );
    finishTrailUpdateProgress({ ok: Boolean(result?.ok), message: progressMessage });
    setTrailIssueStatus(uiText(
      `屏蔽完成：字段与 info 排除说明成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}；${readbackText}；${localReviewText}。`,
      `Shield finished: fields and info notes ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; ${readbackText}; ${localReviewText}.`
    ));
    showToast(
      result?.ok
        ? uiText("Issue 屏蔽已提交，Trail 与判错复核排除标记均已更新。", "Issue shielding and Review exclusion marks were updated.")
        : uiText("Issue 屏蔽部分失败，请查看 Trail 回读和判错复核标记。", "Issue shielding is incomplete; inspect Trail readback and Review marks."),
      !result?.ok
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
    button?.toggleAttribute("disabled", data.write_status !== "ready");
  }
}

async function commitTrailAttributeUpdate() {
  const data = state.trailUpdate?.data;
  if (!data || data.write_status !== "ready") return;
  if (!await openTrailUpdateConfirm({ mode: "review", data })) return;
  const button = $("#trailUpdateCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailAttributeStatus(uiText("正在提交 Trail 属性…", "Committing Trail info…"));
  openTrailUpdateProgress({ mode: "review", total: Number(data?.count || data?.items?.length || 0) });
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
  } catch (error) {
    finishTrailUpdateProgress({ ok: false, message: error?.message || uiText("提交失败，请稍后重试。", "Commit failed; try again later.") });
    setTrailAttributeStatus(error?.message || uiText("Trail 更新失败。", "Trail update failed."));
    showToast(error?.message || uiText("Trail 更新失败。", "Trail update failed."), true);
  } finally {
    button?.toggleAttribute("disabled", data.write_status !== "ready");
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
    clearTrailAttributePreview();
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId: state.trailUpdate.runId }));
    }
    loadTrailAttributePreview().catch((error) => showToast(error.message, true));
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
  $("#trailUpdateIssueEntries")?.addEventListener("input", () => {
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
