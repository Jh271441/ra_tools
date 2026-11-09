/* review-submit.js
 * Review/combined submission, save locks and filtered-queue reconciliation.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

async function reviewSaveNavigationContext(issueId) {
  const cases = typeof reviewNavigationCases === "function" ? reviewNavigationCases() : state.cases;
  const index = cases.findIndex(
    (item) => String(item.issue_id) === String(issueId)
  );
  const params = reviewSaveQueueParams();
  const pageSize = state.casePageSize;
  const context = {
    issueId: String(issueId || ""),
    page: Number(state.casePage || 1),
    index,
    absoluteIndex: index < 0 ? -1 : (state.casePage - 1) * pageSize + index,
    nextId: cases[index + 1]?.issue_id || "",
    previousId: index > 0 ? cases[index - 1]?.issue_id || "" : "",
    hadNext: index >= 0 && (
      index < cases.length - 1 ||
      state.casePage * state.casePageSize < state.caseTotal
    ),
    scrollY: window.scrollY,
    pageContext: capturePageContext(),
    actor: state.session?.username || "",
    filterKey: params.toString(),
  };
  if (index >= 0) return context;
  // A shared detail URL may omit the page, or a collaboration refresh may
  // already have removed the selected Issue. Locate it before submitting.
  try {
    const ids = await reviewSaveQueueIds(params);
    let absolute = ids.indexOf(context.issueId);
    context.hadNext = absolute >= 0 && absolute < ids.length - 1;
    if (absolute < 0 && (params.has("task_progress") || params.has("label_state"))) {
      const taskOrder = new URLSearchParams(params);
      taskOrder.delete("task_progress");
      taskOrder.delete("label_state");
      if (taskOrder.get("task_view") === "pending") taskOrder.set("task_view", "targets");
      const ordered = await reviewSaveQueueIds(taskOrder);
      const anchor = ordered.indexOf(context.issueId);
      if (anchor >= 0) {
        const remaining = new Set(ids);
        const next = ordered.slice(anchor + 1).find(id => remaining.has(id));
        const previous = ordered.slice(0, anchor).reverse().find(id => remaining.has(id));
        absolute = ids.indexOf(next || previous);
        context.hadNext = Boolean(next);
      }
    }
    if (absolute >= 0) {
      context.absoluteIndex = absolute;
      context.page = Math.floor(absolute / pageSize) + 1;
      context.index = absolute % pageSize;
      context.nextId = ids[absolute] === context.issueId ? ids[absolute + 1] || "" : ids[absolute];
      context.previousId = ids[absolute] === context.issueId ? ids[absolute - 1] || "" : ids[absolute];
    }
  } catch (_) { /* A queue read must not prevent saving the label. */ }
  return context;
}

function reviewSaveQueueParams() {
  const params = currentReviewGalleryExportParams();
  params.delete("format");
  params.delete("gallery_scope");
  return params;
}

async function reviewSaveQueueIds(params) {
  // A pre-save collaboration GET must not supply this post-save read.
  const result = await api(`/api/cases/issue-ids?${params}`, {
    cache: "no-store", signal: new AbortController().signal,
  });
  return result.issue_ids || [];
}

function reviewSaveNavigationIsCurrent(context) {
  return Boolean(context?.issueId && state.activePage === "review"
    && String(state.selectedId || "") === context.issueId
    && isPageContextCurrent(context.pageContext, { matchUrl: false })
    && (state.session?.username || "") === context.actor
    && reviewSaveQueueParams().toString() === context.filterKey);
}

