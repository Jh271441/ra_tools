/* Explicit local false → Trail. Opening/previewing never performs a write. */
const trailNonExclusion = { epoch: 0, busy: false, preview: null, context: null, scope: "", actor: "" };

function trailNonExclusionAllowed() {
  return hasDashboardWriteRole() && state.session?.can_write !== false && !state.session?.read_only;
}
function trailNonExclusionCurrent(epoch) {
  return epoch === trailNonExclusion.epoch
    && isPageContextCurrent(trailNonExclusion.context)
    && selectedBaselineQueryValue() === trailNonExclusion.scope
    && String(state.session?.username || "") === trailNonExclusion.actor
    && trailNonExclusionAllowed();
}
function syncTrailNonExclusionControls() {
  const allowed = trailNonExclusionAllowed();
  const busy = trailNonExclusion.busy || Boolean(state.trailUpdate?.selectionBusy);
  const button = $("#trailNonExclusionOpen");
  if (button) {
    button.disabled = !allowed || busy;
    button.title = allowed ? uiText("预览本地不排除结论，确认后同步到 Trail", "Preview local non-exclusion outcomes before syncing to Trail")
      : uiText("需要已验证的写入权限", "Verified write access is required");
  }
  const input = $("#trailNonExclusionInput");
  if (input) input.disabled = busy;
  const parsed = parseIssueIdsInput(input?.value || "");
  const valid = parsed.ids.length > 0 && parsed.ids.length <= 200 && !parsed.invalid.length;
  $("#trailNonExclusionPreview")?.toggleAttribute("disabled", busy || !allowed || !valid);
  const feedback = $("#trailNonExclusionFeedback");
  if (feedback && !feedback.dataset.error) {
    feedback.textContent = busy ? uiText("正在核验，请稍候…", "Checking; please wait…")
      : !parsed.ids.length && !parsed.invalid.length ? uiText("填写 1–200 个 Issue，支持换行、逗号或 Issue 链接。", "Enter 1–200 Issues, separated by lines, commas, or Issue links.")
      : parsed.ids.length > 200 ? uiText("一次最多 200 个 Issue。", "At most 200 Issues per update.") : issueQueryFeedback(parsed);
    feedback.classList.toggle("is-error", Boolean(parsed.invalid.length || parsed.ids.length > 200));
  }
}
function openTrailNonExclusion() {
  if (!trailNonExclusionAllowed() || trailNonExclusion.busy || state.trailUpdate.selectionBusy) return;
  const dialog = $("#trailNonExclusionDialog");
  if (!dialog) return;
  trailNonExclusion.epoch++;
  trailNonExclusion.context = capturePageContext("trail-update");
  trailNonExclusion.scope = selectedBaselineQueryValue();
  trailNonExclusion.actor = String(state.session?.username || "");
  const feedback = $("#trailNonExclusionFeedback");
  if (feedback) delete feedback.dataset.error;
  syncTrailNonExclusionControls();
  dialog.showModal();
  $("#trailNonExclusionInput")?.focus();
}
function trailNonExclusionItemMarkup(item) {
  const before = item.before?.should_exclude;
  const previous = before === true ? uiText("排除", "Excluded") : uiText("未设置", "Unset");
  const source = item.reason_source || {};
  const sourceName = source.kind === "issue_decision" ? uiText("Issue 裁决", "Issue decision") : uiText("Issue 标注", "Issue annotation");
  const reason = [source.rationale, source.decision_rationale].filter(Boolean).join("\n");
  return `<article class="trail-selected-confirm"><strong>${escapeHtml(item.issue_id)}</strong>
    <p class="trail-non-exclusion-transition">${escapeHtml(previous)} <span aria-hidden="true">→</span> <strong>${uiText("不排除", "Not excluded")}</strong></p>
    <div class="trail-reason-comparison"><section><strong>${uiText("本地结论依据", "Local outcome evidence")}</strong><p>${escapeHtml(reason || uiText("未填写理由", "No rationale provided"))}</p><small>${escapeHtml([sourceName, source.author].filter(Boolean).join(" · "))}</small></section>
    <section><strong>${uiText("Trail 原理由（保留不变）", "Original Trail reason (unchanged)")}</strong><p>${escapeHtml(item.before?.should_exclude_comment || uiText("未填写", "Empty"))}</p><small>${uiText("仅修改排除标记为 false，不改本地标注或 GT。", "Only sets exclusion to false; local annotations and GT stay unchanged.")}</small></section></div></article>`;
}
async function previewTrailNonExclusion() {
  if (trailNonExclusion.busy || state.trailUpdate.selectionBusy) return;
  const epoch = trailNonExclusion.epoch;
  const parsed = parseIssueIdsInput($("#trailNonExclusionInput")?.value || "");
  const feedback = $("#trailNonExclusionFeedback");
  if (!trailNonExclusionCurrent(epoch)) {
    feedback.dataset.error = "true";
    feedback.textContent = uiText("页面、数据集或用户已变化，请关闭后重新打开。", "Page, dataset or user changed; close and reopen.");
    return;
  }
  if (!parsed.ids.length || parsed.ids.length > 200 || parsed.invalid.length) return;
  delete feedback.dataset.error;
  trailNonExclusion.busy = true;
  state.trailUpdate.selectionBusy = true;
  syncTrailNonExclusionControls();
  syncTrailAttributeActions();
  let committing = false;
  try {
    const preview = await api("/api/trail-attribute-update/non-exclusion-preview", {
      method: "POST", body: JSON.stringify({ issue_ids: parsed.ids, baselines: trailNonExclusion.scope }),
    });
    if (epoch !== trailNonExclusion.epoch || !$("#trailNonExclusionDialog")?.open) return;
    if (!trailNonExclusionCurrent(epoch)) throw new Error(uiText("范围已变化，请关闭后重新打开。", "Scope changed; close and reopen."));
    if (preview.intent !== "unexclude" || !preview.write_ready || !preview.payload_sha256) throw new Error(uiText("预览无效，请重新核验。", "Invalid preview; check again."));
    trailNonExclusion.preview = preview;
    const confirmed = await openTrailUpdateConfirm({ data: preview });
    trailNonExclusion.preview = null;
    if (!confirmed) return;
    if (!trailNonExclusionCurrent(epoch)) throw new Error(uiText("页面、数据集或用户已变化，请重新打开并预览。", "Page, dataset or user changed; reopen and preview again."));
    committing = true;
    $("#trailNonExclusionDialog").close();
    openTrailUpdateProgress({ mode: "review", total: parsed.ids.length });
    trailUpdateProgressSetStage("request");
    const result = await api("/api/trail-attribute-update/non-exclusion-commit", {
      method: "POST", body: JSON.stringify({ confirm: true, payload_sha256: preview.payload_sha256 }),
    });
    const verified = Number(result.readback?.verified_count || 0) + Number(result.skipped_synced_issue_ids?.length || 0);
    const message = result.ok ? uiText(`已确认 ${verified} 条不排除更新；原理由和本地标注不变。`, `${verified} non-exclusion updates confirmed; original reasons and local annotations are unchanged.`)
      : uiText("部分更新未确认，请查看记录并刷新核对。", "Some updates are unconfirmed; inspect the record and refresh.");
    finishTrailUpdateProgress({ ok: Boolean(result.ok), message, operationId: result.payload_sha256 });
    if (result.ok) $("#trailNonExclusionInput").value = "";
    if (isPageContextCurrent(trailNonExclusion.context) && selectedBaselineQueryValue() === trailNonExclusion.scope) {
      setTrailAttributeStatus(message);
      void refreshTrailAttributeStatus({ runId: "", previewKey: trailUpdatePreviewKey(), requestSeq: state.trailUpdate.requestSeq, force: true }).catch(() => {});
    }
  } catch (error) {
    if (committing) finishTrailUpdateProgress({ ok: false, message: error.message });
    else if (epoch === trailNonExclusion.epoch && $("#trailNonExclusionDialog")?.open) {
      feedback.dataset.error = "true";
      feedback.classList.add("is-error");
      feedback.textContent = error.message;
    }
  } finally {
    trailNonExclusion.preview = null;
    trailNonExclusion.busy = false;
    state.trailUpdate.selectionBusy = false;
    syncTrailNonExclusionControls();
    syncTrailAttributeActions();
  }
}
function bindTrailNonExclusionEvents() {
  $("#trailNonExclusionOpen")?.addEventListener("click", openTrailNonExclusion);
  $("#trailNonExclusionPreview")?.addEventListener("click", previewTrailNonExclusion);
  $("#trailNonExclusionInput")?.addEventListener("input", () => {
    delete $("#trailNonExclusionFeedback").dataset.error;
    syncTrailNonExclusionControls();
  });
  $("#trailNonExclusionDialog")?.addEventListener("close", () => { trailNonExclusion.epoch++; });
  syncTrailNonExclusionControls();
}
function refreshTrailNonExclusionLanguage() {
  syncTrailNonExclusionControls();
  if (trailNonExclusion.preview && $("#trailUpdateConfirmDialog")?.open) {
    const list = $("#trailUpdateConfirmList");
    const scroll = list?.scrollTop || 0;
    openTrailUpdateConfirm({ data: trailNonExclusion.preview, renderOnly: true });
    if (list) list.scrollTop = scroll;
  }
}
