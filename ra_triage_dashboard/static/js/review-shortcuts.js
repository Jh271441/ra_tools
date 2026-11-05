/* review-shortcuts.js
 * Review keyboard actions, discussion entry points and Issue ID copy.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

function bindReviewComposerShortcuts() {
  if (document.documentElement.dataset.reviewComposerShortcutsBound === "1") return;
  document.documentElement.dataset.reviewComposerShortcutsBound = "1";
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      isImeComposing(event) ||
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
    const rationale = $("#combinedCaseRationale");
    const form = $("#annotationForm");
    if (!note || !form) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target === note || target === rationale) {
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        target.blur();
        return;
      }
      if (event.key === "Enter" && !event.shiftKey && !state.savingAnnotation && !reviewTouchTextEntry(target)) {
        event.preventDefault();
        event.stopPropagation();
        if (form.checkValidity()) form.requestSubmit($("#reviewSaveButton") || undefined);
      }
      return;
    }
    if (String(event.key || "").toLowerCase() !== "e") return;
    if (target?.closest("input, textarea, select, button, a, [contenteditable='true'], [role='textbox']")) return;
    const caseAvailable = rationale && !rationale.closest("[hidden]");
    const composer = !event.shiftKey && caseAvailable ? rationale : note;
    if (!composer || composer.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    closeAllReviewDropdowns();
    composer.focus({ preventScroll: false });
    composer.setSelectionRange(composer.value.length, composer.value.length);
  });
}

function openCurrentIssueDiscussion(caseData = state.selectedCase) {
  const issueId = String(caseData?.issue_id || "");
  if (!issueId) return;
  const requestedTaskId = String(state.reviewWorkSplitId || "");
  const assignment = caseData?.review_assignment;
  // Carry only the explicit, server-validated browsing task. Posting still
  // defaults to the shared Issue channel; task selection is independent.
  const taskId = requestedTaskId && String(assignment?.split_id || "") === requestedTaskId
    && String(assignment?.model_run_id || "") === currentReviewRunId(caseData) ? requestedTaskId : "";
  openAnalysisDiscussion(issueId, { runId: "", source: "labeling", kind: "labeling", taskId, discussionChannel: "case" })
    .catch((error) => showToast(error.message, true));
}

function openCurrentReviewDiscussion(caseData = state.selectedCase) {
  const issueId = String(caseData?.issue_id || state.selectedId || "").trim();
  if (!issueId) return;
  openAnalysisDiscussion(issueId, {
    runId: state.selectedRunId || "",
    source: "review",
  }).catch((error) => showToast(error.message, true));
}

function bindReviewDetailActionShortcuts() {
  if (document.documentElement.dataset.reviewDetailActionShortcutsBound === "1") return;
  document.documentElement.dataset.reviewDetailActionShortcutsBound = "1";
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      isImeComposing(event) ||
      event.repeat ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      state.activePage !== "review" ||
      !state.selectedCase
    ) return;
    const target = event.target instanceof Element ? event.target : null;
    if (reviewShortcutHasEditableTarget(target)) return;
    const key = String(event.key || "").toLowerCase();
    if (isReviewDecisionEditor() && !event.shiftKey && ["j", "l", "d", "e"].includes(key)) {
      const dialog = $("#caseLabelDecisionDialog");
      if (["j", "l"].includes(key) && dialog?.open) dialog.close();
      else if (document.querySelector("dialog[open]")) return;
      else if (["j", "l"].includes(key)) openCaseLabelDecision(caseLabelDecisionUi.editor.data, {compareEditor:caseLabelDecisionUi.editor});
      else if (key === "d") $("#caseLabelingOpenDiscussion")?.click();
      else { closeAllReviewDropdowns(); $("#caseLabelingRationale")?.focus(); }
      event.preventDefault(); event.stopPropagation(); return;
    }
    if (event.shiftKey && key !== "d") return;
    const caseDiscussion = !event.shiftKey && Boolean($("#issueLabelCommentsButton")) && !$("#issueLabelCommentsButton").closest("[hidden]");
    const discussionKind = caseDiscussion ? "labeling" : "review";
    const historyKind = key === "j" ? "review" : key === "p" ? "model" : "";
    const historyDialog = $("#historyDialog");
    if (historyKind && historyDialog?.open) {
      event.preventDefault();
      event.stopPropagation();
      toggleHistoryDialog(historyKind, state.selectedCase);
      return;
    }
    const discussionDialog = $("#analysisDiscussionDialog");
    if (
      key === "d" &&
      discussionDialog?.open &&
      state.analysisDiscussion?.kind === discussionKind
    ) {
      event.preventDefault();
      event.stopPropagation();
      closeDialog("analysisDiscussionDialog");
      return;
    }
    const raEventDialog = $("#raEventDialog");
    if (key === "t" && raEventDialog?.open) {
      event.preventDefault();
      event.stopPropagation();
      closeDialog("raEventDialog");
      return;
    }
    const labelSummaryDialog = $("#caseLabelDecisionDialog")?.open ? $("#caseLabelDecisionDialog") : $("#sharedLabelStateDialog");
    if (key === "l" && labelSummaryDialog?.open) {
      event.preventDefault();
      event.stopPropagation();
      labelSummaryDialog.close();
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (key === "l") {
      const summaryButton = $("#reviewSharedLabelState")?.querySelector("[data-open-shared-label-state]");
      if (!summaryButton || summaryButton.disabled || summaryButton.closest("[hidden]")) return;
      event.preventDefault();
      event.stopPropagation();
      closeAllReviewDropdowns();
      summaryButton.click();
      return;
    }
    if (key === "t") {
      const raEventButton = $("#detailExternalLinks")?.querySelector(
        "[data-open-ra-event]"
      );
      if (!raEventButton) return;
      event.preventDefault();
      event.stopPropagation();
      closeAllReviewDropdowns();
      raEventButton.click();
      return;
    }
    if (key === "d") {
      event.preventDefault();
      event.stopPropagation();
      closeAllReviewDropdowns();
      if (caseDiscussion) openCurrentIssueDiscussion(state.selectedCase);
      else openCurrentReviewDiscussion(state.selectedCase);
      return;
    }
    const kind = key === "j" ? "review" : key === "p" ? "model" : "";
    if (!kind) return;
    event.preventDefault();
    event.stopPropagation();
    closeAllReviewDropdowns();
    toggleHistoryDialog(kind, state.selectedCase);
  });
}

async function copyReviewIssueId(issueId, button = null) {
  const value = String(issueId || "").trim();
  if (!value) return;
  try {
    await copyTextToClipboard(value);
    button?.classList.add("is-copied");
    window.setTimeout(() => button?.classList.remove("is-copied"), 900);
    showToast(`已复制 Issue ID：${value}`);
  } catch (_) {
    showToast("复制失败，请检查浏览器剪贴板权限。", true);
  }
}
