/* Trail 属性更新：选择 Run → 检查字段 → 预览差异 → 明确提交。 */

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
  const selected = state.trailUpdate?.runId || state.selectedRunId || "";
  const options = [
    { value: "", label: uiText("请选择模型 Run", "Choose a model Run") },
    ...(state.modelRuns || []).map((run) => ({ value: run.id, label: trailUpdateRunLabel(run) })),
  ];
  select.innerHTML = options
    .map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`)
    .join("");
  select.value = (state.modelRuns || []).some((run) => run.id === selected) ? selected : "";
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
  const resultField = data?.target_fields?.[0] || "ra_stuck_auto_result";
  const infoField = data?.target_fields?.[1] || "ra_stuck_auto_result_info";
  if (panel) panel.dataset.status = status;
  if (badge) {
    badge.dataset.status = status;
    badge.textContent = uiText(
      status === "ready" ? "字段已就绪" : status === "missing_fields" ? "目标字段未暴露" : status === "disabled" ? "写入开关关闭" : "需要检查",
      status === "ready" ? "Fields ready" : status === "missing_fields" ? "Target fields missing" : status === "disabled" ? "Writer disabled" : "Check required"
    );
  }
  if (title) title.textContent = uiText(
    status === "ready" ? "可以提交到 Trail" : status === "missing_fields" ? "当前 view 不能安全写入" : status === "disabled" ? "当前环境只允许预览" : "Trail 字段能力尚未确认",
    status === "ready" ? "Ready to commit to Trail" : status === "missing_fields" ? "The current view is not safe to write" : status === "disabled" ? "Preview only in this environment" : "Trail field capability is not confirmed"
  );
  if (message) {
    const capabilityMessage = capability.message || uiText("生成预览后会显示检查结果。", "Build a preview to see the capability check.");
    message.textContent = status === "disabled"
      ? uiText(`当前环境只允许预览；${capabilityMessage}`, `This environment is preview-only; ${capabilityMessage}`)
      : capabilityMessage;
  }
  if (fields) {
    const visible = Array.isArray(capability.fields_visible) ? capability.fields_visible : [];
    fields.textContent = uiText(
      `目标：${resultField} + ${infoField}；当前 view 可见：${visible.join(", ") || "无"}`,
      `Target: ${resultField} + ${infoField}; visible in view: ${visible.join(", ") || "none"}`
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
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("生成预览后显示案例。", "Cases appear after building a preview.")}</td></tr>`;
  }
}

function trailUpdateEndpoint(runId) {
  const params = new URLSearchParams({ model_run_id: runId });
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
  $("#trailUpdateRunSummary").textContent = run.name || run.id || "—";
  $("#trailUpdateResultField").textContent = data?.target_fields?.[0] || "ra_stuck_auto_result";
  $("#trailUpdateInfoField").textContent = data?.target_fields?.[1] || "ra_stuck_auto_result_info";
  $("#trailUpdateDigest").textContent = digest ? `${digest.slice(0, 12)}…` : "—";
  $("#trailUpdateDigest")?.setAttribute("title", digest || "");
  $("#trailUpdateTableSummary").textContent = uiText(
    `${items.length} 条；按 Issue ID 稳定排序`,
    `${items.length} items; stable Issue ID ordering`
  );
  const statusText = data?.write_status === "ready"
    ? uiText(`已生成预览：${items.length} 条，可提交。`, `Preview ready: ${items.length} item(s); commit is available.`)
    : uiText(`已生成预览：${items.length} 条；${capability.message || "暂不可写入 Trail"}`, `Preview ready: ${items.length} item(s); ${capability.message || "Trail is not writable yet."}`);
  setTrailAttributeStatus(statusText);
  const body = $("#trailUpdateTableBody");
  if (!body) return;
  if (!items.length) {
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("当前 Run 没有已标记“应该排除”的 Review。", "No reviewed “should exclude” cases in this Run.")}</td></tr>`;
    return;
  }
  body.innerHTML = items.map((item) => {
    const review = item.review || {};
    const model = item.model || {};
    const target = item.target || {};
    const patchPath = target.path || "ra_triage_dashboard.should_exclude";
    const ready = item.write_ready !== false;
    return `<tr class="${ready ? "" : "is-invalid"}">
      <td><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong><small>${escapeHtml(item.title || item.scenario || "")}</small></td>
      <td>${labelBadge(item.gt_label, "—")}</td>
      <td>${labelBadge(model.label, "未输出")}<small>${ready ? "" : uiText("label 不在三分类契约内", "label is outside the contract")}</small></td>
      <td><div class="trail-update-reason">${escapeHtml(model.reason || "模型未返回 reason")}</div><small>${escapeHtml(formatModelConfidence(model.confidence))} confidence</small></td>
      <td><div>${escapeHtml(review.reviewer || "未记录")}</div><small>${escapeHtml(review.status || "pending")} · ${escapeHtml(formatTime(review.reviewed_at))}</small></td>
      <td><strong>${escapeHtml(data?.target_fields?.[0] || "ra_stuck_auto_result")}</strong><small>+ ${escapeHtml(data?.target_fields?.[1] || "ra_stuck_auto_result_info")}</small><code>${escapeHtml(patchPath)}</code></td>
    </tr>`;
  }).join("");
}

async function loadTrailAttributePreview() {
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  if (!runId) {
    clearTrailAttributePreview(uiText("请先选择一个模型 Run。", "Choose a model Run first."));
    return null;
  }
  state.trailUpdate.runId = runId;
  const requestSeq = ++state.trailUpdate.requestSeq;
  setTrailAttributeStatus(uiText("正在检查 Trail 字段并生成预览…", "Checking Trail fields and building preview…"));
  $("#trailUpdateLoadButton")?.toggleAttribute("disabled", true);
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
      setTrailAttributeStatus(uiText("预览生成失败，请检查所选 Run 后重试。", "Could not build the preview. Check the selected Run and try again."));
    }
    throw error;
  } finally {
    if (requestSeq === state.trailUpdate.requestSeq) $("#trailUpdateLoadButton")?.toggleAttribute("disabled", false);
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
    setTrailAttributeStatus(uiText(
      `Trail 更新完成：成功 ${stats.success_count || 0}，失败 ${stats.failed_count || 0}。`,
      `Trail update finished: ${stats.success_count || 0} succeeded, ${stats.failed_count || 0} failed.`
    ));
    showToast(uiText("Trail 属性更新已完成。", "Trail attributes updated."));
  } catch (error) {
    setTrailAttributeStatus(error?.message || uiText("Trail 更新失败。", "Trail update failed."));
    showToast(error?.message || uiText("Trail 更新失败。", "Trail update failed."), true);
  } finally {
    button?.toggleAttribute("disabled", data.write_status !== "ready");
  }
}

function bindTrailAttributeUpdateEvents() {
  const select = $("#trailUpdateRunSelect");
  select?.addEventListener("change", () => {
    state.trailUpdate.runId = String(select.value || "");
    clearTrailAttributePreview();
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId: state.trailUpdate.runId }));
    }
  });
  $("#trailUpdateLoadButton")?.addEventListener("click", () => {
    loadTrailAttributePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateCommitButton")?.addEventListener("click", () => {
    commitTrailAttributeUpdate().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateDownloadButton")?.addEventListener("click", downloadTrailAttributeDraft);
  $("#trailUpdateCopyButton")?.addEventListener("click", () => {
    copyTrailAttributeDraft().catch((error) => showToast(error.message, true));
  });
  renderTrailAttributeRunPicker();
}
