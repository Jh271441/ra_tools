/* review-form.js
 * Review detail shell, form rendering and draft-preserving synchronization.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

// Refresh read-only sidebar metadata without replacing the editable form/draft.
// Change display text only: draft inputs, attachments, listeners and focus survive.
function refreshReviewFormLanguage() {
  const root = $("#reviewPane");
  if (!root?.querySelector("#annotationForm")) return;
  applyDomI18n(root);
  applyI18nPlaceholders(root);
  root.querySelectorAll("[data-tag-dropdown-group]").forEach(dropdown => {
    const label = dropdown.querySelector(".tag-group-label")?.textContent || "";
    const creator = dropdown.querySelector("[data-open-review-tag-creator]");
    if (creator) {
      creator.dataset.tagCreateGroupLabel = label;
      creator.title = uiText(`新增${label}标签`, `Add ${label} tag`);
      creator.setAttribute("aria-label", creator.title);
    }
    const shortcut = dropdown.querySelector(".tag-group-shortcut");
    if (shortcut) shortcut.title = uiText(`按 ${shortcut.textContent} 展开或收起`, `Press ${shortcut.textContent} to toggle`);
  });
  const status = root.querySelector("#modelReviewStatusInput");
  if (status) {
    for (const option of status.options) {
      const definition = MODEL_REVIEW_STATUS_OPTIONS.find(item => item.value === option.value);
      if (definition) option.textContent = uiText(definition.labelZh, definition.labelEn);
    }
    status.title = uiText("M 打开；1 待复核 / 2 已完成；Enter 保存", "M opens; 1 Needs review / 2 Completed; Enter saves");
    enhanceNativeUiSelect(status);
  }
  updateTagSummary();
  updateEvidenceSummary();
  syncReviewTagCreatorPlacement(root);
  renderCombinedReviewContextStatus();
  enhanceDashboardSelects(root);
}

function renderReviewSummary(caseData) {
  const shared = $("#reviewSharedLabelState");
  if (shared) {
    const restoreFocus = shared.contains(document.activeElement);
    shared.innerHTML = sharedLabelStateButtonMarkup(caseData, { showEmpty: true, summaryOnly: true });
    bindSharedLabelStateTriggers(shared, () => caseData);
    if (restoreFocus) shared.querySelector("button")?.focus({preventScroll:true});
  }
}

function renderDetail(caseData, { preserveMedia = false } = {}) {
  const retainedMedia = preserveMedia && state.detailMedia.issueId === String(caseData.issue_id)
    ? $("#detailPane")?.querySelector(".detail-hero-media") : null;
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdValue = String(caseData.issue_id || "");
  const issueIdLink = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  const issueIdMarkup = `<span class="detail-issue-id-group">${issueIdLink}<button class="detail-copy-id-button" type="button" data-copy-issue-id aria-label="复制 Issue ID ${issueId}" title="复制 Issue ID"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="6" width="9" height="10" rx="2"></rect><path d="M13 6V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg></button></span>`;
  const externalLinksMarkup = detailExternalLinksMarkup(caseData);
  ensureDetailMediaState(caseData);
  const predCount = (caseData.predictions || []).length;
  const modelHistoryButton = `<button class="history-inline-button" id="modelHistoryLaunchButton" type="button" data-open-history="model" aria-keyshortcuts="P" title="${escapeHtml(uiText("展开或收起评测 Run 历史（P）", "Toggle Run history (P)"))}"><span class="ui-lang-zh">Run 历史 · ${predCount}</span><span class="ui-lang-en">Run history · ${predCount}</span><kbd class="review-control-shortcut" aria-hidden="true">P</kbd></button>`;
  const predictionComparable = MODEL_LABELS.includes(primary?.model_label) && LABELS.includes(caseData.gt_label);
  const predictionMatches = modelLabelMatchesGt(primary?.model_label, caseData.gt_label);
  const compareText = !predictionComparable
    ? ""
    : predictionMatches
      ? `<span class="ui-lang-zh">一致</span><span class="ui-lang-en">Match</span>`
      : `<span class="ui-lang-zh">不一致</span><span class="ui-lang-en">Mismatch</span>`;
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title-group">
          <div class="detail-title"><h2><span class="ui-lang-zh">问题详情</span><span class="ui-lang-en">Issue Details</span></h2>${issueIdMarkup}<span id="detailExternalLinks" class="detail-external-links" ${externalLinksMarkup ? "" : "hidden"}>${externalLinksMarkup}</span></div>
        </div>
        <div class="detail-navigation">
          <div class="case-detail-pager">
            <button class="button button-quiet" id="previousIssueButton" type="button"><span class="ui-lang-zh">← 上一 Issue</span><span class="ui-lang-en">← Prev</span><kbd class="review-control-shortcut review-nav-shortcut" aria-hidden="true">[</kbd></button>
            <span class="detail-queue-position" id="detailQueuePosition" title="${escapeHtml(uiText("输入序号后回车跳转", "Enter index and press Return to jump"))}">
              <input class="detail-queue-index-input" id="detailQueueIndexInput" type="number" min="1" step="1" inputmode="numeric" aria-label="${escapeHtml(uiText("跳转到筛选队列中的第几条", "Jump to queue index"))}" disabled />
              <span class="detail-queue-total" id="detailQueueTotal">/ —</span>
            </span>
            <button class="button button-quiet" id="nextIssueButton" type="button"><span class="ui-lang-zh">下一 Issue →</span><span class="ui-lang-en">Next →</span><kbd class="review-control-shortcut review-nav-shortcut" aria-hidden="true">]</kbd></button>
          </div>
        </div>
      </div>
      <div class="detail-context-row">
        <div class="comparison-summary" aria-label="${escapeHtml(uiText("GT 与当前模型对比", "GT vs current model"))}">
          <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(gtDisplayLabel(caseData), uiText("缺失", "Missing"))}
          <b aria-hidden="true">→</b>
          <span class="comparison-side-label comparison-side-model"><span class="ui-lang-zh">当前模型</span><span class="ui-lang-en">Model</span></span>${labelBadge(primary?.model_label, uiText("未输出", "None"))}
          ${predictionComparable ? `<strong class="${!predictionMatches ? "comparison-fail" : "comparison-neutral"}">${compareText}</strong>` : ""}
        </div>
        <button class="button button-quiet detail-back-button" id="backToGalleryButton" type="button" title="${escapeHtml(uiText("返回筛选结果", "Back to filtered gallery"))}" aria-label="${escapeHtml(uiText("返回筛选结果", "Back to filtered gallery"))}"><span class="ui-lang-zh">← 返回筛选结果</span><span class="ui-lang-en">← Back to gallery</span></button>
        ${caseData.summary ? `<p class="detail-summary">${escapeHtml(caseData.summary)}</p>` : ""}
        <div class="detail-context-actions">
          ${detailMediaCommandMarkup(caseData)}
          <div class="detail-actions">
            <button class="button button-quiet" type="button" data-predict-current-case><span class="ui-lang-zh">API 推理</span><span class="ui-lang-en">API inference</span></button>
            ${modelHistoryButton}
          </div>
        </div>
      </div>
      ${caseData.review_note ? `<details class="review-note-details"><summary><span class="ui-lang-zh">查看历史备注</span><span class="ui-lang-en">Show legacy note</span></summary><div class="review-note"><span><span class="ui-lang-zh">历史备注</span><span class="ui-lang-en">Legacy note</span></span>${escapeHtml(caseData.review_note)}</div></details>` : ""}
    </div>
    ${currentRunOutputMarkup(caseData, primary)}
    ${retainedMedia ? '<div data-retained-detail-media></div>' : heroMediaSection(caseData)}`;
  if (retainedMedia) $("#detailPane").querySelector("[data-retained-detail-media]")?.replaceWith(retainedMedia);
  $("#detailPane").querySelector("[data-predict-current-case]")?.addEventListener("click", () => {
    openBatchDraft([caseData.issue_id], "single");
  });
  $("#detailPane").querySelector("[data-open-history='model']")?.addEventListener("click", () => {
    toggleHistoryDialog("model", caseData);
  });
  $("#detailPane").querySelector("[data-copy-issue-id]")?.addEventListener("click", (event) => {
    copyReviewIssueId(issueIdValue, event.currentTarget);
  });
  bindDetailExternalLinks(caseData);
  renderReviewSummary(caseData);
  $("#detailPane").querySelector("#backToGalleryButton")?.addEventListener("click", returnToReviewGallery);
  $("#detailPane").querySelector("#previousIssueButton")?.addEventListener("click", () => {
    navigateAdjacentCase(-1).catch((error) => showToast(error.message, true));
  });
  $("#detailPane").querySelector("#nextIssueButton")?.addEventListener("click", () => {
    navigateAdjacentCase(1).catch((error) => showToast(error.message, true));
  });
  bindDetailQueueIndexJump($("#detailPane"));
  renderCaseNavigation();
  bindDetailMedia(caseData);
}

function syncReviewFormFromCase(caseData) {
  const reviewPane = $("#reviewPane");
  if (!reviewPane?.querySelector("#annotationForm")) {
    renderReview(caseData);
    return;
  }
  const combinedMode = effectiveReviewWorkflowMode(caseData) === "model_review_and_case_label";
  const serverPrevious = reviewFormAnnotation(caseData, combinedMode);
  const draft = reviewDraftForCase(caseData);
  const previous = applyReviewDraft(serverPrevious, draft);
  const runAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const hasPreviousReview = Boolean(runAnnotations.length || draft);
  const chosenEvidence = new Set(
    hasPreviousReview ? previous.missing_evidence || [] : []
  );
  const chosenTags = new Set(
    combinedMode && savedOwnCaseRevision(caseData)
      ? previous.tags || [] : initialReviewTagsForCurrentRun(caseData, previous, draft)
  );
  const evidenceCatalog = state.config?.missing_evidence_catalog || [];
  const tagCatalog = state.config?.review_tag_catalog || [];
  const evidenceKeys = new Set(evidenceCatalog.map((item) => item.key));
  const tagKeys = new Set(tagCatalog.map((item) => item.key));

  reviewPane.querySelectorAll(".custom-evidence-option").forEach((node) => node.remove());
  reviewPane.querySelectorAll(".custom-tag-option").forEach((node) => node.remove());
  const evidenceList = $("#missingEvidenceOptions");
  for (const key of chosenEvidence) {
    if (evidenceKeys.has(key) || !evidenceList) continue;
    if (
      [...evidenceList.querySelectorAll('input[name="missingEvidence"]')].some(
        (node) => node.value === key
      )
    ) {
      continue;
    }
    const template = document.createElement("template");
    template.innerHTML = missingEvidenceOptionMarkup({
      key,
      label: evidenceLabel(key),
      hint: "本条 Review 新建的缺失信息",
      builtin: false,
    }, true, false);
    const option = template.content.firstElementChild;
    option.classList.add("custom-evidence-option");
    evidenceList.appendChild(option);
    option.querySelector("input")?.addEventListener("change", updateEvidenceSummary);
  }
  let tagHistory = reviewPane.querySelector(".review-tag-legacy");
  let tagHistoryOptions = tagHistory?.querySelector(".review-tag-options");
  for (const key of chosenTags) {
    if (tagKeys.has(key)) continue;
    if (!tagHistoryOptions) {
      tagHistory = document.createElement("div");
      tagHistory.className = "review-tag-legacy";
      tagHistory.innerHTML = '<span>历史标签</span><div class="review-tag-options"></div>';
      reviewPane.querySelector(".review-exclude-toggle")?.before(tagHistory);
      tagHistoryOptions = tagHistory.querySelector(".review-tag-options");
    }
    if (!tagHistoryOptions) continue;
    const template = document.createElement("template");
    template.innerHTML = reviewTagOptionMarkup(
      { key, label: tagLabel(key), builtin: false },
      true,
      "",
      false,
    );
    const option = template.content.firstElementChild;
    option?.classList.add("custom-tag-option");
    tagHistoryOptions.append(option);
    option.querySelector("input")?.addEventListener("change", updateTagSummary);
  }
  reviewPane.querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.checked = chosenEvidence.has(input.value);
  });
  reviewPane.querySelectorAll('input[name="reviewTags"]').forEach((input) => {
    input.checked = chosenTags.has(input.value);
  });
  const excluded = $("#reviewExcludeInput");
  if (excluded && (combinedMode || excluded.dataset?.caseExclusion !== "true")) {
    excluded.checked = Boolean(previous.case_is_excluded ?? previous.is_excluded);
  }
  const rationale = $("#combinedCaseRationale");
  if (combinedMode && rationale) rationale.value = String(previous.case_rationale || "");
  const expectedOutput = annotationExpectedOutput(previous);
  const expectedOutputInput = $("#expectedOutputInput");
  if (expectedOutputInput) {
    expectedOutputInput.value = expectedOutput;
    expectedOutputInput.dataset.selectionSource = expectedOutput ? "stored" : "empty";
  }
  const note = $("#annotationNote");
  if (note) {
    note.value = previous.note || "";
    updateReviewMentionComposer(note);
  }
  const modelReviewStatusInput = $("#modelReviewStatusInput");
  if (modelReviewStatusInput) {
    modelReviewStatusInput.value = modelReviewSubmissionStatus(previous);
    enhanceNativeUiSelect(modelReviewStatusInput);
    syncModelReviewProgress(previous);
  }
  const author = $("#annotationAuthor");
  if (author && !(state.session.verified && state.session.username)) {
    author.value = state.session.username || previous.author || "";
  }
  state.selectedAnnotationLabel = expectedOutput;
  state.reviewEditRunId = currentReviewRunId(caseData);
  // A legacy unbound Review can be displayed as a read-only fallback when a
  // selected Run has no bound version yet. It is not the optimistic-lock
  // predecessor for that Run; the first save must therefore expect no bound
  // annotation and create one for the selected Run.
  state.reviewEditBaseAnnotationId = currentReviewBaseAnnotationId(
    previous,
    state.reviewEditRunId
  );
  state.reviewFormDirty = Boolean(draft) || caseRationalePendingImages(caseData).length > 0;
  reviewPane.querySelector("#annotationForm")._reviewDraftFields = new Set(reviewDraftEditedFields(draft));
  state.deferredDetailRefresh = false;
  clearPendingReviewImages();
  updateEvidenceSummary();
  updateTagSummary();
  bindMissingEvidenceCatalogControls(reviewPane);
  bindReviewTagCatalogControls(reviewPane);
  renderReviewSummary(caseData);
  updateReviewHistory(caseData);
}

function savedOwnCaseRevision(caseData) {
  const username = String(state.session?.username || "").toLowerCase();
  if (!username) return null;
  const revisions = (caseData?.label_state?.sources || []).flatMap((source) =>
    (source.revision_summaries || []).filter((revision) =>
      String(revision.author || "").toLowerCase() === username
      && !(source.method === "adjudication" && Number(source.result_revision_id) === Number(revision.id))
    ));
  return revisions.sort((a, b) => Number(b.id) - Number(a.id))[0] || null;
}

function savedOwnCaseRationale(caseData) {
  return String(savedOwnCaseRevision(caseData)?.rationale || "");
}

function reviewFormAnnotation(caseData, combinedMode) {
  const annotation = currentReviewAnnotation(caseData);
  const revision = combinedMode ? savedOwnCaseRevision(caseData) : null;
  if (!revision) return annotation;
  // Model Reviews deliberately have no Case tags/output. Start with the saved
  // own Case revision so delayed context reads cannot expose an empty label form.
  return {...annotation, expected_output: revision.expected_output || "", tags: revision.tags || [],
    is_excluded: Boolean(revision.is_excluded), case_is_excluded: Boolean(revision.is_excluded),
    case_rationale: String(revision.rationale || "")};
}

function renderReview(caseData) {
  if (typeof isReviewDecisionEditor === "function" && isReviewDecisionEditor()) return;
  const reviewRunId = currentReviewRunId(caseData);
  const runBoundModelReview = Boolean(reviewRunId);
  const combinedMode = syncReviewWorkflowMode(caseData) === "model_review_and_case_label";
  const runAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const allAnnotations = reviewAnnotationsForAllRuns(caseData);
  const sourceSuggestion = currentReviewSourceSuggestion(caseData);
  const serverPrevious = reviewFormAnnotation(caseData, combinedMode);
  const draft = reviewDraftForCase(caseData);
  const previous = applyReviewDraft(serverPrevious, draft);
  state.reviewEditRunId = reviewRunId;
  state.reviewEditBaseAnnotationId = currentReviewBaseAnnotationId(
    previous,
    reviewRunId
  );
  state.reviewFormDirty = false;
  state.deferredDetailRefresh = false;
  const expectedOutput = annotationExpectedOutput(previous);
  state.selectedAnnotationLabel = expectedOutput;
  const catalog = state.config?.missing_evidence_catalog || [];
  const tagCatalog = state.config?.review_tag_catalog || [];
  const hasPreviousReview = Boolean(runAnnotations.length || draft);
  const chosenEvidence = new Set(
    hasPreviousReview ? previous.missing_evidence || [] : []
  );
  const catalogKeys = new Set(catalog.map((item) => item.key));
  const visibleCatalog = catalog.filter((item) => !item.deleted);
  const selectedDeletedEvidence = catalog.filter(
    (item) => item.deleted && chosenEvidence.has(item.key)
  );
  const customEvidenceKeys = [...chosenEvidence].filter((key) => !catalogKeys.has(key));
  const chosenTags = new Set(
    combinedMode && savedOwnCaseRevision(caseData)
      ? previous.tags || [] : initialReviewTagsForCurrentRun(caseData, previous, draft)
  );
  const tagCatalogKeys = new Set(tagCatalog.map((item) => item.key));
  const customTagKeys = [...chosenTags].filter((tag) => !tagCatalogKeys.has(tag));
  const author = state.session.username || previous.author || "";
  const authorLocked = Boolean(state.session.verified && state.session.username);
  const reviewStatus = !expectedOutput
    ? "pending"
    : expectedOutput === String(caseData.gt_label || "")
      ? "reviewed"
      : "needs_gt_review";
  const modelReviewStatus = modelReviewSubmissionStatus(previous);
  const sharedLabelState = caseData.label_state || {};
  const sharedExpectedOutput = String(sharedLabelState.state || "") === "resolved"
    && LABELS.includes(String(sharedLabelState.expected_output || ""))
      ? String(sharedLabelState.expected_output)
      : "";
  const sharedVisual = sharedLabelStateVisual(sharedLabelState);
  const readonlyExpectedOption = sharedExpectedOutput
    ? EXPECTED_OUTPUT_OPTIONS.find((item) => item.value === sharedExpectedOutput)
    : null;
  const readonlyExpectedZh = readonlyExpectedOption?.labelZh || "待确定";
  const readonlyExpectedEn = readonlyExpectedOption?.labelEn || "Undetermined";
  const readonlyStatusZh = sharedVisual.kind === "matches" ? "与 GT 一致" : sharedVisual.kind === "none" || sharedVisual.kind === "pending" ? "待确定" : sharedVisual.zh;
  const readonlyStatusEn = sharedVisual.kind === "matches" ? "Matches GT" : sharedVisual.kind === "none" || sharedVisual.kind === "pending" ? "Undetermined" : sharedVisual.en;
  const sharedLabelSummary = `<span class="review-shared-label-summary" id="reviewSharedLabelState"></span>`;
  const readonlyExpectedMarkup = `<div class="review-expected-output-field review-expected-output-readonly">
    <div class="review-expected-output-heading">
      <span class="review-readonly-label"><span class="ui-lang-zh">期望输出</span><span class="ui-lang-en">Expected output</span></span>
      <span class="derived-review-status" data-status="${escapeHtml(sharedVisual.kind === "matches" ? "reviewed" : sharedVisual.kind === "needs-review" ? "needs_gt_review" : "pending")}"><span class="ui-lang-zh">状态：${escapeHtml(readonlyStatusZh)}</span><span class="ui-lang-en">Status: ${escapeHtml(readonlyStatusEn)}</span></span>
    </div>
    <div class="ui-select expected-output-picker readonly-expected-output-picker">
      <button class="ui-select-trigger" type="button" disabled aria-label="${escapeHtml(uiText(`期望输出 ${readonlyExpectedZh}，只读`, `Expected output ${readonlyExpectedEn}, read only`))}" title="${escapeHtml(uiText("只读；请到 问题标注修改", "Read only; edit in Case labeling"))}">
        <span class="ui-select-summary"><span class="ui-select-summary-value"><span class="ui-lang-zh">${escapeHtml(readonlyExpectedZh)}</span><span class="ui-lang-en">${escapeHtml(readonlyExpectedEn)}</span></span><span class="ui-select-inference-marker"><span class="ui-lang-zh">只读</span><span class="ui-lang-en">Read only</span></span></span>
        <span class="ui-select-caret" aria-hidden="true"></span>
      </button>
    </div>
    ${sharedLabelSummary}
  </div>`;
  const caseLabelingUrl = pageUrl("labeling", {
    issue: caseData.issue_id || "",
    baselines: state.reviewTaskContext?.baseline_ids || state.selectedBaselineIds,
    forceBaselines: true,
  });
  const customEvidenceOptions = customEvidenceKeys
    .map((key) => missingEvidenceOptionMarkup({ key, label: evidenceLabel(key), hint: "本条 Review 新建的缺失信息", builtin: false }, true, false))
    .join("");
  const deletedEvidenceOptions = selectedDeletedEvidence
    .map((item) => missingEvidenceOptionMarkup(item, true, false))
    .join("");
  const tagOption = (key, label, selected, groupKey = "", item = null) => reviewTagOptionMarkup(
    item || { key, label, builtin: true },
    selected,
    groupKey,
  );
  const customTagOptions = customTagKeys
    .map((key) => tagOption(key, tagLabel(key), true))
    .join("");
  const issueTagGroups = renderReviewTagGroups(tagCatalog, chosenTags, tagOption);
  const sourceSuggestionMarkup = issueTagSourceSuggestionMarkup(sourceSuggestion);
  const taskSupplementalOnly = Boolean(
    state.reviewWorkSplitId
    && caseData.review_assignment?.split_id === state.reviewWorkSplitId
    && caseData.review_assignment?.assigned === false
  );
  const taskSupplementalNotice = taskSupplementalOnly
    ? `<div class="review-task-supplemental-notice" role="status"><span>${escapeHtml(uiText("任务外补充复核 · 不计入任务进度", "Supplemental · Not counted toward the task"))}</span><details><summary aria-label="${escapeHtml(uiText("查看补充复核说明", "About supplemental review"))}">ⓘ</summary><span>${escapeHtml(uiText("此 Issue 未分配给你。复核保存在个人记录中，Case 标签参与共享结论，原分配人的进度不变。", "This Issue is assigned to another reviewer. Your review is saved in your personal history; the Case label contributes to the shared result without changing the assignee's progress."))}</span></details></div>`
    : "";
  const noRunModelReviewNotice = `<div class="model-review-readonly-note model-review-run-required" role="status">
    <span class="model-review-readonly-copy">
      <strong><span class="ui-lang-zh">未选 Run</span><span class="ui-lang-en">No Run</span></strong>
      <small><span class="ui-lang-zh">模型复核暂不可用${combinedMode ? " · Case 标签仍可提交" : ""}</span><span class="ui-lang-en">Model review unavailable${combinedMode ? " · Case label still available" : ""}</span></small>
    </span>
    <button type="button" data-select-model-run><span class="ui-lang-zh">选择 Model Run</span><span class="ui-lang-en">Select Model Run</span></button>
    ${combinedMode ? "" : `<a href="${escapeHtml(caseLabelingUrl)}"><span class="ui-lang-zh">打开 问题标注</span><span class="ui-lang-en">Open Case labeling</span></a>`}
    <span class="model-review-run-help">
      <button class="model-review-run-help-button" type="button" aria-label="查看未选择 Run 的说明" aria-describedby="modelReviewRunTooltip">i</button>
      <span class="model-review-run-tooltip" id="modelReviewRunTooltip" role="tooltip"><span class="ui-lang-zh">选择 Run 后可填写判错原因、缺失信息和截图。${combinedMode ? "当前仍可提交上方 问题标注。" : ""}</span><span class="ui-lang-en">Select a Run to enter the model reason, missing evidence, and screenshots.${combinedMode ? " You can still submit the Case label above." : ""}</span></span>
    </span>
  </div>`;
  $("#reviewPane").innerHTML = `
    <form class="review-form" id="annotationForm" data-issue-id="${escapeHtml(caseData.issue_id)}">
      ${taskSupplementalNotice}
      <section class="review-section issue-tag-section combined-case-label-card" ${combinedMode ? "" : "hidden"}>
        <div class="review-section-heading"><div><h2><span class="ui-lang-zh">Issue 标签</span><span class="ui-lang-en">Issue tags</span> <small class="combined-mode-badge" title="${escapeHtml(uiText("联合复核", "Combined review"))}"><span class="ui-lang-zh">联合</span><span class="ui-lang-en">Combined</span></small></h2>${sourceSuggestionMarkup}</div><div class="review-case-heading-meta review-heading-actions">${sharedLabelSummary}<button class="history-inline-button" id="issueLabelCommentsButton" type="button" aria-keyshortcuts="D" title="${escapeHtml(uiText("问题讨论（D）；支持图片与 @", "Issue discussion (D); images and @mentions"))}"><span class="ui-lang-zh">讨论</span><span class="ui-lang-en">Discuss</span><kbd class="review-control-shortcut" aria-hidden="true">D</kbd></button><span class="evidence-summary-count" id="tagSummaryCount" hidden aria-hidden="true">${escapeHtml(t("detail.selected_n", { n: chosenTags.size }))}</span></div></div>
        <div class="review-tag-groups-shell">${issueTagGroups}${customTagOptions ? `<div class="review-tag-legacy"><span class="ui-lang-zh">历史标签</span><span class="ui-lang-en">Legacy tags</span><div class="review-tag-options">${customTagOptions}</div></div>` : ""}</div>
        ${caseExclusionToggleMarkup("reviewExcludeInput", false, true)}
        <label class="combined-case-rationale">
          <span class="combined-case-rationale-heading">
            <span><span class="ui-lang-zh">标签依据 / 说明</span><span class="ui-lang-en">Label rationale</span></span>
            <small class="review-reason-shortcuts"><span class="ui-lang-zh"><kbd>E</kbd> 聚焦 · <kbd>⇧ Enter</kbd> 换行</span><span class="ui-lang-en"><kbd>E</kbd> Focus · <kbd>⇧ Enter</kbd> New line</span></small>
          </span>
          <textarea id="combinedCaseRationale" data-mention-composer rows="2" aria-keyshortcuts="E Escape Enter Shift+Enter" data-has-case-draft="${reviewDraftHasField(draft, "case_rationale") ? "1" : "0"}" placeholder="${escapeHtml(uiText("说明 Case 标签依据；输入 @ 可通知同事", "Explain the Case label; type @ to notify a colleague"))}">${escapeHtml(reviewDraftHasField(draft, "case_rationale") ? String(draft.case_rationale || "") : savedOwnCaseRationale(caseData))}</textarea>
          <div class="review-mention-composer" id="combinedCaseMentionComposer" data-mention-composer-root aria-live="polite"></div>
        </label>
        <div class="review-attachment-field" id="caseRationaleImages">
          <div class="screenshot-paste-zone is-compact" id="caseRationalePasteZone" tabindex="0" role="group" aria-label="${escapeHtml(uiText("标签图片：选择、粘贴或拖入", "Label images: browse, paste or drop"))}">
            <span class="screenshot-paste-copy"><strong><span class="ui-lang-zh">标签图片</span><span class="ui-lang-en">Label images</span></strong><small><span class="ui-lang-zh">可粘贴 / 拖入 · 最多 4 张 · 随标签保存</span><span class="ui-lang-en">Paste / drop · max 4 · saved with label</span></small></span>
            <button class="screenshot-browse-button" id="caseRationaleImageBrowse" type="button" ${hasDashboardWriteRole() && !state.session?.read_only ? "" : "disabled"}><span class="ui-lang-zh">选择图片</span><span class="ui-lang-en">Browse</span></button>
          </div>
          <input class="hidden" id="caseRationaleImageInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
          <div class="pending-screenshot-list" id="caseRationaleImageList" aria-live="polite"></div>
        </div>
      </section>
      <section class="review-section model-error-section">
        <div class="review-section-heading">
          <div>
            <h2>
              <span class="ui-lang-zh">模型结果 Review</span>
              <span class="ui-lang-en">Model Result Review</span>
            </h2>
          </div>
          <div class="review-heading-actions">
            <button class="history-inline-button" id="reviewCommentsButton" type="button" data-review-comments aria-keyshortcuts="Shift+D" title="${escapeHtml(uiText("问题讨论（Shift+D）", "Issue discussion (Shift+D)"))}">
              <span class="ui-lang-zh">讨论</span><span class="ui-lang-en">Discussion</span>
              <kbd class="review-control-shortcut" aria-hidden="true">⇧ D</kbd>
            </button>
            <button class="history-inline-button" type="button" data-open-history="review" id="reviewHistoryLaunchButton" aria-keyshortcuts="J" title="展开或收起 Review 历史（J）">
              <span class="ui-lang-zh">历史 · ${allAnnotations.length}</span>
              <span class="ui-lang-en">History · ${allAnnotations.length}</span>
              <kbd class="review-control-shortcut" aria-hidden="true">J</kbd>
            </button>
          </div>
        </div>
        ${combinedMode ? "" : readonlyExpectedMarkup}
        <div class="review-expected-output-field" hidden>
          <div class="review-expected-output-heading">
            <span id="expectedOutputLabel"><span class="ui-lang-zh">期望输出</span><span class="ui-lang-en">Expected output</span></span>
            <span class="derived-review-status" id="derivedReviewStatus" data-status="${escapeHtml(reviewStatus)}"></span>
            <details class="expected-output-rule">
              <summary><span class="ui-lang-zh">推算规则</span><span class="ui-lang-en">Rules</span></summary>
              <div class="expected-output-rule-popover">
                <strong><span class="ui-lang-zh">先推期望输出，再比较 GT</span><span class="ui-lang-en">Infer output, then compare GT</span></strong>
                <ul class="ui-lang-zh">
                  <li>误触发 Tags → 误触发</li>
                  <li>正确触发 / RA Tags → 正确触发</li>
                  <li>无需协助 Tags → 无需协助</li>
                  <li>无唯一结论 → 待补充；等于 GT → 与 GT 一致；不同 → GT 需复核</li>
                </ul>
                <ul class="ui-lang-en">
                  <li>False-trigger Tags → False trigger</li>
                  <li>Correct-trigger / RA Tags → Correct trigger</li>
                  <li>No-assist Tags → No assist</li>
                  <li>No unique result → Pending; equals GT → Matches GT; differs → Needs GT review</li>
                </ul>
                <small><span class="ui-lang-zh">唯一推断项会在下拉框标记“自动推断”；选择其他项或选择互相冲突的 Tags 时会提示冲突并禁止保存。</span><span class="ui-lang-en">The inferred option is marked in the dropdown; choosing another option or conflicting Tags shows a conflict and blocks saving.</span></small>
              </div>
            </details>
          </div>
          <div class="ui-select expected-output-picker" id="expectedOutputPicker">
            <button class="ui-select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="expectedOutputPickerPanel" aria-labelledby="expectedOutputLabel expectedOutputPickerSummary" aria-describedby="expectedOutputHint" aria-invalid="false">
              <span class="ui-select-summary" id="expectedOutputPickerSummary">${escapeHtml(i18nLocale() === "en" ? "Pending" : "待补充")}</span>
              <span class="ui-select-caret" aria-hidden="true"></span>
            </button>
            <div class="ui-select-panel" id="expectedOutputPickerPanel" role="listbox" hidden></div>
            <select class="ui-select-native gateway-model-native-select" id="expectedOutputInput" data-selection-source="${expectedOutput ? "stored" : "empty"}" aria-hidden="true" tabindex="-1">
              ${EXPECTED_OUTPUT_OPTIONS.map((item) => `<option value="${escapeHtml(item.value)}" ${item.value === expectedOutput ? "selected" : ""}>${escapeHtml(i18nLocale() === "en" ? item.labelEn : item.labelZh)}</option>`).join("")}
            </select>
          </div>
          <small class="review-expected-output-hint" id="expectedOutputHint" hidden></small>
          <input id="reviewStatusInput" type="hidden" value="${escapeHtml(reviewStatus)}" />
        </div>
        ${runBoundModelReview ? `<label class="model-review-status-field"><span class="model-review-status-heading"><span><span class="ui-lang-zh">判错复核状态</span><span class="ui-lang-en">Model review status</span></span><small id="modelReviewCurrentProgress">${modelReviewProgressMarkup(serverPrevious)}</small></span><select id="modelReviewStatusInput" aria-keyshortcuts="M" title="${escapeHtml(uiText("M 打开；1 待复核 / 2 已完成；Enter 保存", "M opens; 1 Needs review / 2 Completed; Enter saves"))}">${MODEL_REVIEW_STATUS_OPTIONS.map((item) => `<option value="${item.value}" ${item.value === modelReviewStatus ? "selected" : ""}>${escapeHtml(i18nLocale() === "en" ? item.labelEn : item.labelZh)}</option>`).join("")}</select></label>` : noRunModelReviewNotice}
        <label class="review-reason">
          <span class="review-reason-heading">
            <span><span class="ui-lang-zh">模型为什么判错？</span><span class="ui-lang-en">Why was the model wrong?</span></span>
            <small class="review-reason-shortcuts">
              <span class="ui-lang-zh"><kbd>⇧ E</kbd> 聚焦 · <kbd>⇧ Enter</kbd> 换行</span>
              <span class="ui-lang-en"><kbd>⇧ E</kbd> Focus · <kbd>⇧ Enter</kbd> New line</span>
            </small>
          </span>
          <textarea id="annotationNote" rows="2" aria-keyshortcuts="Shift+E Escape Enter Shift+Enter" placeholder="说明关键证据；输入 @ 可通知同事。" ${runBoundModelReview ? "" : "disabled"}>${escapeHtml(previous.note || "")}</textarea>
        </label>
        <div class="review-mention-composer" id="reviewMentionComposer" aria-live="polite"></div>
        <details class="evidence-dropdown review-dropdown review-tag-dropdown" data-missing-evidence-dropdown>
          <summary aria-keyshortcuts="I">
            <span class="tag-group-label"><span class="ui-lang-zh">缺失信息（多选）</span><span class="ui-lang-en">Missing evidence</span></span>
            <kbd class="review-control-shortcut tag-group-shortcut" aria-hidden="true" title="${escapeHtml(uiText("按 I 展开或收起缺失信息", "Press I to toggle missing evidence"))}">I</kbd>
            <span class="tag-group-trailing">
              <button class="tag-catalog-add-button" type="button" data-open-missing-evidence-creator aria-label="新增缺失信息" title="新增缺失信息">＋</button>
              <span class="evidence-summary-count tag-group-summary" id="evidenceSummaryCount">已选 ${chosenEvidence.size} 项</span>
              <span class="tag-group-chevron" aria-hidden="true"></span>
            </span>
            <span class="review-axis-selected review-evidence-selected" data-selected-missing-evidence${chosenEvidence.size ? "" : " hidden"}></span>
          </summary>
          <div class="evidence-options review-tag-options" id="missingEvidenceOptions">${visibleCatalog.map((item) => missingEvidenceOptionMarkup(item, chosenEvidence.has(item.key), true)).join("")}${deletedEvidenceOptions}${customEvidenceOptions}${!visibleCatalog.length && !deletedEvidenceOptions && !customEvidenceOptions ? '<div class="review-tag-empty">暂无条目，点 ＋ 添加</div>' : ""}</div>
        </details>
        <div class="review-attachment-field">
          <div class="screenshot-paste-zone is-compact" id="screenshotPasteZone" tabindex="0" role="group" aria-label="拖拽、粘贴或选择补充截图">
            <span class="screenshot-paste-copy">
              <strong><span class="ui-lang-zh">补充截图</span><span class="ui-lang-en">Screenshots</span></strong>
              <small><span class="ui-lang-zh">拖拽到此处 / 粘贴 Ctrl/⌘+V · 最多 4 张</span><span class="ui-lang-en">Drop here / Paste Ctrl/⌘+V · max 4</span></small>
            </span>
            <button class="screenshot-browse-button" id="reviewScreenshotBrowse" type="button"><span class="ui-lang-zh">选择图片</span><span class="ui-lang-en">Browse</span></button>
          </div>
          <input class="hidden" id="reviewScreenshotInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
          <div class="pending-screenshot-list" id="pendingScreenshotList"></div>
        </div>
      </section>
      <label><span><span class="ui-lang-zh">复核人${authorLocked ? "（SSO）" : "（必填）"}</span><span class="ui-lang-en">Reviewer${authorLocked ? " (SSO)" : " (required)"}</span></span><input id="annotationAuthor" value="${escapeHtml(author)}" placeholder="姓名或工号" autocomplete="off" required ${authorLocked ? "readonly" : ""} /></label>
      <button class="button button-primary full-width review-save-button" id="reviewSaveButton" type="submit" aria-keyshortcuts="Enter" title="输入原因时按 Enter 保存；Shift+Enter 换行" ${runBoundModelReview ? "" : "disabled"}><span class="ui-lang-zh">保存新的模型复核版本</span><span class="ui-lang-en">Save model review version</span><kbd class="review-save-shortcut" aria-hidden="true">Enter</kbd></button>
      ${combinedMode ? '<div class="combined-review-context-status" id="combinedReviewContextStatus" role="status" aria-live="polite" hidden></div>' : ""}
    </form>`;
  if (!runBoundModelReview) {
    $("#annotationForm")?.querySelectorAll(
      "#missingEvidenceOptions input, #reviewScreenshotInput, #reviewScreenshotBrowse, #annotationAuthor, [data-open-missing-evidence-creator]"
    ).forEach((control) => { control.disabled = true; });
  }
  if (combinedMode) {
    const expectedField = $("#reviewPane .review-expected-output-field");
    const combinedCard = $("#reviewPane .combined-case-label-card");
    if (expectedField && combinedCard) {
      expectedField.hidden = false;
      combinedCard.querySelector(".review-tag-groups-shell")?.before(expectedField);
    }
    $("#reviewPane .model-error-section .review-attachment-field")?.setAttribute("hidden", "");
    const save = $("#reviewSaveButton");
    if (save) {
      save.disabled = false;
      save.querySelector(".ui-lang-zh").textContent = taskSupplementalOnly ? "提交任务外补充" : runBoundModelReview ? "提交联合复核" : "提交 问题标注";
      save.querySelector(".ui-lang-en").textContent = taskSupplementalOnly ? "Submit supplemental review" : runBoundModelReview ? "Submit combined review" : "Submit Case label";
    }
  }
  renderReviewSummary(caseData);
  enhanceDashboardSelects($("#reviewPane"));
  bindSelectedReviewTagControls($("#reviewPane"));
  $("#reviewPane").querySelector("[data-review-comments]")?.addEventListener("click", () => {
    openCurrentReviewDiscussion(caseData);
  });
  const expectedOutputInput = $("#expectedOutputInput");
  if (expectedOutputInput) {
    expectedOutputInput.addEventListener("change", () => {
      expectedOutputInput.dataset.selectionSource = "manual";
      syncExpectedOutputFromTags();
    });
  }
  bindUiSelect($("#expectedOutputPicker"), { maxHeight: 260, maxWidth: 420 });
  $("#reviewPane").querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.addEventListener("change", updateEvidenceSummary);
  });
  updateEvidenceSummary();
  bindMissingEvidenceCatalogControls($("#reviewPane"));
  bindReviewTagCatalogControls($("#reviewPane"));
  bindReviewDropdownDismiss();
  $("#reviewPane").querySelectorAll('input[name="reviewTags"]').forEach((input) => {
    input.addEventListener("change", updateTagSummary);
  });
  updateTagSummary();
  syncReviewDropdownShortcutHints($("#reviewPane"));
  bindReviewKeyboardShortcuts();
  bindReviewComposerShortcuts();
  bindReviewDetailActionShortcuts();
  bindReviewDropdownToggles($("#reviewPane"));
  $("#reviewPane").querySelector("[data-open-history='review']")?.addEventListener("click", () => {
    toggleHistoryDialog("review", caseData);
  });
  $("#reviewPane").querySelector("[data-select-model-run]")?.addEventListener("click", () => {
    exitReviewTaskAndOpenRunPicker().catch((error) => showToast(error.message, true));
  });
  bindCaseRationaleImages(caseData);
  bindReviewAttachmentInputs();
  restoreFailedReviewUploadImages(caseData.issue_id);
  renderPendingReviewImages();
  bindReviewMentionComposer($("#annotationNote"));
  bindReviewMentionComposer($("#combinedCaseRationale"), $("#combinedCaseMentionComposer"));
  $("#issueLabelCommentsButton")?.addEventListener("click", () => openCurrentIssueDiscussion(caseData));
  $("#combinedCaseRationale")?.addEventListener("input", (event) => { event.target.dataset.caseRationaleDirty = "1"; });
  const annotationForm = $("#annotationForm");
  annotationForm._reviewDraftFields = new Set(reviewDraftEditedFields(draft));
  const markDraftDirty = (event) => {
    state.reviewFormDirty = true;
    markReviewDraftField(annotationForm, event.target);
    persistReviewDraft(caseData);
  };
  annotationForm.addEventListener("input", markDraftDirty);
  annotationForm.addEventListener("change", markDraftDirty);
  annotationForm.addEventListener("focusout", () => {
    window.setTimeout(() => resumeDeferredReviewRefresh(caseData), 0);
  });
  bindReviewDraftLifecycle();
  state.reviewFormDirty = Boolean(draft);
  annotationForm.addEventListener("submit", saveAnnotation);
  bindAnnotationHistory($("#reviewPane"), caseData);
  if (combinedMode) {
    loadCombinedReviewContext(caseData).catch((error) => showToast(error.message, true));
  } else {
    state.combinedReviewContext = null;
    if (!runBoundModelReview && $("#reviewSaveButton")) {
      $("#reviewSaveButton").disabled = true;
    }
  }
}
