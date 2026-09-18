/* Independent RA Case labeling workspace; model predictions are never loaded. */

function caseLabelingRouteOptions(overrides = {}) {
  const labeling = state.caseLabeling || {};
  return {
    issue: overrides.issue ?? labeling.issueId ?? "",
    taskId: overrides.taskId ?? labeling.taskId ?? "",
    search: overrides.search ?? labeling.search ?? "",
    status: overrides.status ?? labeling.status ?? "all",
    page: overrides.page ?? labeling.page ?? 1,
    pageSize: overrides.pageSize ?? labeling.pageSize ?? DEFAULT_CASE_PAGE_SIZE,
    baselines: overrides.baselines ?? state.selectedBaselineIds,
  };
}

function persistCaseLabelingRoute(overrides = {}, mode = "replace") {
  const url = pageUrl("labeling", caseLabelingRouteOptions(overrides));
  window.history[mode === "push" ? "pushState" : "replaceState"](
    { page: "labeling" }, "", url
  );
}

function activeLabelingBaselineIds() {
  return [...new Set(state.config?.case_labeling?.active_baseline_ids || [])].map(String);
}

function selectedActiveLabelingBaselineIds() {
  const active = new Set(activeLabelingBaselineIds());
  return normalizeBaselineIds(state.selectedBaselineIds).filter((id) => active.has(id));
}

function labelingBaselineItems(ids) {
  const wanted = new Set((ids || []).map(String));
  return (state.config?.baselines || state.baselineCatalog || []).filter((item) =>
    wanted.has(String(item.id))
  );
}

function canAccessCaseLabelingPreview() {
  return Boolean(state.session?.is_admin);
}

function caseLabelingStateText(value) {
  return ({ pending: "待标注", resolved: "已形成结果", conflict: "冲突待处理", stale: "裁决需确认" })[value] || value || "待标注";
}

function renderCaseLabelingTaskPicker() {
  const root = $("#caseLabelingTaskPicker");
  if (!root) return;
  const options = [
    { value: "", label: "全部标注" },
    ...(state.caseLabeling.tasks || []).map((task) => ({
      value: task.id,
      label: `${task.name || task.id} · ${task.member_count} Case`,
    })),
  ];
  populateUiSelect(root, options, state.caseLabeling.taskId || "");
  bindUiSelect(root);
}

function renderCaseLabelingStatusPicker() {
  const root = $("#caseLabelingStatusPicker");
  if (!root) return;
  populateUiSelect(root, [
    { value: "all", label: "全部状态" },
    { value: "pending", label: "待标注" },
    { value: "resolved", label: "已形成结果" },
    { value: "conflict", label: "冲突 / 需重新确认" },
  ], state.caseLabeling.status || "all");
  bindUiSelect(root);
}

async function loadCaseLabelingTasks() {
  const result = await api(withBaselineQuery("/api/labeling/tasks"));
  state.caseLabeling.tasks = result.items || [];
  if (
    state.caseLabeling.taskId &&
    !state.caseLabeling.tasks.some((item) => item.id === state.caseLabeling.taskId)
  ) {
    state.caseLabeling.taskId = "";
  }
  renderCaseLabelingTaskPicker();
}

function caseLabelingGalleryItem(item) {
  return {
    ...item,
    gallery_workspace: "labeling",
    thumbnail: {
      url: item.thumbnail_url || item.thumbnail?.url || "",
      label: item.thumbnail?.label || t("gallery.bev_keyframe"),
    },
    annotation: {
      label: item.expected_output || "",
      author: item.author || "",
      author_verified: Boolean(item.author_verified),
      is_excluded: Boolean(item.is_excluded),
      missing_evidence: item.evidence_gaps || [],
    },
  };
}

