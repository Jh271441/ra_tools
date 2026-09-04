function bindTrailAttributeUpdateEvents() {
  $("#trailUpdateProgressClose")?.addEventListener("click", closeTrailUpdateProgress);
  $("#trailUpdateProgressDialog")?.addEventListener("cancel", (event) => {
    const dialog = $("#trailUpdateProgressDialog");
    if (dialog?.dataset.running === "true") {
      event.preventDefault();
      return;
    }
    closeTrailUpdateProgress();
  });
  $("#trailUpdateProgressDialog")?.addEventListener("close", () => {
    window.clearInterval(trailUpdateProgressTimer);
    window.clearTimeout(trailUpdateProgressCloseTimer);
    trailUpdateProgressTimer = null;
    trailUpdateProgressCloseTimer = null;
    if (state.trailUpdate?.progress) state.trailUpdate.progress.active = false;
  });
  $("#trailUpdateConfirmClose")?.addEventListener("click", () => trailUpdateConfirmClose(false));
  $("#trailUpdateConfirmCancel")?.addEventListener("click", () => trailUpdateConfirmClose(false));
  $("#trailUpdateConfirmSubmit")?.addEventListener("click", () => trailUpdateConfirmClose(true));
  $("#trailUpdateConfirmExpand")?.addEventListener("click", () => {
    const button = $("#trailUpdateConfirmExpand");
    trailUpdateConfirmSetExpanded(button?.dataset.expanded !== "true");
  });
  $("#trailUpdateConfirmDialog")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    trailUpdateConfirmClose(false);
  });
  $("#trailUpdateConfirmDialog")?.addEventListener("close", () => {
    if (trailUpdateConfirmResolver) trailUpdateConfirmClose(false);
  });
  document.querySelectorAll("[data-trail-update-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTab = button.dataset.trailUpdateTab || "review";
      setTrailUpdateTab(nextTab);
      if (nextTab === "issue") void loadTrailIssueHistory();
      if (typeof pageUrl === "function") {
        history.replaceState(
          { page: "trail-update" },
          "",
          pageUrl("trail-update", { runId: state.trailUpdate?.runId || "" })
        );
      }
    });
  });
  const select = $("#trailUpdateRunSelect");
  select?.addEventListener("change", () => {
    state.trailUpdate.runId = String(select.value || "");
    state.trailUpdate.page = 1;
    clearTrailAttributePreview();
    if (typeof pageUrl === "function") {
      history.replaceState({ page: "trail-update" }, "", pageUrl("trail-update", { runId: state.trailUpdate.runId }));
    }
    loadTrailAttributePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateFilterForm")?.addEventListener("submit", (event) => {
    event.preventDefault();
    state.trailUpdate.filters.search = String($("#trailUpdateSearchInput")?.value || "");
    applyTrailUpdateFilters();
  });
  $("#trailUpdateSearchInput")?.addEventListener("input", scheduleTrailUpdateFilterRender);
  $("#trailUpdateResetFiltersButton")?.addEventListener("click", () => {
    state.trailUpdate.filters = {
      search: "",
      gtLabel: [],
      modelLabel: [],
      reviewer: [],
      reviewStatus: [],
      trailStatus: [],
    };
    const search = $("#trailUpdateSearchInput");
    if (search) search.value = "";
    applyTrailUpdateFilters();
  });
  $("#trailUpdatePagePrevious")?.addEventListener("click", () => {
    goToTrailUpdatePage((Number(state.trailUpdate?.page) || 1) - 1);
  });
  $("#trailUpdatePageNext")?.addEventListener("click", () => {
    goToTrailUpdatePage((Number(state.trailUpdate?.page) || 1) + 1);
  });
  const pageJump = $("#trailUpdatePageJump");
  const jumpTrailUpdatePage = () => goToTrailUpdatePage(pageJump?.value);
  $("#trailUpdatePageJumpButton")?.addEventListener("click", jumpTrailUpdatePage);
  pageJump?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      jumpTrailUpdatePage();
    }
  });
  $("#trailUpdatePageSize")?.addEventListener("change", (event) => {
    const nextSize = Number(event.currentTarget?.value);
    state.trailUpdate.pageSize = CASE_PAGE_SIZES.includes(nextSize)
      ? nextSize
      : DEFAULT_CASE_PAGE_SIZE;
    applyTrailUpdateFilters();
  });
  $("#trailUpdateCommitButton")?.addEventListener("click", () => {
    commitTrailAttributeUpdate().catch((error) => showToast(error.message, true));
  });
  document.querySelectorAll("[data-trail-json-preview]").forEach((button) => {
    button.addEventListener("click", openTrailUpdateJsonPreview);
  });
  $("#trailUpdateJsonClose")?.addEventListener("click", () => $("#trailUpdateJsonDialog")?.close());
  $("#trailUpdateJsonCancel")?.addEventListener("click", () => $("#trailUpdateJsonDialog")?.close());
  $("#trailUpdateJsonDownload")?.addEventListener("click", downloadTrailUpdateJson);
  $("#trailUpdateJsonCopy")?.addEventListener("click", () => {
    copyTrailUpdateJson().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateJsonDialog")?.addEventListener("cancel", (event) => {
    event.preventDefault();
    $("#trailUpdateJsonDialog")?.close();
  });
  $("#trailUpdateIssueAddButton")?.addEventListener("click", () => {
    addTrailIssueEntryRow();
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssueClearAllButton")?.addEventListener("click", clearTrailIssueEntries);
  $("#trailUpdateIssueJsonImportButton")?.addEventListener("click", () => openTrailIssueImport("json"));
  $("#trailUpdateIssueExcelImportButton")?.addEventListener("click", () => openTrailIssueImport("excel"));
  bindTrailIssueImportEvents("json");
  bindTrailIssueImportEvents("excel");
  $("#trailUpdateIssueEntries")?.addEventListener("input", (event) => {
    const target = event.target;
    const row = target?.closest?.("[data-trail-issue-entry-row]");
    if (row && target?.matches?.("[data-trail-issue-entry-id], [data-trail-issue-entry-comment]")) {
      // Editing a source-loaded row deliberately turns it into a manual row;
      // server-side validation then cannot attribute user-edited text to the
      // historical workbook.
      clearTrailIssueEntrySource(row);
    }
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssueEntries")?.querySelectorAll("[data-trail-issue-entry-comment]")
    .forEach((textarea) => bindReviewMentionComposer(
      textarea,
      textarea.parentElement?.querySelector("[data-mention-composer-root]")
    ));
  $("#trailUpdateIssueEntries")?.addEventListener("click", (event) => {
    const remove = event.target.closest("[data-trail-issue-entry-remove]");
    if (!remove || remove.disabled) return;
    remove.closest("[data-trail-issue-entry-row]")?.remove();
    syncTrailIssueEntryRemoveButtons();
    parseTrailIssueIds();
    clearTrailIssuePreview();
  });
  $("#trailUpdateIssuePreviewButton")?.addEventListener("click", () => {
    loadTrailIssuePreview().catch((error) => showToast(error.message, true));
  });
  $("#trailUpdateIssueCommitButton")?.addEventListener("click", () => {
    commitTrailIssueExclusion().catch((error) => showToast(error.message, true));
  });
  setTrailUpdateTab(state.trailUpdate?.tab || "review");
  void loadTrailIssueHistory();
  $("#trailUpdateIssueHistoryRefresh")?.addEventListener("click", () => {
    void loadTrailIssueHistory();
  });
  parseTrailIssueIds();
  setTrailAttributeCapability(null);
  renderTrailAttributeRunPicker();
}
