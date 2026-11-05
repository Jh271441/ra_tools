/* review-expected-output.js
 * Expected-output inference, validation and model-review progress.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
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

const MODEL_REVIEW_STATUS_OPTIONS = [
  { value: "in_progress", labelZh: "待复核", labelEn: "Needs review" },
  { value: "completed", labelZh: "已完成", labelEn: "Completed" },
];

// Pending is the persisted progress before a submission, not a save choice.
function modelReviewSubmissionStatus(annotation) {
  const value = String(annotation?.model_review_status || "");
  return value === "in_progress" || value === "blocked_by_label" ? "in_progress" : "completed";
}

function modelReviewProgressText(annotation) {
  if (!annotation?.id) return uiText("待开始", "Not started");
  return annotation.model_review_status === "completed" || (!annotation.model_review_status && annotation.note)
    ? uiText("已完成", "Completed") : uiText("待复核", "Needs review");
}

function modelReviewProgressMarkup(annotation) {
  const status = !annotation?.id ? "pending"
    : annotation.model_review_status === "completed" || (!annotation.model_review_status && annotation.note)
      ? "completed" : "in_progress";
  const labels = { pending: ["待开始", "Not started"], in_progress: ["待复核", "Needs review"], completed: ["已完成", "Completed"] };
  return `<span class="ui-lang-zh">当前：${labels[status][0]}</span><span class="ui-lang-en">Current: ${labels[status][1]}</span>`;
}

function syncModelReviewProgress(annotation) {
  const progress = $("#modelReviewCurrentProgress");
  if (progress) progress.innerHTML = modelReviewProgressMarkup(annotation);
}

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
  renderCombinedReviewContextStatus();
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
