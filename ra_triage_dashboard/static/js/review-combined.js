/* review-combined.js
 * Combined Review/Case context loading, ownership guards and form hydration.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function latestCaseVoteFromLabelingDetail(detail, username) {
  const author = String(username || "").trim().toLowerCase();
  return (detail?.label_cases || [])
    .flatMap((item) => item.revisions || [])
    .filter((revision) => String(revision.author || "").trim().toLowerCase() === author)
    .sort((a, b) => Number(b.id || 0) - Number(a.id || 0))[0] || null;
}

function populateCombinedCaseExclusion(context, caseData) {
  const revision = context?.case_revision || null;
  const excluded = $("#reviewExcludeInput");
  if (excluded) {
    const draft = reviewDraftForCase(caseData);
    excluded.checked = reviewDraftHasField(draft, "case_is_excluded") && typeof draft.case_is_excluded === "boolean"
      ? draft.case_is_excluded : Boolean(revision?.is_excluded);
  }
}

function populateCombinedCaseLabel(context, caseData, {preserveFields = new Set()} = {}) {
  state.combinedReviewContext = context;
  const revision = context?.case_revision || null;
  const expected = String(revision?.expected_output || "");
  const input = $("#expectedOutputInput");
  if (input && !preserveFields.has("expected_output")) {
    input.value = expected;
    input.dataset.selectionSource = expected ? "stored" : "empty";
  }
  const rationale = $("#combinedCaseRationale");
  if (rationale && !preserveFields.has("case_rationale") && !hasFocusedTextInput(rationale)) {
    rationale.value = String(revision?.rationale || "");
    updateReviewMentionComposer(rationale, $("#combinedCaseMentionComposer"));
  }
  const tags = new Set(revision?.tags || []);
  $("#reviewPane")?.querySelectorAll('input[name="reviewTags"]').forEach((checkbox) => {
    if (!preserveFields.has("tags")) checkbox.checked = tags.has(checkbox.value);
  });
  updateTagSummary();
  syncExpectedOutputFromTags();
  if (context?.model_review) {
    caseData.annotations = [
      context.model_review,
      ...(caseData.annotations || []).filter((item) => String(item.id) !== String(context.model_review.id)),
    ];
    const status = $("#modelReviewStatusInput");
    if (status && !preserveFields.has("model_review_status")) {
      status.value = modelReviewSubmissionStatus(context.model_review);
      syncModelReviewProgress(context.model_review);
      enhanceNativeUiSelect(status);
    }
    const note = $("#annotationNote");
    if (note && !preserveFields.has("note") && !hasFocusedTextInput(note)) {
      note.value = context.model_review.note || "";
      updateReviewMentionComposer(note);
    }
    if (!preserveFields.has("missing_evidence")) {
      const evidence = new Set(context.model_review.missing_evidence || []);
      $("#reviewPane")?.querySelectorAll('input[name="missingEvidence"]').forEach((checkbox) => {
        checkbox.checked = evidence.has(checkbox.value);
      });
      updateEvidenceSummary();
    }
    renderReviewSummary(caseData);
  } else {
    syncModelReviewProgress(null);
  }
}

function combinedReviewContextKey(caseData) {
  return JSON.stringify([
    String(caseData?.issue_id || ""), currentReviewRunId(caseData),
    String(state.reviewWorkSplitId || ""), String(state.session?.username || "").toLowerCase(),
  ]);
}

function renderCombinedReviewContextStatus() {
  const root = $("#combinedReviewContextStatus");
  const load = state.combinedReviewLoad;
  const current = load?.key === combinedReviewContextKey(state.selectedCase);
  const ready = current && load.status === "ready";
  const loading = current && load.status === "loading";
  const excluded = $("#reviewExcludeInput");
  if (excluded) excluded.disabled = !ready || !hasDashboardWriteRole() || Boolean(state.session?.read_only);
  if (!root) return;
  root.hidden = ready;
  root.dataset.status = loading ? "loading" : "error";
  root.innerHTML = loading
    ? escapeHtml(uiText("正在加载联合复核上下文…", "Loading combined review context…"))
    : `<span>${escapeHtml(current && load.error || uiText("联合复核上下文未就绪。", "Combined review context is not ready."))}</span><button class="button button-quiet" type="button" data-retry-combined-context>${escapeHtml(uiText("重试加载", "Retry loading"))}</button>`;
  root.querySelector("[data-retry-combined-context]")?.addEventListener("click", () => {
    loadCombinedReviewContext(state.selectedCase).catch((error) => showToast(error.message, true));
  });
  const save = $("#reviewSaveButton");
  if (save) save.disabled = !ready || Boolean(caseRationaleUploadTask(state.selectedCase)) || Boolean(state.savingAnnotation) || !hasDashboardWriteRole()
    || Boolean(state.session?.read_only) || $("#annotationForm")?.dataset.expectedOutputConflict === "1";
}

async function loadCombinedReviewContext(caseData, {preserveForm = false, fresh = false} = {}) {
  if (state.selectedCase !== caseData || state.activePage !== "review") return;
  const requestSeq = (state.combinedReviewContextRequestSeq || 0) + 1;
  state.combinedReviewContextRequestSeq = requestSeq;
  const runId = currentReviewRunId(caseData);
  const key = combinedReviewContextKey(caseData);
  const pageContext = capturePageContext();
  const current = () => state.combinedReviewContextRequestSeq === requestSeq
    && state.selectedCase === caseData && combinedReviewContextKey(caseData) === key
    && isPageContextCurrent(pageContext, { matchUrl: false });
  state.combinedReviewContext = null;
  state.combinedReviewLoad = { key, status: "loading" };
  renderCombinedReviewContextStatus();
  try {
    const campaignId = combinedReviewCampaignBinding(caseData);
    const params = new URLSearchParams();
    if (runId) params.set("model_run_id", runId);
    if (campaignId) params.set("campaign_id", campaignId);
    // After a commit, do not join an older in-flight read with stale head IDs.
    const request = fresh ? apiRequest : api;
    const result = await request(`/api/cases/${encodeURIComponent(caseData.issue_id)}/combined-review-context?${params.toString()}`,
      fresh ? {cache: "no-store"} : {});
    if (!current()) return;
    const context = result.context;
    if (!context?.assigned || String(context.issue?.issue_id || "") !== String(caseData.issue_id)
        || String(context.campaign?.id || "") !== campaignId
        || String(context.campaign?.evaluation_run_id || "") !== runId) {
      throw new Error("联合复核返回的任务上下文不一致，请从任务入口重新打开。");
    }
    state.combinedReviewContext = context;
    state.combinedReviewLoad = { key, status: "ready" };
    caseData.label_state = context.label_state || caseData.label_state;
    if($('#humanReviewStatus'))renderHumanReviewStatus(caseData.label_state?.human_publication);
    syncModelReviewProgress(context.model_review);
    if (context.model_review) {
      caseData.annotations = [context.model_review, ...(caseData.annotations || []).filter(
        (item) => String(item.id) !== String(context.model_review.id)
      )];
      updateReviewHistory(caseData);
    }
    // Exclusion must hydrate even when other fields have a restored/early draft.
    // Only the Case-specific draft flag can override the current Case revision.
    if (!preserveForm) populateCombinedCaseExclusion(context, caseData);
    if (!preserveForm) {
      // Protect actual edits independently: a model-note draft must not block
      // saved Case tags/rationale, nor a Case edit block the saved model note.
      const draft = reviewDraftForCase(caseData);
      const formFields = $("#annotationForm")?._reviewDraftFields;
      const preserveFields = new Set(formFields || reviewDraftEditedFields(draft));
      if (!formFields && !draft && state.reviewFormDirty) REVIEW_DRAFT_FIELDS.forEach((field) => preserveFields.add(field));
      populateCombinedCaseLabel(context, caseData, {preserveFields});
    }
    renderCaseRationaleImages(caseData);
    renderCombinedReviewContextStatus();
    return context;
  } catch (error) {
    if (!current()) return;
    const message = uiText("联合复核上下文加载失败：", "Combined review context failed: ") + error.message;
    state.combinedReviewLoad = { key, status: "error", error: message };
    renderCombinedReviewContextStatus();
    throw error;
  }
}
