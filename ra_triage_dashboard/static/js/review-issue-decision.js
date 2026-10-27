/* Review uses the same Issue decision dialog, form and append-only endpoint. */
let reviewDecisionRequest = 0;
function isReviewDecisionEditor() {
  return state.activePage === "review" && Boolean(caseLabelDecisionUi.editor?.reviewHost);
}
async function openReviewIssueDecision(item, opener) {
  if (!hasDashboardWriteRole() || caseLabelDecisionUi.saving) return;
  const sequence = ++reviewDecisionRequest, context = capturePageContext();
  const baselines = selectedBaselineQueryValue(), actor = state.session?.username;
  opener?.setAttribute("aria-busy", "true");
  try {
    const data = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(item.issue_id)}`));
    if (sequence !== reviewDecisionRequest || !isPageContextCurrent(context)
        || baselines !== selectedBaselineQueryValue() || actor !== state.session?.username) return;
    if (state.selectedId !== item.issue_id) {
      // Gallery badges keep their read-only behavior; edit only the visible Issue.
      openSharedLabelStateDialog(item); return;
    }
    openCaseLabelDecision(data);
    caseLabelDecisionUi.context.opener = opener;
  } catch (error) { if (isPageContextCurrent(context)) showToast(error.message, true); }
  finally { opener?.removeAttribute("aria-busy"); }
}
function mountReviewDecisionEditor(data) {
  const pane = $("#reviewPane"), editor = $("#caseLabelingEditor");
  const host = {pane,editor,parent:editor.parentNode,next:editor.nextSibling,
    editorNodes:[...editor.childNodes], reviewNodes:[...pane.childNodes],
    labeling:state.caseLabeling, dirty:state.reviewFormDirty, scrollTop:pane.scrollTop,
    focus:caseLabelDecisionUi.context?.opener, contextWasLoading:state.combinedReviewLoad?.status === "loading"};
  // Invalidate late combined-form hydration before detaching its inputs.
  state.combinedReviewContextRequestSeq = (state.combinedReviewContextRequestSeq || 0) + 1;
  state.caseLabeling = {...state.caseLabeling, issueId:data.issue_id, caseData:data, taskId:"", pendingImages:[], dirty:false};
  state.reviewFormDirty = true;
  editor.replaceChildren(); pane.replaceChildren(editor);
  pane.classList.add("review-decision-active");
  return host;
}
function restoreReviewDecisionEditor(host) {
  host.parent.insertBefore(host.editor,host.next);
  host.editor.replaceChildren(...host.editorNodes);
  host.pane.replaceChildren(...host.reviewNodes);
  host.pane.classList.remove("review-decision-active");
  state.caseLabeling = host.labeling;
  state.reviewFormDirty = host.dirty;
  // Detached personal inputs miss locale updates while the decision form is mounted.
  // Relabel the original nodes, never rehydrate values from saved server records.
  refreshReviewFormLanguage();
  host.pane.scrollTop = host.scrollTop;
  if (state.selectedCase) renderReviewSummary(state.selectedCase);
  $("#reviewSharedLabelState [data-open-shared-label-state]")?.focus({preventScroll:true});
  if (host.contextWasLoading) void loadCombinedReviewContext(state.selectedCase, {preserveForm:true}).catch(error => showToast(error.message, true));
}
async function refreshReviewDecisionResult(fresh) {
  const current = state.selectedCase;
  if (!current || current.issue_id !== fresh.issue_id) return;
  for (const key of ["label_state","label_source_contexts","label_cases","decision_history","exclusion_summary"]) current[key] = fresh[key];
  for (const item of state.cases || []) if (item.issue_id === fresh.issue_id) item.label_state = fresh.label_state;
  state.caseDetailPrefetch?.forEach(entry => entry.controller?.abort());
  state.caseDetailPrefetch?.clear();
  if (caseLabelDecisionUi.context?.caseData.issue_id === fresh.issue_id) caseLabelDecisionUi.context.caseData = fresh;
  renderReviewSummary(current);
  // Refresh the concurrency token without overwriting the personal Review draft.
  if (state.combinedReviewContext || $("#combinedReviewContextStatus")) {
    await loadCombinedReviewContext(current, {preserveForm:true});
  }
}
