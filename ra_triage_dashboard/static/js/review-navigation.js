/* review-navigation.js
 * Review Issue loading, prefetch, deferred media and navigation cancellation.
 * Classic script; shared globals are initialized before bind-bootstrap.js.
 */

const CASE_DETAIL_PREFETCH_TTL_MS = 15000;
const CASE_DETAIL_PREFETCH_LIMIT = 4;
const TRAIL_DETAIL_DELAY_MS = 350;

function caseCorePath(issueId) {
  let path = `/api/cases/${encodeURIComponent(issueId)}?include_media=false`;
  if (state.selectedRunId) {
    path += `&model_run_id=${encodeURIComponent(state.selectedRunId)}`;
  }
  if (state.reviewWorkSplitId) {
    path += `&work_split_id=${encodeURIComponent(state.reviewWorkSplitId)}`;
  }
  return path;
}

function prefetchCaseCore(issueId) {
  const id = String(issueId || "");
  const key = caseCorePath(id);
  if (!id || id === state.selectedId || state.caseDetailPrefetch.has(key)) return;
  const entry = { createdAt: Date.now(), promise: null, controller: new AbortController() };
  entry.promise = api(key, { cache: "no-store", signal: entry.controller.signal }).catch(() => {
    if (state.caseDetailPrefetch.get(key) === entry) state.caseDetailPrefetch.delete(key);
    return null;
  });
  state.caseDetailPrefetch.set(key, entry);
  while (state.caseDetailPrefetch.size > CASE_DETAIL_PREFETCH_LIMIT) {
    const oldest = state.caseDetailPrefetch.keys().next().value;
    state.caseDetailPrefetch.get(oldest)?.controller?.abort();
    state.caseDetailPrefetch.delete(oldest);
  }
}

async function loadCaseCore(issueId) {
  const key = caseCorePath(issueId);
  const entry = state.caseDetailPrefetch.get(key);
  state.caseDetailPrefetch.delete(key);
  if (entry && Date.now() - entry.createdAt <= CASE_DETAIL_PREFETCH_TTL_MS) {
    state.caseCoreController = entry.controller;
    const prefetched = await entry.promise;
    if (entry.controller?.signal.aborted) throw new DOMException("Aborted", "AbortError");
    if (prefetched) return prefetched;
  }
  entry?.controller?.abort();
  const controller = new AbortController();
  state.caseCoreController = controller;
  return api(key, { cache: "no-store", signal: controller.signal });
}

function prefetchAdjacentCaseCores(issueId) {
  const index = state.cases.findIndex((item) => item.issue_id === issueId);
  if (index < 0) return;
  [state.cases[index - 1], state.cases[index + 1]].forEach((item) => {
    if (item?.issue_id) prefetchCaseCore(item.issue_id);
  });
}

function cancelCaseHydration() {
  releaseBevVideoPlayer($("#detailHeroMedia"));
  state.caseCoreController?.abort();
  state.caseCoreController = null;
  state.caseMediaController?.abort();
  state.caseMediaController = null;
  state.trailMetadataController?.abort();
  state.trailMetadataController = null;
  if (state.trailMetadataTimer !== null) {
    window.clearTimeout(state.trailMetadataTimer);
    state.trailMetadataTimer = null;
  }
}

function scheduleTrailDetailMetadata(issueId, requestSeq) {
  state.trailMetadataTimer = window.setTimeout(() => {
    state.trailMetadataTimer = null;
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId) return;
    const controller = new AbortController();
    state.trailMetadataController = controller;
    void startTrailDetailMetadata(issueId, requestSeq, controller.signal).then((result) => {
      if (state.trailMetadataController === controller) state.trailMetadataController = null;
      applyTrailDetailMetadata(result, issueId, requestSeq);
    });
  }, TRAIL_DETAIL_DELAY_MS);
}

function resumeDeferredReviewRefresh(caseData) {
  if (state.activePage !== "review" || state.selectedCase !== caseData
      || !state.deferredDetailRefresh || state.reviewFormDirty || state.savingAnnotation
      || hasFocusedTextInput($("#reviewPane"))) return;
  void refreshReviewCorePreservingMedia().catch(() => {
    // Keep the deferred flag so the normal collaboration refresh can retry.
  });
}