async function reconcileReviewQueueAfterSave(context) {
  if (!reviewSaveNavigationIsCurrent(context)) return false;
  const ids = await reviewSaveQueueIds(new URLSearchParams(context.filterKey));
  if (!reviewSaveNavigationIsCurrent(context)) return false;
  const retainedIndex = ids.indexOf(context.issueId);
  const hasDraft = state.reviewFormDirty || state.pendingReviewImages?.length
    || (typeof caseRationalePendingImages === "function" && caseRationalePendingImages(state.selectedCase).length);
  if (retainedIndex >= 0 || hasDraft) {
    await loadCases({keepSelection:true, fresh:true, queueIds:ids,
      page:retainedIndex >= 0 ? Math.floor(retainedIndex / state.casePageSize) + 1 : context.page});
    return false;
  }
  if (!ids.length) {
    await loadCases({keepSelection:true, page:1, fresh:true, queueIds:ids});
    if (!reviewSaveNavigationIsCurrent(context) || state.reviewFormDirty) return false;
    clearDetail({ showGallery: true });
    showPage("review", { historyMode: "replace", issue: "" });
    showToast(uiText("已保存；当前筛选已没有更多 Issue。", "Saved; no Issues remain in this filter."));
    return true;
  }
  const adjacent = context.hadNext ? context.nextId : context.previousId;
  let targetIndex = ids.indexOf(adjacent);
  if (targetIndex < 0) targetIndex = Math.min(Math.max(0, context.absoluteIndex), ids.length - 1);
  const targetId = ids[targetIndex];
  const targetPage = Math.floor(targetIndex / state.casePageSize) + 1;
  if (!reviewSaveNavigationIsCurrent(context) || state.reviewFormDirty) return false;
  state.casePage = targetPage;
  state.caseTotal = ids.length;
  state.reviewNavigationQueue = {ids, pageSize:state.casePageSize,
    filterKey:context.filterKey, actor:context.actor};
  state.reviewQueueStale = true;
  // Commit the new detail route first. Gallery rows and thumbnails must not
  // delay opening a server-confirmed next Issue.
  const navigation = selectCase(targetId, {
    historyMode: "replace",
    preserveScrollY: context.scrollY,
  });
  const pageContext = capturePageContext();
  const current = () => state.activePage === "review" && state.selectedId === targetId
    && isPageContextCurrent(pageContext) && (state.session?.username || "") === context.actor
    && reviewSaveQueueParams().toString() === context.filterKey;
  let pageFailed = false;
  void loadCases({keepSelection:true, page:targetPage, fresh:true, queueIds:ids}).catch(() => {
    pageFailed = true;
    if (current()) reportReviewQueueRefreshFailure(context);
  });
  await navigation;
  if (current() && !pageFailed) showToast(uiText(
    context.hadNext ? "已保存，已跳到下一个筛选结果。" : "已保存，已回到上一个筛选结果。",
    context.hadNext ? "Saved; moved to the next filtered Issue." : "Saved; returned to the previous filtered Issue.",
  ));
  return true;
}

function reportReviewQueueRefreshFailure(context) {
  state.reviewQueueStale = true;
  refreshReviewDerivedData({includeCases:false});
  showToast(context?.savedKind === "decision" ? uiText(
    "裁决已保存，但筛选队列刷新失败；请刷新页面继续。",
    "Decision saved, but the filtered queue could not refresh. Refresh the page to continue.",
  ) : uiText(
    "Review 已保存，但筛选队列刷新失败；请刷新页面继续。",
    "Review saved, but the filtered queue could not refresh. Refresh the page to continue.",
  ), true);
}

async function refreshReviewAfterSave(context) {
  const stillOnSavedIssue = reviewSaveNavigationIsCurrent(context);
  try {
    if (stillOnSavedIssue) {
      await reconcileReviewQueueAfterSave(context);
    }
    if (state.activePage === "review" && !stillOnSavedIssue) {
      refreshReviewDerivedData({ includeCases: true });
    } else {
      if (state.activePage !== "review") state.reviewQueueStale = true;
      refreshReviewDerivedData({ includeCases: false });
    }
  } catch (_error) {
    reportReviewQueueRefreshFailure(context);
  }
}

