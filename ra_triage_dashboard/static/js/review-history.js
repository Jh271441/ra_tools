/* ra_triage_dashboard/static/js/review-history.js
 * Review annotation history pane
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function annotationHistory(annotations) {
  if (!annotations?.length) {
    return '<div class="annotation-history"><p class="muted history-empty">尚无人工 review；保存后会保留旧版本。</p></div>';
  }
  return `<div class="annotation-history">${annotations
    .map(
      (annotation) => {
        const expectedOutput = annotationExpectedOutput(annotation);
        return `<article class="history-row">
        <div class="history-head">
          <span class="history-expected-output" title="期望输出">期望 ${labelBadge(expectedOutput, "待补充")}</span>
          <span class="history-derived-status">${escapeHtml(reviewStatusLabel(annotation.review_status))}</span>
          ${annotation.is_excluded ? '<span class="tag exclusion-tag">已排除</span>' : ""}
          <span class="history-reviewer" title="${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}` : "复核人：历史记录未填写")}">${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO" : " · 未验证"}` : "复核人：未记录")}</span>
          <span class="history-run" title="Review 绑定的 Model Run">Run · ${escapeHtml(reviewRunLabel(annotation.model_run_id))}</span>
          <span class="history-actions"><span class="history-time">${formatTime(annotation.created_at)}</span><button class="history-delete-button" type="button" data-delete-annotation="${escapeHtml(annotation.id)}" title="删除这条 Review 版本" aria-label="删除 ${escapeHtml(formatTime(annotation.created_at))} 的 Review 版本"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 3h4l1 2H7zM6 6l.7 11h6.6L14 6M8.5 9v5m3-5v5"/></svg></button></span>
        </div>
        ${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map((key) => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
        ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map((tag) => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>` : ""}
        ${annotation.attachments?.length ? `<div class="history-attachments">${annotation.attachments.map((attachment, index) => `<a href="${escapeHtml(attachment.url)}" target="_blank" rel="noreferrer" title="打开补充截图 ${index + 1}"><img src="${escapeHtml(attachment.url)}" alt="补充截图 ${index + 1}" loading="lazy" /></a>`).join("")}</div>` : ""}
        ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}
      </article>`;
      }
    )
    .join("")}</div>`;
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
    launch.innerHTML = `<span class="ui-lang-zh">Review 历史 · ${annotations.length} 条</span><span class="ui-lang-en">Review history · ${annotations.length}</span>`;
  }
  const dialog = $("#historyDialog");
  const dialogContent = $("#historyDialogContent");
  const title = $("#historyDialogTitle")?.textContent || "";
  if (
    dialog?.open &&
    dialogContent &&
    (title === "Review 历史" || title === "Review history")
  ) {
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

function refreshReviewDerivedData() {
  void Promise.allSettled([
    loadOverview(),
    loadClusters(),
    loadCases(),
    loadReviewers(),
  ]);
}

async function deleteAnnotationVersion(caseData, annotationId, button) {
  if (state.savingAnnotation) return;
  const allAnnotations = reviewAnnotationsForAllRuns(caseData);
  const annotation = allAnnotations.find(
    (item) => String(item.id) === String(annotationId)
  );
  if (!annotation) return;
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