async function refreshReviewCorePreservingMedia() {
  if (typeof isReviewDecisionEditor === "function" && isReviewDecisionEditor()) return;
  // XIM preedit may not emit input yet. Preserve the focused node, including
  // while media is loading and while a collaboration read is in flight.
  if (hasFocusedTextInput($("#reviewPane"))) { state.deferredDetailRefresh = true; return; }
  const previous = state.selectedCase;
  if (!previous || previous.media_status !== "ready") {
    return selectCase(state.selectedId, { updateRoute: false });
  }
  const context = capturePageContext();
  const data = await api(caseCorePath(previous.issue_id), { cache: "no-store" });
  if (!isPageContextCurrent(context) || state.selectedCase !== previous) return;
  // Edits can begin while the read is in flight; never replace those fields.
  if (hasFocusedTextInput($("#reviewPane")) || state.reviewFormDirty || state.savingAnnotation || state.pendingReviewImages.length
      || caseRationaleUploadTask(previous)) { state.deferredDetailRefresh = true; return; }
  for (const field of ["assets", "camera", "media_status", "preview_thumbnail_url", "external_links", "trail_metadata_status"]) {
    data[field] = previous[field];
  }
  state.selectedCase = data;
  renderDetail(data, { preserveMedia: true });
  renderReview(data);
}