function releaseReviewSubmitLock(submitButton) {
  state.savingAnnotation = false;
  if (submitButton?.isConnected) {
    submitButton.disabled = Boolean(expectedOutputSelectionState().conflictKind);
    submitButton.removeAttribute("aria-busy");
  }
}

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId || state.savingAnnotation) return;
  if (effectiveReviewWorkflowMode(state.selectedCase) === "model_review_and_case_label") {
    await saveCombinedReview(event);
    return;
  }
  const issueId = String(state.selectedId);
  const runBoundModelReview = Boolean(
    state.reviewEditRunId || currentReviewRunId(state.selectedCase)
  );
  if (!runBoundModelReview) {
    showToast("请先选择 Model Run；共享标签和 GT 请到 问题标注工作台修改。", true);
    return;
  }
  const expectedOutputState = expectedOutputSelectionState();
  if (!runBoundModelReview && expectedOutputState.conflictKind === "tags") {
    showToast("Tags 指向多个期望输出，请先消除冲突。", true);
    return;
  }
  if (!runBoundModelReview && expectedOutputState.conflictKind === "selection") {
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
    work_split_id: reviewWorkSplitBinding(state.selectedCase),
    expected_previous_annotation_id: currentReviewBaseAnnotationId(
      currentReviewAnnotation(state.selectedCase),
      state.reviewEditRunId || currentReviewRunId(state.selectedCase),
      $("#annotationAuthor")?.value || ""
    ),
    expected_output: $("#expectedOutputInput")?.value || "",
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...document.querySelectorAll('input[name="reviewTags"]:checked')].map(
      (input) => input.value
    ),
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote").value,
    author: $("#annotationAuthor").value,
  };
  payload.model_review_status = modelReviewSubmissionStatus({ model_review_status: $("#modelReviewStatusInput")?.value });
  delete payload.expected_output;
  delete payload.is_excluded;
  delete payload.tags;
  const screenshotItems = [...state.pendingReviewImages];
  const screenshotFiles = screenshotItems.map((item) => item.file);
  const navigationContext = await reviewSaveNavigationContext(issueId);
  const uploadKey = reviewUploadTaskKey(issueId, payload);
  const activeBackgroundUpload = state.backgroundReviewUploads.get(uploadKey);
  if (activeBackgroundUpload && !activeBackgroundUpload.failed) {
    releaseReviewSubmitLock(submitButton);
    showToast("该 Issue 的截图正在后台上传，请稍候。", true);
    return;
  }
  if (screenshotFiles.length) {
    const task = {
      key: uploadKey,
      issueId,
      payload,
      files: screenshotFiles,
      previewItems: screenshotItems,
      navigationContext,
      queuedAt: Date.now(),
      failed: false,
      status: "queued",
    };
    state.backgroundReviewUploads.set(uploadKey, task);
    state.pendingReviewImages = [];
    renderPendingReviewImages();
    state.reviewFormDirty = false;
    state.deferredDetailRefresh = false;
    $("#annotationNote")?.blur();
    enqueueBackgroundReviewUpload(task);
    showToast(uiText(
      `Review 和 ${screenshotFiles.length} 张截图已进入后台保存，可继续切换 Issue。`,
      `Review and ${screenshotFiles.length} screenshot(s) are saving in background; you can switch Issues.`,
    ));
    releaseReviewSubmitLock(submitButton);
    return;
  }
  try {
    const result = await api(`/api/cases/${encodeURIComponent(issueId)}/annotations`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    acknowledgeLocalChange(result);
    if (result?.annotation) {
      state.reviewEditRunId = result.annotation.model_run_id || state.reviewEditRunId;
      state.reviewEditBaseAnnotationId = result.annotation.id || null;
    }
    clearReviewDraft(issueId, payload.model_run_id, payload.work_split_id, payload.author);
    const screenshotCount = 0;
    state.reviewFormDirty = false;
    state.deferredDetailRefresh = false;
    clearPendingReviewImages();
    if (result?.annotation && state.selectedCase?.issue_id === issueId) {
      state.selectedCase.annotations = [
        result.annotation,
        ...(state.selectedCase.annotations || []).filter(
          (item) => String(item.id) !== String(result.annotation.id)
        ),
      ];
      updateReviewHistory(state.selectedCase);
    }
    if (
      payload.work_split_id &&
      result?.annotation &&
      state.selectedCase?.issue_id === issueId
    ) {
      const refreshed = await api(
        `/api/cases/${encodeURIComponent(issueId)}?include_media=false&model_run_id=${encodeURIComponent(payload.model_run_id || "")}&work_split_id=${encodeURIComponent(payload.work_split_id || "")}`
      );
      if (state.selectedCase?.issue_id === refreshed?.issue_id) {
        state.selectedCase.annotations = refreshed.annotations || state.selectedCase.annotations;
        state.selectedCase.review_assignment = refreshed.review_assignment || state.selectedCase.review_assignment;
        updateReviewHistory(state.selectedCase);
      }
    }
    const queuedCount = result?.annotation?.notification?.queued?.length || 0;
    showToast(
      `已保存新的 review 版本${screenshotCount ? `和 ${screenshotCount} 张截图` : ""}${queuedCount ? `；DChat 通知已排队 ${queuedCount} 人` : ""}。`
    );
    $("#annotationNote")?.blur();
    await refreshReviewAfterSave(navigationContext);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    releaseReviewSubmitLock(submitButton);
  }
}

