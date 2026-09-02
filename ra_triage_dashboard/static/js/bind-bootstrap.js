/* ra_triage_dashboard/static/js/bind-bootstrap.js
 * Event binding and bootstrap
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
let reviewSearchTimer = null;

function shortcutGuidePage() {
  return ["review", "intent"].includes(state.activePage) ? state.activePage : "";
}

function openShortcutGuide() {
  const page = shortcutGuidePage();
  const dialog = $("#shortcutGuideDialog");
  if (!page || !dialog || (document.querySelector("dialog[open]") && !dialog.open)) return;
  dialog.querySelectorAll("[data-shortcut-guide-page]").forEach((panel) => {
    panel.hidden = panel.dataset.shortcutGuidePage !== page;
  });
  $("#shortcutGuideSubtitle").textContent = page === "intent"
    ? "意图标注页 · 当前焦点位于输入控件时快捷键暂停"
    : "判错复核页 · 媒体快捷键在 Issue 详情中可用";
  if (!dialog.open) dialog.showModal();
}

function bindShortcutGuide() {
  const dialog = $("#shortcutGuideDialog");
  $("#shortcutHelpButton")?.addEventListener("click", openShortcutGuide);
  document.querySelectorAll("[data-open-shortcut-guide]").forEach((button) => {
    button.addEventListener("click", openShortcutGuide);
  });
  dialog?.addEventListener("close", () => {
    window.requestAnimationFrame(() => {
      const active = document.activeElement;
      if (active?.matches?.("#shortcutHelpButton, [data-open-shortcut-guide]")) active.blur();
    });
  });
  document.addEventListener("keydown", (event) => {
    if (String(event.key || "").toLowerCase() !== "h" || event.isComposing || event.repeat) return;
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    if (dialog?.open) {
      event.preventDefault();
      event.stopPropagation();
      dialog.close();
      return;
    }
    if (!shortcutGuidePage() || document.querySelector("dialog[open]")) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("input, textarea, select, [contenteditable='true'], [role='textbox']")) return;
    event.preventDefault();
    event.stopPropagation();
    openShortcutGuide();
  }, true);
}

function bindGlobalRefreshShortcut() {
  document.addEventListener("keydown", (event) => {
    if (event.code !== "KeyR" || event.isComposing || event.repeat) return;
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
    if (document.querySelector("dialog[open]")) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("input, textarea, select, button, a, [contenteditable='true'], [role='textbox']")) return;
    const refreshButton = $("#refreshButton");
    if (!refreshButton || refreshButton.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    refreshButton.click();
  }, true);
}

function scheduleReviewFilterReload(delay = 0) {
  if (reviewSearchTimer) window.clearTimeout(reviewSearchTimer);
  reviewSearchTimer = window.setTimeout(() => {
    reviewSearchTimer = null;
    state.reviewIssueIds = [];
    if (typeof updateIssueQueryButton === "function") updateIssueQueryButton();
    state.casePage = 1;
    reloadReviewGallery({ includeOverview: false, historyMode: "replace" }).catch(
      (error) => showToast(error.message, true)
    );
  }, Math.max(0, Number(delay) || 0));
}

function bindEvents() {
  bindShortcutGuide();
  bindGlobalRefreshShortcut();
  if (typeof bindIntentLabelingEvents === "function") bindIntentLabelingEvents();
  bindWorkSplitControls();
  if (typeof bindRunComparisonEvents === "function") bindRunComparisonEvents();
  if (typeof bindIssueQueryControls === "function") bindIssueQueryControls();
  document.querySelectorAll("[data-page-target]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (
        element.tagName === "A" &&
        (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      ) {
        return;
      }
      event.preventDefault();
      navigatePage(element.dataset.pageTarget);
      closeMobileSidebar();
    });
  });
  $("#filterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    // Filters auto-apply on change; form submit is treated as reset.
    await resetReviewFilters();
  });
  $("#resetReviewFiltersButton")?.addEventListener("click", () => {
    resetReviewFilters().catch((error) => showToast(error.message, true));
  });
  $("#searchInput")?.addEventListener("input", () => scheduleReviewFilterReload(280));
  $("#reviewAnalysisFilterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#analysisRunFilter").addEventListener("change", async () => {
    const runId = $("#analysisRunFilter").value;
    const previouslyHadRun = Boolean(state.selectedRunId);
    const nextStatus = !runId
      ? "all"
      : previouslyHadRun
        ? checkedAnalysisComparisonStatus()
        : "mismatch";
    setAnalysisComparisonStatus(nextStatus, { hasRun: Boolean(runId) });
    state.selectedRunId = state.modelRuns.some((run) => run.id === runId) ? runId : "";
    const run = state.modelRuns.find((item) => item.id === state.selectedRunId);
    if (run) {
      await applyInferredBaselinesFromRun(run, {
        reason: "run",
        reloadActivePage: false,
      });
    }
    scheduleAnalysisFilterReload();
  });
  // analysisComparisonFilter is a multi-filter; its onChange schedules reload.
  if (typeof renderAnalysisComparisonFilter === "function") {
    renderAnalysisComparisonFilter();
  } else if (typeof bindAnalysisComparisonPicker === "function") {
    bindAnalysisComparisonPicker();
  }
  if (typeof bindTrailAttributeUpdateEvents === "function") {
    bindTrailAttributeUpdateEvents();
  }
  $("#analysisSearchInput")?.addEventListener("input", () => {
    scheduleAnalysisFilterReload(220);
  });
  document.addEventListener("click", () => closeAllMultiFilters());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeAllMultiFilters();
      hideAnalysisPieTooltip?.();
    }
  });
  document.addEventListener(
    "scroll",
    (event) => {
      if (!document.querySelector(".multi-filter.is-open")) return;
      const target = event.target;
      if (
        target instanceof Element &&
        target.closest(".multi-filter-panel.is-fixed-dropdown")
      ) {
        return;
      }
      closeAllMultiFilters();
    },
    true
  );
  window.addEventListener("resize", () => closeAllMultiFilters());
  $("#resetReviewAnalysisButton").addEventListener("click", async () => {
    $("#analysisRunFilter").value = "";
    setAnalysisComparisonStatus("all", { hasRun: false });
    [
      "#analysisReviewerFilter",
      "#analysisStatusFilter",
      "#analysisGtFilter",
      "#analysisModelLabelFilter",
      "#analysisExclusionFilter",
      "#analysisEvidenceFilter",
      "#analysisSceneFilter",
      "#analysisTriggerFilter",
      "#analysisEgressFilter",
    ].forEach((selector) => setMultiFilterValues($(selector), []));
    // See resetReviewFilters: clear the durable route state as well as the
    // widget state, otherwise an analysis reset would restore reviewer=… on
    // the next async facet refresh.
    persistReviewerFilterRoute?.("analysis", []);
    $("#analysisSearchInput").value = "";
    state.reviewAnalysis.page = 1;
    try {
      await reloadReviewAnalysis();
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#exportReviewAnalysisCsvButton").addEventListener("click", () => downloadReviewAnalysis("csv"));
  $("#exportReviewAnalysisXlsxButton").addEventListener("click", () => downloadReviewAnalysis("xlsx"));
  $("#exportTrailExpectedOutputButton").addEventListener("click", () => downloadReviewAnalysis("trail_xlsx"));
  $("#analysisPagePrevious").addEventListener("click", () => {
    changeAnalysisPage(-1).catch((error) => showToast(error.message, true));
  });
  $("#analysisPageNext").addEventListener("click", () => {
    changeAnalysisPage(1).catch((error) => showToast(error.message, true));
  });
  const analysisPageJump = $("#analysisPageJump");
  const commitAnalysisPageJump = () => {
    jumpToAnalysisPage(analysisPageJump?.value).catch((error) => showToast(error.message, true));
  };
  $("#analysisPageJumpButton")?.addEventListener("click", commitAnalysisPageJump);
  analysisPageJump?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitAnalysisPageJump();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      analysisPageJump.value = String(state.reviewAnalysis.page);
      analysisPageJump.blur();
    }
  });
  analysisPageJump?.addEventListener("focus", () => {
    window.requestAnimationFrame(() => analysisPageJump.select());
  });
  $("#analysisPageSize")?.addEventListener("change", (event) => {
    changeAnalysisPageSize(event.target.value).catch((error) => showToast(error.message, true));
  });
  $("#modelRunFilter").addEventListener("change", async () => {
    const previousRunId = state.selectedRunId;
    state.selectedRunId = $("#modelRunFilter").value;
    if (!state.selectedRunId) state.reviewComparisonStatus = "all";
    if (state.selectedRunId && !previousRunId) {
      // Run selection changes the prediction overlay, not the immutable
      // baseline queue.  Keep the established failure-focused default while
      // retaining uncovered baseline Issues for the NONE/全部 filters.
      state.reviewComparisonStatus = "mismatch";
      state.failureOnly = true;
    }
    if (state.selectedRunId) {
      const run = (state.modelRuns || []).find(
        (item) => String(item.id) === String(state.selectedRunId)
      );
      // 单集评测 Run：切换对比时自动勾选对应 GT 数据集。
      if (run) {
        await applyInferredBaselinesFromRun(run, { reason: "run" });
      }
    }
    if (typeof renderReviewCatalogFilters === "function") {
      renderReviewCatalogFilters();
    }
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    await reloadReviewGallery();
  });
  const clearClusterButton = $("#clearClusterButton");
  if (clearClusterButton) {
    clearClusterButton.addEventListener("click", async () => {
      state.clusterKey = "";
      await reloadReviewGallery({ includeOverview: false });
    });
  }
  $("#casePagePrevious").addEventListener("click", () => {
    changeCasePage(-1).catch((error) => showToast(error.message, true));
  });
  $("#casePageNext").addEventListener("click", () => {
    changeCasePage(1).catch((error) => showToast(error.message, true));
  });
  const casePageJump = $("#casePageJump");
  const commitCasePageJump = () => {
    jumpToCasePage(casePageJump?.value).catch((error) => showToast(error.message, true));
  };
  $("#casePageJumpButton")?.addEventListener("click", commitCasePageJump);
  casePageJump?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      commitCasePageJump();
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      renderCasePagination();
      casePageJump.blur();
    }
  });
  casePageJump?.addEventListener("focus", () => {
    window.requestAnimationFrame(() => casePageJump.select());
  });
  $("#casePageSize").addEventListener("change", (event) => {
    changeCasePageSize(event.target.value).catch((error) => showToast(error.message, true));
  });
  $("#refreshButton").addEventListener("click", async () => {
    try {
      if (state.activePage === "intent") {
        await intentFlushSave();
        await loadIntentLabeling({
          datasetId: state.intentLabeling.datasetId,
          caseId: state.intentLabeling.caseId,
          offsetMs: intentActiveTimepoint()?.offset_ms,
        });
        showToast(t("toast.page_refreshed"));
        return;
      }
      await refreshAll();
      if (state.activePage === "analysis") {
        await loadReviewReasonAnalysis();
      } else if (state.selectedId) {
        await selectCase(state.selectedId, { updateRoute: false });
      }
      showToast(t("toast.page_refreshed"));
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#gtSyncButton")?.addEventListener("click", () => {
    refreshAuthoritativeGt().catch((error) => showToast(error.message, true));
  });
  $("#refreshSystemStatusButton").addEventListener("click", async () => {
    const button = $("#refreshSystemStatusButton");
    button.disabled = true;
    try {
      await loadStatus();
      showToast(t("toast.status_refreshed"));
    } catch (error) {
      showToast(error.message, true);
    } finally {
      button.disabled = false;
    }
  });
  $("#checkTrailButton").addEventListener("click", () => syncTrail("preview"));
  $("#syncTrailButton").addEventListener("click", () => syncTrail("create"));
  $("#runManagerImportButton").addEventListener("click", () => {
    $("#importResult").classList.add("hidden");
    $("#importResult").textContent = "";
    activateRunSourceTab("upload");
  });
  $("#openAutoTriageImportButton").addEventListener("click", openAutoTriageImport);
  $("#openTrailImportButton").addEventListener("click", () => {
    activateRunSourceTab("trail");
  });
  $("#reviewUploadModelButton").addEventListener("click", () => openRunImport("model"));
  $("#accessUserForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#accessUserName");
    const username = String(input.value || "").trim().toLowerCase();
    if (!username) return showToast(t("toast.enter_username"), true);
    const submit = event.submitter || event.currentTarget.querySelector("button[type='submit']");
    submit.disabled = true;
    try {
      await saveAccessUser(username, $("#accessUserRole").value);
      input.value = "";
      showToast(t("toast.access_saved"));
    } catch (error) {
      showToast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  $("#accessUserList").addEventListener("click", async (event) => {
    const row = event.target.closest("[data-access-user]");
    if (!row) return;
    const username = row.dataset.accessUser;
    if (event.target.closest("[data-save-access-user]")) {
      try {
        await saveAccessUser(username, row.querySelector("[data-access-role]").value);
        showToast(t("toast.access_updated"));
      } catch (error) { showToast(error.message, true); }
    }
    if (event.target.closest("[data-remove-access-user]")) {
      if (!window.confirm(t("access.confirm_remove", { user: username }))) return;
      try {
        const result = await api(`/api/access-users/${encodeURIComponent(username)}`, { method: "DELETE" });
        acknowledgeLocalChange(result);
        await loadAccessUsers();
        showToast(t("toast.access_removed"));
      } catch (error) { showToast(error.message, true); }
    }
  });
  $("#mentionUserForm")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#mentionUserName");
    const username = String(input?.value || "").trim().toLowerCase();
    if (!username) return showToast("请输入 LDAP 用户名。", true);
    try {
      await saveMentionUser(username, true);
      input.value = "";
      showToast("可 @ 人员已保存。");
    } catch (error) { showToast(error.message, true); }
  });
  $("#mentionUserList")?.addEventListener("click", async (event) => {
    const row = event.target.closest("[data-mention-user]");
    if (!row) return;
    const username = row.dataset.mentionUser;
    try {
      if (event.target.closest("[data-save-mention-user]")) {
        await saveMentionUser(username, row.querySelector("[data-mention-enabled]").checked);
        showToast("@ 人员状态已更新。");
      } else if (event.target.closest("[data-remove-mention-user]")) {
        const result = await api(`/api/mention-users/${encodeURIComponent(username)}`, { method: "DELETE" });
        acknowledgeLocalChange(result);
        await loadMentionUsers();
        showToast("@ 人员已移除。");
      }
    } catch (error) { showToast(error.message, true); }
  });
  bindAnalysisDiscussionEditor();
  $("#analysisDiscussionDialog")?.addEventListener("close", clearAnalysisDiscussionImages);
  $("#analysisDiscussionForm")?.addEventListener("submit", saveAnalysisDiscussion);
  $("#predictFilteredButton").addEventListener("click", () => {
    const limit = predictionBatchLimit();
    if (state.caseTotal > limit) {
      showToast(
        `当前筛选有 ${state.caseTotal} 个 Issue；单批最多 ${limit} 个，请继续收窄筛选。`,
        true
      );
      return;
    }
    if (state.cases.length !== state.caseTotal) {
      showToast(
        `当前仅加载 ${state.cases.length} / ${state.caseTotal} 个筛选结果，不能创建不完整 Batch。`,
        true
      );
      return;
    }
    openBatchDraft(
      state.cases.map((item) => item.issue_id),
      "filtered"
    );
  });
  $("#refreshRunsButton").addEventListener("click", async () => {
    try {
      await loadRuns();
      await loadOverview();
      showToast(t("toast.runs_refreshed"));
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#runPersonFilter").addEventListener("change", renderRunManager);
  $("#runKindFilter").addEventListener("change", renderRunManager);
  $("#runSearchInput").addEventListener("input", renderRunManager);
  $("#batchRequesterFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  $("#batchStatusFilter").addEventListener("change", () => {
    loadPredictionBatches().catch((error) => showToast(error.message, true));
  });
  ["#batchModelFilter", "#batchPromptFilter", "#batchInputFilter"].forEach((selector) => {
    $(selector).addEventListener("change", () => {
      loadPredictionBatches().catch((error) => showToast(error.message, true));
    });
  });
  $("#refreshPredictionBatchesButton").addEventListener("click", () => {
    loadPredictionBatches()
      .then(() => showToast(t("toast.batch_refreshed")))
      .catch((error) => showToast(error.message, true));
  });
  $("#refreshGatewayModelsButton").addEventListener("click", () => {
    const button = $("#refreshGatewayModelsButton");
    button.disabled = true;
    loadGatewayModels({ refresh: true })
      .then(() => showToast(t("toast.models_refreshed")))
      .catch((error) => showToast(error.message, true))
      .finally(() => {
        button.disabled = false;
      });
  });
  $("#predictionModelSelect").addEventListener("change", () => {
    state.selectedGatewayModelId = $("#predictionModelSelect").value;
    renderGatewayModels();
  });
  $("#predictionPromptSelect").addEventListener("change", loadSelectedPromptTemplate);
  $("#predictionPromptTemplate").addEventListener("input", updatePromptEditorSummary);
  $("#predictionInputProfile").addEventListener("change", applyBatchInputPreset);
  $("#predictionCameraPreset").addEventListener("change", applyCameraFramePreset);
  $("#predictionFrameOffsets").addEventListener("input", () => {
    syncCameraFramePreset();
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaEvent").addEventListener("change", () => {
    if (!$("#predictionUseRaEvent").checked) $("#predictionUseRaOptions").checked = false;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseRaOptions").addEventListener("change", () => {
    if ($("#predictionUseRaOptions").checked) $("#predictionUseRaEvent").checked = true;
    renderBatchRuntimeSummary();
  });
  $("#predictionUseBev").addEventListener("change", renderBatchRuntimeSummary);
  $("#languageToggleButton").addEventListener("click", () => {
    applyUiLanguage(state.uiLanguage === "en" ? "zh" : "en");
  });
  $("#themeToggleButton").addEventListener("click", () => {
    applyColorTheme(state.colorTheme === "light" ? "dark" : "light");
  });
  $("#sidebarToggle").addEventListener("click", toggleSidebar);
  $("#sidebarBrandToggle").addEventListener("click", toggleSidebar);
  $("#mobileSidebarBackdrop")?.addEventListener("click", closeMobileSidebar);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeMobileSidebar();
  });
  const sidebarMedia = typeof window.matchMedia === "function"
    ? window.matchMedia("(max-width: 639px)")
    : null;
  const syncSidebarViewport = () => {
    if (!isMobileSidebarViewport()) state.mobileSidebarOpen = false;
    applySidebarState();
  };
  if (sidebarMedia?.addEventListener) sidebarMedia.addEventListener("change", syncSidebarViewport);
  else if (sidebarMedia?.addListener) sidebarMedia.addListener(syncSidebarViewport);
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  $("#mediaDialog").addEventListener("close", cleanupMediaDialog);
  $("#raEventSearchInput").addEventListener("input", (event) => {
    renderRaEventRows(state.raEventDialog.events, event.target.value);
  });
  $("#raEventSearchButton").addEventListener("click", () => $("#raEventSearchInput")?.focus());
  $("#raEventDialog").addEventListener("close", () => {
    state.raEventDialog = { issueId: "", events: [], trailUrl: "" };
  });
  $("#importFile").addEventListener("change", () => {
    const filename = $("#importFileName");
    if (filename) filename.textContent = $("#importFile").files[0]?.name || t("filter.no_file");
  });
  $("#openImportExamplesButton").addEventListener("click", openImportExamples);
  document.querySelectorAll("[data-import-example-format]").forEach((tab) => {
    tab.addEventListener("click", () => renderImportExample(tab.dataset.importExampleFormat));
  });
  $("#copyImportExampleButton").addEventListener("click", () => copyImportExample().catch((error) => showToast(error.message, true)));
  $("#importForm").addEventListener("submit", submitImport);
  $("#autotriageImportForm").addEventListener("submit", submitAutoTriageImport);
  $("#predictionBatchIssues").addEventListener("input", () => {
    state.batchDraftSource = "";
    updatePredictionBatchCount();
    renderPredictionSourceSummary();
  });
  $("#predictionBatchForm").addEventListener("submit", submitPredictionBatch);
  $("#sourcePreviewPrevious").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page <= 1) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page - 1).catch((error) => showToast(error.message, true));
  });
  $("#sourcePreviewNext").addEventListener("click", () => {
    if (!state.sourcePreview.runId || state.sourcePreview.page >= state.sourcePreview.pageCount) return;
    loadSourcePreviewPage(state.sourcePreview.runId, state.sourcePreview.page + 1).catch((error) => showToast(error.message, true));
  });
  $("#mediaPrevButton").addEventListener("click", () => moveMedia(-1));
  $("#mediaNextButton").addEventListener("click", () => moveMedia(1));
  $("#mediaZoomOutButton").addEventListener("click", () => setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP));
  $("#mediaZoomResetButton").addEventListener("click", () => setMediaZoom(1, { resetScroll: true }));
  $("#mediaZoomInButton").addEventListener("click", () => setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP));
  $("#mediaOriginalSizeButton").addEventListener("click", showMediaAtOriginalSize);
  $("#mediaFullscreenButton").addEventListener("click", () => toggleMediaFullscreen());
  $("#mediaPreviewImage").addEventListener("load", () => {
    setMediaZoom(state.media.zoom);
  });
  bindMediaPanViewport($("#mediaViewport"));
  document.addEventListener("fullscreenchange", () => {
    updateMediaViewControls();
    window.requestAnimationFrame(updateMediaPanState);
  });
  document.addEventListener("keydown", (event) => {
    if (!$("#mediaDialog").open) {
      const target = event.target instanceof Element ? event.target : null;
      const interactiveTarget = target?.closest("input, textarea, select, button, a, [contenteditable='true']");
      const detailMediaActive =
        state.activePage === "review" &&
        Boolean(state.selectedCase) &&
        Boolean($("#detailHeroMedia")) &&
        !document.querySelector("dialog[open]");
      if (!detailMediaActive || interactiveTarget || event.ctrlKey || event.metaKey || event.altKey) return;
      const activate = (control) => {
        if (!control || control.disabled) return false;
        event.preventDefault();
        control.click();
        return true;
      };
      const key = event.key.toLowerCase();
      if (["b", "c", "v"].includes(key)) {
        const kind = { b: "bev", c: "camera", v: "video" }[key];
        const select = $("#detailMediaKindSelect");
        const option = select?.querySelector(`option[value="${kind}"]`);
        if (select && option && !option.disabled && select.value !== kind) {
          event.preventDefault();
          select.value = kind;
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
      } else if (key === " " && state.detailMedia.kind === "video") {
        event.preventDefault();
        if (!event.repeat) $("#detailHeroMedia")?.querySelector("[data-video-play]")?.click();
      } else if (key === "arrowleft" || key === "arrowright") {
        const direction = key === "arrowleft" ? -1 : 1;
        const control = state.detailMedia.kind === "video"
          ? $("#detailHeroMedia")?.querySelector(`[data-video-jump="${direction}"]`)
          : $(direction < 0 ? "#detailMediaPreviousButton" : "#detailMediaNextButton");
        activate(control);
      } else if (key === "f") {
        if (!event.repeat) activate($("#detailMediaExpandButton"));
      }
      return;
    }
    const intentPreview = Boolean(state.media.snapshot?.intentPreview);
    if (intentPreview) {
      if (event.key === "ArrowLeft") { event.preventDefault(); moveMedia(-1); }
      if (event.key === "ArrowRight") { event.preventDefault(); moveMedia(1); }
      if (event.key === " " && !event.repeat) { event.preventDefault(); cycleIntentMediaKind(); }
      if (event.key.toLowerCase() === "b") switchMediaKind("bev");
      if (event.key.toLowerCase() === "c") switchMediaKind("camera");
    } else {
      if (["ArrowLeft", "ArrowUp", "["].includes(event.key)) { event.preventDefault(); moveMedia(-1); }
      if (["ArrowRight", "ArrowDown", "]"].includes(event.key)) { event.preventDefault(); moveMedia(1); }
      if (event.key.toLowerCase() === "b") switchMediaKind("bev");
      if (event.key.toLowerCase() === "c") switchMediaKind("camera");
      if (event.key.toLowerCase() === "v") switchMediaKind("video");
      if (event.key === " " && state.media.kind === "video") {
        event.preventDefault();
        $("#mediaVideoStage")?.querySelector("[data-video-play]")?.click();
      }
    }
    if (["+", "="].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom + MEDIA_ZOOM_STEP); }
    if (["-", "_"].includes(event.key)) { event.preventDefault(); setMediaZoom(state.media.zoom - MEDIA_ZOOM_STEP); }
    if (event.key === "0") {
      event.preventDefault();
      setMediaZoom(1, { resetScroll: true });
    }
    if (event.key.toLowerCase() === "f") { event.preventDefault(); toggleMediaFullscreen(); }
  });
  window.addEventListener("popstate", async () => {
    const route = parsePageRoute();
    if (route.page === "comparison") {
      if (!state.session.is_admin) {
        showPage("review", { historyMode: "replace" });
        showToast(uiText("Run 对比仅对管理员开放。", "Run comparison is admin-only."), true);
        return;
      }
      applyRunComparisonRoute(route.comparisonFilters);
      showPage("comparison", { restoreRoute: true, loadPageData: false });
      try {
        await loadRunComparison({ historyMode: "" });
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }
    if (route.page === "analysis") {
      const previousRunId = state.selectedRunId;
      const previousFailureOnly = state.failureOnly;
      const previousComparisonStatus = state.reviewAnalysis.comparisonStatus;
      const nextRunId =
        route.runId && state.modelRuns.some((run) => run.id === route.runId)
          ? route.runId
          : "";
      const nextComparisonStatus = nextRunId
        ? normalizedAnalysisComparisonStatus(
            route.analysisFilters.comparisonStatus,
            state.config?.default_failure_only ? "mismatch" : "all"
          )
        : "all";
      state.selectedRunId = nextRunId;
      state.reviewAnalysis.comparisonStatus = nextComparisonStatus;
      state.failureOnly = Boolean(
        nextRunId && nextComparisonStatus === "mismatch"
      );
      if (
        previousRunId !== state.selectedRunId ||
        previousFailureOnly !== state.failureOnly ||
        previousComparisonStatus !== state.reviewAnalysis.comparisonStatus
      ) {
        state.reviewQueueStale = true;
      }
      $("#modelRunFilter").value = nextRunId;
      setReviewComparisonStatus(state.reviewComparisonStatus, {
        hasRun: Boolean(nextRunId),
      });
      renderAnalysisRunFilter();
      applyAnalysisRouteControls(route);
      showPage("analysis", { restoreRoute: true });
      renderActiveRun();
      renderRunManager();
      try {
        await enterAnalysisPage({ includeOverview: true });
      } catch (error) {
        showToast(error.message, true);
      }
      return;
    }
    if (route.page === "trail-update") {
      const nextRunId =
        route.runId && state.modelRuns.some((run) => run.id === route.runId)
          ? route.runId
          : "";
      state.trailUpdate.runId = nextRunId;
      if (typeof applyTrailUpdateRouteControls === "function") {
        applyTrailUpdateRouteControls(route.trailUpdateFilters);
      }
      renderTrailAttributeRunPicker();
      showPage("trail-update", {
        runId: nextRunId,
        restoreRoute: true,
        loadPageData: false,
      });
      if (typeof trailAttributePreviewNeedsLoad !== "function" || trailAttributePreviewNeedsLoad(nextRunId)) {
        try {
          await loadTrailAttributePreview();
        } catch (error) {
          showToast(error.message, true);
        }
      }
      return;
    }
    if (route.page !== "review") {
      showPage(route.page, {
        issues: route.issues,
        source: route.source,
        importKind: route.importKind,
        runId: route.runId,
        restoreRoute: true,
        intentDatasetId: route.intentDatasetId,
        intentCaseId: route.intentCaseId,
        intentOffsetMs: route.intentOffsetMs,
      });
      return;
    }
    const nextRunId =
      route.runId && state.modelRuns.some((run) => run.id === route.runId)
        ? route.runId
        : "";
    const nextComparisonStatus = nextRunId
      ? normalizedReviewComparisonStatus(
          route.comparisonStatus,
          route.failureOnly ? "mismatch" : "all"
        )
      : "all";
    state.selectedRunId = nextRunId;
    $("#modelRunFilter").value = nextRunId;
    state.reviewComparisonStatus = nextComparisonStatus;
    setReviewComparisonStatus(nextComparisonStatus, {
      hasRun: Boolean(nextRunId),
    });
    applyReviewRouteControls(route);
    renderAnalysisRunFilter();
    renderActiveRun();
    renderRunManager();
    if (!route.issue) {
      if (state.selectedId) clearPendingReviewImages();
      clearDetail({ showGallery: true });
    }
    showPage("review", {
      issue: route.issue,
      restoreRoute: true,
    });
    try {
      await Promise.all([
        loadCases({ keepSelection: true, page: route.casePage }),
        loadClusters(),
        loadOverview(),
        loadWorkAssignees(),
      ]);
      if (route.issue) {
        if (route.issue !== state.selectedId || !state.selectedCase) {
          await selectCase(route.issue, { updateRoute: false });
        } else {
          setReviewView(route.issue);
          renderCaseNavigation();
        }
        if (route.openComments) {
          await openAnalysisDiscussion(route.issue, {
            runId: route.runId || "",
            source: "deep-link",
            focusCommentId: route.commentId || 0,
          });
        }
      }
    } catch (error) {
      showToast(error.message, true);
    }
  });
}

async function bootstrap() {
  const initialRoute = parsePageRoute();
  applyColorTheme(
    localStorage.getItem("ra-triage-color-theme") || document.documentElement.dataset.colorTheme,
    { persist: false }
  );
  applyUiLanguage(localStorage.getItem("ra-triage-ui-language") || "zh", { persist: false });
  const savedSidebarState = localStorage.getItem("ra-triage-sidebar-collapsed");
  state.sidebarCollapsed = savedSidebarState === "true";
  applySidebarState();
  markUiReady();
  bindMobileFilterDrawers();
  if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
  bindEvents();
  updateImportFields();
  showPage(initialRoute.page, {
    historyMode: initialRoute.legacyRoute ? "replace" : "",
    issue: initialRoute.issue,
    issues: initialRoute.issues,
    source: initialRoute.source,
    runId: initialRoute.runId,
    importKind: initialRoute.importKind,
    restoreRoute: true,
    loadPageData: false,
    intentDatasetId: initialRoute.intentDatasetId,
    intentCaseId: initialRoute.intentCaseId,
    intentOffsetMs: initialRoute.intentOffsetMs,
  });
  const sessionRequest = resolveSessionInBackground();
  try {
    await settleInitialRequests([loadConfig()], "基础配置");
    if (["users", "comparison", "intent"].includes(initialRoute.page)) {
      await sessionRequest;
    }
    if (["users", "comparison", "intent"].includes(initialRoute.page) && !state.session.is_admin) {
      initialRoute.page = "review";
      showToast(t("toast.admin_only"), true);
    }
    const defaultFailureOnly = Boolean(state.config?.default_failure_only);
    // An implicit team default is selected only after the Run API confirms it
    // has coverage in the active dataset. Explicit route selections are kept.
    state.selectedRunId =
      initialRoute.runId === "none" ? "" : initialRoute.runId || "";
    state.trailUpdate.runId =
      initialRoute.page === "trail-update" && initialRoute.runId !== "none"
        ? initialRoute.runId || ""
        : "";
    if (initialRoute.page === "trail-update" && typeof applyTrailUpdateRouteControls === "function") {
      applyTrailUpdateRouteControls(initialRoute.trailUpdateFilters);
    }
    if (initialRoute.page === "analysis") {
      state.reviewAnalysis.comparisonStatus = state.selectedRunId
        ? normalizedAnalysisComparisonStatus(
            initialRoute.analysisFilters.comparisonStatus,
            defaultFailureOnly ? "mismatch" : "all"
          )
        : "all";
      state.failureOnly =
        state.reviewAnalysis.comparisonStatus === "mismatch";
    } else {
      state.reviewComparisonStatus = state.selectedRunId
          ? normalizedReviewComparisonStatus(
            initialRoute.comparisonStatus,
            "mismatch"
          )
        : "all";
      state.failureOnly = state.reviewComparisonStatus === "mismatch";
    }
    // Resolve the Run before loading queue-dependent facets. Otherwise a
    // dataset can briefly (or permanently, after a race) render counts for an
    // unrelated newest Run.
    await settleInitialRequests(
      [
        loadRuns({
          preferDefault: !initialRoute.runId,
          preserveEmpty: initialRoute.runId === "none",
        }),
      ],
      "模型 Run"
    );
    if (initialRoute.page === "comparison") {
      applyRunComparisonRoute(initialRoute.comparisonFilters);
    }
    const sharedDataPromise = settleInitialRequests(
      [
        loadReviewers(),
        loadWorkAssignees(),
      ],
      "共享数据"
    );
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    if (initialRoute.page === "review") applyReviewRouteControls(initialRoute);
    if (initialRoute.page === "analysis") applyAnalysisRouteControls(initialRoute);
    // Review home: paint cases first; cluster chips are secondary chrome.
    const initialPageRequests = [loadOverview()];
    let initialDetailRequest = null;
    if (initialRoute.page === "review") {
      initialPageRequests.push(
        loadCases({
          keepSelection: Boolean(initialRoute.issue),
          page: initialRoute.casePage,
        })
      );
      if (initialRoute.issue) {
        initialDetailRequest = selectCase(initialRoute.issue, { updateRoute: false });
      }
    } else if (initialRoute.page === "status") {
      initialPageRequests.push(loadStatus());
    } else if (initialRoute.page === "users") {
      initialPageRequests.push(loadAccessUsers(), loadMentionUsers());
    } else if (initialRoute.page === "prediction") {
      initialPageRequests.push(loadPredictionConfig(), loadPredictionBatches());
    } else if (initialRoute.page === "comparison") {
      initialPageRequests.push(loadRunComparison({ historyMode: "" }));
    } else if (initialRoute.page === "intent") {
      initialPageRequests.push(loadIntentLabeling({
        datasetId: initialRoute.intentDatasetId,
        caseId: initialRoute.intentCaseId,
        offsetMs: initialRoute.intentOffsetMs,
      }));
    }
    if (initialRoute.page === "analysis") {
      initialPageRequests.push(loadReviewReasonAnalysis());
    }
    const initialPageResults = settleInitialRequests(
      initialPageRequests,
      initialRoute.page === "review" ? "首页" : "页面"
    );
    // Wait only for the first review-critical payloads; shared Run metadata can
    // finish in the background without holding the case gallery blank.
    if (initialRoute.page === "review") {
      await Promise.all([sharedDataPromise, initialPageResults]);
    } else {
      await sharedDataPromise;
      await initialPageResults;
    }
    setReviewComparisonStatus(state.reviewComparisonStatus, {
      hasRun: Boolean(state.selectedRunId),
    });
    if (initialDetailRequest) {
      await settleInitialRequests([initialDetailRequest], "问题详情");
    }
    if (initialRoute.openComments && initialRoute.issue) {
      await sessionRequest;
      await openAnalysisDiscussion(initialRoute.issue, {
        runId: initialRoute.runId || "",
        source: "deep-link",
        focusCommentId: initialRoute.commentId || 0,
      });
    }
    showPage(initialRoute.page, {
      historyMode: "replace",
      issue: initialRoute.issue,
      issues: initialRoute.issues,
      source: initialRoute.source,
      runId: initialRoute.runId,
      importKind: initialRoute.importKind,
      restoreRoute: true,
      loadPageData: false,
      intentDatasetId: initialRoute.intentDatasetId,
      intentCaseId: initialRoute.intentCaseId,
      intentOffsetMs: initialRoute.intentOffsetMs,
    });
    if (initialRoute.page === "trail-update") {
      // Do not hold the initial shell on the remote Trail read. The local
      // exclusion aggregate paints after navigation; loadTrailAttributePreview
      // then performs its single batched status check asynchronously.
      void loadTrailAttributePreview().catch((error) => showToast(error.message, true));
    }
    if (initialRoute.page === "review") {
      // Defer cluster strip so it does not compete with gallery thumbs.
      window.setTimeout(() => {
        void loadClusters().catch(() => {});
      }, 250);
    }
  } catch (error) {
    showToast(`启动失败：${error.message}`, true);
  }
  startChangePolling();
}

if (document.readyState === "loading") {
  window.addEventListener("DOMContentLoaded", bootstrap, { once: true });
} else {
  bootstrap();
}
