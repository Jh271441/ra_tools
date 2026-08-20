/* ra_triage_dashboard/static/js/review-gallery.js
 * Review gallery, cases, batch draft entry
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function reviewComparisonStatusForItem(item) {
  if (!state.selectedRunId) return "";
  const prediction = item?.prediction || {};
  if (!prediction.model_run_id) return "none";
  if (!LABELS.includes(prediction.label)) return "none";
  return prediction.mismatch ? "mismatch" : "match";
}

function issueCard(item) {
  const isSelected = item.issue_id === state.selectedId;
  const rawTitle = String(item.title || item.scenario || "").trim();
  const title =
    rawTitle && !LABELS.includes(rawTitle) && rawTitle !== item.gt_label ? rawTitle : "";
  const annotation = item.annotation?.label;
  const prediction = item.prediction?.label;
  const comparisonStatus = reviewComparisonStatusForItem(item);
  const comparisonMeta = REVIEW_COMPARISON_META[comparisonStatus];
  const mismatch = comparisonStatus === "mismatch";
  const displayPrediction = prediction || (comparisonStatus === "none" ? "NONE" : "");
  const thumbnailUrl = safeSameOriginAssetUrl(item.thumbnail?.url);
  const thumbnailLabel = String(
    item.thumbnail?.label || (thumbnailUrl ? t("gallery.bev_keyframe") : t("gallery.no_thumb"))
  );
  const issueUrl = safeUrl(item.voyager_issue_url);
  const evidenceKeys = Array.isArray(item.annotation?.missing_evidence)
    ? item.annotation.missing_evidence
    : [];
  const evidenceTitle = evidenceKeys.map((key) => evidenceLabel(key)).join(" · ");
  const evidenceRow = evidenceKeys.length
    ? `<div class="row-evidence" title="${escapeHtml(evidenceTitle)}">${evidenceKeys
        .map((key) => `<span>${escapeHtml(evidenceLabel(key))}</span>`)
        .join("")}</div>`
    : "";
  return `
    <article class="issue-card ${isSelected ? "selected" : ""}" data-issue-id="${escapeHtml(item.issue_id)}">
      <button class="issue-card-open" type="button" data-open-issue="${escapeHtml(item.issue_id)}" aria-label="打开 ${escapeHtml(item.issue_id)} Review"></button>
      <div class="issue-thumbnail">
        <div class="issue-thumbnail-placeholder" aria-hidden="true"><span>RA</span><small>${escapeHtml(t("gallery.no_bev_thumb"))}</small></div>
        ${thumbnailUrl ? `<img src="${escapeHtml(thumbnailUrl)}" alt="${escapeHtml(item.issue_id)} ${escapeHtml(thumbnailLabel)}" loading="lazy" decoding="async" data-case-thumbnail />` : ""}
        <span class="issue-thumbnail-label">${escapeHtml(thumbnailLabel)}</span>
        <button class="issue-media-preview" type="button" data-case-media-preview="${escapeHtml(item.issue_id)}" aria-label="${escapeHtml(uiText(`预览 ${item.issue_id} 的 BEV、Camera 和视频`, `Preview BEV, Camera, and video for ${item.issue_id}`))}"><span class="ui-lang-zh">媒体预览</span><span class="ui-lang-en">Media</span></button>
        ${comparisonMeta ? `<span class="comparison-chip comparison-${comparisonStatus} issue-thumbnail-status">${escapeHtml(comparisonMeta.label)}</span>` : ""}
      </div>
      <div class="issue-card-body">
        <div class="issue-card-heading">
          <div class="issue-card-heading-main">
            ${issueUrl ? `<a class="issue-id" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" data-card-link title="打开 Voyager Issue">${escapeHtml(item.issue_id)}</a>` : `<span class="issue-id">${escapeHtml(item.issue_id)}</span>`}
            ${evidenceRow}
          </div>
          ${!mismatch ? labelBadge(annotation, t("gallery.pending_review")) : ""}
        </div>
        ${title ? `<div class="issue-title">${escapeHtml(title)}</div>` : ""}
        <div class="issue-card-labels">
          <span class="issue-label-pair"><small>GT</small>${labelBadge(item.gt_label, "—")}</span>
          <span class="issue-label-pair"><small class="ui-lang-zh">模型</small><small class="ui-lang-en">Model</small>${displayPrediction ? labelBadge(displayPrediction, "—") : labelBadge("", "—")}</span>
          ${item.annotation?.author ? `<span class="issue-reviewer" title="${escapeHtml(uiText(`复核人：${item.annotation.author}${item.annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}`, `Reviewer: ${item.annotation.author}${item.annotation.author_verified ? " · SSO verified" : " · unverified"}`))}"><span class="ui-lang-zh">复核</span><span class="ui-lang-en">Review</span> · ${escapeHtml(item.annotation.author)}${item.annotation.author_verified ? " · SSO" : ""}</span>` : ""}
        </div>
      </div>
    </article>`;
}

function caseGallerySignature(items) {
  return JSON.stringify({
    selectedId: state.selectedId,
    items: (items || []).map((item) => ({
      issue_id: item.issue_id,
      title: item.title || item.scenario || "",
      gt_label: item.gt_label || "",
      prediction: item.prediction
        ? {
            label: item.prediction.label || "",
            model_run_id: item.prediction.model_run_id || "",
          }
        : null,
      annotation: item.annotation
        ? {
            label: item.annotation.label || "",
            author: item.annotation.author || "",
            author_verified: Boolean(item.annotation.author_verified),
            missing_evidence: item.annotation.missing_evidence || [],
          }
        : null,
      thumbnail: item.thumbnail?.url || "",
      voyager_issue_url: item.voyager_issue_url || "",
    })),
  });
}

function reuseGalleryThumbnails(list, previousThumbnails) {
  if (!list || !previousThumbnails?.size) return;
  list.querySelectorAll("article[data-issue-id]").forEach((card) => {
    const nextImage = card.querySelector("img[data-case-thumbnail]");
    const previous = previousThumbnails.get(card.dataset.issueId);
    if (
      !nextImage ||
      !previous ||
      previous.image === nextImage ||
      previous.url !== nextImage.src ||
      !previous.image.complete ||
      previous.image.naturalWidth <= 0
    ) {
      return;
    }
    nextImage.replaceWith(previous.image);
  });
}

function totalCasePages() {
  return Math.max(1, Math.ceil(Number(state.caseTotal || 0) / state.casePageSize));
}

function renderCasePagination() {
  const totalPages = totalCasePages();
  const previous = $("#casePagePrevious");
  const next = $("#casePageNext");
  const summary = $("#casePageSummary");
  const jumpInput = $("#casePageJump");
  const jumpButton = $("#casePageJumpButton");
  const pageSize = $("#casePageSize");
  const result = $("#galleryResultSummary");
  if (previous) previous.disabled = state.casePage <= 1 || !state.caseTotal;
  if (next) next.disabled = state.casePage >= totalPages || !state.caseTotal;
  if (summary) summary.textContent = `${state.casePage} / ${totalPages}`;
  if (jumpInput) {
    const focused = document.activeElement === jumpInput;
    jumpInput.min = "1";
    jumpInput.max = String(totalPages);
    jumpInput.disabled = totalPages <= 1;
    jumpInput.dataset.pageCount = String(totalPages);
    if (!focused) jumpInput.value = String(state.casePage);
  }
  if (jumpButton) jumpButton.disabled = totalPages <= 1;
  if (pageSize) pageSize.value = String(state.casePageSize);
  if (result) {
    const start = state.caseTotal ? (state.casePage - 1) * state.casePageSize + 1 : 0;
    const end = Math.min(state.casePage * state.casePageSize, state.caseTotal);
    result.textContent = state.caseTotal
      ? t("gallery.summary_range", { from: start, to: end, n: state.caseTotal })
      : t("gallery.no_match");
  }
}

function renderCaseNavigation() {
  const index = state.cases.findIndex((item) => item.issue_id === state.selectedId);
  const previous = $("#previousIssueButton");
  const next = $("#nextIssueButton");
  const input = $("#detailQueueIndexInput");
  const totalEl = $("#detailQueueTotal");
  const hasPrevious = index > 0 || (index === 0 && state.casePage > 1);
  const hasNext =
    index >= 0 &&
    (index < state.cases.length - 1 ||
      state.casePage * state.casePageSize < state.caseTotal);
  if (previous) previous.disabled = !hasPrevious;
  if (next) next.disabled = !hasNext;
  const absolute =
    index >= 0
      ? (state.casePage - 1) * state.casePageSize + index + 1
      : null;
  const total = Math.max(0, Number(state.caseTotal) || 0);
  if (totalEl) {
    totalEl.textContent =
      absolute != null ? `/ ${total}` : total ? `/ ${total}` : "/ —";
  }
  if (input) {
    const focused = document.activeElement === input;
    input.min = "1";
    input.max = total > 0 ? String(total) : "";
    input.disabled = total <= 0;
    input.placeholder = total > 0 ? "—" : "—";
    input.title =
      absolute == null
        ? uiText("当前 Issue 不在本页筛选结果中；仍可输入序号跳转", "Issue not on this page; you can still jump by index")
        : uiText("输入筛选队列序号后回车跳转", "Enter queue index and press Return");
    // Do not clobber in-progress typing while the field is focused.
    if (!focused) {
      input.value = absolute != null ? String(absolute) : "";
    }
    input.dataset.queueTotal = String(total);
    if (absolute != null) input.dataset.queueIndex = String(absolute);
  }
}

function bindDetailQueueIndexJump(root = document) {
  const input = root.querySelector?.("#detailQueueIndexInput") || $("#detailQueueIndexInput");
  if (!input || input.dataset.queueJumpBound === "1") return;
  input.dataset.queueJumpBound = "1";
  const commit = () => {
    void jumpToQueueIndex(input.value).catch((error) => showToast(error.message, true));
  };
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      commit();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      renderCaseNavigation();
      input.blur();
    }
  });
  input.addEventListener("blur", () => {
    // Restore canonical display if the user left an invalid draft.
    if (input.dataset.queueJumpBusy === "1") return;
    renderCaseNavigation();
  });
  input.addEventListener("focus", () => {
    window.requestAnimationFrame(() => input.select());
  });
}

async function jumpToQueueIndex(raw) {
  const total = Math.max(0, Number(state.caseTotal) || 0);
  if (total <= 0) {
    showToast(t("gallery.jump_empty"), true);
    renderCaseNavigation();
    return;
  }
  const text = String(raw ?? "").trim();
  if (!/^\d+$/.test(text)) {
    showToast(t("gallery.jump_range", { total }), true);
    renderCaseNavigation();
    return;
  }
  const target = Number.parseInt(text, 10);
  if (!Number.isFinite(target) || target < 1 || target > total) {
    showToast(t("gallery.jump_range", { total }), true);
    renderCaseNavigation();
    return;
  }
  const pageSize = Math.max(1, Number(state.casePageSize) || DEFAULT_CASE_PAGE_SIZE);
  const targetPage = Math.max(1, Math.ceil(target / pageSize));
  const indexOnPage = (target - 1) % pageSize;
  const input = $("#detailQueueIndexInput");
  if (input) input.dataset.queueJumpBusy = "1";
  try {
    if (targetPage !== state.casePage || !state.cases.length) {
      await loadCases({ keepSelection: true, page: targetPage });
    }
    const item = state.cases[indexOnPage];
    if (!item?.issue_id) {
      showToast(t("gallery.jump_fail"), true);
      renderCaseNavigation();
      return;
    }
    if (item.issue_id === state.selectedId) {
      renderCaseNavigation();
      return;
    }
    await selectCase(item.issue_id, { historyMode: "replace" });
  } finally {
    if (input) delete input.dataset.queueJumpBusy;
  }
}

async function changeCasePage(delta) {
  const targetPage = state.casePage + delta;
  if (targetPage < 1 || targetPage > totalCasePages()) return;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  await loadCases({ keepSelection: false, page: targetPage });
  showPage("review", { historyMode: "push", issue: "" });
}

async function jumpToCasePage(raw) {
  const totalPages = totalCasePages();
  const input = $("#casePageJump");
  const text = String(raw ?? "").trim();
  const target = /^\d+$/.test(text) ? Number.parseInt(text, 10) : NaN;
  if (!Number.isFinite(target) || target < 1 || target > totalPages) {
    showToast(uiText(`请输入 1–${totalPages} 的页码`, `Enter a page from 1 to ${totalPages}`), true);
    if (input) {
      input.value = String(state.casePage);
      input.focus();
      input.select();
    }
    return;
  }
  if (target === state.casePage) {
    if (input) input.value = String(target);
    return;
  }
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  await loadCases({ keepSelection: false, page: target });
  showPage("review", { historyMode: "push", issue: "" });
}

async function changeCasePageSize(value) {
  const nextPageSize = CASE_PAGE_SIZES.includes(Number(value))
    ? Number(value)
    : DEFAULT_CASE_PAGE_SIZE;
  if (nextPageSize === state.casePageSize) return;
  state.casePageSize = nextPageSize;
  state.casePage = 1;
  state.galleryScrollY = 0;
  clearPendingReviewImages();
  await loadCases({ keepSelection: false, page: 1 });
  showPage("review", { historyMode: "push", issue: "" });
}

function returnToReviewGallery() {
  clearPendingReviewImages();
  if (window.history.state?.openedFromGallery) {
    window.history.back();
    return;
  }
  clearDetail({ showGallery: true });
  showPage("review", { historyMode: "replace", issue: "" });
}

function renderCases(data) {
  state.cases = data.items || [];
  state.caseTotal = Number(data.total ?? state.cases.length);
  $("#caseCount").textContent = state.caseTotal;
  updateFilteredPredictionButton();
  renderCasePagination();
  renderCaseNavigation();
  const list = $("#issueList");
  const signature = caseGallerySignature(state.cases);
  if (list.dataset.gallerySignature === signature) {
    return;
  }
  const previousThumbnails = new Map();
  list.querySelectorAll("article[data-issue-id]").forEach((card) => {
    const image = card.querySelector("img[data-case-thumbnail]");
    if (image) previousThumbnails.set(card.dataset.issueId, { image, url: image.src });
  });
  list.dataset.gallerySignature = signature;
  if (!state.cases.length) {
    const comparisonStatus = state.reviewComparisonStatus;
    const comparisonMeta = REVIEW_COMPARISON_META[comparisonStatus];
    const hint = comparisonStatus !== "all"
      ? t("gallery.no_match_cmp", { label: comparisonMeta?.label || comparisonStatus })
      : t("gallery.no_match_plain");
    list.innerHTML = `<div class="no-asset issue-grid-empty">${hint}</div>`;
    return;
  }
  list.innerHTML = state.cases.map(issueCard).join("");
  reuseGalleryThumbnails(list, previousThumbnails);
  list.querySelectorAll("[data-open-issue]").forEach((button) => {
    button.addEventListener("click", () => selectCase(button.dataset.openIssue));
  });
  list.querySelectorAll("[data-case-media-preview]").forEach((button) => {
    button.addEventListener("click", () => {
      openCaseMediaPreview(button.dataset.caseMediaPreview, button).catch((error) => {
        showToast(error.message, true);
      });
    });
  });
  list.querySelectorAll("[data-case-thumbnail]").forEach((image) => {
    image.addEventListener("error", () => {
      const thumbnail = image.closest(".issue-thumbnail");
      thumbnail?.classList.add("thumbnail-missing");
      const label = thumbnail?.querySelector(".issue-thumbnail-label");
      if (label) label.textContent = t("gallery.thumb_fail");
      image.remove();
    });
  });
}

function predictionBatchLimit() {
  return Math.min(
    50,
    Number(
      state.config?.prediction_batch?.max_issues ||
        state.config?.batch_prediction?.max_issues ||
        50
    )
  );
}

function updateFilteredPredictionButton() {
  const total = Number(state.caseTotal || 0);
  const limit = predictionBatchLimit();
  const predict = $("#predictFilteredButton");
  if (predict) {
    predict.disabled = total === 0 || state.config?.batch_prediction?.enabled === false;
    predict.innerHTML = total
      ? `<span class="ui-lang-zh">预测当前筛选 · ${total}</span><span class="ui-lang-en">Predict selection · ${total}</span>`
      : `<span class="ui-lang-zh">预测当前筛选</span><span class="ui-lang-en">Predict selection</span>`;
    predict.title = total > limit
      ? uiText(
          `单批最多 ${limit} 个 Issue，请继续收窄筛选后再发起。`,
          `Batch limit is ${limit} issues; narrow the filter first.`
        )
      : uiText(
          `把当前 ${total} 个筛选结果带入 Batch 页面；不会立即运行或自动推送。`,
          `Carry ${total} filtered issues into Batch; does not run or publish yet.`
        );
    predict.classList.toggle("button-limit-warning", total > limit);
  }
  updateWorkSplitAdminVisibility();
  const split = $("#splitFilteredButton");
  if (split && !split.hidden) {
    split.disabled = total === 0;
    split.innerHTML = total
      ? `<span class="ui-lang-zh">均分任务 · ${total}</span><span class="ui-lang-en">Split work · ${total}</span>`
      : `<span class="ui-lang-zh">均分任务</span><span class="ui-lang-en">Split work</span>`;
    split.title = total
      ? uiText(
          `管理员：把当前 ${total} 个筛选 Issue 写入任务负责人；可指定数量，剩余均分。`,
          `Admin: assign ${total} filtered issues to owners.`
        )
      : t("gallery.no_issues_filter");
  }
  const summary = $("#galleryResultSummary");
  if (summary) {
    const assignee = joinFilterList(
      typeof workAssigneeFilterSelection === "function"
        ? workAssigneeFilterSelection()
        : getMultiFilterValues($("#workAssigneeFilter"))
    );
    if (assignee && assignee !== "__none__") {
      summary.textContent = uiText(
        `任务负责人 ${assignee} · ${total} 个 Issue`,
        `Assignee ${assignee} · ${total} issues`
      );
    } else if (assignee === "__none__") {
      summary.textContent = total
        ? t("gallery.unassigned_n", { n: total })
        : t("gallery.no_unassigned");
    } else if (state.reviewIssueIds?.length) {
      summary.textContent = uiText(
        `自定义 Issue 列表 · ${state.reviewIssueIds.length}`,
        `Custom issue list · ${state.reviewIssueIds.length}`
      );
    } else {
      summary.textContent = total
        ? t("gallery.summary", { n: total })
        : t("gallery.no_match");
    }
  }
}

function openBatchDraft(issueIds, source = "") {
  const ids = [
    ...new Set(
      (issueIds || [])
        .map((issueId) => String(issueId || "").trim())
        .filter((issueId) => /^[A-Za-z0-9_-]{3,128}$/.test(issueId))
    ),
  ];
  if (!ids.length) {
    showToast(t("toast.no_batch_issues"), true);
    return;
  }
  const limit = predictionBatchLimit();
  if (ids.length > limit) {
    showToast(
      uiText(
        `当前筛选有 ${ids.length} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`,
        `${ids.length} issues selected; batch limit is ${limit}. Narrow the filter.`
      ),
      true
    );
    return;
  }
  navigatePage("prediction", { issues: ids, source });
}

function predictionActorSlug() {
  const username = String(state.session.username || "triage").trim();
  const safe = username.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
  return (safe || "triage").slice(0, 48);
}

function defaultPredictionBatchName() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, "0");
  const date = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`;
  const time = `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${predictionActorSlug()}_${date}_${time}`;
}

function ensurePredictionBatchName() {
  const input = $("#predictionBatchName");
  if (!input) return;
  const current = input.value.trim();
  if (current && current !== state.batchDefaultName) return;
  const next = defaultPredictionBatchName();
  input.value = next;
  state.batchDefaultName = next;
}

function renderPredictionSourceSummary() {
  const target = $("#predictionSourceSummary");
  if (!target) return;
  const count = predictionIssueIds();
  if (!state.batchDraftSource || !count.length) {
    target.classList.add("hidden");
    target.textContent = "";
    return;
  }
  target.classList.remove("hidden");
  target.textContent =
    state.batchDraftSource === "filtered"
      ? `已从 Review 当前筛选带入 ${count.length} 个 Issue；请核对模型和列表后再开始。`
      : `已从 Review 当前 Case 带入 ${count.length} 个 Issue；仍按 Batch 任务保存为独立 Model Run。`;
}

async function loadCases({
  keepSelection = true,
  page = state.casePage,
} = {}) {
  const requestSeq = ++state.caseListRequestSeq;
  state.casePage = Math.max(1, Number(page) || 1);
  const params = new URLSearchParams();
  const search = $("#searchInput").value.trim();
  const gtLabel = joinFilterList(getMultiFilterValues($("#gtFilter")));
  const modelLabel = joinFilterList(getMultiFilterValues($("#annotationFilter")));
  const annotationAuthor = joinFilterList(
    typeof reviewerFilterSelection === "function"
      ? reviewerFilterSelection("review")
      : getMultiFilterValues($("#reviewerFilter"))
  );
  const reviewStatus = joinFilterList(
    getMultiFilterValues($("#reviewStatusFilter"))
  );
  const workAssignee = joinFilterList(
    typeof workAssigneeFilterSelection === "function"
      ? workAssigneeFilterSelection()
      : getMultiFilterValues($("#workAssigneeFilter"))
  );
  const runFilter = $("#modelRunFilter");
  // During first paint the Run request and gallery request overlap.  A deep
  // link already owns ``state.selectedRunId``, but the native select has no
  // options until loadRuns() finishes.  Do not let that temporary empty DOM
  // value erase the route Run; once options exist, the select is authoritative
  // and a deliberate "不叠加模型输出" choice still clears it normally.
  const runOptionsReady = Boolean(
    runFilter && [...runFilter.options].some((option) => option.value)
  );
  if (runOptionsReady) {
    state.selectedRunId = runFilter.value;
  }
  state.reviewComparisonStatus = selectedReviewComparisonStatus();
  state.failureOnly = state.reviewComparisonStatus === "mismatch";
  if (search) params.set("search", search);
  if (gtLabel) params.set("gt_label", gtLabel);
  if (modelLabel) params.set("model_label", modelLabel);
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  if (reviewStatus) params.set("review_status", reviewStatus);
  if (workAssignee) params.set("work_assignee", workAssignee);
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  if (state.selectedRunId && state.reviewComparisonStatus !== "all") {
    params.set("comparison", state.reviewComparisonStatus);
  }
  if (state.clusterKey) params.set("missing_evidence", state.clusterKey);
  if (Array.isArray(state.reviewIssueIds) && state.reviewIssueIds.length) {
    params.set("issue_ids", state.reviewIssueIds.join(","));
  }
  params.set("page", String(state.casePage));
  params.set("page_size", String(state.casePageSize));
  params.set("include_thumbnail", "true");
  appendBaselineParams(params);
  const data = await api(`/api/cases?${params.toString()}`);
  if (requestSeq !== state.caseListRequestSeq) return;
  const totalPages = Math.max(
    1,
    Math.ceil(Number(data.total || 0) / state.casePageSize)
  );
  if (state.casePage > totalPages) {
    state.casePage = totalPages;
    return loadCases({ keepSelection, page: totalPages });
  }
  renderCases(data);
  state.reviewQueueStale = false;
  if (!keepSelection) {
    clearDetail({ showGallery: state.activePage === "review" });
  }
}
