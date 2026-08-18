/* Trail 属性更新：Review 汇总 / Issue ID 屏蔽两个独立的预览→提交工作流。 */

function setTrailUpdateTab(tab = "review") {
  const nextTab = tab === "issue" ? "issue" : "review";
  state.trailUpdate.tab = nextTab;
  const pageTitle = $("#trailUpdateSectionTitle");
  if (pageTitle) {
    const zh = pageTitle.querySelector(".ui-lang-zh");
    const en = pageTitle.querySelector(".ui-lang-en");
    if (zh) zh.textContent = nextTab === "issue" ? "Issue ID 屏蔽" : "排除案例汇总";
    if (en) en.textContent = nextTab === "issue" ? "Shield by Issue ID" : "Excluded case summary";
  }
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

function clearTrailAttributePreview(message = "") {
  state.trailUpdate.data = null;
  state.trailUpdate.previewKey = "";
  state.trailUpdate.previewLoadedAt = 0;
  setTrailAttributeUpdatePreviewVisible(false);
  setTrailAttributeCapability(null);
  $("#trailUpdateCount").textContent = "—";
  $("#trailUpdateRunSummary").textContent = "—";
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) digestElement.textContent = "—";
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

function trailUpdateEndpoint(runId, probeTrail = true) {
  const params = new URLSearchParams();
  if (runId) params.set("model_run_id", runId);
  const baselines = selectedBaselineQueryValue();
  if (baselines) params.set("baselines", baselines);
  if (!probeTrail) params.set("probe_trail", "false");
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
  $("#trailUpdateResultField").textContent = data?.model_result_field || data?.target_fields?.[0] || "ra_stuck_auto_result";
  $("#trailUpdateInfoField").textContent = data?.target_field || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1]) || "ra_stuck_auto_result_info";
  const digestElement = $("#trailUpdateDigest");
  if (digestElement) {
    digestElement.textContent = digest ? `${digest.slice(0, 12)}…` : "—";
    digestElement.setAttribute("title", digest || "");
  }
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
      <td><strong>${escapeHtml(data?.target_field || (data?.write_mode === "info_only" ? data?.target_fields?.[0] : data?.target_fields?.[1]) || "ra_stuck_auto_result_info")}</strong><small>${data?.write_mode === "info_only" ? uiText("仅 deep_merge，不改 label", "deep-merge only; label unchanged") : `+ ${escapeHtml(data?.target_fields?.[1] || "ra_stuck_auto_result_info")}`}</small><code>${escapeHtml(patchPath)}</code></td>
    </tr>`;
  }).join("");
}

async function loadTrailAttributePreview(force = false) {
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  state.trailUpdate.runId = runId;
  const previewKey = `${runId}|${selectedBaselineQueryValue()}`;
  const cachedData = state.trailUpdate?.data;
  if (
    !force &&
    cachedData &&
    state.trailUpdate.previewKey === previewKey &&
    Date.now() - Number(state.trailUpdate.previewLoadedAt || 0) < 60000
  ) {
    renderTrailAttributePreview(cachedData);
    return cachedData;
  }
  const requestSeq = ++state.trailUpdate.requestSeq;
  const applyPreview = (data, { loaded = false } = {}) => {
    if (requestSeq !== state.trailUpdate.requestSeq) return false;
    state.trailUpdate.data = data;
    state.trailUpdate.previewKey = previewKey;
    state.trailUpdate.previewLoadedAt = loaded ? Date.now() : 0;
    renderTrailAttributePreview(data);
    $("#trailUpdateDownloadButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateCopyButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateCommitButton")?.toggleAttribute("disabled", data?.write_status !== "ready");
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
      applyPreview(data, { loaded: true });
      return data;
    }
    setTrailAttributeStatus(uiText(
      "排除案例已加载，正在后台检查 Trail 字段…",
      "Excluded cases loaded; checking Trail fields in the background…"
    ));
    try {
      const checked = await api(trailUpdateEndpoint(runId, true));
      if (requestSeq !== state.trailUpdate.requestSeq) return checked;
      applyPreview(checked, { loaded: true });
      return checked;
    } catch (error) {
      if (requestSeq === state.trailUpdate.requestSeq) {
        setTrailAttributeStatus(uiText(
          "排除案例已加载，但 Trail 字段检查失败；可稍后刷新重试。",
          "Excluded cases loaded, but the Trail field check failed; refresh to retry."
        ));
      }
      return data;
    }
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

function trailInfoPreviewJson(value) {
  if (!value || typeof value !== "object") return "{}";
  try {
    return JSON.stringify(value, null, 2);
  } catch (_error) {
    return "{}";
  }
}

function trailInfoPreviewText(item) {
  const update = item?.field_update || {};
  const after = update.after && typeof update.after === "object"
    ? update.after
    : (update.patch || item?.target?.patch || {});
  return trailInfoPreviewJson(after);
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
    ? uiText(`仅写 ${infoField}`, `Info only · ${infoField}`)
    : uiText(`写入 ${resultField} + ${infoField}`, `Write ${resultField} + ${infoField}`);
  if (bannerText) bannerText.textContent = infoOnly
    ? uiText("模型 label 保持不变；info 使用 deep_merge。", "Model label stays unchanged; info is deep-merged.")
    : uiText("模型 label 和 info 将按预览写入。", "Model label and info will be written as previewed.");

  const summary = $("#trailUpdateConfirmSummary");
  if (summary) {
    const cards = [
      [uiText("提交模式", "Mode"), directMode ? uiText("Issue ID 屏蔽", "Issue shielding") : uiText("Review 排除汇总", "Review summary")],
      [uiText("Issue 数量", "Issues"), String(count)],
      [directMode ? uiText("目标字段", "Target field") : uiText("Run / 数据集", "Run / dataset"), directMode ? infoField : `${runLabel} · ${baselineLabel}`],
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
    `${infoOnly ? `仅更新 ${infoField}，不改模型 label。` : `将更新 ${resultField} 和 ${infoField}。`} 提交前会再次校验预览指纹${digest ? `（${digest.slice(0, 12)}…）` : ""}。`,
    `${infoOnly ? `Only ${infoField} will be updated; model labels stay unchanged. ` : `Both ${resultField} and ${infoField} will be updated. `}The preview fingerprint will be checked again before commit${digest ? ` (${digest.slice(0, 12)}…)` : ""}.`
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
    const expectedInfo = trailInfoPreviewText(item);
    return `<tr>
      <td><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong></td>
      <td>${labelBadge(item.current_label, "未输出")}</td>
      <td><span class="trail-update-state-badge ${item.current_should_exclude ? "is-on" : ""}">${escapeHtml(currentState)}</span></td>
      <td class="trail-update-info-cell"><strong>${escapeHtml(data?.target_field || "ra_stuck_auto_result_info")}</strong><small>deep_merge · ${uiText("写入后 info（不改 label）", "info after write (label unchanged)")}</small><code>${escapeHtml(patchPath)} = true</code><pre class="trail-update-json-preview">${escapeHtml(expectedInfo)}</pre></td>
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
  if (!await openTrailUpdateConfirm({ mode: "direct_issue_ids", data })) return;
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
  if (!await openTrailUpdateConfirm({ mode: "review", data })) return;
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
