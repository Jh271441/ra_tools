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
      `已识别 ${ids.length} 个 Issue；无法识别：${invalid.slice(0, 4).join("、")}${invalid.length > 4 ? "…" : ""}`,
      `${ids.length} Issues recognized; invalid: ${invalid.slice(0, 4).join(", ")}${invalid.length > 4 ? "…" : ""}`
    );
  }
  return uiText(
    ids.length ? `已识别 ${ids.length} 个 Issue（重复项已去重）` : "请输入 Issue ID",
    ids.length ? `${ids.length} Issues recognized (duplicates removed)` : "Enter at least one Issue ID"
  );
}

function parseTrailIssueIds() {
  const input = $("#trailUpdateIssueIdsInput");
  const feedback = $("#trailUpdateIssueIdsFeedback");
  const parsed = typeof parseIssueIdsInput === "function"
    ? parseIssueIdsInput(input?.value || "")
    : { ids: [], invalid: ["Issue parser unavailable"] };
  if (feedback) {
    feedback.textContent = trailIssueIdsFeedback(parsed);
    feedback.classList.toggle("is-error", parsed.invalid.length > 0);
    feedback.classList.toggle("is-ready", !parsed.invalid.length && parsed.ids.length > 0);
  }
  return parsed;
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
  select.innerHTML = options
    .map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`)
    .join("");
  select.value = (state.modelRuns || []).some((run) => run.id === selected) ? selected : "";
  select.disabled = !hasRuns;
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
  const status = data?.write_status === "disabled"
    ? "disabled"
    : String(capability.status || "not_checked");
  const badge = $("#trailUpdateSafetyBadge");
  const panel = $("#trailUpdateCapability");
  const title = $("#trailUpdateCapabilityTitle");
  const message = $("#trailUpdateCapabilityMessage");
  const fields = $("#trailUpdateVisibleFields");
  const resultField = directMode
    ? data?.model_result_field || "ra_stuck_auto_result"
    : data?.target_fields?.[0] || "ra_stuck_auto_result";
  const infoField = directMode
    ? data?.target_field || data?.target_fields?.[0] || "ra_stuck_auto_result_info"
    : data?.target_fields?.[1] || "ra_stuck_auto_result_info";
  if (panel) panel.dataset.status = status;
  if (badge) {
    badge.dataset.status = status;
    badge.textContent = uiText(
      !hasPreview ? "尚未预览" : status === "ready" ? "字段已就绪" : status === "missing_fields" ? "目标字段未暴露" : status === "disabled" ? "写入开关关闭" : "需要检查",
      !hasPreview ? "No preview yet" : status === "ready" ? "Fields ready" : status === "missing_fields" ? "Target fields missing" : status === "disabled" ? "Writer disabled" : "Check required"
    );
  }
  if (title) title.textContent = uiText(
    !hasPreview ? "尚未生成预览" : status === "ready" ? "可以提交到 Trail" : status === "missing_fields" ? "当前 view 不能安全写入" : status === "disabled" ? "当前环境只允许预览" : "Trail 字段能力尚未确认",
    !hasPreview ? "Preview not generated" : status === "ready" ? "Ready to commit to Trail" : status === "missing_fields" ? "The current view is not safe to write" : status === "disabled" ? "Preview only in this environment" : "Trail field capability is not confirmed"
  );
  if (message) {
    const capabilityMessage = capability.message || uiText("选择 Run 后生成预览，页面会检查 2410 view 是否同时暴露两个目标字段。", "Choose a Run and build a preview to check whether view 2410 exposes both target fields.");
    message.textContent = status === "disabled"
      ? uiText(`当前环境只允许预览；${capabilityMessage}`, `This environment is preview-only; ${capabilityMessage}`)
      : capabilityMessage;
  }
  if (fields) {
    const visible = Array.isArray(capability.fields_visible) ? capability.fields_visible : [];
    fields.textContent = uiText(
      directMode
        ? `目标：仅更新 ${infoField} 的 Dashboard 排除标记；当前 view 可见：${visible.join(", ") || "无"}`
        : `目标：${resultField} + ${infoField}；当前 view 可见：${visible.join(", ") || "无"}`,
      directMode
        ? `Target: Dashboard exclusion marker in ${infoField}; visible in view: ${visible.join(", ") || "none"}`
        : `Target: ${resultField} + ${infoField}; visible in view: ${visible.join(", ") || "none"}`
    );
  }
}

function clearTrailAttributePreview(message = "") {
  state.trailUpdate.data = null;
  setTrailAttributeUpdatePreviewVisible(false);
  setTrailAttributeCapability(null);
  $("#trailUpdateCount").textContent = "—";
  $("#trailUpdateRunSummary").textContent = "—";
  $("#trailUpdateDigest").textContent = "—";
  $("#trailUpdateTableSummary").textContent = "—";
  $("#trailUpdateDownloadButton")?.toggleAttribute("disabled", true);
  $("#trailUpdateCopyButton")?.toggleAttribute("disabled", true);
  $("#trailUpdateCommitButton")?.toggleAttribute("disabled", true);
  setTrailAttributeStatus(message);
  const body = $("#trailUpdateTableBody");
  if (body) {
    body.innerHTML = `<tr><td colspan="7" class="trail-update-empty">${uiText("正在加载排除案例。", "Loading excluded cases.")}</td></tr>`;
  }
}

function clearTrailIssuePreview(message = "") {
  state.trailUpdate.directData = null;
  const results = $("#trailUpdateIssueResults");
  if (results) results.hidden = true;
  $("#trailUpdateIssueCount").textContent = "—";
  $("#trailUpdateIssueMissingCount").textContent = "—";
  $("#trailUpdateIssueSummary").textContent = "—";
  $("#trailUpdateIssueDigest").textContent = "—";
  $("#trailUpdateIssueTableSummary").textContent = "—";
  $("#trailUpdateIssueDownloadButton")?.toggleAttribute("disabled", true);
  $("#trailUpdateIssueCopyButton")?.toggleAttribute("disabled", true);
  $("#trailUpdateIssueCommitButton")?.toggleAttribute("disabled", true);
  setTrailIssueStatus(message);
  const body = $("#trailUpdateIssueTableBody");
  if (body) {
    body.innerHTML = `<tr><td colspan="5" class="trail-update-empty">${uiText("生成预览后显示 Issue。", "Issues appear after building a preview.")}</td></tr>`;
  }
}

function trailUpdateEndpoint(runId) {
  const params = new URLSearchParams();
  if (runId) params.set("model_run_id", runId);
  const baselines = selectedBaselineQueryValue();
  if (baselines) params.set("baselines", baselines);
  return `/api/trail-attribute-update/preview?${params.toString()}`;
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
  $("#trailUpdateResultField").textContent = data?.target_fields?.[0] || "ra_stuck_auto_result";
  $("#trailUpdateInfoField").textContent = data?.target_fields?.[1] || "ra_stuck_auto_result_info";
  $("#trailUpdateDigest").textContent = digest ? `${digest.slice(0, 12)}…` : "—";
  $("#trailUpdateDigest")?.setAttribute("title", digest || "");
  $("#trailUpdateTableSummary").textContent = uiText(
    `${items.length} 条；按 Issue ID 稳定排序`,
    `${items.length} items; stable Issue ID ordering`
  );
  const body = $("#trailUpdateTableBody");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="7" class="trail-update-empty">${uiText("当前筛选范围没有已标记“应该排除”的 Review。", "No reviewed “should exclude” cases in the current filter.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const review = item.review || {};
    const model = item.model || {};
    const comment = String(item.comment || review.note || "").trim();
    const target = item.target || {};
    const patchPath = target.path || "ra_triage_dashboard.should_exclude";
    const ready = item.write_ready !== false;
    return `<tr class="${ready ? "" : "is-invalid"}">
      <td><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong><small>${escapeHtml(item.title || item.scenario || "")}</small></td>
      <td>${labelBadge(item.gt_label, "—")}</td>
      <td>${labelBadge(model.label, "未输出")}<small>${ready ? "" : uiText("label 不在三分类契约内", "label is outside the contract")}</small></td>
      <td><div class="trail-update-reason">${escapeHtml(model.reason || "模型未返回 reason")}</div><small>${escapeHtml(formatModelConfidence(model.confidence))} confidence</small></td>
      <td><div>${escapeHtml(review.reviewer || "未记录")}</div><small>${escapeHtml(review.status || "pending")} · ${escapeHtml(formatTime(review.reviewed_at))}</small></td>
      <td><div class="trail-update-comment">${escapeHtml(comment || "未填写")}</div><small>${comment ? uiText("提交时将追加到 Trail Comment", "Added to Trail Comment on commit") : uiText("不会写入 Comment", "No Comment will be written")}</small></td>
      <td><strong>${escapeHtml(data?.target_fields?.[0] || "ra_stuck_auto_result")}</strong><small>+ ${escapeHtml(data?.target_fields?.[1] || "ra_stuck_auto_result_info")}</small><code>${escapeHtml(patchPath)}</code></td>
    </tr>`;
  }).join("");
}

async function loadTrailAttributePreview() {
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  state.trailUpdate.runId = runId;
  const requestSeq = ++state.trailUpdate.requestSeq;
  try {
    const data = await api(trailUpdateEndpoint(runId));
    if (requestSeq !== state.trailUpdate.requestSeq) return data;
    state.trailUpdate.data = data;
    renderTrailAttributePreview(data);
    $("#trailUpdateDownloadButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateCopyButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateCommitButton")?.toggleAttribute("disabled", data?.write_status !== "ready");
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId }));
    }
    return data;
  } catch (error) {
    if (requestSeq === state.trailUpdate.requestSeq) {
      setTrailAttributeStatus(uiText("排除案例加载失败，请稍后重试。", "Could not load excluded cases. Try again later."));
    }
    throw error;
  }
}

function trailUpdateDraftText() {
  const draft = state.trailUpdate?.data?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

function downloadTrailAttributeDraft() {
  const text = trailUpdateDraftText();
  if (!text) return;
  const run = state.trailUpdate?.data?.selected_run || {};
  const safeName = String(run.name || run.id || "run").replace(/[^A-Za-z0-9._-]+/g, "_");
  const blob = new Blob([text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `trail_attribute_update_${safeName}.json`;
  link.click();
  URL.revokeObjectURL(url);
}

async function copyTrailAttributeDraft() {
  const text = trailUpdateDraftText();
  if (!text) return;
  if (!navigator.clipboard?.writeText) throw new Error(uiText("当前浏览器不支持复制。", "Clipboard is unavailable in this browser."));
  await navigator.clipboard.writeText(text);
  showToast(uiText("已复制 Trail 属性更新 JSON。", "Trail attribute update JSON copied."));
}

function trailIssueDraftText() {
  const draft = state.trailUpdate?.directData?.draft;
  return draft ? JSON.stringify(draft, null, 2) : "";
}

function downloadTrailIssueDraft() {
  const text = trailIssueDraftText();
  if (!text) return;
  const blob = new Blob([text], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "trail_issue_exclusion_update.json";
  link.click();
  URL.revokeObjectURL(url);
}

async function copyTrailIssueDraft() {
  const text = trailIssueDraftText();
  if (!text) return;
  if (!navigator.clipboard?.writeText) throw new Error(uiText("当前浏览器不支持复制。", "Clipboard is unavailable in this browser."));
  await navigator.clipboard.writeText(text);
  showToast(uiText("已复制 Issue 屏蔽 JSON。", "Issue shielding JSON copied."));
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
  $("#trailUpdateIssueField").textContent = data?.target_field || "ra_stuck_auto_result_info";
  const digest = String(data?.payload_sha256 || "");
  $("#trailUpdateIssueDigest").textContent = digest ? `${digest.slice(0, 12)}…` : "—";
  $("#trailUpdateIssueDigest")?.setAttribute("title", digest || "");
  $("#trailUpdateIssueTableSummary").textContent = uiText(
    `${items.length} 条；按 Issue ID 稳定排序`,
    `${items.length} items; stable Issue ID ordering`
  );
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
    body.innerHTML = `<tr><td colspan="5" class="trail-update-empty">${uiText("没有可写的 Issue，请检查 ID 和 Trail view。", "No writable Issues; check IDs and the Trail view.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const target = item.target || {};
    const patchPath = target.path || "ra_triage_dashboard.should_exclude";
    const currentState = item.current_should_exclude
      ? uiText("已屏蔽", "Shielded")
      : uiText("未屏蔽", "Not shielded");
    return `<tr>
      <td><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong></td>
      <td>${labelBadge(item.current_label, "未输出")}</td>
      <td><span class="trail-update-state-badge ${item.current_should_exclude ? "is-on" : ""}">${escapeHtml(currentState)}</span></td>
      <td><strong>${escapeHtml(data?.target_field || "ra_stuck_auto_result_info")}</strong><small>deep_merge</small><code>${escapeHtml(patchPath)} = true</code></td>
      <td><div class="trail-update-comment">${escapeHtml(item.comment || "未填写")}</div><small>${item.comment ? uiText("将追加到 Trail Comment", "Added to Trail Comment") : uiText("不会写入 Comment", "No Comment")}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailIssuePreview() {
  const parsed = parseTrailIssueIds();
  if (parsed.invalid.length || !parsed.ids.length) {
    clearTrailIssuePreview(uiText("请输入合法的 Issue ID。", "Enter valid Issue IDs first."));
    return null;
  }
  const comment = String($("#trailUpdateIssueCommentInput")?.value || "").trim().slice(0, 4000);
  const requestSeq = ++state.trailUpdate.directRequestSeq;
  setTrailIssueStatus(uiText("正在检查 Issue 和 Trail 字段…", "Checking Issues and Trail fields…"));
  $("#trailUpdateIssuePreviewButton")?.toggleAttribute("disabled", true);
  try {
    const data = await api("/api/trail-attribute-update/issue-preview", {
      method: "POST",
      allowReadOnlyMutation: true,
      body: JSON.stringify({ issue_ids: parsed.ids, comment }),
    });
    if (requestSeq !== state.trailUpdate.directRequestSeq) return data;
    state.trailUpdate.directData = data;
    renderTrailIssuePreview(data);
    $("#trailUpdateIssueDownloadButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateIssueCopyButton")?.toggleAttribute("disabled", !data?.draft);
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
  if (!window.confirm(uiText(
    `确认通过真实 Trail 接口屏蔽 ${ids.length} 个 Issue？已有模型 label 会保留。`,
    `Commit shielding for ${ids.length} Issue(s) through the real Trail API? Existing model labels will be preserved.`
  ))) return;
  const button = $("#trailUpdateIssueCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailIssueStatus(uiText("正在写入 Trail 字段和 Comment…", "Writing Trail fields and Comments…"));
  try {
    const result = await api("/api/trail-attribute-update/issue-commit", {
      method: "POST",
      body: JSON.stringify({
        confirm: true,
        issue_ids: ids,
        comment: data.comment || "",
        payload_sha256: data.payload_sha256,
      }),
    });
    const stats = result?.stats || {};
    const readback = result?.readback || {};
    const readbackText = uiText(
      `回读 ${readback.verified_count || 0}/${readback.checked_count || 0}`,
      `read back ${readback.verified_count || 0}/${readback.checked_count || 0}`
    );
    setTrailIssueStatus(uiText(
      `屏蔽完成：字段成功 ${stats.success_count || 0}，字段失败 ${stats.failed_count || 0}；Comment 成功 ${stats.comment_success_count || 0}，失败 ${stats.comment_failed_count || 0}，跳过 ${stats.comment_skipped_count || 0}；${readbackText}。`,
      `Shield finished: fields ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; Comments ${stats.comment_success_count || 0} succeeded / ${stats.comment_failed_count || 0} failed / ${stats.comment_skipped_count || 0} skipped; ${readbackText}.`
    ));
    showToast(
      result?.ok
        ? uiText("Issue 屏蔽已提交并完成回读。", "Issue shielding was submitted and read back.")
        : uiText("Issue 屏蔽部分失败，请查看回读和失败明细。", "Issue shielding is incomplete; inspect readback and failures."),
      !result?.ok
    );
  } catch (error) {
    setTrailIssueStatus(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."));
    showToast(error?.message || uiText("Issue 屏蔽失败。", "Issue shielding failed."), true);
  } finally {
    button?.toggleAttribute("disabled", data.write_status !== "ready");
  }
}

async function commitTrailAttributeUpdate() {
  const data = state.trailUpdate?.data;
  if (!data || data.write_status !== "ready") return;
  const count = Number(data.count || 0);
  const message = uiText(
    `确认将 ${count} 个排除候选写入 Trail？目标字段为 ${data.target_fields.join(" + ")}。`,
    `Commit ${count} excluded candidate(s) to Trail? Target fields: ${data.target_fields.join(" + ")}.`
  );
  if (!window.confirm(message)) return;
  const button = $("#trailUpdateCommitButton");
  button?.toggleAttribute("disabled", true);
  setTrailAttributeStatus(uiText("正在提交 Trail 属性…", "Committing Trail attributes…"));
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
    setTrailAttributeStatus(uiText(
      `Trail 更新完成：字段成功 ${stats.success_count || 0}，字段失败 ${stats.failed_count || 0}；Comment 成功 ${stats.comment_success_count || 0}，失败 ${stats.comment_failed_count || 0}，跳过 ${stats.comment_skipped_count || 0}；${readbackText}。`,
      `Trail update finished: fields ${stats.success_count || 0} succeeded / ${stats.failed_count || 0} failed; Comments ${stats.comment_success_count || 0} succeeded / ${stats.comment_failed_count || 0} failed / ${stats.comment_skipped_count || 0} skipped; ${readbackText}.`
    ));
    showToast(
      result?.ok
        ? uiText("Trail 属性更新已完成并回读确认。", "Trail attributes updated and read back.")
        : uiText("Trail 属性更新部分失败，请查看回读和失败明细。", "Trail attribute update is incomplete; inspect readback and failures."),
      !result?.ok
    );
  } catch (error) {
    setTrailAttributeStatus(error?.message || uiText("Trail 更新失败。", "Trail update failed."));
    showToast(error?.message || uiText("Trail 更新失败。", "Trail update failed."), true);
  } finally {
    button?.toggleAttribute("disabled", data.write_status !== "ready");
  }
}

function bindTrailAttributeUpdateEvents() {
  document.querySelectorAll("[data-trail-update-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      setTrailUpdateTab(button.dataset.trailUpdateTab || "review");
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
  $("#trailUpdateDownloadButton")?.addEventListener("click", downloadTrailAttributeDraft);
  $("#trailUpdateCopyButton")?.addEventListener("click", () => {
    copyTrailAttributeDraft().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateIssueIdsInput")?.addEventListener("input", () => {
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssueCommentInput")?.addEventListener("input", () => {
    if (state.trailUpdate.directData) clearTrailIssuePreview();
  });
  $("#trailUpdateIssuePreviewButton")?.addEventListener("click", () => {
    loadTrailIssuePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateIssueCommitButton")?.addEventListener("click", () => {
    commitTrailIssueExclusion().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateIssueDownloadButton")?.addEventListener("click", downloadTrailIssueDraft);
  $("#trailUpdateIssueCopyButton")?.addEventListener("click", () => {
    copyTrailIssueDraft().catch((error) => showToast(error.message, true));
  });
  setTrailUpdateTab(state.trailUpdate?.tab || "review");
  parseTrailIssueIds();
  setTrailAttributeCapability(null);
  renderTrailAttributeRunPicker();
}
