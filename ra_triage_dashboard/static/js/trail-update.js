/* Trail 属性更新 draft preview.
 *
 * This page intentionally stops at a deterministic, write-disabled payload.
 * A future Trail writer can consume the downloaded draft only after the
 * allowlist, audit, deep-merge and conflict checks described in the dashboard
 * architecture have been implemented server-side.
 */

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

function clearTrailAttributePreview(message = "") {
  state.trailUpdate.data = null;
  $("#trailUpdateCount").textContent = "—";
  $("#trailUpdateRunSummary").textContent = "—";
  $("#trailUpdateDigest").textContent = "—";
  $("#trailUpdateTableSummary").textContent = "—";
  $("#trailUpdateDownloadButton")?.toggleAttribute("disabled", true);
  $("#trailUpdateCopyButton")?.toggleAttribute("disabled", true);
  const status = $("#trailUpdateStatus");
  if (status) status.textContent = message || uiText("请选择 Run 后生成预览。", "Choose a Run to generate a preview.");
  const body = $("#trailUpdateTableBody");
  if (body) {
    body.innerHTML = `<tr><td colspan="6" class="trail-update-empty">${uiText("加载后显示应该排除案例。", "Excluded cases appear after loading.")}</td></tr>`;
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
  $("#trailUpdateCount").textContent = String(items.length);
  $("#trailUpdateRunSummary").textContent = run.name || run.id || "—";
  $("#trailUpdateDigest").textContent = digest ? `${digest.slice(0, 12)}…` : "—";
  $("#trailUpdateDigest")?.setAttribute("title", digest || "");
  $("#trailUpdateTableSummary").textContent = uiText(
    `${items.length} 条；按 Issue ID 稳定排序`,
    `${items.length} items; stable Issue ID ordering`
  );
  const status = $("#trailUpdateStatus");
  if (status) {
    status.textContent = uiText(
      `已生成草稿：${items.length} 条。当前仅预览，不写入 Trail。`,
      `Draft ready: ${items.length} item(s). Preview only; Trail is not written.`
    );
  }
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
    return `<tr>
      <td><strong class="trail-update-issue">${escapeHtml(item.issue_id || "—")}</strong><small>${escapeHtml(item.title || item.scenario || "")}</small></td>
      <td>${labelBadge(item.gt_label, "—")}</td>
      <td>${labelBadge(model.label, "未输出")}</td>
      <td><div class="trail-update-reason">${escapeHtml(model.reason || "模型未返回 reason")}</div><small>${escapeHtml(formatModelConfidence(model.confidence))} confidence</small></td>
      <td><div>${escapeHtml(review.reviewer || "未记录")}</div><small>${escapeHtml(review.status || "pending")} · ${escapeHtml(formatTime(review.reviewed_at))}</small></td>
      <td><code>${escapeHtml(patchPath)}</code><small>deep merge · ${escapeHtml(String(review.model_run_id || data?.selected_run?.id || ""))}</small></td>
    </tr>`;
  }).join("");
}

async function loadTrailAttributePreview() {
  const select = $("#trailUpdateRunSelect");
  const runId = String(select?.value || state.trailUpdate?.runId || "").trim();
  if (!runId) {
    clearTrailAttributePreview();
    return null;
  }
  state.trailUpdate.runId = runId;
  const requestSeq = ++state.trailUpdate.requestSeq;
  const status = $("#trailUpdateStatus");
  if (status) status.textContent = uiText("正在聚合最新 Review…", "Aggregating latest Reviews…");
  $("#trailUpdateLoadButton")?.toggleAttribute("disabled", true);
  try {
    const data = await api(trailUpdateEndpoint(runId));
    if (requestSeq !== state.trailUpdate.requestSeq) return data;
    state.trailUpdate.data = data;
    renderTrailAttributePreview(data);
    $("#trailUpdateDownloadButton")?.toggleAttribute("disabled", !data?.draft);
    $("#trailUpdateCopyButton")?.toggleAttribute("disabled", !data?.draft);
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId }));
    }
    return data;
  } finally {
    if (requestSeq === state.trailUpdate.requestSeq) {
      $("#trailUpdateLoadButton")?.toggleAttribute("disabled", false);
    }
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
  showToast(uiText("已复制 Trail 属性更新草稿。", "Trail attribute update draft copied."));
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
  $("#trailUpdateDownloadButton")?.addEventListener("click", downloadTrailAttributeDraft);
  $("#trailUpdateCopyButton")?.addEventListener("click", () => {
    copyTrailAttributeDraft().catch((error) => showToast(error.message, true));
  });
  renderTrailAttributeRunPicker();
}
