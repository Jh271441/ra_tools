/* ra_triage_dashboard/static/js/review-form.js
 * Review detail shell, status picker, screenshots, selectCase/save
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */

const REVIEW_STATUS_OPTIONS = [
  { value: "reviewed", labelKey: "status.reviewed", labelZh: "已 Review", labelEn: "Reviewed" },
  { value: "pending", labelKey: "status.pending", labelZh: "待补充", labelEn: "Pending" },
  { value: "needs_gt_review", labelKey: "status.needs_gt", labelZh: "GT 需复核", labelEn: "Needs GT review" },
];

function renderDetail(caseData) {
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdMarkup = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  ensureDetailMediaState(caseData);
  const predCount = (caseData.predictions || []).length;
  const modelHistoryButton = `<button class="history-inline-button" type="button" data-open-history="model"><span class="ui-lang-zh">评测 Run 历史 · ${predCount} 条</span><span class="ui-lang-en">Run history · ${predCount}</span></button>`;
  const compareText = !primary?.model_label
    ? `<span class="ui-lang-zh">不可比较</span><span class="ui-lang-en">N/A</span>`
    : primary.model_label === caseData.gt_label
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
            <button class="button button-quiet" id="previousIssueButton" type="button"><span class="ui-lang-zh">← 上一 Issue</span><span class="ui-lang-en">← Prev</span></button>
            <span class="detail-queue-position" id="detailQueuePosition" title="${escapeHtml(uiText("输入序号后回车跳转", "Enter index and press Return to jump"))}">
              <input class="detail-queue-index-input" id="detailQueueIndexInput" type="number" min="1" step="1" inputmode="numeric" aria-label="${escapeHtml(uiText("跳转到筛选队列中的第几条", "Jump to queue index"))}" disabled />
              <span class="detail-queue-total" id="detailQueueTotal">/ —</span>
            </span>
            <button class="button button-quiet" id="nextIssueButton" type="button"><span class="ui-lang-zh">下一 Issue →</span><span class="ui-lang-en">Next →</span></button>
          </div>
        </div>
      </div>
      <div class="detail-context-row">
        <div class="comparison-summary" aria-label="${escapeHtml(uiText("GT 与当前模型对比", "GT vs current model"))}">
          <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(caseData.gt_label, uiText("缺失", "Missing"))}
          <b aria-hidden="true">→</b>
          <span class="comparison-side-label comparison-side-model"><span class="ui-lang-zh">当前模型</span><span class="ui-lang-en">Model</span></span>${labelBadge(primary?.model_label, uiText("未输出", "None"))}
          <strong class="${primary?.model_label && primary.model_label !== caseData.gt_label ? "comparison-fail" : "comparison-neutral"}">${compareText}</strong>
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
  const statusValue =
    previous.review_status === "needs_gt_review"
      ? "needs_gt_review"
      : previous.review_status === "pending"
        ? "pending"
        : "reviewed";
  setReviewStatusValue(statusValue);
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
        <div class="review-section-heading"><div><h2><span class="ui-lang-zh">Issue 标签</span><span class="ui-lang-en">Issue tags</span></h2></div><span class="evidence-summary-count" id="tagSummaryCount">${escapeHtml(t("detail.selected_n", { n: chosenTags.size }))}</span></div>
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
          <button class="history-inline-button" type="button" data-open-history="review" id="reviewHistoryLaunchButton">
            <span class="ui-lang-zh">Review 历史 · ${allAnnotations.length} 条</span>
            <span class="ui-lang-en">Review history · ${allAnnotations.length}</span>
          </button>
        </div>
        <label class="review-status-field">
          <span><span class="ui-lang-zh">复核状态</span><span class="ui-lang-en">Review status</span></span>
          <div class="ui-select review-status-picker" id="reviewStatusPicker">
            <button class="ui-select-trigger review-status-picker-trigger" id="reviewStatusPickerTrigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="reviewStatusPickerPanel" aria-label="复核状态">
              <span class="ui-select-summary" id="reviewStatusPickerSummary">${escapeHtml(reviewStatusDisplayLabel(reviewStatus))}</span>
              <span class="ui-select-caret review-status-picker-caret" aria-hidden="true"></span>
            </button>
            <div class="ui-select-panel review-status-picker-panel" id="reviewStatusPickerPanel" role="listbox" hidden></div>
            <select id="reviewStatusInput" class="ui-select-native gateway-model-native-select" aria-hidden="true" tabindex="-1">
              ${REVIEW_STATUS_OPTIONS.map((item) => `<option value="${escapeHtml(item.value)}" ${item.value === reviewStatus ? "selected" : ""}>${escapeHtml(item.labelZh)}</option>`).join("")}
            </select>
          </div>
        </label>
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
      <button class="button button-primary full-width" type="submit"><span class="ui-lang-zh">保存新的 review 版本</span><span class="ui-lang-en">Save new review version</span></button>
    </form>`;
  bindSelectedReviewTagControls($("#reviewPane"));
  bindReviewStatusPicker();
  setReviewStatusValue(reviewStatus);
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
    if (dropdown.dataset.reviewDropdownToggleBound === "1") return;
    dropdown.dataset.reviewDropdownToggleBound = "1";
    const summary = dropdown.querySelector(":scope > summary");
    // Park off-screen before <details> flips open so the first paint never uses absolute top:100%.
    summary?.addEventListener(
      "pointerdown",
      () => {
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

function reviewStatusDisplayLabel(value) {
  const match = REVIEW_STATUS_OPTIONS.find((item) => item.value === value);
  if (!match) return String(value || t("status.reviewed"));
  if (match.labelKey && typeof t === "function") return t(match.labelKey);
  return i18nLocale() === "en" ? match.labelEn : match.labelZh;
}

function reviewStatusUiOptions() {
  return REVIEW_STATUS_OPTIONS.map((item) => ({
    value: item.value,
    label:
      item.labelKey && typeof t === "function"
        ? t(item.labelKey)
        : i18nLocale() === "en"
          ? item.labelEn
          : item.labelZh,
  }));
}

function setReviewStatusValue(value) {
  const normalized =
    value === "needs_gt_review"
      ? "needs_gt_review"
      : value === "pending"
        ? "pending"
        : "reviewed";
  const picker = $("#reviewStatusPicker");
  if (picker && typeof populateUiSelect === "function") {
    populateUiSelect(picker, reviewStatusUiOptions(), normalized);
  } else {
    const select = $("#reviewStatusInput");
    if (select) select.value = normalized;
    const summary = $("#reviewStatusPickerSummary");
    if (summary) summary.textContent = reviewStatusDisplayLabel(normalized);
  }
}

function bindReviewStatusPicker() {
  const picker = $("#reviewStatusPicker");
  if (!picker) return;
  // Form re-renders replace nodes; clear bind flag on new trigger each paint.
  const trigger = picker.querySelector(".review-status-picker-trigger, .ui-select-trigger");
  if (trigger) delete trigger.dataset.uiSelectBound;
  populateUiSelect(
    picker,
    reviewStatusUiOptions(),
    $("#reviewStatusInput")?.value || "reviewed"
  );
  bindUiSelect(picker, {
    maxHeight: 240,
    maxWidth: 280,
    onChange: () => {
      state.reviewFormDirty = true;
      const form = $("#annotationForm");
      if (form) form.dispatchEvent(new Event("change", { bubbles: true }));
    },
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