function bindCaseLabelingGalleryCards(list) {
  list.querySelectorAll("[data-open-issue]").forEach((button) => {
    button.addEventListener("click", () => selectCaseLabelingIssue(button.dataset.openIssue));
  });
  list.querySelectorAll("[data-case-media-preview]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (typeof openCaseMediaPreview !== "function") return;
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

function renderCaseLabelingInactiveState() {
  const selected = labelingBaselineItems(normalizeBaselineIds(state.selectedBaselineIds));
  const active = labelingBaselineItems(activeLabelingBaselineIds());
  const selectedText = selected.length
    ? selected.map((item) => item.label || item.id).join("、")
    : "当前数据集";
  const switches = active.length
    ? `<div class="case-labeling-active-switchers">${active.map((item) => `<button class="button button-primary" type="button" data-labeling-baseline="${escapeHtml(item.id)}">查看 ${escapeHtml(item.label || item.id)} · ${escapeHtml(String(item.count ?? "—"))}</button>`).join("")}</div>`
    : `<p>当前还没有已激活的标注数据集。</p>`;
  return `<div class="empty-state issue-grid-empty case-labeling-inactive-state"><h2>${escapeHtml(selectedText)} 尚未切换到 Case 标注<small class="case-labeling-preview-badge">内测 · 仅管理员</small></h2><p>该范围仍在「判错复核」工作台。Case 标注内测只列出已激活数据集，避免把未迁移范围显示成 0 个 Case。</p>${switches}</div>`;
}

function renderCaseLabelingList(data) {
  const list = $("#caseLabelingList");
  const items = data.items || [];
  const pagination = $("#caseLabelingGallery")?.querySelector(".case-pagination");
  const command = document.querySelector(".case-labeling-command");
  if (pagination) pagination.hidden = Boolean(data.inactive);
  if (command) command.hidden = Boolean(data.inactive);
  if (data.inactive) {
    list.innerHTML = renderCaseLabelingInactiveState();
    list.querySelectorAll("[data-labeling-baseline]").forEach((button) => {
      button.addEventListener("click", () => {
        setBaselineScopes([button.dataset.labelingBaseline]).catch((error) => showToast(error.message, true));
      });
    });
    $("#caseLabelingCount").textContent = "0";
    $("#caseLabelingSummary").textContent = "内测中 · 当前数据集尚未激活";
    $("#caseLabelingPageSummary").textContent = "— / —";
    $("#caseLabelingPrevious").disabled = true;
    $("#caseLabelingNext").disabled = true;
    if ($("#caseLabelingExportGt")) $("#caseLabelingExportGt").disabled = true;
    return;
  }
  list.innerHTML = items.length
    ? items.map((item) => issueCard(caseLabelingGalleryItem(item), { workspace: "labeling" })).join("")
    : `<div class="empty-state issue-grid-empty"><h2>当前范围没有 Case</h2><p>请切换已激活的数据集、任务或状态。</p></div>`;
  bindCaseLabelingGalleryCards(list);
  $("#caseLabelingCount").textContent = String(data.total || 0);
  $("#caseLabelingSummary").textContent = state.caseLabeling.taskId
    ? `任务范围 · ${data.total || 0} 个 Case`
    : `当前已激活数据集 · ${data.total || 0} 个 Case`;
  $("#caseLabelingPageSummary").textContent = `${data.page || 1} / ${data.pages || 1}`;
  $("#caseLabelingPrevious").disabled = Number(data.page || 1) <= 1;
  $("#caseLabelingNext").disabled = Number(data.page || 1) >= Number(data.pages || 1);
  $("#caseLabelingPageSize").value = String(data.page_size || DEFAULT_CASE_PAGE_SIZE);
  if ($("#caseLabelingExportGt")) {
    $("#caseLabelingExportGt").disabled = !state.session?.is_admin;
  }
}

async function loadCaseLabelingCases({ page = state.caseLabeling.page } = {}) {
  const seq = ++state.caseLabeling.requestSeq;
  if (!selectedActiveLabelingBaselineIds().length) {
    if (seq !== state.caseLabeling.requestSeq) return;
    state.caseLabeling.page = 1;
    state.caseLabeling.data = { items: [], total: 0, page: 1, pages: 1, page_size: state.caseLabeling.pageSize, inactive: true };
    renderCaseLabelingList(state.caseLabeling.data);
    persistCaseLabelingRoute({ issue: "", page: 1 });
    return;
  }
  const params = new URLSearchParams({
    baselines: selectedBaselineQueryValue(),
    task_id: state.caseLabeling.taskId || "",
    q: state.caseLabeling.search || "",
    status: state.caseLabeling.status || "all",
    page: String(Math.max(1, Number(page) || 1)),
    page_size: String(state.caseLabeling.pageSize || DEFAULT_CASE_PAGE_SIZE),
  });
  const result = await api(`/api/labeling/cases?${params}`);
  if (seq !== state.caseLabeling.requestSeq) return;
  state.caseLabeling.page = result.page || 1;
  state.caseLabeling.data = result;
  renderCaseLabelingList(result);
  persistCaseLabelingRoute({ issue: "", page: state.caseLabeling.page });
}

function caseLabelingQueueItems() {
  return state.caseLabeling.data?.items || [];
}

function navigateCaseLabelingIssue(direction) {
  const items = caseLabelingQueueItems();
  const current = String(state.caseLabeling.issueId || "");
  const index = items.findIndex((item) => item.issue_id === current);
  const next = items[index + direction];
  if (!next?.issue_id) return Promise.resolve();
  return selectCaseLabelingIssue(next.issue_id);
}

function renderCaseLabelingDetailMedia(caseData) {
  const issueUrl = safeUrl(caseData.voyager_issue_url || caseData.trail_url);
  const issueId = escapeHtml(caseData.issue_id);
  const issueIdValue = String(caseData.issue_id || "");
  const issueIdLink = issueUrl
    ? `<a class="detail-id detail-id-link" href="${escapeHtml(issueUrl)}" target="_blank" rel="noreferrer" title="打开 Voyager Issue">${issueId}</a>`
    : `<span class="detail-id">${issueId}</span>`;
  const issueIdMarkup = `<span class="detail-issue-id-group">${issueIdLink}<button class="detail-copy-id-button" type="button" data-copy-issue-id aria-label="复制 Issue ID ${issueId}" title="复制 Issue ID"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="7" y="6" width="9" height="10" rx="2"></rect><path d="M13 6V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"></path></svg></button></span>`;
  ensureDetailMediaState(caseData);
  const items = caseLabelingQueueItems();
  const index = items.findIndex((item) => item.issue_id === issueIdValue);
  $("#caseLabelingMedia").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title-group">
          <div class="detail-title"><h2><span class="ui-lang-zh">问题详情</span><span class="ui-lang-en">Issue Details</span></h2>${issueIdMarkup}<span id="caseLabelingExternalLinks" class="detail-external-links">${typeof detailExternalLinksMarkup === "function" ? detailExternalLinksMarkup(caseData) : ""}</span></div>
        </div>
        <div class="detail-navigation">
          <div class="case-detail-pager">
            <button class="button button-quiet" id="caseLabelingPreviousIssue" type="button" ${index <= 0 ? "disabled" : ""}><span class="ui-lang-zh">← 上一 Issue</span><span class="ui-lang-en">← Prev</span><kbd class="review-control-shortcut review-nav-shortcut" aria-hidden="true">[</kbd></button>
            <span class="detail-queue-position">${index >= 0 ? index + 1 : "—"} / ${items.length || "—"}</span>
            <button class="button button-quiet" id="caseLabelingNextIssue" type="button" ${index < 0 || index >= items.length - 1 ? "disabled" : ""}><span class="ui-lang-zh">下一 Issue →</span><span class="ui-lang-en">Next →</span><kbd class="review-control-shortcut review-nav-shortcut" aria-hidden="true">]</kbd></button>
          </div>
        </div>
      </div>
      <div class="detail-context-row">
        <div class="comparison-summary" aria-label="当前 GT">
          <span class="comparison-side-label comparison-side-gt">GT</span>${labelBadge(caseData.gt_label, uiText("缺失", "Missing"))}
        </div>
        <button class="button button-quiet detail-back-button" id="caseLabelingBack" type="button"><span class="ui-lang-zh">← 返回筛选结果</span><span class="ui-lang-en">← Back to gallery</span></button>
        ${caseData.summary ? `<p class="detail-summary">${escapeHtml(caseData.summary)}</p>` : ""}
        <div class="detail-context-actions">${detailMediaCommandMarkup(caseData)}</div>
      </div>
    </div>
    ${heroMediaSection(caseData)}`;
  $("#caseLabelingMedia").querySelector("[data-copy-issue-id]")?.addEventListener("click", (event) => {
    if (typeof copyReviewIssueId === "function") copyReviewIssueId(issueIdValue, event.currentTarget);
  });
  $("#caseLabelingBack")?.addEventListener("click", () => closeCaseLabelingDetail());
  $("#caseLabelingPreviousIssue")?.addEventListener("click", () => {
    navigateCaseLabelingIssue(-1).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingNextIssue")?.addEventListener("click", () => {
    navigateCaseLabelingIssue(1).catch((error) => showToast(error.message, true));
  });
  if (typeof bindDetailExternalLinks === "function") {
    bindDetailExternalLinks(caseData, $("#caseLabelingExternalLinks"));
  }
  bindDetailMedia(caseData);
}

function currentEditableLabelCase(caseData) {
  const cases = caseData?.label_cases || [];
  if (state.caseLabeling.taskId) {
    return cases.find((item) => item.task_id === state.caseLabeling.taskId) || null;
  }
  return cases.find((item) => !item.task_id && !item.source_run_id) || null;
}

function currentLabelingRevision(caseData) {
  const editable = currentEditableLabelCase(caseData);
  if (!editable) return null;
  const currentUser = String(state.session?.username || "").trim().toLowerCase();
  return (editable.resolution?.heads || []).find(
    (item) => String(item.author || "").trim().toLowerCase() === currentUser
  ) || editable.resolution?.result_revision || null;
}

function caseLabelingHistoryAnnotations(caseData) {
  const gtLabel = String(caseData?.gt_label || "");
  return (caseData?.label_cases || [])
    .flatMap((labelCase) =>
      (labelCase.resolution?.heads || []).map((revision) => ({ labelCase, revision }))
    )
    .sort((a, b) => Number(b.revision.id) - Number(a.revision.id))
    .map(({ labelCase, revision }) => {
      const expectedOutput = String(revision.expected_output || "").trim();
      return {
        id: revision.id,
        expected_output: expectedOutput,
        review_status: !expectedOutput
          ? "pending"
          : expectedOutput === gtLabel
            ? "reviewed"
            : "needs_gt_review",
        is_excluded: Boolean(revision.is_excluded),
        author: revision.author || "",
        author_verified: Boolean(revision.author_verified),
        created_at: revision.created_at || "",
        tags: revision.tags || [],
        missing_evidence: revision.evidence_gaps || [],
        attachments: revision.attachments || [],
        note: revision.rationale || "",
        labeling_task_id: labelCase.task_id || "",
      };
    });
}

function caseLabelingHistoryMarkup(caseData) {
  return annotationHistory(caseLabelingHistoryAnnotations(caseData), {
    deletable: false,
    emptyText: "尚无工作台标注。",
    runMeta: (item) => ({
      title: "标注来源",
      text: item.labeling_task_id
        ? `任务标注 · ${item.labeling_task_id}`
        : "历史/自由标注",
    }),
  });
}

function caseLabelingCommentsMarkup(caseData) {
  const comments = caseData.comments || [];
  const count = comments.length;
  const button = `<button class="button button-quiet" type="button" id="caseLabelingOpenDiscussion">打开讨论${count ? ` · ${count}` : ""} <kbd>D</kbd></button>`;
  if (!comments.length) {
    return `${button}<p class="muted">尚无标注讨论。可在讨论面板回复历史线程或发起新讨论。</p>`;
  }
  const items = comments.map((comment) => {
    const body = typeof reviewCommentBodyMarkup === "function"
      ? reviewCommentBodyMarkup(comment.body || "", comment.attachments || [])
      : `<p>${escapeHtml(comment.body || "")}</p>`;
    const displayName = typeof reviewMentionDisplayName === "function"
      ? reviewMentionDisplayName(comment.author || "未记录")
      : (comment.author || "未记录");
    const sourceBits = [
      comment.label_task_id ? "任务讨论" : "",
      comment.source_run_id ? `历史来源 Run · ${comment.source_run_id}` : "",
    ].filter(Boolean);
    return `<article class="case-labeling-history-row"><header><strong>${escapeHtml(displayName)}</strong><span>${escapeHtml(comment.created_at || "")}</span></header><div class="comment-thread-body">${body}</div>${sourceBits.length ? `<small>${escapeHtml(sourceBits.join(" · "))}</small>` : ""}</article>`;
  }).join("");
  return `${button}<div class="case-labeling-history">${items}</div>`;
}

function renderCaseLabelingEditor(caseData) {
  const revision = currentLabelingRevision(caseData);
  const aggregateResolved = (caseData.label_cases || []).find(
    (item) => item.resolution?.state === "resolved"
  )?.resolution?.result_revision;
  const source = revision || aggregateResolved || {};
  const exactTaskCase = state.caseLabeling.taskId
    ? (caseData.label_cases || []).find((item) => item.task_id === state.caseLabeling.taskId)
    : null;
  const resolution = exactTaskCase?.resolution || null;
  const expectedOutput = String(source.expected_output || "");
  const reviewStatus = !expectedOutput
    ? "pending"
    : expectedOutput === String(caseData.gt_label || "")
      ? "reviewed"
      : "needs_gt_review";
  const chosenTags = new Set(source.tags || []);
  const tagCatalog = state.config?.review_tag_catalog || [];
  const tagOption = (key, label, selected, groupKey = "", item = null) => reviewTagOptionMarkup(
    item || { key, label, builtin: true },
    selected,
    groupKey,
  );
  const issueTagGroups = renderReviewTagGroups(tagCatalog, chosenTags, tagOption);
  const historyCount = (caseData.label_cases || []).reduce(
    (count, labelCase) => count + (labelCase.resolution?.heads || []).length, 0
  );
  $("#caseLabelingEditor").innerHTML = `
    <form class="review-form" id="caseLabelingForm">
      <section class="review-section issue-tag-section">
        <div class="review-section-heading"><div><h2><span class="ui-lang-zh">Issue 标签</span><span class="ui-lang-en">Issue tags</span></h2></div><span class="evidence-summary-count" id="tagSummaryCount">${escapeHtml(t("detail.selected_n", { n: chosenTags.size }))}</span></div>
        <div class="review-tag-groups-shell">${issueTagGroups}</div>
        <label class="review-exclude-toggle" title="${escapeHtml(uiText("按 K 切换应该排除", "Press K to toggle Exclude"))}"><input id="caseLabelingExcluded" type="checkbox" aria-keyshortcuts="K" ${source.is_excluded ? "checked" : ""} /><span><strong class="ui-lang-zh">应该排除</strong><strong class="ui-lang-en">Exclude</strong><small class="ui-lang-zh">不是模型需要解决的场景 case</small><small class="ui-lang-en">Not a case the model is expected to solve</small></span><kbd class="review-control-shortcut review-exclude-shortcut" aria-hidden="true">K</kbd></label>
      </section>
      <section class="review-section model-error-section">
        <div class="review-section-heading">
          <div>
            <h2><span class="ui-lang-zh">Case 标注</span><span class="ui-lang-en">Case labeling</span></h2>
          </div>
          <div class="review-heading-actions">
            <button class="history-inline-button" id="caseLabelingOpenDiscussion" type="button" aria-keyshortcuts="D" title="展开或收起讨论（D）">
              <span class="ui-lang-zh">讨论</span><span class="ui-lang-en">Discussion</span>
              <kbd class="review-control-shortcut" aria-hidden="true">D</kbd>
            </button>
            <button class="history-inline-button" id="caseLabelingHistoryToggle" type="button" aria-keyshortcuts="J" title="展开或收起标注历史（J）">
              <span class="ui-lang-zh">历史 · ${historyCount}</span>
              <span class="ui-lang-en">History · ${historyCount}</span>
              <kbd class="review-control-shortcut" aria-hidden="true">J</kbd>
            </button>
          </div>
        </div>
        <div class="review-expected-output-field">
          <div class="review-expected-output-heading">
            <span id="caseLabelingExpectedOutputLabel"><span class="ui-lang-zh">期望输出</span><span class="ui-lang-en">Expected output</span></span>
            <span class="derived-review-status">${escapeHtml(caseLabelingStateText(resolution?.state || (expectedOutput ? "resolved" : "pending")))}</span>
          </div>
          <div class="ui-select expected-output-picker" id="caseLabelingExpectedOutputPicker">
            <button class="ui-select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">
              <span class="ui-select-summary">${escapeHtml(expectedOutput || "待补充")}</span>
              <span class="ui-select-caret" aria-hidden="true"></span>
            </button>
            <div class="ui-select-panel" role="listbox" hidden></div>
            <select class="ui-select-native" id="caseLabelingExpectedOutput" aria-hidden="true" tabindex="-1">
              ${EXPECTED_OUTPUT_OPTIONS.map((item) => `<option value="${escapeHtml(item.value)}" ${item.value === expectedOutput ? "selected" : ""}>${escapeHtml(item.labelZh)}</option>`).join("")}
            </select>
          </div>
        </div>
        <label class="review-reason">
          <span class="review-reason-heading">
            <span><span class="ui-lang-zh">标注依据</span><span class="ui-lang-en">Label rationale</span></span>
            <small class="review-reason-shortcuts"><span class="ui-lang-zh"><kbd>E</kbd> 聚焦 · <kbd>⇧ Enter</kbd> 换行</span></small>
          </span>
          <textarea id="caseLabelingRationale" rows="2" placeholder="说明判断依据；此处不填写模型判错原因。">${escapeHtml(source.rationale || "")}</textarea>
        </label>
        <div class="review-attachment-field">
          <div class="screenshot-paste-zone is-compact" id="caseLabelingPasteZone" tabindex="0" role="group" aria-label="拖拽、粘贴或选择标注截图">
            <span class="screenshot-paste-copy">
              <strong><span class="ui-lang-zh">标注截图</span><span class="ui-lang-en">Screenshots</span></strong>
              <small><span class="ui-lang-zh">拖拽到此处 / 粘贴 Ctrl/⌘+V · 最多 4 张</span><span class="ui-lang-en">Drop here / Paste Ctrl/⌘+V · max 4</span></small>
            </span>
            <button class="screenshot-browse-button" id="caseLabelingScreenshotBrowse" type="button"><span class="ui-lang-zh">选择图片</span><span class="ui-lang-en">Browse</span></button>
          </div>
          <input class="hidden" id="caseLabelingScreenshotInput" type="file" accept="image/png,image/jpeg,image/webp" multiple />
          <div class="pending-screenshot-list" id="caseLabelingPendingScreenshots"></div>
        </div>
        ${resolution?.state === "conflict" || resolution?.state === "stale" ? `<section class="case-labeling-adjudication"><strong>标注冲突</strong><p>${(resolution.heads || []).map((item) => `${escapeHtml(item.author)}：${escapeHtml(item.expected_output || "待补充")}`).join(" · ")}</p><button class="button button-quiet" id="caseLabelingAdjudicate" type="button">按当前表单显式裁决</button></section>` : ""}
        <button class="button button-primary full-width review-save-button" type="submit" ${state.session?.is_admin ? "" : "disabled"}><span class="ui-lang-zh">保存标注</span><span class="ui-lang-en">Save label</span><kbd class="review-save-shortcut" aria-hidden="true">Enter</kbd></button>
      </section>
    </form>`;
  const editor = $("#caseLabelingEditor");
  $("#caseLabelingForm").addEventListener("submit", saveCaseLabelingRevision);
  $("#caseLabelingForm").addEventListener("input", () => { state.caseLabeling.dirty = true; });
  $("#caseLabelingForm").addEventListener("change", () => { state.caseLabeling.dirty = true; });
  $("#caseLabelingAdjudicate")?.addEventListener("click", adjudicateCaseLabeling);
  $("#caseLabelingOpenDiscussion")?.addEventListener("click", () => {
    openCaseLabelingDiscussion().catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingHistoryToggle")?.addEventListener("click", () => {
    toggleHistoryDialog("labeling", state.caseLabeling.caseData);
  });
  bindUiSelect($("#caseLabelingExpectedOutputPicker"), { maxHeight: 260, maxWidth: 420 });
  bindSelectedReviewTagControls(editor);
  bindReviewTagCatalogControls(editor);
  bindReviewDropdownToggles(editor);
  bindReviewDropdownDismiss();
  bindCaseLabelingAttachmentInputs();
  renderPendingCaseLabelingImages();
  editor.querySelectorAll('input[name="reviewTags"]').forEach((input) => {
    input.addEventListener("change", updateTagSummary);
  });
  updateTagSummary();
  syncReviewDropdownShortcutHints(editor);
  bindReviewKeyboardShortcuts();
}

async function selectCaseLabelingIssue(issueId, { updateRoute = true } = {}) {
  const normalized = String(issueId || "").trim();
  if (!normalized) return;
  const seq = ++state.caseLabeling.detailSeq;
  const task = state.caseLabeling.taskId ? `&task_id=${encodeURIComponent(state.caseLabeling.taskId)}` : "";
  const caseData = await api(withBaselineQuery(`/api/labeling/cases/${encodeURIComponent(normalized)}?${task ? task.slice(1) : ""}`));
  if (seq !== state.caseLabeling.detailSeq) return;
  state.caseLabeling.issueId = normalized;
  state.caseLabeling.caseData = caseData;
  state.caseLabeling.dirty = false;
  clearPendingCaseLabelingImages();
  $("#caseLabelingGalleryView")?.classList.add("hidden");
  $("#caseLabelingGallery")?.classList.add("hidden");
  $("#caseLabelingDetail").classList.remove("hidden");
  caseData.media_status = "pending";
  caseData.trail_metadata_status = "pending";
  renderCaseLabelingDetailMedia(caseData);
  renderCaseLabelingEditor(caseData);
  if (updateRoute) persistCaseLabelingRoute({ issue: normalized }, "push");
  void startTrailDetailMetadata(normalized, seq).then((result) => {
    if (seq !== state.caseLabeling.detailSeq || state.caseLabeling.issueId !== normalized) return;
    caseData.external_links = result?.external_links || {};
    caseData.trail_metadata_status = result?.status || "unavailable";
    const links = $("#caseLabelingExternalLinks");
    if (links) {
      links.innerHTML = detailExternalLinksMarkup(caseData);
      bindDetailExternalLinks(caseData, links);
    }
  });
  try {
    const media = await api(`/api/cases/${encodeURIComponent(normalized)}/media`);
    if (seq !== state.caseLabeling.detailSeq || state.caseLabeling.issueId !== normalized) return;
    Object.assign(caseData, media);
    caseData.media_status = "";
    renderCaseLabelingDetailMedia(caseData);
  } catch (error) {
    if (seq === state.caseLabeling.detailSeq) {
      $("#caseLabelingMedia").innerHTML = `<div class="empty-state"><h2>媒体加载失败</h2><p>${escapeHtml(error.message)}</p></div>`;
    }
  }
}

function closeCaseLabelingDetail({ updateRoute = true } = {}) {
  $("#caseLabelingMedia")?.querySelector("video")?.pause();
  state.caseLabeling.issueId = "";
  state.caseLabeling.caseData = null;
  state.caseLabeling.dirty = false;
  clearPendingCaseLabelingImages();
  state.caseLabeling.detailSeq += 1;
  $("#caseLabelingDetail").classList.add("hidden");
  $("#caseLabelingGalleryView")?.classList.remove("hidden");
  $("#caseLabelingGallery")?.classList.remove("hidden");
  if (updateRoute) persistCaseLabelingRoute({ issue: "" }, "push");
}

function caseLabelingFormPayload() {
  const editor = $("#caseLabelingEditor");
  return {
    task_id: state.caseLabeling.taskId || "",
    expected_output: $("#caseLabelingExpectedOutput")?.value || "",
    tags: [...(editor?.querySelectorAll('input[name="reviewTags"]:checked') || [])].map((item) => item.value),
    evidence_gaps: [],
    rationale: $("#caseLabelingRationale")?.value || "",
    is_excluded: Boolean($("#caseLabelingExcluded")?.checked),
  };
}

function addPendingCaseLabelingImages(files) {
  const limits = state.config?.review_attachment_limits || {};
  const maxCount = Number(limits.max_count || 4);
  const maxBytes = Number(limits.max_bytes_each || 8 * 1024 * 1024);
  const maxTotalBytes = Number(limits.max_bytes_total || 24 * 1024 * 1024);
  const allowed = new Set(limits.media_types || ["image/png", "image/jpeg", "image/webp"]);
  let rejected = "";
  files.forEach((file) => {
    if (state.caseLabeling.pendingImages.length >= maxCount) {
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
    const currentBytes = state.caseLabeling.pendingImages.reduce(
      (sum, item) => sum + item.file.size,
      0
    );
    if (currentBytes + file.size > maxTotalBytes) {
      rejected = "本次截图总大小不能超过 24 MB。";
      return;
    }
    state.caseLabeling.pendingImages.push({
      id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      file,
      previewUrl: URL.createObjectURL(file),
    });
  });
  renderPendingCaseLabelingImages();
  if (rejected) showToast(rejected, true);
}

function renderPendingCaseLabelingImages() {
  const target = $("#caseLabelingPendingScreenshots");
  if (!target) return;
  target.innerHTML = state.caseLabeling.pendingImages
    .map(
      (item) => `<div class="pending-screenshot">
        <img src="${escapeHtml(item.previewUrl)}" alt="${escapeHtml(item.file.name || "待上传截图")}" />
        <button type="button" data-remove-case-screenshot="${escapeHtml(item.id)}" aria-label="移除截图">×</button>
      </div>`
    )
    .join("");
  target.querySelectorAll("[data-remove-case-screenshot]").forEach((button) => {
    button.addEventListener("click", () => {
      const index = state.caseLabeling.pendingImages.findIndex(
        (item) => item.id === button.dataset.removeCaseScreenshot
      );
      if (index < 0) return;
      const previewUrl = state.caseLabeling.pendingImages[index].previewUrl;
      state.caseLabeling.pendingImages.splice(index, 1);
      renderPendingCaseLabelingImages();
      releasePreviewUrlLater(previewUrl);
    });
  });
}

function clearPendingCaseLabelingImages() {
  if (!state.caseLabeling.pendingImages.length) return;
  const previewUrls = state.caseLabeling.pendingImages.map((item) => item.previewUrl);
  state.caseLabeling.pendingImages = [];
  renderPendingCaseLabelingImages();
  previewUrls.forEach(releasePreviewUrlLater);
}

function bindCaseLabelingAttachmentInputs() {
  const pasteZone = $("#caseLabelingPasteZone");
  const screenshotInput = $("#caseLabelingScreenshotInput");
  const screenshotBrowse = $("#caseLabelingScreenshotBrowse");
  if (!pasteZone || !screenshotInput) return;

  const openScreenshotPicker = () => screenshotInput.click();
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

  const acceptImagePasteOrDrop = (event, dataTransfer) => {
    const files = imageFilesFromDataTransfer(dataTransfer);
    if (!files.length) return false;
    event.preventDefault();
    event.stopPropagation();
    addPendingCaseLabelingImages(files);
    return true;
  };
  $("#caseLabelingForm")?.addEventListener("paste", (event) => {
    const target = event.target;
    if (
      target instanceof HTMLTextAreaElement ||
      (target instanceof HTMLInputElement &&
        !["checkbox", "radio", "file", "button", "submit"].includes(target.type))
    ) {
      const hasImage = [...(event.clipboardData?.items || [])].some(
        (item) => item.kind === "file" && item.type.startsWith("image/")
      );
      if (!hasImage) return;
    }
    acceptImagePasteOrDrop(event, event.clipboardData);
  });

  let dragDepth = 0;
  const setDragOver = (active) => pasteZone.classList.toggle("is-dragover", active);
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
    addPendingCaseLabelingImages([...screenshotInput.files]);
    screenshotInput.value = "";
  });
}

async function saveCaseLabelingRevision(event) {
  event.preventDefault();
  const caseData = state.caseLabeling.caseData;
  if (!caseData) return;
  const revision = currentLabelingRevision(caseData);
  const payload = {
    ...caseLabelingFormPayload(),
    expected_previous_revision_id: revision?.id || null,
  };
  const files = state.caseLabeling.pendingImages.map((item) => item.file);
  if (files.length > 4) {
    showToast("标注截图最多 4 张。", true);
    return;
  }
  const button = event.submitter || event.currentTarget.querySelector('[type="submit"]');
  button.disabled = true;
  try {
    let result;
    if (files.length) {
      const form = new FormData();
      form.append("payload", JSON.stringify(payload));
      files.forEach((file) => form.append("attachments", file, file.name));
      result = await api(`/api/labeling/cases/${encodeURIComponent(caseData.issue_id)}/revisions-with-attachments`, {
        method: "POST",
        body: form,
        headers: { "X-RA-Triage-Request": "labeling-v1" },
      });
    } else {
      result = await api(`/api/labeling/cases/${encodeURIComponent(caseData.issue_id)}/revisions`, {
        method: "POST", body: JSON.stringify(payload),
      });
    }
    acknowledgeLocalChange(result);
    state.caseLabeling.dirty = false;
    clearPendingCaseLabelingImages();
    showToast("标注已保存。");
    await Promise.all([
      selectCaseLabelingIssue(caseData.issue_id, { updateRoute: false }),
      loadCaseLabelingCases({ page: state.caseLabeling.page }),
    ]);
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function adjudicateCaseLabeling() {
  const caseData = state.caseLabeling.caseData;
  const labelCase = (caseData?.label_cases || []).find(
    (item) => item.task_id === state.caseLabeling.taskId
  );
  if (!labelCase) return;
  const resolution = labelCase.resolution || {};
  const payload = {
    ...caseLabelingFormPayload(),
    source_revision_ids: (resolution.heads || []).map((item) => item.id),
    expected_previous_resolution_id: resolution.adjudication?.id || null,
  };
  try {
    const result = await api(`/api/labeling/label-cases/${encodeURIComponent(labelCase.id)}/adjudications`, {
      method: "POST", body: JSON.stringify(payload),
    });
    acknowledgeLocalChange(result);
    state.caseLabeling.dirty = false;
    showToast("裁决已保存。");
    await selectCaseLabelingIssue(caseData.issue_id, { updateRoute: false });
    await loadCaseLabelingCases({ page: state.caseLabeling.page });
  } catch (error) {
    showToast(error.message, true);
  }
}

function openCaseLabelingDiscussion(focusCommentId = 0) {
  const issueId = state.caseLabeling.issueId || state.caseLabeling.caseData?.issue_id;
  if (!issueId || typeof openAnalysisDiscussion !== "function") return Promise.resolve();
  return openAnalysisDiscussion(issueId, {
    source: "labeling",
    kind: "labeling",
    taskId: state.caseLabeling.taskId || "",
    focusCommentId,
  });
}

function bindCaseLabelingEditorShortcuts() {
  if (document.documentElement.dataset.caseLabelingKeys === "1") return;
  document.documentElement.dataset.caseLabelingKeys = "1";
  document.addEventListener("keydown", (event) => {
    if (
      event.defaultPrevented ||
      event.isComposing ||
      event.repeat ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      state.activePage !== "labeling" ||
      !state.caseLabeling.issueId
    ) return;
    const key = String(event.key || "").toLowerCase();
    const target = event.target instanceof Element ? event.target : null;
    const rationale = $("#caseLabelingRationale");
    if (rationale && target === rationale) {
      // Enter-submit is already handled by the shared submitReviewFromKeyboard.
      if (key === "escape") {
        event.preventDefault();
        event.stopPropagation();
        rationale.blur();
      }
      return;
    }
    if (key !== "d" && key !== "j" && key !== "e" && key !== "t") return;
    if (target?.closest("textarea, input, select, [contenteditable='true']")) return;
    if (key === "t") {
      const raEventDialog = $("#raEventDialog");
      if (raEventDialog?.open) {
        event.preventDefault();
        closeDialog("raEventDialog");
        return;
      }
      if (document.querySelector("dialog[open]")) return;
      const raEventButton = $("#caseLabelingExternalLinks")?.querySelector("[data-open-ra-event]");
      if (!raEventButton) return;
      event.preventDefault();
      closeAllReviewDropdowns();
      raEventButton.click();
      return;
    }
    if (key === "d") {
      event.preventDefault();
      const dialog = $("#analysisDiscussionDialog");
      if (dialog?.open && state.analysisDiscussion?.kind === "labeling") {
        if (typeof closeDialog === "function") closeDialog("analysisDiscussionDialog");
        else dialog.close();
        return;
      }
      if (document.querySelector("dialog[open]")) return;
      openCaseLabelingDiscussion().catch((error) => showToast(error.message, true));
      return;
    }
    const historyDialog = $("#historyDialog");
    if (key === "j" && historyDialog?.open) {
      event.preventDefault();
      toggleHistoryDialog("labeling", state.caseLabeling.caseData);
      return;
    }
    if (document.querySelector("dialog[open]")) return;
    if (key === "j") {
      event.preventDefault();
      toggleHistoryDialog("labeling", state.caseLabeling.caseData);
      return;
    }
    if (key === "e" && !event.shiftKey) {
      event.preventDefault();
      closeAllReviewDropdowns();
      rationale?.focus({ preventScroll: false });
    }
  });
}

async function enterCaseLabeling({ route = null } = {}) {
  if (!canAccessCaseLabelingPreview() && !state.session?.identity_pending) {
    showToast("Case 标注内测仅限管理员。", true);
    if (typeof showPage === "function") showPage("review", { historyMode: "replace" });
    return;
  }
  const filters = route?.labelingFilters || parsePageRoute().labelingFilters || {};
  state.caseLabeling.taskId = filters.taskId ?? state.caseLabeling.taskId;
  state.caseLabeling.search = filters.search ?? state.caseLabeling.search;
  state.caseLabeling.status = filters.status ?? state.caseLabeling.status;
  state.caseLabeling.page = filters.page || 1;
  state.caseLabeling.pageSize = filters.pageSize || DEFAULT_CASE_PAGE_SIZE;
  $("#caseLabelingSearch").value = state.caseLabeling.search;
  await loadCaseLabelingTasks();
  renderCaseLabelingStatusPicker();
  await loadCaseLabelingCases({ page: state.caseLabeling.page });
  const issue = route?.issue || filters.issue || "";
  if (issue) await selectCaseLabelingIssue(issue, { updateRoute: false });
  else closeCaseLabelingDetail({ updateRoute: false });
}

function bindCaseLabelingEvents() {
  bindCaseLabelingEditorShortcuts();
  $("#caseLabelingFilterForm")?.addEventListener("submit", (event) => event.preventDefault());
  $("#caseLabelingTask")?.addEventListener("change", () => {
    state.caseLabeling.taskId = $("#caseLabelingTask").value || "";
    state.caseLabeling.page = 1;
    closeCaseLabelingDetail({ updateRoute: false });
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingStatus")?.addEventListener("change", () => {
    state.caseLabeling.status = $("#caseLabelingStatus").value || "all";
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  let timer = null;
  $("#caseLabelingSearch")?.addEventListener("input", () => {
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(() => {
      state.caseLabeling.search = $("#caseLabelingSearch").value.trim();
      loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
    }, 250);
  });
  $("#caseLabelingReset")?.addEventListener("click", () => {
    state.caseLabeling.taskId = "";
    state.caseLabeling.status = "all";
    state.caseLabeling.search = "";
    $("#caseLabelingSearch").value = "";
    renderCaseLabelingTaskPicker();
    renderCaseLabelingStatusPicker();
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingPrevious")?.addEventListener("click", () => loadCaseLabelingCases({ page: state.caseLabeling.page - 1 }).catch((error) => showToast(error.message, true)));
  $("#caseLabelingNext")?.addEventListener("click", () => loadCaseLabelingCases({ page: state.caseLabeling.page + 1 }).catch((error) => showToast(error.message, true)));
  $("#caseLabelingPageSize")?.addEventListener("change", (event) => {
    state.caseLabeling.pageSize = Number(event.target.value) || DEFAULT_CASE_PAGE_SIZE;
    loadCaseLabelingCases({ page: 1 }).catch((error) => showToast(error.message, true));
  });
  $("#caseLabelingBack")?.addEventListener("click", () => closeCaseLabelingDetail());
  $("#caseLabelingExportGt")?.addEventListener("click", () => {
    (async () => {
      try {
        const result = await api("/api/labeling/gt-export-previews", {
          method: "POST",
          body: JSON.stringify({ baselines: selectedBaselineQueryValue(), issue_ids: [] }),
        });
        acknowledgeLocalChange(result);
        window.location.href = result.download_url;
      } catch (error) {
        showToast(error.message, true);
      }
    })();
  });
}
