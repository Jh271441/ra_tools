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
    item.thumbnail?.label || (thumbnailUrl ? "BEV 关键帧" : "暂无缩略图")
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
        <div class="issue-thumbnail-placeholder" aria-hidden="true"><span>RA</span><small>暂无 BEV 缩略图</small></div>
        ${thumbnailUrl ? `<img src="${escapeHtml(thumbnailUrl)}" alt="${escapeHtml(item.issue_id)} ${escapeHtml(thumbnailLabel)}" loading="lazy" decoding="async" data-case-thumbnail />` : ""}
        <span class="issue-thumbnail-label">${escapeHtml(thumbnailLabel)}</span>
        <button class="issue-media-preview" type="button" data-case-media-preview="${escapeHtml(item.issue_id)}" aria-label="预览 ${escapeHtml(item.issue_id)} 的 BEV、Camera 和视频">媒体预览</button>
        ${comparisonMeta ? `<span class="comparison-chip comparison-${comparisonStatus} issue-thumbnail-status">${escapeHtml(comparisonMeta.label)}</span>` : ""}
      </div>
      <div class="issue-card-body">
        <div class="issue-card-heading">
          <div class="issue-card-heading-main">
            ${issueUrl ? `<a class="issue-id" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" data-card-link title="打开 Voyager Issue">${escapeHtml(item.issue_id)}</a>` : `<span class="issue-id">${escapeHtml(item.issue_id)}</span>`}
            ${evidenceRow}
          </div>
          ${!mismatch ? labelBadge(annotation, "待 review") : ""}
        </div>
        ${title ? `<div class="issue-title">${escapeHtml(title)}</div>` : ""}
        <div class="issue-card-labels">
          <span class="issue-label-pair"><small>GT</small>${labelBadge(item.gt_label, "—")}</span>
          <span class="issue-label-pair"><small>模型</small>${displayPrediction ? labelBadge(displayPrediction, "—") : labelBadge("", "—")}</span>
          ${item.annotation?.author ? `<span class="issue-reviewer" title="复核人：${escapeHtml(item.annotation.author)}${item.annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}">复核 · ${escapeHtml(item.annotation.author)}${item.annotation.author_verified ? " · SSO" : ""}</span>` : ""}
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
  const pageSize = $("#casePageSize");
  const result = $("#galleryResultSummary");
  if (previous) previous.disabled = state.casePage <= 1 || !state.caseTotal;
  if (next) next.disabled = state.casePage >= totalPages || !state.caseTotal;
  if (summary) summary.textContent = state.caseTotal ? `${state.casePage} / ${totalPages}` : "0 / 0";
  if (pageSize) pageSize.value = String(state.casePageSize);
  if (result) {
    const start = state.caseTotal ? (state.casePage - 1) * state.casePageSize + 1 : 0;
    const end = Math.min(state.casePage * state.casePageSize, state.caseTotal);
    result.textContent = state.caseTotal
      ? `当前 ${start}–${end} / 共 ${state.caseTotal} 条`
      : "当前没有匹配的 Issue";
  }
}

function renderCaseNavigation() {
  const index = state.cases.findIndex((item) => item.issue_id === state.selectedId);
  const previous = $("#previousIssueButton");
  const next = $("#nextIssueButton");
  const position = $("#detailQueuePosition");
  const hasPrevious = index > 0 || (index === 0 && state.casePage > 1);
  const hasNext =
    index >= 0 &&
    (index < state.cases.length - 1 ||
      state.casePage * state.casePageSize < state.caseTotal);
  if (previous) previous.disabled = !hasPrevious;
  if (next) next.disabled = !hasNext;
  if (position) {
    position.textContent =
      index >= 0
        ? `${(state.casePage - 1) * state.casePageSize + index + 1} / ${state.caseTotal}`
        : "不在当前筛选页";
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
      ? `没有符合 ${comparisonMeta?.label || comparisonStatus} 的 Issue，可切换模型判断结果筛选。`
      : "没有匹配的 Issue。";
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
      if (label) label.textContent = "缩略图加载失败";
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
    predict.textContent = total ? `预测当前筛选 · ${total}` : "预测当前筛选";
    predict.title =
      total > limit
        ? `单批最多 ${limit} 个 Issue，请继续收窄筛选后再发起。`
        : `把当前 ${total} 个筛选结果带入 Batch 页面；不会立即运行或自动推送。`;
    predict.classList.toggle("button-limit-warning", total > limit);
  }
  updateWorkSplitAdminVisibility();
  const split = $("#splitFilteredButton");
  if (split && !split.hidden) {
    split.disabled = total === 0;
    split.textContent = total ? `均分任务 · ${total}` : "均分任务";
    split.title = total
      ? `管理员：把当前 ${total} 个筛选 Issue 写入任务负责人；可指定数量，剩余均分。`
      : "当前筛选没有 Issue。";
  }
  const summary = $("#galleryResultSummary");
  if (summary) {
    const assignee = $("#workAssigneeFilter")?.value || "";
    if (assignee && assignee !== "__none__") {
      summary.textContent = `任务负责人 ${assignee} · ${total} 个 Issue`;
    } else if (assignee === "__none__") {
      summary.textContent = total ? `未分配任务 · ${total} 个 Issue` : "没有未分配 Issue";
    } else if (state.reviewIssueIds?.length) {
      summary.textContent = `自定义 Issue 列表 · ${state.reviewIssueIds.length}`;
    } else {
      summary.textContent = total ? `当前筛选 ${total} 个 Issue` : "没有匹配的 Issue";
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
    showToast("当前没有可加入 Batch 的 Issue。", true);
    return;
  }
  const limit = predictionBatchLimit();
  if (ids.length > limit) {
    showToast(`当前筛选有 ${ids.length} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`, true);
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
    getMultiFilterValues($("#reviewerFilter"))
  );
  const workAssignee = joinFilterList(
    getMultiFilterValues($("#workAssigneeFilter"))
  );
  state.selectedRunId = $("#modelRunFilter").value;
  state.reviewComparisonStatus = selectedReviewComparisonStatus();
  state.failureOnly = state.reviewComparisonStatus === "mismatch";
  if (search) params.set("search", search);
  if (gtLabel) params.set("gt_label", gtLabel);
  if (modelLabel) params.set("model_label", modelLabel);
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
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
