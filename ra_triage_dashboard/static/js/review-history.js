/* ra_triage_dashboard/static/js/review-history.js
 * Review annotation history pane
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
/* One compact record layout shared by Review history and Issue decisions. */
function historyRecordMarkup({author, authorTitle = "", createdAt, badges = "", meta = "", body = "", actions = ""}) {
  return `<article class="history-row history-record">
    <header class="history-record-heading"><div class="history-record-identity"><strong class="history-reviewer" title="${escapeHtml(authorTitle || author)}">${escapeHtml(author)}</strong>${badges ? `<div class="history-record-badges tags">${badges}</div>` : ""}</div><div class="history-record-tools"><time class="history-time" datetime="${escapeHtml(createdAt || "")}">${escapeHtml(formatTime(createdAt))}</time>${actions}</div></header>
    ${meta ? `<div class="history-record-meta">${meta}</div>` : ""}${body}
  </article>`;
}
function annotationHistory(annotations, options = {}) {
  const deletable = options.deletable !== false;
  const runMeta = typeof options.runMeta === "function" ? options.runMeta : null;
  if (!annotations?.length) {
    const emptyText = options.emptyText || uiText("尚无人工 Review；保存后会保留旧版本。", "No reviews yet. Saving preserves earlier revisions.");
    return `<div class="annotation-history"><p class="muted history-empty">${escapeHtml(emptyText)}</p></div>`;
  }
  return `<div class="annotation-history">${annotations.map(annotation => {
    const expectedOutput = annotationExpectedOutput(annotation);
    const modelReview = annotation.review_domain === "model_review";
    const currentUser = String(state.session?.username || "").trim().toLowerCase();
    const canDelete = deletable && !annotation.legacy_read_only && (!modelReview || hasDashboardWriteRole()) && (!(annotation.work_split_id || modelReview) || state.session?.is_admin || (
      currentUser && String(annotation.author || "").trim().toLowerCase() === currentUser
    ));
    const author = annotation.author || uiText("未记录作者", "Unknown author");
    const verified = annotation.author_verified ? uiText("SSO 已验证", "SSO verified") : uiText("未验证身份", "Unverified identity");
    const run = runMeta ? runMeta(annotation) : {title:uiText("Review 绑定的 Model Run", "Model run for this review"),text:`Run · ${reviewRunLabel(annotation.model_run_id)}`};
    const badges = `${modelReview ? `<span class="tag">${uiText("模型复核", "Model review")} · ${escapeHtml(reviewStatusLabel(annotation.model_review_status))}</span>` : `${labelBadge(expectedOutput, uiText("待补充分类", "Classification missing"), typeof expectedOutputDisplayText === "function" ? expectedOutputDisplayText(expectedOutput) : expectedOutput)}<span class="tag">${escapeHtml(reviewStatusLabel(annotation.review_status))}</span>`}
      ${annotation.legacy_read_only ? `<span class="tag legacy-history-tag">${uiText("历史 Review（只读）", "Earlier review (read-only)")}</span>` : ""}
      ${annotation.is_excluded ? `<span class="tag exclusion-tag">${uiText("已排除", "Excluded")}</span>` : ""}`;
    const actionText = modelReview ? uiText("撤销这条 Run 复核（保留 Case 标签）", "Revoke this run review (keep Case labels)") : uiText("删除这条 Review 版本", "Delete this review revision");
    const actions = canDelete ? `<button class="history-delete-button" type="button" data-delete-annotation="${escapeHtml(annotation.id)}" title="${escapeHtml(actionText)}" aria-label="${escapeHtml(actionText)}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 3h4l1 2H7zM6 6l.7 11h6.6L14 6M8.5 9v5m3-5v5"/></svg></button>` : "";
    const body = `${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map(key => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
      ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map(tag => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>` : ""}
      ${annotation.mentions?.length ? `<div class="tags">${annotation.mentions.map(name => `<span class="review-mention-chip is-selected">@${escapeHtml(name)}</span>`).join("")}</div>` : ""}
      ${annotation.attachments?.length ? `<div class="history-attachments">${annotation.attachments.map((attachment,index) => `<a href="${escapeHtml(attachment.url)}" target="_blank" rel="noreferrer" title="${escapeHtml(uiText(`打开补充截图 ${index+1}`, `Open evidence image ${index+1}`))}"><img src="${escapeHtml(attachment.url)}" alt="${escapeHtml(uiText(`补充截图 ${index+1}`, `Evidence image ${index+1}`))}" loading="lazy" /></a>`).join("")}</div>` : ""}
      ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}`;
    return historyRecordMarkup({author,authorTitle:`${author} · ${verified}`,createdAt:annotation.created_at,badges,
      meta:run ? `<span class="history-run" title="${escapeHtml(run.title)}">${escapeHtml(run.text)}</span>` : "",body,actions});
  }).join("")}</div>`;
}

function bindAnnotationHistory(root, caseData) {
  if (!root || !caseData) return;
  root.querySelectorAll("[data-delete-annotation]").forEach((button) => {
    button.addEventListener("click", () => {
      deleteAnnotationVersion(caseData, button.dataset.deleteAnnotation, button);
    });
  });
}

function updateReviewHistory(caseData) {
  if (!caseData || state.selectedId !== caseData.issue_id) return;
  const annotations = reviewAnnotationsForAllRuns(caseData);
  const launch = $("#reviewHistoryLaunchButton");
  if (launch) {
    launch.innerHTML = `<span class="ui-lang-zh">历史 · ${annotations.length}</span><span class="ui-lang-en">History · ${annotations.length}</span><kbd class="review-control-shortcut" aria-hidden="true">J</kbd>`;
    launch.title = uiText("展开或收起 Review 历史（J）", "Toggle Review history (J)");
  }
  const dialog = $("#historyDialog");
  const dialogContent = $("#historyDialogContent");
  const title = $("#historyDialogTitle")?.textContent || "";
  if (
    dialog?.open &&
    dialogContent &&
    (title === "Review 历史" || title === "Review history")
  ) {
    dialog.historyCaseData = caseData;
    dialogContent.innerHTML = annotationHistory(annotations);
    bindAnnotationHistory(dialogContent, caseData);
    if ($("#historyDialogMeta")) {
      const runCount = new Set(
        annotations.map((item) => String(item.model_run_id || "legacy"))
      ).size;
      $("#historyDialogMeta").textContent =
        state.uiLanguage === "en"
          ? `${annotations.length} reviews · across ${runCount} model runs`
          : `${annotations.length} 条历史 Review · 跨 ${runCount} 个 Model Run`;
    }
  }
}

function refreshReviewDerivedData({ includeCases = true } = {}) {
  const requests = [loadOverview(), loadClusters(), loadReviewers()];
  if (includeCases) requests.push(loadCases());
  void Promise.allSettled(requests);
}

async function deleteAnnotationVersion(caseData, annotationId, button) {
  if (state.savingAnnotation) return;
  const allAnnotations = reviewAnnotationsForAllRuns(caseData);
  const annotation = allAnnotations.find(
    (item) => String(item.id) === String(annotationId)
  );
  if (!annotation) return;
  if (annotation.review_domain === "model_review") {
    await revokeModelReviewVersion(caseData, annotation, button);
    return;
  }
  const annotationRunId = String(annotation.model_run_id || "").trim();
  const sameRunAnnotations = allAnnotations.filter(
    (item) => String(item.model_run_id || "").trim() === annotationRunId
  );
  const deletingLatest = String(sameRunAnnotations[0]?.id) === String(annotationId);
  const currentRunAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const deletingCurrentRunLatest =
    String(currentRunAnnotations[0]?.id) === String(annotationId);
  const unsavedWarning = deletingLatest && state.reviewFormDirty
    ? "\n当前表单有未保存编辑，删除后会恢复上一版本并丢弃这些编辑。"
    : "";
  const confirmed = window.confirm(
    `确认删除 ${formatTime(annotation.created_at)} 保存的 Review 版本？\n\n复核人：${annotation.author || "未记录"}\n该操作不可恢复；如果删除当前版本，会自动恢复上一版本为当前 Review。${unsavedWarning}`
  );
  if (!confirmed) return;
  state.savingAnnotation = true;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  try {
    const result = await api(
      `/api/cases/${encodeURIComponent(caseData.issue_id)}/annotations/${encodeURIComponent(annotationId)}`,
      { method: "DELETE" }
    );
    acknowledgeLocalChange(result);
    caseData.annotations = (caseData.annotations || []).filter(
      (item) => String(item.id) !== String(annotationId)
    );
    if (
      state.selectedCase?.issue_id === caseData.issue_id &&
      deletingLatest &&
      deletingCurrentRunLatest
    ) {
      state.selectedCase = caseData;
      syncReviewFormFromCase(caseData);
    } else {
      updateReviewHistory(caseData);
    }
    showToast("已删除该 Review 版本。");
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
    if (button.isConnected) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  } finally {
    state.savingAnnotation = false;
  }
}

async function revokeModelReviewVersion(caseData, annotation, button) {
  const head = reviewAnnotationsForAllRuns(caseData).find((item) =>
    item.review_domain === "model_review" &&
    item.model_run_id === annotation.model_run_id &&
    (item.campaign_id || "") === (annotation.campaign_id || "") &&
    (item.reference_id || "") === (annotation.reference_id || "") &&
    String(item.author || "").toLowerCase() === String(annotation.author || "").toLowerCase()
  );
  const isHead = String(head?.id) === String(annotation.id);
  const affectsForm = isHead && String(currentReviewAnnotation(caseData)?.id) === String(annotation.id);
  if (!window.confirm(`确认撤销 ${formatTime(annotation.created_at)} 的 Run 复核？\nCase 标签和原始审计记录会保留；任务进度按剩余有效复核重算。${affectsForm && state.reviewFormDirty ? "\n当前表单有未保存编辑，撤销后将重新加载。" : ""}`)) return;
  state.savingAnnotation = true;
  button.disabled = true;
  try {
    const detailKey = caseCorePath(caseData.issue_id);
    const requestSeq = state.caseRequestSeq;
    const result = await api(`/api/cases/${encodeURIComponent(caseData.issue_id)}/model-reviews/${encodeURIComponent(annotation.id)}/revoke`, {
      method: "POST", body: JSON.stringify({ expected_head_id: head?.id || null }),
    });
    acknowledgeLocalChange(result);
    state.caseDetailPrefetch.clear();
    if (state.selectedId === caseData.issue_id && state.caseRequestSeq === requestSeq && caseCorePath(caseData.issue_id) === detailKey) {
      const data = await api(caseCorePath(caseData.issue_id));
      if (state.selectedId === caseData.issue_id && state.caseRequestSeq === requestSeq && caseCorePath(caseData.issue_id) === detailKey) {
        state.selectedCase = data;
        if (affectsForm) {
          clearReviewDraft(data.issue_id, currentReviewRunId(data), reviewWorkSplitBinding(data));
          syncReviewFormFromCase(data);
          if (effectiveReviewWorkflowMode(data) === "model_review_and_case_label") await loadCombinedReviewContext(data);
        }
        updateReviewHistory(data);
      }
    }
    showToast("已撤销 Run 复核，Case 标签已保留。");
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.savingAnnotation = false;
    if (button.isConnected) button.disabled = false;
  }
}

function refreshHistoryDialogLanguage() {
  const dialog = $("#historyDialog");
  if (!dialog?.open || !dialog.historyCaseData || dialog.dataset.historyKind === "model") return;
  const content = $("#historyDialogContent"), scroll = content.scrollTop;
  openHistoryDialog(dialog.dataset.historyKind, dialog.historyCaseData);
  content.scrollTop = scroll;
}
