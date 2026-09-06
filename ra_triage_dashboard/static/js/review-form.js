/* ra_triage_dashboard/static/js/review-form.js
 * Review detail shell, expected output, screenshots, selectCase/save
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

const EXPECTED_OUTPUT_OPTIONS = [
  { value: "", labelZh: "待补充", labelEn: "Pending" },
  { value: "误触发", labelZh: "误触发", labelEn: "False trigger" },
  { value: "正确触发", labelZh: "正确触发", labelEn: "Correct trigger" },
  { value: "无需协助", labelZh: "无需协助", labelEn: "No assistance needed" },
];

const EXPECTED_OUTPUT_BY_TAG_GROUP = {
  false_trigger: "误触发",
  ra: "正确触发",
  no_assist: "无需协助",
};

function annotationExpectedOutput(annotation) {
  if (annotation && Object.prototype.hasOwnProperty.call(annotation, "expected_output")) {
    return String(annotation.expected_output || "").trim();
  }
  return String(annotation?.label || "").trim();
}

function issueTagSourceSuggestionMarkup(suggestion) {
  const source = suggestion?.source;
  if (!source?.label) return "";
  const label = String(source.label || "").trim();
  const filename = String(source.filename || "").trim();
  const row = Number(source.row_number || 0);
  const partial = suggestion.status === "partial";
  const title = [
    filename,
    row ? `第 ${row} 行` : "",
    partial ? "部分标签未映射，请人工补充" : "保存后才会创建新的 Review 版本",
  ]
    .filter(Boolean)
    .join(" · ");
  return `<span class="evidence-summary-count review-tag-source" title="${escapeHtml(title)}"><span class="ui-lang-zh">${escapeHtml(partial ? "历史抽检部分预填" : "历史抽检预填")} · ${escapeHtml(label)}</span><span class="ui-lang-en">${escapeHtml(partial ? "Partial historical prefill" : "Historical prefill")} · ${escapeHtml(label)}</span></span>`;
}

function inferExpectedOutputFromSelectedTags(root = $("#reviewPane") || document) {
  const inferred = new Set(
    [...root.querySelectorAll('input[name="reviewTags"]:checked')]
      .map((input) => EXPECTED_OUTPUT_BY_TAG_GROUP[input.dataset.tagGroup || ""])
      .filter(Boolean)
  );
  return {
    value: inferred.size === 1 ? [...inferred][0] : "",
    conflict: inferred.size > 1,
  };
}

function expectedOutputSelectionState() {
  const select = $("#expectedOutputInput");
  const inference = inferExpectedOutputFromSelectedTags();
  const selectedValue = String(select?.value || "");
  const conflictKind = inference.conflict
    ? "tags"
    : inference.value && selectedValue !== inference.value
      ? "selection"
      : "";
  return { ...inference, selectedValue, conflictKind };
}

function updateDerivedReviewStatusPreview(expectedOutput, conflictKind = "") {
  const conflict = Boolean(conflictKind);
  const statusInput = $("#reviewStatusInput");
  const status = conflict
    ? "pending"
    : !expectedOutput
      ? "pending"
      : expectedOutput === String(state.selectedCase?.gt_label || "")
        ? "reviewed"
        : "needs_gt_review";
  if (statusInput) statusInput.value = status;
  const preview = $("#derivedReviewStatus");
  const form = $("#annotationForm");
  if (form) form.dataset.expectedOutputConflict = conflict ? "1" : "0";
  const submit = form?.querySelector('button[type="submit"]');
  if (submit && !state.savingAnnotation) submit.disabled = conflict;
  if (!preview) return;
  preview.dataset.status = status;
  preview.dataset.conflict = conflictKind;
  preview.classList.toggle("is-conflict", conflict);
  preview.textContent = conflict
    ? conflictKind === "selection"
      ? uiText("状态：选择冲突", "Status: Selection conflict")
      : uiText("状态：Tags 冲突", "Status: Tag conflict")
    : status === "pending"
      ? uiText("状态：待补充", "Status: Pending")
      : status === "needs_gt_review"
        ? uiText("状态：GT 需复核", "Status: Needs GT review")
        : uiText("状态：与 GT 一致", "Status: Matches GT");
}

function syncExpectedOutputFromTags() {
  const select = $("#expectedOutputInput");
  if (!select) return;
  const inference = inferExpectedOutputFromSelectedTags();
  const selectionSource = select.dataset.selectionSource || "empty";
  if (selectionSource === "auto") {
    select.value = inference.value || "";
    if (!inference.value) select.dataset.selectionSource = "empty";
  } else if (selectionSource === "empty" && inference.value) {
    select.value = inference.value;
    select.dataset.selectionSource = "auto";
  }
  select.disabled = false;
  const picker = $("#expectedOutputPicker");
  const pickerOptions = EXPECTED_OUTPUT_OPTIONS.map((item) => {
    const label = i18nLocale() === "en" ? item.labelEn : item.labelZh;
    const isInferred = Boolean(item.value && item.value === inference.value);
    return {
      value: item.value,
      label,
      inferred: isInferred,
    };
  });
  populateUiSelect(picker, pickerOptions, select.value);
  if (inference.value) {
    const inferredMarker = uiText("自动推断", "Inferred");
    const inferredOption = picker?.querySelector(
      `[data-ui-select-value="${inference.value}"]`
    );
    if (inferredOption) {
      inferredOption.classList.add("is-inferred");
      inferredOption.insertAdjacentHTML(
        "beforeend",
        `<span class="ui-select-inference-marker">${escapeHtml(inferredMarker)}</span>`
      );
    }
    if (select.value === inference.value) {
      const summary = $("#expectedOutputPickerSummary");
      const selectedLabel =
        pickerOptions.find((item) => item.value === select.value)?.label || "";
      if (summary) {
        summary.innerHTML = `<span class="ui-select-summary-value">${escapeHtml(selectedLabel)}</span><span class="ui-select-inference-marker">${escapeHtml(inferredMarker)}</span>`;
      }
    }
  }
  [...select.options].forEach((option) => {
    option.dataset.inferred =
      option.value && option.value === inference.value ? "true" : "false";
  });
  const hint = $("#expectedOutputHint");
  const validation = expectedOutputSelectionState();
  picker?.classList.toggle("is-conflict", Boolean(validation.conflictKind));
  const trigger = picker?.querySelector(".ui-select-trigger");
  trigger?.setAttribute("aria-invalid", validation.conflictKind ? "true" : "false");
  if (hint) {
    hint.classList.toggle("is-conflict", Boolean(validation.conflictKind));
    hint.hidden = !validation.conflictKind;
    hint.removeAttribute("title");
    if (validation.conflictKind === "tags") {
      const message = uiText(
        "Tags 指向多个输出；请只保留一种输出方向。",
        "Tags imply multiple outputs; keep one output direction."
      );
      hint.textContent = message;
      hint.title = message;
    } else if (validation.conflictKind === "selection") {
      const message = uiText(
        `与 Tags 推断“${validation.value}”冲突；改回自动推断项或调整 Tags。`,
        `Conflicts with inferred “${validation.value}”; use it or adjust Tags.`
      );
      hint.textContent = message;
      hint.title = message;
    }
  }
  state.selectedAnnotationLabel = select.value;
  updateDerivedReviewStatusPreview(select.value, validation.conflictKind);
}

function renderDetail(caseData) {
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdMarkup = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  ensureDetailMediaState(caseData);
  const predCount = (caseData.predictions || []).length;
  const modelHistoryButton = `<button class="history-inline-button" id="modelHistoryLaunchButton" type="button" data-open-history="model" aria-keyshortcuts="M" title="打开模型预测历史（M）"><span class="ui-lang-zh">评测 Run 历史 · ${predCount} 条</span><span class="ui-lang-en">Run history · ${predCount}</span><kbd class="review-control-shortcut" aria-hidden="true">M</kbd></button>`;
  const predictionComparable = MODEL_LABELS.includes(primary?.model_label);
  const predictionMatches = modelLabelMatchesGt(primary?.model_label, caseData.gt_label);
  const compareText = !predictionComparable
    ? `<span class="ui-lang-zh">不可比较</span><span class="ui-lang-en">N/A</span>`
    : predictionMatches
      ? `<span class="ui-lang-zh">一致</span><span class="ui-lang-en">Match</span>`
      : `<span class="ui-lang-zh">不一致</span><span class="ui-lang-en">Mismatch</span>`;
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title-group">
          <div class="detail-title"><h2><span class="ui-lang-zh">问题详情</span><span class="ui-lang-en">Issue Details</span></h2>${issueIdMarkup}<span id="detailExternalLinks" class="detail-external-links">${detailExternalLinksMarkup(caseData)}</span></div>
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
          <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(caseData.gt_label, uiText("缺失", "Missing"))}
          <b aria-hidden="true">→</b>
          <span class="comparison-side-label comparison-side-model"><span class="ui-lang-zh">当前模型</span><span class="ui-lang-en">Model</span></span>${labelBadge(primary?.model_label, uiText("未输出", "None"))}
          <strong class="${predictionComparable && !predictionMatches ? "comparison-fail" : "comparison-neutral"}">${compareText}</strong>
        </div>
        <button class="button button-quiet detail-back-button" id="backToGalleryButton" type="button"><span class="ui-lang-zh">← 返回筛选结果</span><span class="ui-lang-en">← Back to gallery</span></button>
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
    ${heroMediaSection(caseData)}`;
  $("#detailPane").querySelector("[data-predict-current-case]")?.addEventListener("click", () => {
    openBatchDraft([caseData.issue_id], "single");
  });
  $("#detailPane").querySelector("[data-open-history='model']")?.addEventListener("click", () => {
    openHistoryDialog("model", caseData);
  });
  bindDetailExternalLinks(caseData);
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
  const serverPrevious = currentReviewAnnotation(caseData);
  const draft = reviewDraftForCase(caseData);
  const previous = applyReviewDraft(serverPrevious, draft);
  const runAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const hasPreviousReview = Boolean(runAnnotations.length || draft);
  const chosenEvidence = new Set(
    hasPreviousReview ? previous.missing_evidence || [] : []
  );
  const chosenTags = new Set(
    initialReviewTagsForCurrentRun(caseData, previous, draft)
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
  if (excluded) excluded.checked = Boolean(previous.is_excluded);
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
  state.reviewFormDirty = Boolean(draft);
  state.deferredDetailRefresh = false;
  clearPendingReviewImages();
  updateEvidenceSummary();
  updateTagSummary();
  bindMissingEvidenceCatalogControls(reviewPane);
  bindReviewTagCatalogControls(reviewPane);
  updateReviewHistory(caseData);
}

function renderReview(caseData) {
  const reviewRunId = currentReviewRunId(caseData);
  const runAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const allAnnotations = reviewAnnotationsForAllRuns(caseData);
  const sourceSuggestion = currentReviewSourceSuggestion(caseData);
  const serverPrevious = currentReviewAnnotation(caseData);
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
    initialReviewTagsForCurrentRun(caseData, previous, draft)
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
  $("#reviewPane").innerHTML = `
    <form class="review-form" id="annotationForm">
      <section class="review-section issue-tag-section">
        <div class="review-section-heading"><div><h2><span class="ui-lang-zh">Issue 标签</span><span class="ui-lang-en">Issue tags</span></h2>${sourceSuggestionMarkup}</div><span class="evidence-summary-count" id="tagSummaryCount">${escapeHtml(t("detail.selected_n", { n: chosenTags.size }))}</span></div>
        <div class="review-tag-groups-shell">${issueTagGroups}${customTagOptions ? `<div class="review-tag-legacy"><span class="ui-lang-zh">历史标签</span><span class="ui-lang-en">Legacy tags</span><div class="review-tag-options">${customTagOptions}</div></div>` : ""}</div>
        <label class="review-exclude-toggle"><input id="reviewExcludeInput" type="checkbox" ${previous.is_excluded ? "checked" : ""} /><span><strong class="ui-lang-zh">应该排除</strong><strong class="ui-lang-en">Exclude</strong><small class="ui-lang-zh">不是模型需要解决的场景 case</small><small class="ui-lang-en">Not a case the model is expected to solve</small></span></label>
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
            <button class="history-inline-button" type="button" data-review-comments>
              <span class="ui-lang-zh">评论</span><span class="ui-lang-en">Comments</span>
            </button>
            <button class="history-inline-button" type="button" data-open-history="review" id="reviewHistoryLaunchButton" aria-keyshortcuts="J" title="打开 Review 历史（J）">
              <span class="ui-lang-zh">Review 历史 · ${allAnnotations.length} 条</span>
              <span class="ui-lang-en">Review history · ${allAnnotations.length}</span>
              <kbd class="review-control-shortcut" aria-hidden="true">J</kbd>
            </button>
          </div>
        </div>
        <div class="review-expected-output-field">
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
        <label class="review-reason">
          <span><span class="ui-lang-zh">模型为什么判错？</span><span class="ui-lang-en">Why was the model wrong?</span></span>
          <textarea id="annotationNote" rows="2" aria-keyshortcuts="E Escape Enter Shift+Enter" placeholder="说明关键证据；输入 @ 可通知同事。">${escapeHtml(previous.note || "")}</textarea>
        </label>
        <div class="review-mention-composer" id="reviewMentionComposer" aria-live="polite"></div>
        <details class="evidence-dropdown review-dropdown review-tag-dropdown">
          <summary>
            <span class="tag-group-label"><span class="ui-lang-zh">缺失信息（多选）</span><span class="ui-lang-en">Missing evidence</span></span>
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
      <button class="button button-primary full-width review-save-button" id="reviewSaveButton" type="submit"><span class="ui-lang-zh">保存新的 review 版本</span><span class="ui-lang-en">Save new review version</span></button>
    </form>`;
  bindSelectedReviewTagControls($("#reviewPane"));
  $("#reviewPane").querySelector("[data-review-comments]")?.addEventListener("click", () => {
    openAnalysisDiscussion(state.selectedId, {
      runId: state.selectedRunId || "",
      source: "review",
    }).catch((error) => showToast(error.message, true));
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
  syncReviewTagShortcutHints($("#reviewPane"));
  bindReviewKeyboardShortcuts();
  bindReviewComposerShortcuts();
  bindReviewHistoryShortcuts();
  $("#reviewPane").querySelectorAll(".review-dropdown").forEach((dropdown) => {
    if (dropdown.dataset.reviewDropdownToggleBound === "1") return;
    dropdown.dataset.reviewDropdownToggleBound = "1";
    const summary = dropdown.querySelector(":scope > summary");
    // Creator controls remain in the compact familiar order: ＋ → count →
    // chevron.  Prevent only the surrounding details summary from toggling;
    // the native button keeps its own complete click target and handler.
    summary?.addEventListener(
      "click",
      (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest(".tag-catalog-add-button")) event.preventDefault();
      },
      true
    );
    // Park off-screen before <details> flips open so the first paint never uses absolute top:100%.
    summary?.addEventListener(
      "pointerdown",
      (event) => {
        const target = event.target instanceof Element ? event.target : null;
        if (target?.closest(".tag-catalog-add-button")) return;
        if (dropdown.open) return;
        prepareReviewDropdownPanelForMeasure(reviewDropdownPanel(dropdown));
      },
      true
    );
    dropdown.addEventListener("toggle", () => {
      const panel = reviewDropdownPanel(dropdown);
      if (!dropdown.open) {
        resetReviewDropdownPanel(panel);
        return;
      }
      $("#reviewPane").querySelectorAll(".review-dropdown").forEach((other) => {
        if (other === dropdown) return;
        other.open = false;
        resetReviewDropdownPanel(reviewDropdownPanel(other));
      });
      // Same tick as open: measure + place + reveal only at final coords (no rAF down-flash).
      prepareReviewDropdownPanelForMeasure(panel);
      positionReviewDropdownPanel(dropdown);
    });
  });
  $("#reviewPane").querySelector("[data-open-history='review']")?.addEventListener("click", () => {
    openHistoryDialog("review", caseData);
  });
  const pasteZone = $("#screenshotPasteZone");
  const screenshotInput = $("#reviewScreenshotInput");
  const screenshotBrowse = $("#reviewScreenshotBrowse");
  if (pasteZone && screenshotInput) {
    const openScreenshotPicker = () => {
      screenshotInput.click();
    };
    // Only the explicit browse button opens the OS picker — whole-zone click
    // used to steal focus and break Ctrl/⌘+V paste.
    screenshotBrowse?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openScreenshotPicker();
    });
    pasteZone.addEventListener("click", () => {
      pasteZone.focus({ preventScroll: true });
    });
    pasteZone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openScreenshotPicker();
      }
    });
    const imageFilesFromDataTransfer = (dataTransfer) => {
      if (!dataTransfer) return [];
      // Prefer FileList once; do not also walk items — that doubles the same paste.
      let candidates = [...(dataTransfer.files || [])].filter((file) =>
        String(file.type || "").startsWith("image/")
      );
      if (!candidates.length) {
        candidates = [...(dataTransfer.items || [])]
          .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
          .map((item) => item.getAsFile())
          .filter(Boolean);
      }
      // Clipboard may expose the same blob under multiple MIME entries.
      const seen = new Set();
      return candidates.filter((file) => {
        const key = `${file.type}|${file.size}|${file.lastModified}|${file.name || ""}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    };
    const acceptImagePasteOrDrop = (event, dataTransfer) => {
      const files = imageFilesFromDataTransfer(dataTransfer);
      if (!files.length) return false;
      event.preventDefault();
      event.stopPropagation();
      addPendingReviewImages(files);
      return true;
    };
    // Single form-level paste handler (pasteZone is inside the form — a second
    // zone listener would bubble and add the same image twice).
    $("#annotationForm")?.addEventListener("paste", (event) => {
      const target = event.target;
      if (
        target instanceof HTMLTextAreaElement ||
        (target instanceof HTMLInputElement &&
          !["checkbox", "radio", "file", "button", "submit"].includes(target.type))
      ) {
        // Prefer not to intercept plain text paste into text fields.
        const hasImage = [...(event.clipboardData?.items || [])].some(
          (item) => item.kind === "file" && item.type.startsWith("image/")
        );
        if (!hasImage) return;
      }
      acceptImagePasteOrDrop(event, event.clipboardData);
    });
    let dragDepth = 0;
    const setDragOver = (active) => {
      pasteZone.classList.toggle("is-dragover", active);
    };
    pasteZone.addEventListener("dragenter", (event) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
      dragDepth += 1;
      setDragOver(true);
    });
    pasteZone.addEventListener("dragover", (event) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      setDragOver(true);
    });
    pasteZone.addEventListener("dragleave", (event) => {
      if (![...(event.dataTransfer?.types || [])].includes("Files")) return;
      event.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) setDragOver(false);
    });
    pasteZone.addEventListener("drop", (event) => {
      dragDepth = 0;
      setDragOver(false);
      if (!acceptImagePasteOrDrop(event, event.dataTransfer)) {
        event.preventDefault();
        showToast("请拖入 PNG / JPEG / WebP 图片。", true);
      }
    });
    screenshotInput.addEventListener("change", () => {
      addPendingReviewImages([...screenshotInput.files]);
      screenshotInput.value = "";
    });
  }
  renderPendingReviewImages();
  bindReviewMentionComposer($("#annotationNote"));
  const annotationForm = $("#annotationForm");
  const markDraftDirty = () => {
    state.reviewFormDirty = true;
    persistReviewDraft(caseData);
  };
  annotationForm.addEventListener("input", markDraftDirty);
  annotationForm.addEventListener("change", markDraftDirty);
  bindReviewDraftLifecycle();
  state.reviewFormDirty = Boolean(draft);
  annotationForm.addEventListener("submit", saveAnnotation);
  bindAnnotationHistory($("#reviewPane"), caseData);
}

function releasePreviewUrlLater(previewUrl) {
  window.setTimeout(() => URL.revokeObjectURL(previewUrl), 5000);
}

function clearPendingReviewImages() {
  const previewUrls = state.pendingReviewImages.map((item) => item.previewUrl);
  state.pendingReviewImages = [];
  renderPendingReviewImages();
  previewUrls.forEach(releasePreviewUrlLater);
}

function addPendingReviewImages(files) {
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = "";
  const previousCount = state.pendingReviewImages.length;
  files.forEach((file) => {
    if (state.pendingReviewImages.length >= maxCount) {
      rejected = `最多只能添加 ${maxCount} 张截图。`;
      return;
    }
    if (!allowed.has(file.type)) {
      rejected = "仅支持 PNG、JPEG 或 WebP 图片。";
      return;
    }
    if (file.size > maxBytes) {
      rejected = "单张截图不能超过 8 MB。";
      return;
    }
    const currentBytes = state.pendingReviewImages.reduce(
      (sum, item) => sum + item.file.size,
      0
    );
    if (currentBytes + file.size > maxTotalBytes) {
      rejected = "本次截图总大小不能超过 24 MB。";
      return;
    }
    state.pendingReviewImages.push({
      id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
    });
  });
  if (state.pendingReviewImages.length !== previousCount) {
    state.reviewFormDirty = true;
  }
  renderPendingReviewImages();
  if (rejected) showToast(rejected, true);
}

function renderPendingReviewImages() {
  const target = $("#pendingScreenshotList");
  if (!target) return;
  if (!state.pendingReviewImages.length) {
    target.innerHTML = "";
    return;
  }
  target.innerHTML = state.pendingReviewImages
    .map(
      (item) => `<div class="pending-screenshot">
        <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || "待上传截图")}" />
        <button type="button" data-remove-screenshot="${escapeHtml(item.id)}" aria-label="移除截图">×</button>
      </div>`
    )
    .join("");
  target.querySelectorAll("[data-remove-screenshot]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = state.pendingReviewImages.findIndex(
        (item) => item.id === button.dataset.removeScreenshot
      );
      if (index < 0) return;
      const previewUrl = state.pendingReviewImages[index].previewUrl;
      state.pendingReviewImages.splice(index, 1);
      state.reviewFormDirty = true;
      renderPendingReviewImages();
      releasePreviewUrlLater(previewUrl);
    });
  });
}

const CASE_DETAIL_PREFETCH_TTL_MS = 15000;
const CASE_DETAIL_PREFETCH_LIMIT = 4;
const TRAIL_DETAIL_DELAY_MS = 350;

function caseCorePath(issueId) {
  return `/api/cases/${encodeURIComponent(issueId)}?include_media=false`;
}

function prefetchCaseCore(issueId) {
  const id = String(issueId || "");
  if (!id || id === state.selectedId || state.caseDetailPrefetch.has(id)) return;
  const entry = { createdAt: Date.now(), promise: null };
  entry.promise = api(caseCorePath(id), { cache: "no-store" }).catch(() => {
    if (state.caseDetailPrefetch.get(id) === entry) state.caseDetailPrefetch.delete(id);
    return null;
  });
  state.caseDetailPrefetch.set(id, entry);
  while (state.caseDetailPrefetch.size > CASE_DETAIL_PREFETCH_LIMIT) {
    state.caseDetailPrefetch.delete(state.caseDetailPrefetch.keys().next().value);
  }
}

async function loadCaseCore(issueId) {
  const entry = state.caseDetailPrefetch.get(issueId);
  state.caseDetailPrefetch.delete(issueId);
  if (entry && Date.now() - entry.createdAt <= CASE_DETAIL_PREFETCH_TTL_MS) {
    const prefetched = await entry.promise;
    if (prefetched) return prefetched;
  }
  return api(caseCorePath(issueId), { cache: "no-store" });
}

function prefetchAdjacentCaseCores(issueId) {
  const index = state.cases.findIndex((item) => item.issue_id === issueId);
  if (index < 0) return;
  [state.cases[index - 1], state.cases[index + 1]].forEach((item) => {
    if (item?.issue_id) prefetchCaseCore(item.issue_id);
  });
}

function cancelCaseHydration() {
  state.caseMediaController?.abort();
  state.caseMediaController = null;
  state.trailMetadataController?.abort();
  state.trailMetadataController = null;
  if (state.trailMetadataTimer !== null) {
    window.clearTimeout(state.trailMetadataTimer);
    state.trailMetadataTimer = null;
  }
}

function scheduleTrailDetailMetadata(issueId, requestSeq) {
  state.trailMetadataTimer = window.setTimeout(() => {
    state.trailMetadataTimer = null;
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    const controller = new AbortController();
    state.trailMetadataController = controller;
    void startTrailDetailMetadata(issueId, requestSeq, controller.signal).then((result) => {
      if (state.trailMetadataController === controller) state.trailMetadataController = null;
      applyTrailDetailMetadata(result, issueId, requestSeq);
    });
  }, TRAIL_DETAIL_DELAY_MS);
}

async function selectCase(
  issueId,
  { updateRoute = true, historyMode = "push" } = {}
) {
  if (!issueId) return;
  const gallery = $("#reviewGalleryView");
  if (gallery && !gallery.classList.contains("hidden")) {
    state.galleryScrollY = window.scrollY;
  }
  if (state.selectedId && state.selectedId !== issueId) clearPendingReviewImages();
  cancelCaseHydration();
  const hadDetail = Boolean(state.selectedCase);
  state.selectedId = issueId;
  state.selectedCase = null;
  const requestSeq = ++state.caseRequestSeq;
  renderCaseNavigation();
  let loadingTimer = null;
  if (!hadDetail) {
    loadingTimer = window.setTimeout(() => {
      if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
      $("#detailPane").innerHTML = `
          <div class="empty-state detail-loading-state">
          <div class="empty-glyph" aria-hidden="true">…</div>
          <h2>正在加载 ${escapeHtml(issueId)}</h2>
          <p>正在读取 Issue 与模型输出。</p>
        </div>`;
      $("#reviewPane").innerHTML = `
        <div class="review-placeholder"><h2>正在加载标注</h2><p>Issue 数据返回后即可继续 Review。</p></div>`;
    }, 140);
  }
  if (updateRoute && state.activePage === "review") {
    const nextUrl = pageUrl("review", { issue: issueId });
    if (`${window.location.pathname}${window.location.search}` !== nextUrl) {
      showPage("review", { historyMode, issue: issueId });
    } else {
      setReviewView(issueId);
    }
  } else {
    setReviewView(issueId);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  try {
    // Review text and form state do not depend on filesystem media.  Ask for
    // the lightweight core record first; BEV/video/camera hydrate below.
    const data = await loadCaseCore(issueId);
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    const caseSummary = state.cases.find((item) => item.issue_id === issueId);
    data.preview_thumbnail_url = safeSameOriginAssetUrl(caseSummary?.thumbnail?.url);
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    void loadDeferredCaseMedia(issueId, requestSeq);
    scheduleTrailDetailMetadata(issueId, requestSeq);
    prefetchAdjacentCaseCores(issueId);
  } catch (error) {
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    $("#detailPane").innerHTML = `
      <div class="empty-state">
        <div class="empty-glyph" aria-hidden="true">!</div>
        <h2>Issue 加载失败</h2>
        <p>${escapeHtml(error.message)}</p>
      </div>`;
    showToast(error.message, true);
  }
}

async function loadDeferredCaseMedia(issueId, requestSeq) {
  const controller = new AbortController();
  state.caseMediaController = controller;
  try {
    const media = await api(`/api/cases/${encodeURIComponent(issueId)}/media`, {
      cache: "no-store",
      signal: controller.signal,
    });
    if (
      requestSeq !== state.caseRequestSeq ||
      state.selectedId !== issueId ||
      !state.selectedCase
    ) return;
    state.selectedCase.assets = media?.assets || state.selectedCase.assets;
    state.selectedCase.camera = media?.camera || state.selectedCase.camera;
    state.selectedCase.media_status = media?.media_status || "ready";
    // Only replace the media/detail pane.  The Review form remains mounted so
    // a reviewer can start typing before a cold media index completes.
    renderDetail(state.selectedCase);
  } catch (_error) {
    if (
      requestSeq !== state.caseRequestSeq ||
      state.selectedId !== issueId ||
      !state.selectedCase
    ) return;
    state.selectedCase.media_status = "unavailable";
    renderDetail(state.selectedCase);
  } finally {
    if (state.caseMediaController === controller) state.caseMediaController = null;
  }
}

async function navigateAdjacentCase(delta) {
  if (!state.selectedId || ![-1, 1].includes(delta)) return;
  let index = state.cases.findIndex((item) => item.issue_id === state.selectedId);
  if (index < 0) return;
  let targetIndex = index + delta;
  if (targetIndex < 0 && state.casePage > 1) {
    await loadCases({ keepSelection: true, page: state.casePage - 1 });
    targetIndex = state.cases.length - 1;
  } else if (
    targetIndex >= state.cases.length &&
    state.casePage * state.casePageSize < state.caseTotal
  ) {
    await loadCases({ keepSelection: true, page: state.casePage + 1 });
    targetIndex = 0;
  }
  const target = state.cases[targetIndex];
  if (target) await selectCase(target.issue_id, { historyMode: "replace" });
}

function bindReviewComposerShortcuts() {
  if (document.documentElement.dataset.reviewComposerShortcutsBound === "1") return;
  document.documentElement.dataset.reviewComposerShortcutsBound = "1";
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      event.isComposing ||
      event.repeat ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      state.activePage !== "review" ||
      !state.selectedCase ||
      document.querySelector("dialog[open]")
    ) {
      return;
    }
    const note = $("#annotationNote");
    const form = $("#annotationForm");
    if (!note || !form) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target === note) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        note.blur();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey && !state.savingAnnotation) {
        event.preventDefault();
        event.stopPropagation();
        form.requestSubmit($("#reviewSaveButton") || undefined);
      }
      return;
    }
    if (String(event.key || "").toLowerCase() !== "e" || event.shiftKey) return;
    if (target?.closest("input, textarea, select, button, a, [contenteditable='true'], [role='textbox']")) return;
    event.preventDefault();
    event.stopPropagation();
    note.focus({ preventScroll: false });
    note.setSelectionRange(note.value.length, note.value.length);
  });
}

function bindReviewHistoryShortcuts() {
  if (document.documentElement.dataset.reviewHistoryShortcutsBound === "1") return;
  document.documentElement.dataset.reviewHistoryShortcutsBound = "1";
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      event.isComposing ||
      event.repeat ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.shiftKey ||
      state.activePage !== "review" ||
      !state.selectedCase ||
      document.querySelector("dialog[open]")
    ) return;
    const target = event.target instanceof Element ? event.target : null;
    if (reviewShortcutHasEditableTarget(target)) return;
    const key = String(event.key || "").toLowerCase();
    const kind = key === "j" ? "review" : key === "m" ? "model" : "";
    if (!kind) return;
    event.preventDefault();
    event.stopPropagation();
    closeAllReviewDropdowns();
    openHistoryDialog(kind, state.selectedCase);
  });
}

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId || state.savingAnnotation) return;
  const expectedOutputState = expectedOutputSelectionState();
  if (expectedOutputState.conflictKind === "tags") {
    showToast("Tags 指向多个期望输出，请先消除冲突。", true);
    return;
  }
  if (expectedOutputState.conflictKind === "selection") {
    showToast(
      `当前期望输出与 Tags 自动推断的“${expectedOutputState.value}”冲突，请改回自动推断项或调整 Tags。`,
      true
    );
    return;
  }
  state.savingAnnotation = true;
  const submitButton = event.submitter || $("#annotationForm button[type='submit']");
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
  }
  const payload = {
    model_run_id: state.reviewEditRunId || currentReviewRunId(state.selectedCase),
    expected_previous_annotation_id: state.reviewEditBaseAnnotationId || null,
    expected_output: $("#expectedOutputInput")?.value || "",
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...document.querySelectorAll('input[name="reviewTags"]:checked')].map(
      (input) => input.value
    ),
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote").value,
    author: $("#annotationAuthor").value,
  };
  try {
    let result;
    if (state.pendingReviewImages.length) {
      const form = new FormData();
      form.append("payload", JSON.stringify(payload));
      state.pendingReviewImages.forEach((item, index) => {
        form.append(
          "attachments",
          item.file,
          item.file.name || `clipboard-${index + 1}.png`
        );
      });
      result = await api(
        `/api/cases/${encodeURIComponent(state.selectedId)}/annotations-with-attachments`,
        {
          method: "POST",
          body: form,
          headers: { "X-RA-Triage-Request": "review-v1" },
        }
      );
    } else {
      result = await api(`/api/cases/${encodeURIComponent(state.selectedId)}/annotations`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    acknowledgeLocalChange(result);
    if (result?.annotation) {
      state.reviewEditRunId = result.annotation.model_run_id || state.reviewEditRunId;
      state.reviewEditBaseAnnotationId = result.annotation.id || null;
    }
    clearReviewDraft(state.selectedId, payload.model_run_id);
    const screenshotCount = state.pendingReviewImages.length;
    state.reviewFormDirty = false;
    state.deferredDetailRefresh = false;
    clearPendingReviewImages();
    if (result?.annotation && state.selectedCase?.issue_id === state.selectedId) {
      state.selectedCase.annotations = [
        result.annotation,
        ...(state.selectedCase.annotations || []).filter(
          (item) => String(item.id) !== String(result.annotation.id)
        ),
      ];
      updateReviewHistory(state.selectedCase);
    }
    const queuedCount = result?.annotation?.notification?.queued?.length || 0;
    showToast(
      `已保存新的 review 版本${screenshotCount ? `和 ${screenshotCount} 张截图` : ""}${queuedCount ? `；DChat 通知已排队 ${queuedCount} 人` : ""}。`
    );
    $("#annotationNote")?.blur();
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.savingAnnotation = false;
    if (submitButton?.isConnected) {
      submitButton.disabled = Boolean(expectedOutputSelectionState().conflictKind);
      submitButton.removeAttribute("aria-busy");
    }
  }
}