async function selectCase(
  issueId,
  { updateRoute = true, historyMode = "push", preserveScrollY = null } = {}
) {
  if (!issueId || state.activePage !== "review") return;
  if (typeof isReviewDecisionEditor === "function" && isReviewDecisionEditor()) {
    if (caseLabelDecisionUi.saving) return;
    exitCaseDecisionEditor();
  }
  const preservedScrollY = Number.isFinite(Number(preserveScrollY))
    ? Math.max(0, Number(preserveScrollY))
    : null;
  const gallery = $("#reviewGalleryView");
  if (gallery && !gallery.classList.contains("hidden")) {
    state.galleryScrollY = window.scrollY;
  }
  if (state.selectedId && state.selectedId !== issueId) clearPendingReviewImages();
  cancelCaseHydration();
  const hadDetail = Boolean(state.selectedCase);
  state.selectedId = issueId;
  state.selectedCase = null;
  const requestSeq = ++state.caseRequestSeq;
  renderCaseNavigation();
  let loadingTimer = null;
  if (!hadDetail) {
    loadingTimer = window.setTimeout(() => {
      if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId || !isPageContextCurrent(pageContext)) return;
      $("#detailPane").innerHTML = `
          <div class="empty-state detail-loading-state">
          <div class="empty-glyph" aria-hidden="true">…</div>
          <h2>正在加载 ${escapeHtml(issueId)}</h2>
          <p>正在读取 Issue 与模型输出。</p>
        </div>`;
      $("#reviewPane").innerHTML = `
        <div class="review-placeholder"><h2>正在加载标注</h2><p>Issue 数据返回后即可继续 Review。</p></div>`;
    }, 140);
  }
  if (updateRoute && state.activePage === "review") {
    const nextUrl = pageUrl("review", { issue: issueId });
    if (`${window.location.pathname}${window.location.search}` !== nextUrl) {
      showPage("review", {
        historyMode,
        issue: issueId,
        preserveScroll: preservedScrollY !== null,
      });
    } else {
      setReviewView(issueId);
    }
  } else {
    setReviewView(issueId);
    window.scrollTo({ top: 0, behavior: "auto" });
  }
  const pageContext = capturePageContext();
  try {
    // Review text and form state do not depend on filesystem media.  Ask for
    // the lightweight core record first; BEV/video/camera hydrate below.
    const data = await loadCaseCore(issueId);
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId || !isPageContextCurrent(pageContext)) return;
    if (loadingTimer !== null) {
      window.clearTimeout(loadingTimer);
      loadingTimer = null;
    }
    const caseSummary = state.cases.find((item) => item.issue_id === issueId);
    data.preview_thumbnail_url = safeSameOriginAssetUrl(
      caseSummary?.thumbnail?.url || `/api/case-thumbnails/${encodeURIComponent(issueId)}`
    );
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    restoreFailedReviewUploadImages(issueId);
    if (preservedScrollY !== null) {
      window.requestAnimationFrame(() => {
        if (isPageContextCurrent(pageContext)) window.scrollTo({ top: preservedScrollY, behavior: "auto" });
      });
    }
    void loadDeferredCaseMedia(issueId, requestSeq);
    scheduleTrailDetailMetadata(issueId, requestSeq);
    prefetchAdjacentCaseCores(issueId);
  } catch (error) {
    if (requestSeq !== state.caseRequestSeq || state.selectedId !== issueId || !isPageContextCurrent(pageContext)) return;
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

async function loadDeferredCaseMedia(issueId, requestSeq) {
  const controller = new AbortController();
  state.caseMediaController = controller;
  const request = (kind) => api(`/api/cases/${encodeURIComponent(issueId)}/media?kind=${kind}`, {
    cache: "no-store",
    signal: controller.signal,
  }).then(
    (value) => ({ value, error: null }),
    (error) => ({ value: null, error })
  );
  // Start both reads together and paint each independently. A cold media
  // volume must not block already available images or the default video view.
  const videoRequest = request("video");
  const imagesRequest = request("images");
  let hydrated = false;
  const isCurrent = () => (
    requestSeq === state.caseRequestSeq &&
    state.selectedId === issueId &&
    !controller.signal.aborted && state.activePage === "review" &&
    String(state.selectedCase?.issue_id || "") === issueId
  );
  const mergeMedia = (media) => {
    const currentAssets = state.selectedCase.assets || {};
    const nextAssets = media?.assets || {};
    state.selectedCase.assets = {
      ...currentAssets,
      ...nextAssets,
      available: Boolean(
        currentAssets.available || nextAssets.available ||
        currentAssets.video?.url || nextAssets.video?.url ||
        currentAssets.frames?.length || nextAssets.frames?.length
      ),
      frames: nextAssets.frames?.length ? nextAssets.frames : currentAssets.frames || [],
      video: nextAssets.video || currentAssets.video || null,
      capture: Object.keys(nextAssets.capture || {}).length
        ? nextAssets.capture
        : currentAssets.capture || {},
    };
    if (media?.camera?.frames?.length || !state.selectedCase.camera?.frames?.length) {
      state.selectedCase.camera = media?.camera || state.selectedCase.camera;
    }
  };
  try {
    await Promise.all([
      videoRequest.then(videoResult => {
        if (!isCurrent() || !videoResult.value?.assets?.video?.url) return;
        mergeMedia(videoResult.value);
        state.selectedCase.media_status = "ready";
        if (!state.detailMedia.userSelected) state.detailMedia.kind = "video";
        hydrated = hydrateDetailMedia(state.selectedCase) || hydrated;
      }),
      imagesRequest.then(imagesResult => {
        if (!isCurrent() || !imagesResult.value) return;
        mergeMedia(imagesResult.value);
        state.selectedCase.media_status = "ready";
        hydrated = hydrated && state.detailMedia.kind === "video"
          ? hydrateDetailMediaControls(state.selectedCase)
          : hydrateDetailMedia(state.selectedCase) || hydrated;
      }),
    ]);
    if (!isCurrent()) return;
    if (!hydrated) {
      state.selectedCase.media_status = "unavailable";
      renderDetail(state.selectedCase);
    }
  } finally {
    if (state.caseMediaController === controller) state.caseMediaController = null;
  }
}

async function navigateAdjacentCase(delta) {
  const pageContext = capturePageContext();
  if (state.activePage !== "review" || !state.selectedId || ![-1, 1].includes(delta)) return;
  const preserveScrollY = window.scrollY;
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
  if (!isPageContextCurrent(pageContext)) return;
  const target = state.cases[targetIndex];
  if (target) {
    await selectCase(target.issue_id, {
      historyMode: "replace",
      preserveScrollY,
    });
  }
}


function clearDetail({ showGallery = true } = {}) {
  if (typeof isReviewDecisionEditor === "function" && isReviewDecisionEditor()) {
    if (caseLabelDecisionUi.saving) return;
    exitCaseDecisionEditor();
  }
  if (typeof cancelCaseHydration === "function") cancelCaseHydration();
  state.selectedId = "";
  state.selectedCase = null;
  state.caseRequestSeq += 1;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>正在准备 Issue 详情</h2>
      <p>从筛选结果中打开一个 Issue 后，这里会显示 BEV / Camera 与模型输出。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
  renderCaseNavigation();
  if (showGallery) setReviewView("");
}