async function saveCombinedReview(event) {
  const caseData = state.selectedCase;
  const issueId = String(caseData?.issue_id || state.selectedId || "");
  if (!issueId || state.savingAnnotation) return;
  const context = state.combinedReviewContext;
  if (!context || String(context.issue?.issue_id || "") !== issueId
      || state.combinedReviewLoad?.key !== combinedReviewContextKey(caseData)
      || state.combinedReviewLoad?.status !== "ready") {
    renderCombinedReviewContextStatus();
    showToast(state.combinedReviewLoad?.error || "联合复核上下文未就绪，请在提交按钮下重试加载。", true);
    return;
  }
  if (caseRationaleUploadTask(caseData)) {
    showToast(uiText("此条图片提交正在保存或等待重试，请先处理上传状态。", "This image submission is saving or awaiting retry. Check its upload status first."), true);
    return;
  }
  const expectedState = expectedOutputSelectionState();
  if (!expectedState.selectedValue) {
    showToast("请明确选择 Case 标签。", true);
    return;
  }
  if (expectedState.conflictKind) {
    showToast("Case 标签与所选 Tags 冲突，请先修正。", true);
    return;
  }
  const runId = currentReviewRunId(caseData);
  let campaignId;
  try {
    campaignId = combinedReviewCampaignBinding(caseData);
    if (String(context.campaign?.id || "") !== campaignId ||
        String(context.campaign?.evaluation_run_id || "") !== runId) {
      throw new Error("联合复核任务或 Run 已切换，请等待上下文重新加载后提交。");
    }
  } catch (error) {
    showToast(error.message, true);
    return;
  }
  const payload = {
    author: $("#annotationAuthor")?.value || state.session?.username || "",
    expected_output: expectedState.selectedValue,
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...document.querySelectorAll('input[name="reviewTags"]:checked')].map((input) => input.value),
    rationale: $("#combinedCaseRationale")?.value || "",
    update_case_details: true,
    expected_case_revision_id: context.case_revision_id || null,
    expected_label_state_fingerprint: context.label_state_fingerprint || "",
  };
  if (runId) Object.assign(payload, {
    model_run_id: runId, campaign_id: campaignId || "", work_split_id: campaignId || "",
    model_review_status: modelReviewSubmissionStatus({ model_review_status: $("#modelReviewStatusInput")?.value }),
    reason: $("#annotationNote")?.value || "",
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    expected_model_review_storage_id: context.model_review_storage_id || null,
  });
  const imageKey = caseRationaleImageKey(caseData);
  const imageItems = [...caseRationalePendingImages(caseData)];
  const contextKey = combinedReviewContextKey(caseData);
  const draftScope = [issueId, runId, reviewWorkSplitBinding(caseData), reviewDraftReviewer(caseData)];
  const submittedDraft = persistReviewDraft(caseData);
  state.savingAnnotation = true;
  const button = event.submitter || $("#reviewSaveButton");
  if (button) {
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
  }
  try {
    const navigationContext = await reviewSaveNavigationContext(issueId);
    if (imageItems.length) {
      const task = { key: imageKey, issueId, payload, imageItems, draftScope, navigationContext,
        draft: submittedDraft || readReviewDraft(...draftScope), contextKey,
        action: runId ? "combined-review" : "case-label-from-review",
        headers: runId ? { "Idempotency-Key": globalThis.crypto?.randomUUID?.() || `combined-${Date.now()}-${Math.random().toString(16).slice(2)}` } : {},
      };
      state.backgroundCaseUploads ||= new Map();
      state.backgroundCaseUploads.set(imageKey, task);
      enqueueCaseRationaleUpload(task);
      showToast(uiText("图片和复核已进入后台保存，可继续切换 Issue。", "Images and review are saving in the background; you can switch Issues."));
      return;
    }
    let result;
    if (!runId) {
      result = await submitCaseRationalePayload(issueId, "case-label-from-review", payload, imageItems);
      acknowledgeLocalChange(result);
      showToast(uiText("标注已保存", "Label saved"));
    } else {
      const idempotencyKey = globalThis.crypto?.randomUUID?.() || `combined-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      result = await submitCaseRationalePayload(issueId, "combined-review", payload, imageItems, { "Idempotency-Key": idempotencyKey });
      acknowledgeLocalChange(result);
      const combined = result?.combined_review || {};
      if (combined.model_review && caseData.issue_id === issueId) {
        caseData.annotations = [
          combined.model_review,
          ...(caseData.annotations || []).filter((item) => String(item.id) !== String(combined.model_review.id)),
        ];
        caseData.label_state = combined.label_state || caseData.label_state;
        delete caseData.label_source_contexts;
      }
      showToast(uiText("联合复核已保存", "Combined review saved"));
    }
    clearSavedCaseRationaleImages(imageKey, imageItems);
    const current = state.activePage === "review" && state.selectedCase === caseData
      && combinedReviewContextKey(caseData) === contextKey;
    const newerDraft = retireSavedCaseReviewDraft(draftScope, submittedDraft, result, current ? caseData : null);
    caseData.label_state = (result.combined_review || result.case_label)?.label_state || caseData.label_state;
    delete caseData.label_source_contexts;
    if (current) {
      state.reviewFormDirty = newerDraft || caseRationalePendingImages(caseData).length > 0;
    }
    await refreshReviewAfterSave(navigationContext);
    if (state.activePage === "review" && state.selectedCase === caseData
        && combinedReviewContextKey(caseData) === contextKey) {
      loadCombinedReviewContext(caseData, {preserveForm: newerDraft, fresh: true}).catch(() => {});
    }
  } catch (error) {
    if (Number(error?.status || 0) === 409 || String(error?.message || "").includes("变化")) {
      showToast("数据已变化，联合提交未写入任何一边；请刷新后重新确认。", true);
    } else {
      showToast(error.message, true);
    }
  } finally {
    state.savingAnnotation = false;
    if (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
    renderCombinedReviewContextStatus();
  }
}
