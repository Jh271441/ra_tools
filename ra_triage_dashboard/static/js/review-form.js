/* ra_triage_dashboard/static/js/review-form.js
 * Review form, tags, evidence, save/delete
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function currentReviewRunId(caseData) {
  const selected = String(state.selectedRunId || "").trim();
  if (selected) return selected;
  // An empty selection means the legacy/unbound Review stream.  Do not
  // silently attach those records to whichever prediction happens to be
  // first in the case payload.
  return "";
}

function reviewAnnotationsForCurrentRun(caseData) {
  const runId = currentReviewRunId(caseData);
  const annotations = caseData?.annotations || [];
  const bound = annotations.filter(
    (annotation) => String(annotation.model_run_id || "").trim() === runId
  );
  if (runId && bound.length) return bound;
  // Existing pre-run-binding Reviews have no model_run_id.  Keep them
  // visible as a compatibility fallback until this Issue is first reviewed
  // in the selected Run; once a bound version exists, never mix the streams.
  return runId
    ? annotations.filter((annotation) => !String(annotation.model_run_id || "").trim())
    : bound;
}

// The edit form is scoped to the selected Run, while the Issue-level history
// is a complete append-only audit trail across every model Run.
function reviewAnnotationsForAllRuns(caseData) {
  return [...(caseData?.annotations || [])].sort(
    (left, right) => Number(right?.id || 0) - Number(left?.id || 0)
  );
}

function currentReviewAnnotation(caseData) {
  return reviewAnnotationsForCurrentRun(caseData)[0] || {};
}

const REVIEW_DRAFT_STORAGE_PREFIX = "ra-triage-review-draft:v1:";
const REVIEW_DRAFT_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
const REVIEW_DRAFT_FIELDS = [
  "label",
  "review_status",
  "is_excluded",
  "tags",
  "missing_evidence",
  "note",
  "author",
];

function reviewDraftStorageKey(issueId, runId = "") {
  return `${REVIEW_DRAFT_STORAGE_PREFIX}${encodeURIComponent(String(issueId || ""))}:${encodeURIComponent(String(runId || "legacy"))}`;
}

function readReviewDraft(issueId, runId = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return null;
  const key = reviewDraftStorageKey(issueId, runId);
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const draft = JSON.parse(raw);
    const savedAt = Number(draft?.saved_at || 0);
    if (draft?.version !== 1 || !savedAt || Date.now() - savedAt > REVIEW_DRAFT_MAX_AGE_MS) {
      window.localStorage.removeItem(key);
      return null;
    }
    return draft;
  } catch {
    return null;
  }
}

function clearReviewDraft(issueId, runId = "") {
  if (!issueId || typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.removeItem(reviewDraftStorageKey(issueId, runId));
  } catch {
    // Storage can be unavailable in private browsing; the Review itself still works.
  }
}

function annotationTimestamp(annotation) {
  const value = annotation?.updated_at || annotation?.created_at || "";
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function reviewDraftForCase(caseData) {
  const runId = currentReviewRunId(caseData);
  const draft = readReviewDraft(caseData?.issue_id, runId);
  if (!draft) return null;
  const serverAnnotation = reviewAnnotationsForCurrentRun(caseData)[0];
  if (serverAnnotation && Number(draft.saved_at) <= annotationTimestamp(serverAnnotation)) {
    clearReviewDraft(caseData.issue_id, runId);
    return null;
  }
  return draft;
}

function applyReviewDraft(annotation, draft) {
  if (!draft) return annotation || {};
  const next = { ...(annotation || {}), _review_draft: true };
  REVIEW_DRAFT_FIELDS.forEach((field) => {
    if (Object.prototype.hasOwnProperty.call(draft, field)) next[field] = draft[field];
  });
  return next;
}

function persistReviewDraft(caseData) {
  const form = $("#annotationForm");
  if (!caseData?.issue_id || !form || typeof window === "undefined" || !window.localStorage) return;
  const runId = state.reviewEditRunId || currentReviewRunId(caseData);
  const draft = {
    version: 1,
    issue_id: caseData.issue_id,
    model_run_id: runId,
    saved_at: Date.now(),
    label: state.selectedAnnotationLabel || "",
    review_status: $("#reviewStatusInput")?.value || "reviewed",
    is_excluded: Boolean($("#reviewExcludeInput")?.checked),
    tags: [...form.querySelectorAll('input[name="reviewTags"]:checked')].map((input) => input.value),
    missing_evidence: [...form.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote")?.value || "",
    author: $("#annotationAuthor")?.value || "",
  };
  try {
    window.localStorage.setItem(reviewDraftStorageKey(caseData.issue_id, runId), JSON.stringify(draft));
  } catch {
    // Draft persistence is best effort and must never block Review input.
  }
}

function bindReviewDraftLifecycle() {
  if (typeof window === "undefined" || window.__raTriageReviewDraftBound) return;
  window.__raTriageReviewDraftBound = true;
  window.addEventListener("beforeunload", () => {
    if (state.reviewFormDirty && state.selectedCase) persistReviewDraft(state.selectedCase);
  });
}

function currentReviewBaseAnnotationId(annotation, runId) {
  if (!annotation?.id) return null;
  const annotationRunId = String(annotation.model_run_id || "").trim();
  return annotationRunId === String(runId || "").trim()
    ? annotation.id
    : null;
}

function reviewRunLabel(runId) {
  const normalized = String(runId || "").trim();
  if (!normalized) return "未绑定 Model Run";
  const run = (state.modelRuns || []).find((item) => String(item.id) === normalized);
  return run?.name || normalized;
}

function renderDetail(caseData) {
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdMarkup = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  ensureDetailMediaState(caseData);
  const modelHistoryButton = `<button class="history-inline-button" type="button" data-open-history="model">评测 Run 历史 · ${(caseData.predictions || []).length} 条</button>`;
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title-group">
          <div class="detail-title"><h2><span class="ui-lang-zh">问题详情</span><span class="ui-lang-en">Issue Details</span></h2>${issueIdMarkup}<span id="detailExternalLinks" class="detail-external-links">${detailExternalLinksMarkup(caseData)}</span></div>
        </div>
        <div class="detail-navigation">
          <div class="case-detail-pager">
            <button class="button button-quiet" id="previousIssueButton" type="button">← 上一 Issue</button>
            <span id="detailQueuePosition">— / —</span>
            <button class="button button-quiet" id="nextIssueButton" type="button">下一 Issue →</button>
          </div>
        </div>
      </div>
      <div class="detail-context-row">
        <div class="comparison-summary" aria-label="GT 与当前模型对比">
          <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(caseData.gt_label, "缺失")}
          <b aria-hidden="true">→</b>
          <span class="comparison-side-label comparison-side-model">当前模型</span>${labelBadge(primary?.model_label, "未输出")}
          <strong class="${primary?.model_label && primary.model_label !== caseData.gt_label ? "comparison-fail" : "comparison-neutral"}">${primary?.model_label ? primary.model_label === caseData.gt_label ? "一致" : "不一致" : "不可比较"}</strong>
        </div>
        <button class="button button-quiet detail-back-button" id="backToGalleryButton" type="button">← 返回筛选结果</button>
        ${caseData.summary ? `<p class="detail-summary">${escapeHtml(caseData.summary)}</p>` : ""}
        <div class="detail-context-actions">
          ${detailMediaCommandMarkup(caseData)}
          <div class="detail-actions">
            <button class="button button-quiet" type="button" data-predict-current-case>API 推理</button>
            ${modelHistoryButton}
          </div>
        </div>
      </div>
      ${caseData.review_note ? `<details class="review-note-details"><summary>查看历史备注</summary><div class="review-note"><span>历史备注</span>${escapeHtml(caseData.review_note)}</div></details>` : ""}
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
  renderCaseNavigation();
  bindDetailMedia(caseData);
}

function annotationHistory(annotations) {
  if (!annotations?.length) {
    return '<div class="annotation-history"><p class="muted history-empty">尚无人工 review；保存后会保留旧版本。</p></div>';
  }
  return `<div class="annotation-history">${annotations
    .map(
      (annotation) => `<article class="history-row">
        <div class="history-head">
          ${labelBadge(annotation.label, annotation.review_status === "needs_gt_review" ? "GT 待复核" : "已记录")}
          ${annotation.is_excluded ? '<span class="tag exclusion-tag">已排除</span>' : ""}
          <span class="history-reviewer" title="${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO 已验证" : " · 未验证身份"}` : "复核人：历史记录未填写")}">${escapeHtml(annotation.author ? `复核人：${annotation.author}${annotation.author_verified ? " · SSO" : " · 未验证"}` : "复核人：未记录")}</span>
          <span class="history-run" title="Review 绑定的 Model Run">Run · ${escapeHtml(reviewRunLabel(annotation.model_run_id))}</span>
          <span class="history-actions"><span class="history-time">${formatTime(annotation.created_at)}</span><button class="history-delete-button" type="button" data-delete-annotation="${escapeHtml(annotation.id)}" title="删除这条 Review 版本" aria-label="删除 ${escapeHtml(formatTime(annotation.created_at))} 的 Review 版本"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 6h12M8 3h4l1 2H7zM6 6l.7 11h6.6L14 6M8.5 9v5m3-5v5"/></svg></button></span>
        </div>
        ${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map((key) => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
        ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map((tag) => `<span class="tag">${escapeHtml(tagLabel(tag))}</span>`).join("")}</div>` : ""}
        ${annotation.attachments?.length ? `<div class="history-attachments">${annotation.attachments.map((attachment, index) => `<a href="${escapeHtml(attachment.url)}" target="_blank" rel="noreferrer" title="打开补充截图 ${index + 1}"><img src="${escapeHtml(attachment.url)}" alt="补充截图 ${index + 1}" loading="lazy" /></a>`).join("")}</div>` : ""}
        ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}
      </article>`
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

function renderReviewTagGroups(tagCatalog, chosenTags, tagOption) {
  const definitions = [
    {
      section: "scene",
      label: "场景",
      groups: [
        { key: "environment", label: "环境" },
        { key: "self_intent", label: "自车意图" },
      ],
    },
    {
      section: "interaction_decision",
      label: "触发判定",
      groups: [
        { key: "false_trigger", label: "误触发" },
        { key: "true_trigger", label: "应该触发" },
      ],
    },
    {
      section: "egress",
      label: "如何驶离",
      groups: [
        { key: "ra", label: "正确触发" },
        { key: "no_assist", label: "无需协助" },
      ],
    },
  ];
  const visible = (tagCatalog || []).filter(
    (item) => item.visible !== false && !item.deleted
  );
  const selectedChipMarkup = (items, section) => items
    .map((item) => `<button class="tag-group-selected-chip" type="button" data-remove-review-tag="${escapeHtml(item.key)}" data-remove-review-tag-group="${escapeHtml(item.group || "")}" data-tag-section="${escapeHtml(section)}" data-tag-group="${escapeHtml(item.group || "")}" title="取消选择 ${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
    .join("");
  const sections = definitions.map((section) => {
    const sectionItems = visible
      .filter((item) => item.section === section.section && chosenTags.has(item.key))
      .map((item) => ({ ...item, group: item.group || "" }));
    return `
    <div class="review-tag-axis" data-tag-section="${escapeHtml(section.section)}">
      <div class="review-tag-axis-title">
        <span>${escapeHtml(section.label)}</span>
        <span class="review-axis-selected" data-selected-tags-section="${escapeHtml(section.section)}"${sectionItems.length ? "" : " hidden"}>${selectedChipMarkup(sectionItems, section.section)}</span>
      </div>
      <div class="review-tag-groups">
        ${section.groups.map((group) => {
          const items = visible.filter(
            (item) => item.section === section.section && item.group === group.key
          );
          const selectedCount = items.filter((item) => chosenTags.has(item.key)).length;
          // All six managed axes (场景 / 触发判定 / 如何驶离) can extend the shared catalog.
          const creatorAction = `<button class="tag-catalog-add-button" type="button" data-open-review-tag-creator="${escapeHtml(group.key)}" data-tag-create-group-label="${escapeHtml(group.label)}" aria-label="新增${escapeHtml(group.label)}标签" title="新增${escapeHtml(group.label)}标签">＋</button>`;
          return `<details class="review-tag-dropdown review-dropdown" data-tag-dropdown-group="${escapeHtml(group.key)}">
            <summary>
              <span class="tag-group-label">${escapeHtml(group.label)}</span>
              <span class="tag-group-trailing">
                ${creatorAction}
                <span class="tag-group-summary" data-tag-summary="${escapeHtml(group.key)}">${selectedCount} 项</span>
                <span class="tag-group-chevron" aria-hidden="true"></span>
              </span>
            </summary>
            <div class="review-tag-options">${items.map((item) => tagOption(item.key, item.label, chosenTags.has(item.key), group.key, item)).join("") || '<div class="review-tag-empty">暂无标签，点 ＋ 添加</div>'}</div>
          </details>`;
        }).join("")}
      </div>
    </div>`;
  }).join("");
  const legacy = (tagCatalog || []).filter(
    (item) => (item.visible === false || item.deleted) && chosenTags.has(item.key)
  );
  if (legacy.length) {
    return `${sections}
      <div class="review-tag-legacy"><span>历史标签</span><div class="review-tag-options">${legacy.map((item) => tagOption(item.key, item.label, true)).join("")}</div></div>`;
  }
  return sections;
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
  const chosenTags = new Set(previous.tags || []);
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
  const status = $("#reviewStatusInput");
  if (status) {
    status.value = previous.review_status === "needs_gt_review"
      ? "needs_gt_review"
      : previous.review_status === "pending"
        ? "pending"
        : "reviewed";
  }
  const note = $("#annotationNote");
  if (note) note.value = previous.note || "";
  const author = $("#annotationAuthor");
  if (author && !(state.session.verified && state.session.username)) {
    author.value = state.session.username || previous.author || "";
  }
  state.selectedAnnotationLabel = previous.label || "";
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

function renderReview(caseData) {
  const reviewRunId = currentReviewRunId(caseData);
  const runAnnotations = reviewAnnotationsForCurrentRun(caseData);
  const allAnnotations = reviewAnnotationsForAllRuns(caseData);
  const serverPrevious = runAnnotations[0] || {};
  const draft = reviewDraftForCase(caseData);
  const previous = applyReviewDraft(serverPrevious, draft);
  state.reviewEditRunId = reviewRunId;
  state.reviewEditBaseAnnotationId = currentReviewBaseAnnotationId(
    previous,
    reviewRunId
  );
  state.reviewFormDirty = false;
  state.deferredDetailRefresh = false;
  state.selectedAnnotationLabel = previous.label || "";
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
  const chosenTags = new Set(previous.tags || []);
  const tagCatalogKeys = new Set(tagCatalog.map((item) => item.key));
  const customTagKeys = [...chosenTags].filter((tag) => !tagCatalogKeys.has(tag));
  const author = state.session.username || previous.author || "";
  const authorLocked = Boolean(state.session.verified && state.session.username);
  const reviewStatus = previous.review_status === "needs_gt_review"
    ? "needs_gt_review"
    : previous.review_status === "pending"
      ? "pending"
      : "reviewed";
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
  $("#reviewPane").innerHTML = `
    <form class="review-form" id="annotationForm">
      <section class="review-section issue-tag-section">
        <div class="review-section-heading"><div><h2><span class="ui-lang-zh">Issue 标签</span><span class="ui-lang-en">Issue tags</span></h2></div><span class="evidence-summary-count" id="tagSummaryCount">已选 ${chosenTags.size} 项</span></div>
        <div class="review-tag-groups-shell">${issueTagGroups}${customTagOptions ? `<div class="review-tag-legacy"><span>历史标签</span><div class="review-tag-options">${customTagOptions}</div></div>` : ""}</div>
        <label class="review-exclude-toggle"><input id="reviewExcludeInput" type="checkbox" ${previous.is_excluded ? "checked" : ""} /><span><strong>应该排除</strong><small>不是模型需要解决的场景 case</small></span></label>
      </section>
      <section class="review-section model-error-section">
        <div class="review-section-heading">
          <div>
            <h2>
              <span class="ui-lang-zh">模型结果 Review</span>
              <span class="ui-lang-en">Model Result Review</span>
            </h2>
          </div>
          <button class="history-inline-button" type="button" data-open-history="review" id="reviewHistoryLaunchButton">
            <span class="ui-lang-zh">Review 历史 · ${allAnnotations.length} 条</span>
            <span class="ui-lang-en">Review history · ${allAnnotations.length}</span>
          </button>
        </div>
        <label class="review-status-field"><span><span class="ui-lang-zh">复核状态</span><span class="ui-lang-en">Review status</span></span><select id="reviewStatusInput"><option value="reviewed" ${reviewStatus === "reviewed" ? "selected" : ""}>已 Review</option><option value="pending" ${reviewStatus === "pending" ? "selected" : ""}>待补充</option><option value="needs_gt_review" ${reviewStatus === "needs_gt_review" ? "selected" : ""}>GT 需复核</option></select></label>
        <label class="review-reason">
          <span><span class="ui-lang-zh">模型为什么判错？</span><span class="ui-lang-en">Why was the model wrong?</span></span>
          <textarea id="annotationNote" rows="2" placeholder="简要说明模型漏掉的关键证据，例如 routing、绕行空间或时序。">${escapeHtml(previous.note || "")}</textarea>
        </label>
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
          <div class="screenshot-paste-zone is-compact" id="screenshotPasteZone" tabindex="0" role="group" aria-label="粘贴补充截图">
            <span class="screenshot-paste-copy">
              <strong><span class="ui-lang-zh">补充截图</span><span class="ui-lang-en">Screenshots</span></strong>
              <small><span class="ui-lang-zh">粘贴 Ctrl/⌘+V · 最多 4 张</span><span class="ui-lang-en">Paste Ctrl/⌘+V · max 4</span></small>
            </span>
            <button class="screenshot-browse-button" id="reviewScreenshotBrowse" type="button"><span class="ui-lang-zh">选择图片</span><span class="ui-lang-en">Browse</span></button>
          </div>
          <input class="hidden" id="reviewScreenshotInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
          <div class="pending-screenshot-list" id="pendingScreenshotList"></div>
        </div>
      </section>
      <label><span><span class="ui-lang-zh">复核人${authorLocked ? "（SSO）" : "（必填）"}</span><span class="ui-lang-en">Reviewer${authorLocked ? " (SSO)" : " (required)"}</span></span><input id="annotationAuthor" value="${escapeHtml(author)}" placeholder="姓名或工号" autocomplete="off" required ${authorLocked ? "readonly" : ""} /></label>
      <button class="button button-primary full-width" type="submit"><span class="ui-lang-zh">保存新的 review 版本</span><span class="ui-lang-en">Save new review version</span></button>
    </form>`;
  bindSelectedReviewTagControls($("#reviewPane"));
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
  $("#reviewPane").querySelectorAll(".review-dropdown").forEach((dropdown) => {
    dropdown.addEventListener("toggle", () => {
      if (!dropdown.open) return;
      $("#reviewPane").querySelectorAll(".review-dropdown").forEach((other) => {
        if (other !== dropdown) other.open = false;
      });
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
    pasteZone.addEventListener("click", (event) => {
      event.preventDefault();
      openScreenshotPicker();
    });
    pasteZone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openScreenshotPicker();
      }
    });
    pasteZone.addEventListener("paste", (event) => {
      const files = [...(event.clipboardData?.items || [])]
        .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (files.length) {
        event.preventDefault();
        addPendingReviewImages(files);
      }
    });
    screenshotInput.addEventListener("change", () => {
      addPendingReviewImages([...screenshotInput.files]);
      screenshotInput.value = "";
    });
  }
  renderPendingReviewImages();
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

function updateEvidenceSummary() {
  const root = $("#reviewPane") || document;
  const selected = [...root.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => ({
    key: input.value,
    label: input.parentElement?.querySelector("span")?.textContent?.trim() || evidenceLabel(input.value),
  }));
  const count = selected.length;
  const target = $("#evidenceSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
  const selectedContainer = root.querySelector("[data-selected-missing-evidence]");
  if (!selectedContainer) return;
  selectedContainer.innerHTML = selected
    .map((item) => `<button class="tag-group-selected-chip missing-evidence-selected-chip" type="button" data-remove-review-evidence="${escapeHtml(item.key)}" title="取消选择 ${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
    .join("");
  selectedContainer.hidden = selected.length === 0;
}

function setMissingEvidenceCatalogFromResult(result) {
  if (!result || !Array.isArray(result.missing_evidence_catalog)) return;
  state.config = {
    ...(state.config || {}),
    missing_evidence_catalog: result.missing_evidence_catalog,
  };
  acknowledgeLocalChange(result);
  renderConfig();
}

function missingEvidenceCatalogItem(key) {
  return (state.config?.missing_evidence_catalog || []).find(
    (item) => String(item.key) === String(key)
  );
}

function updateMissingEvidenceOptionRow(item) {
  const row = [...document.querySelectorAll("[data-evidence-option]")].find(
    (node) => node.dataset.evidenceOption === String(item?.key || "")
  );
  if (!row) return;
  const label = row.querySelector(".tag-option-check span, span");
  const shell = row.querySelector(".tag-option") || row;
  if (label) label.textContent = String(item?.label || evidenceLabel(item?.key));
  if (shell) {
    if (item?.hint) shell.title = String(item.hint);
    else shell.removeAttribute("title");
  }
}

function markDeletedMissingEvidenceOption(item) {
  const row = [...document.querySelectorAll("[data-evidence-option]")].find(
    (node) => node.dataset.evidenceOption === String(item?.key || "")
  );
  if (!row) return;
  const checkbox = row.querySelector('input[name="missingEvidence"]');
  if (checkbox?.checked) {
    row.classList.add("tag-option-deleted", "evidence-option-deleted");
    row.querySelector(".tag-option")?.classList.add("tag-option-deleted");
    row.querySelector(".tag-option-menu")?.remove();
    const shell = row.querySelector(".tag-option") || row;
    shell.title = "已从共享目录删除；当前 Review 仍保留此历史值";
  } else {
    row.remove();
  }
  updateEvidenceSummary();
}

function openMissingEvidenceEditorDialog({
  mode = "create",
  key = "",
  label = "",
  hint = "",
} = {}) {
  const dialog = $("#missingEvidenceCreateDialog");
  const form = $("#missingEvidenceCreateForm");
  const modeInput = $("#missingEvidenceCreateMode");
  const keyInput = $("#missingEvidenceCreateKey");
  const labelInput = $("#missingEvidenceCreateLabel");
  const hintInput = $("#missingEvidenceCreateHint");
  const title = $("#missingEvidenceCreateDialogTitle");
  const copy = $("#missingEvidenceCreateDialogHint");
  const submit = $("#missingEvidenceCreateSubmit");
  if (!dialog || !form || !labelInput) return;
  const resolvedMode = mode === "edit" ? "edit" : "create";
  if (modeInput) modeInput.value = resolvedMode;
  if (keyInput) keyInput.value = resolvedMode === "edit" ? String(key || "") : "";
  labelInput.value = resolvedMode === "edit" ? String(label || "") : "";
  if (hintInput) hintInput.value = resolvedMode === "edit" ? String(hint || "") : "";
  if (title) title.textContent = resolvedMode === "edit" ? "编辑缺失信息" : "新增缺失信息";
  if (copy) {
    copy.textContent =
      resolvedMode === "edit"
        ? "修改共享目录条目；历史 Review 中的 key 不变。"
        : "写入共享目录后，所有用户与 Issue 均可使用。";
  }
  if (submit) submit.textContent = resolvedMode === "edit" ? "保存修改" : "添加条目";
  openDialog("missingEvidenceCreateDialog");
  window.requestAnimationFrame(() => {
    labelInput.focus();
    if (resolvedMode === "edit") labelInput.select();
  });
}

function appendMissingEvidenceOption(item) {
  const key = String(item?.key || "");
  if (!key) return;
  const list = $("#missingEvidenceOptions");
  if (!list) return;
  if (
    [...document.querySelectorAll('input[name="missingEvidence"]')].some(
      (node) => node.value === key
    )
  ) {
    return;
  }
  list.querySelector(".review-tag-empty")?.remove();
  const template = document.createElement("template");
  template.innerHTML = missingEvidenceOptionMarkup(
    {
      ...item,
      label: item.label || evidenceLabel(key),
      hint: item.hint || "",
      builtin: false,
    },
    true,
    true
  );
  const option = template.content.firstElementChild;
  list.appendChild(option);
  option?.querySelector("input")?.addEventListener("change", updateEvidenceSummary);
  bindMissingEvidenceCatalogControls(option || list);
  bindReviewTagCatalogControls(option || list);
}

function bindMissingEvidenceCatalogControls(root = document) {
  root.querySelectorAll("[data-open-missing-evidence-creator]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openMissingEvidenceEditorDialog({ mode: "create" });
    });
  });
  // Dialog form lives outside the review pane; bind once from document.
  const createForm = $("#missingEvidenceCreateForm");
  if (createForm && createForm.dataset.missingEvidenceBound !== "1") {
    createForm.dataset.missingEvidenceBound = "1";
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const mode = String($("#missingEvidenceCreateMode")?.value || "create");
      const key = String($("#missingEvidenceCreateKey")?.value || "").trim();
      const value = String($("#missingEvidenceCreateLabel")?.value || "").trim();
      const hint = String($("#missingEvidenceCreateHint")?.value || "").trim();
      const submit = $("#missingEvidenceCreateSubmit");
      if (!value) return showToast("请输入缺失信息标题。", true);
      if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) {
        return showToast("缺失信息标题长度或字符不合法。", true);
      }
      if (hint.length > 160 || /[\x00-\x1f\x7f]/.test(hint)) {
        return showToast("缺失信息说明长度或字符不合法。", true);
      }
      if (mode === "edit" && !key) {
        return showToast("缺少要编辑的缺失信息。", true);
      }
      if (submit) {
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
      }
      try {
        if (mode === "edit") {
          const result = await api(`/api/missing-evidence/${encodeURIComponent(key)}`, {
            method: "PUT",
            body: JSON.stringify({ label: value, hint }),
          });
          setMissingEvidenceCatalogFromResult(result);
          updateMissingEvidenceOptionRow(result.item || { key, label: value, hint });
          closeDialog("missingEvidenceCreateDialog");
          showToast("缺失信息已更新。");
        } else {
          const result = await api("/api/missing-evidence", {
            method: "POST",
            body: JSON.stringify({ label: value, hint }),
          });
          setMissingEvidenceCatalogFromResult(result);
          appendMissingEvidenceOption(result.item || {});
          state.reviewFormDirty = true;
          updateEvidenceSummary();
          closeDialog("missingEvidenceCreateDialog");
          showToast("已加入共享目录，所有用户和 Issue 均可使用。");
        }
      } catch (error) {
        showToast(error.message, true);
      } finally {
        if (submit) {
          submit.disabled = false;
          submit.removeAttribute("aria-busy");
        }
      }
    });
  }
  root.querySelectorAll("[data-edit-missing-evidence]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.editMissingEvidence || "");
      const item = missingEvidenceCatalogItem(key);
      if (!item || item.deleted) return;
      openMissingEvidenceEditorDialog({
        mode: "edit",
        key,
        label: item.label || "",
        hint: item.hint || "",
      });
    });
  });
  root.querySelectorAll("[data-delete-missing-evidence]").forEach((button) => {
    if (button.dataset.missingEvidenceBound === "1") return;
    button.dataset.missingEvidenceBound = "1";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.deleteMissingEvidence || "");
      const item = missingEvidenceCatalogItem(key);
      if (!item || item.deleted) return;
      if (!window.confirm(`确认删除“${item.label}”？\n历史 Review 仍会保留该标签。`)) return;
      button.disabled = true;
      try {
        const result = await api(`/api/missing-evidence/${encodeURIComponent(key)}`, {
          method: "DELETE",
          body: JSON.stringify({}),
        });
        setMissingEvidenceCatalogFromResult(result);
        markDeletedMissingEvidenceOption(result.item || { key });
        showToast("缺失信息已删除。");
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function updateTagSummary() {
  const inputs = [...document.querySelectorAll('input[name="reviewTags"]')];
  const count = inputs.filter((input) => input.checked).length;
  const target = $("#tagSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
  document.querySelectorAll("[data-tag-summary]").forEach((summary) => {
    const group = summary.dataset.tagSummary || "";
    const groupCount = inputs.filter(
      (input) => input.checked && input.dataset.tagGroup === group
    ).length;
    summary.textContent = `${groupCount} 项`;
  });
  document.querySelectorAll("[data-selected-tags-section]").forEach((container) => {
    const root = container.closest(".review-tag-axis");
    if (!root) return;
    const section = container.dataset.selectedTagsSection || "";
    const selected = [...root.querySelectorAll('input[name="reviewTags"]')]
      .filter((input) => input.checked)
      .map((input) => ({
        key: input.value,
        label: input.parentElement?.querySelector("span")?.textContent?.trim() || input.value,
        group: input.dataset.tagGroup || "",
      }));
    container.innerHTML = selected
      .map((item) => `<button class="tag-group-selected-chip" type="button" data-remove-review-tag="${escapeHtml(item.key)}" data-remove-review-tag-group="${escapeHtml(item.group)}" data-tag-section="${escapeHtml(section)}" data-tag-group="${escapeHtml(item.group)}" title="取消选择 ${escapeHtml(item.label)}"><span>${escapeHtml(item.label)}</span><b aria-hidden="true">×</b></button>`)
      .join("");
    container.hidden = selected.length === 0;
  });
}

function bindSelectedReviewTagControls(root) {
  if (!root || root.dataset.selectedReviewTagControlsBound === "1") return;
  root.dataset.selectedReviewTagControlsBound = "1";
  root.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-review-tag], [data-remove-review-evidence]");
    if (!button || !root.contains(button)) return;
    event.preventDefault();
    event.stopPropagation();
    const isEvidence = button.hasAttribute("data-remove-review-evidence");
    const key = isEvidence
      ? button.dataset.removeReviewEvidence || ""
      : button.dataset.removeReviewTag || "";
    const input = root.querySelector(
      `${isEvidence ? 'input[name="missingEvidence"]' : 'input[name="reviewTags"]'}[value="${CSS.escape(key)}"]`
    );
    if (!input) return;
    input.checked = false;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function setReviewTagCatalogFromResult(result) {
  if (!result || !Array.isArray(result.review_tag_catalog)) return;
  state.config = {
    ...(state.config || {}),
    review_tag_catalog: result.review_tag_catalog,
  };
  acknowledgeLocalChange(result);
  renderConfig();
}

function reviewTagCatalogOptionRow(key) {
  return [...document.querySelectorAll("[data-review-tag-option]")].find(
    (node) => node.dataset.reviewTagOption === String(key || "")
  );
}

function updateReviewTagOptionRow(item) {
  const row = reviewTagCatalogOptionRow(item?.key);
  if (!row) return;
  const option = row.querySelector(".tag-option");
  const label = option?.querySelector(".tag-option-check span, span");
  if (label) label.textContent = String(item?.label || tagLabel(item?.key));
  if (option) {
    if (item?.hint) option.title = String(item.hint);
    else option.removeAttribute("title");
  }
}

function markDeletedReviewTagOption(item) {
  const row = reviewTagCatalogOptionRow(item?.key);
  if (!row) return;
  const checkbox = row.querySelector('input[name="reviewTags"]');
  if (checkbox?.checked) {
    row.classList.add("tag-option-deleted");
    row.querySelector(".tag-option")?.classList.add("tag-option-deleted");
    row.querySelector(".tag-option-menu")?.remove();
  } else {
    row.remove();
  }
  updateTagSummary();
}

function reviewTagGroupLabel(group = "environment") {
  const key = String(group || "environment");
  if (key === "environment") return "环境";
  if (key === "self_intent") return "自车意图";
  if (key === "false_trigger") return "误触发";
  if (key === "true_trigger") return "应该触发";
  if (key === "ra") return "正确触发";
  if (key === "no_assist") return "无需协助";
  return key;
}

// Keep the historical name for any remaining callers.
function sceneTagGroupLabel(group = "environment") {
  return reviewTagGroupLabel(group);
}

function openReviewTagEditorDialog({
  mode = "create",
  group = "environment",
  groupLabel = "",
  key = "",
  label = "",
  hint = "",
} = {}) {
  const dialog = $("#reviewTagCreateDialog");
  const form = $("#reviewTagCreateForm");
  const modeInput = $("#reviewTagCreateMode");
  const keyInput = $("#reviewTagCreateKey");
  const groupInput = $("#reviewTagCreateGroup");
  const labelInput = $("#reviewTagCreateLabel");
  const hintInput = $("#reviewTagCreateHint");
  const title = $("#reviewTagCreateDialogTitle");
  const copy = $("#reviewTagCreateDialogHint");
  const submit = $("#reviewTagCreateSubmit");
  if (!dialog || !form || !groupInput || !labelInput) return;
  const resolvedMode = mode === "edit" ? "edit" : "create";
  const resolvedGroup = String(group || "environment");
  const resolvedLabel = String(groupLabel || reviewTagGroupLabel(resolvedGroup));
  if (modeInput) modeInput.value = resolvedMode;
  if (keyInput) keyInput.value = resolvedMode === "edit" ? String(key || "") : "";
  groupInput.value = resolvedGroup;
  labelInput.value = resolvedMode === "edit" ? String(label || "") : "";
  if (hintInput) hintInput.value = resolvedMode === "edit" ? String(hint || "") : "";
  if (title) {
    title.textContent = resolvedMode === "edit"
      ? `编辑${resolvedLabel}标签`
      : `新增${resolvedLabel}标签`;
  }
  if (copy) {
    copy.textContent = resolvedMode === "edit"
      ? `修改「${resolvedLabel}」共享目录中的标签；历史 Review 中的 key 不变。`
      : `添加到「${resolvedLabel}」共享目录；所有用户与 Issue 均可使用。`;
  }
  if (submit) submit.textContent = resolvedMode === "edit" ? "保存修改" : "添加标签";
  openDialog("reviewTagCreateDialog");
  window.requestAnimationFrame(() => {
    labelInput.focus();
    if (resolvedMode === "edit") labelInput.select();
  });
}

function openReviewTagCreateDialog(group = "environment", groupLabel = "") {
  openReviewTagEditorDialog({ mode: "create", group, groupLabel });
}

function appendReviewTagOptionToGroup(item, group) {
  const key = String(item?.key || "");
  if (!key || reviewTagCatalogOptionRow(key)) return;
  const groupKey = String(group || "").replace(/["\\]/g, "");
  const list = document.querySelector(
    `.review-tag-dropdown[data-tag-dropdown-group="${groupKey}"] .review-tag-options`
  );
  if (!list) return;
  list.querySelector(".review-tag-empty")?.remove();
  const template = document.createElement("template");
  template.innerHTML = reviewTagOptionMarkup(item, true, group, true);
  const option = template.content.firstElementChild;
  list.appendChild(option);
  option?.querySelector('input[name="reviewTags"]')?.addEventListener("change", updateTagSummary);
  bindReviewTagCatalogControls(option || list);
}

function closeAllTagOptionMenus(except = null) {
  document.querySelectorAll(".tag-option-menu.is-open").forEach((menu) => {
    if (except && menu === except) return;
    menu.classList.remove("is-open");
    const toggle = menu.querySelector("[data-tag-menu-toggle]");
    const panel = menu.querySelector(".tag-option-menu-panel");
    if (toggle) toggle.setAttribute("aria-expanded", "false");
    if (panel) panel.hidden = true;
  });
}

function closeAllReviewDropdowns(except = null) {
  document.querySelectorAll(".review-dropdown[open]").forEach((dropdown) => {
    if (except && dropdown === except) return;
    dropdown.open = false;
  });
}

function bindReviewDropdownDismiss() {
  if (document.documentElement.dataset.reviewDropdownDismissBound === "1") return;
  document.documentElement.dataset.reviewDropdownDismissBound = "1";
  document.addEventListener(
    "click",
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const current = target?.closest(".review-dropdown") || null;
      closeAllReviewDropdowns(current);
    },
    true
  );
  document.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Escape") closeAllReviewDropdowns();
    },
    true
  );
}

function bindReviewTagCatalogControls(root = document) {
  root.querySelectorAll("[data-open-review-tag-creator]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openReviewTagCreateDialog(
        button.dataset.openReviewTagCreator || "environment",
        button.dataset.tagCreateGroupLabel || ""
      );
    });
  });
  root.querySelectorAll("[data-tag-menu-toggle]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const menu = button.closest(".tag-option-menu");
      const panel = menu?.querySelector(".tag-option-menu-panel");
      if (!menu || !panel) return;
      const willOpen = panel.hidden;
      closeAllTagOptionMenus(willOpen ? menu : null);
      panel.hidden = !willOpen;
      menu.classList.toggle("is-open", willOpen);
      button.setAttribute("aria-expanded", willOpen ? "true" : "false");
    });
  });
  if (!document.documentElement.dataset.tagMenuDismissBound) {
    document.documentElement.dataset.tagMenuDismissBound = "1";
    document.addEventListener(
      "click",
      (event) => {
        if (event.target.closest(".tag-option-menu")) return;
        closeAllTagOptionMenus();
      },
      true
    );
    document.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Escape") closeAllTagOptionMenus();
      },
      true
    );
  }
  // Dialog lives outside the review pane; bind once from document.
  const createForm = $("#reviewTagCreateForm");
  if (createForm && createForm.dataset.reviewTagBound !== "1") {
    createForm.dataset.reviewTagBound = "1";
    createForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const mode = String($("#reviewTagCreateMode")?.value || "create");
      const key = String($("#reviewTagCreateKey")?.value || "").trim();
      const group = String($("#reviewTagCreateGroup")?.value || "environment");
      const value = String($("#reviewTagCreateLabel")?.value || "").trim();
      const hint = String($("#reviewTagCreateHint")?.value || "").trim();
      const submit = $("#reviewTagCreateSubmit");
      if (!value) return showToast("请输入场景标签标题。", true);
      if (value.length > 48 || /[\x00-\x1f\x7f]/.test(value)) {
        return showToast("场景标签标题长度或字符不合法。", true);
      }
      if (hint.length > 160 || /[\x00-\x1f\x7f]/.test(hint)) {
        return showToast("场景标签说明长度或字符不合法。", true);
      }
      if (mode === "edit" && !key) {
        return showToast("缺少要编辑的场景标签。", true);
      }
      if (submit) {
        submit.disabled = true;
        submit.setAttribute("aria-busy", "true");
      }
      try {
        if (mode === "edit") {
          const result = await api(`/api/review-tags/${encodeURIComponent(key)}`, {
            method: "PUT",
            body: JSON.stringify({ label: value, hint, group }),
          });
          setReviewTagCatalogFromResult(result);
          updateReviewTagOptionRow(result.item || { key, label: value, hint });
          closeDialog("reviewTagCreateDialog");
          showToast("场景标签已更新。");
        } else {
          const result = await api("/api/review-tags", {
            method: "POST",
            body: JSON.stringify({ label: value, hint, group }),
          });
          setReviewTagCatalogFromResult(result);
          const item = result.item || {};
          appendReviewTagOptionToGroup(item, group);
          state.reviewFormDirty = true;
          updateTagSummary();
          closeDialog("reviewTagCreateDialog");
          showToast("场景标签已加入共享目录，所有用户和 Issue 均可使用。");
        }
      } catch (error) {
        showToast(error.message, true);
      } finally {
        if (submit) {
          submit.disabled = false;
          submit.removeAttribute("aria-busy");
        }
      }
    });
  }
  root.querySelectorAll("[data-edit-review-tag]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.editReviewTag || "");
      const item = reviewTagCatalogItem(key);
      if (!item || item.deleted) return;
      openReviewTagEditorDialog({
        mode: "edit",
        group: item.group || "environment",
        groupLabel: reviewTagGroupLabel(item.group || "environment"),
        key,
        label: item.label || "",
        hint: item.hint || "",
      });
    });
  });
  root.querySelectorAll("[data-delete-review-tag]").forEach((button) => {
    if (button.dataset.reviewTagBound === "1") return;
    button.dataset.reviewTagBound = "1";
    button.addEventListener("click", async (event) => {
      event.preventDefault();
      event.stopPropagation();
      closeAllTagOptionMenus();
      const key = String(button.dataset.deleteReviewTag || "");
      const item = reviewTagCatalogItem(key);
      if (!item || item.deleted) return;
      if (!window.confirm(`确认删除“${item.label}”？\n历史 Review 仍会保留该标签。`)) return;
      button.disabled = true;
      try {
        const result = await api(`/api/review-tags/${encodeURIComponent(key)}`, {
          method: "DELETE",
          body: JSON.stringify({}),
        });
        setReviewTagCatalogFromResult(result);
        markDeletedReviewTagOption(result.item || { key });
        showToast("场景标签已删除。 ");
      } catch (error) {
        showToast(error.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
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
          <p>正在读取 Issue 媒体与模型输出。</p>
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
    const data = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    scheduleTrailDetailMetadata(issueId, requestSeq);
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

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId || state.savingAnnotation) return;
  state.savingAnnotation = true;
  const submitButton = event.submitter || $("#annotationForm button[type='submit']");
  if (submitButton) {
    submitButton.disabled = true;
    submitButton.setAttribute("aria-busy", "true");
  }
  const payload = {
    model_run_id: state.reviewEditRunId || currentReviewRunId(state.selectedCase),
    expected_previous_annotation_id: state.reviewEditBaseAnnotationId || null,
    label: state.selectedAnnotationLabel,
    review_status: $("#reviewStatusInput").value,
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
    showToast(
      `已保存新的 review 版本${screenshotCount ? `和 ${screenshotCount} 张截图` : ""}。`
    );
    refreshReviewDerivedData();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    state.savingAnnotation = false;
    if (submitButton?.isConnected) {
      submitButton.disabled = false;
      submitButton.removeAttribute("aria-busy");
    }
  }
}
