/* ra_triage_dashboard/static/js/format-api.js
 * Formatters, API client, change polling, sidebar
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const BASELINE_STORAGE_KEY = "ra-triage-baselines";

function defaultBaselineIdsFromConfig(config = state.config) {
  const fromConfig = config?.default_baseline_ids;
  if (Array.isArray(fromConfig) && fromConfig.length) {
    return fromConfig.map(String);
  }
  const defaults = (config?.baselines || state.baselineCatalog || [])
    .filter((item) => item?.default_selected)
    .map((item) => String(item.id));
  if (defaults.length) return defaults;
  return ["0508"];
}

function normalizeBaselineIds(raw, { allowed = null, fallback = null } = {}) {
  const allowedSet = allowed
    ? new Set([...allowed].map(String))
    : null;
  const values = [];
  const push = (text) => {
    const id = String(text || "").trim();
    if (!id) return;
    if (allowedSet && !allowedSet.has(id)) return;
    if (!values.includes(id)) values.push(id);
  };
  if (Array.isArray(raw)) {
    raw.forEach((item) => {
      String(item || "")
        .split(",")
        .forEach((part) => push(part));
    });
  } else if (raw != null && raw !== "") {
    String(raw)
      .split(",")
      .forEach((part) => push(part));
  }
  if (values.length) return values;
  return (fallback || defaultBaselineIdsFromConfig()).slice();
}

function selectedBaselineQueryValue() {
  const ids = normalizeBaselineIds(state.selectedBaselineIds);
  return ids.join(",");
}

/** Issue count of the currently selected dataset union (not the primary 0508 slot). */
function currentWorksetIssueCount() {
  const catalog = state.baselineCatalog.length
    ? state.baselineCatalog
    : state.config?.baselines || [];
  const selected = new Set(normalizeBaselineIds(state.selectedBaselineIds));
  let total = 0;
  let matched = false;
  for (const item of catalog) {
    const id = String(item?.id || "");
    if (!id || !selected.has(id)) continue;
    const n = Number(item?.count);
    if (Number.isFinite(n) && n >= 0) {
      total += n;
      matched = true;
    }
  }
  if (matched) return total;
  // Fallback: overview metric already reflects current union.
  const stat = Number(
    String($("#statIssues")?.textContent || "").replace(/[^\d]/g, "")
  );
  if (Number.isFinite(stat) && stat > 0) return stat;
  return Number(state.config?.baseline?.count || 0) || 0;
}

function baselineLabelForScope(scope) {
  const normalized = String(scope || "").trim();
  const catalog = state.baselineCatalog.length
    ? state.baselineCatalog
    : state.config?.baselines || [];
  const item = catalog.find((entry) => String(entry?.scope || "") === normalized);
  return item?.label || item?.id || uiText("当前数据集", "Selected dataset");
}

function appendBaselineParams(params) {
  const value = selectedBaselineQueryValue();
  if (value) params.set("baselines", value);
  return params;
}

function withBaselineQuery(path) {
  const value = selectedBaselineQueryValue();
  if (!value) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}baselines=${encodeURIComponent(value)}`;
}

function persistBaselineIds(ids) {
  try {
    localStorage.setItem(BASELINE_STORAGE_KEY, ids.join(","));
  } catch {
    /* ignore quota / private mode */
  }
}

function readStoredBaselineIds() {
  try {
    return localStorage.getItem(BASELINE_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function renderBaselinePicker() {
  const root = $("#baselineFilter");
  if (!root || typeof renderMultiFilter !== "function") return;
  const catalog = state.baselineCatalog.length
    ? state.baselineCatalog
    : state.config?.baselines || [];
  const options = catalog.map((item) => {
    const count =
      item.count != null && item.count !== ""
        ? ` · ${item.count}`
        : item.status === "ready"
          ? ""
          : "";
    return {
      value: String(item.id),
      label: `${item.label || item.id}${count}`,
    };
  });
  renderMultiFilter(root, {
    options,
    selected: state.selectedBaselineIds,
    onlyThis: true,
    onChange: () => {
      const next = getMultiFilterValues(root);
      void setBaselineScopes(next);
    },
  });
}

function inferredBaselineIdsFromRun(run) {
  if (!run || typeof run !== "object") return [];
  const allowed = new Set(
    (state.baselineCatalog.length
      ? state.baselineCatalog
      : state.config?.baselines || []
    ).map((item) => String(item.id))
  );
  return normalizeBaselineIds(run.inferred_baseline_ids || [], {
    allowed: allowed.size ? allowed : null,
    fallback: [],
  });
}

/**
 * After import / Run 选择：按预测命中的 GT scope 自动勾选顶栏数据集。
 * 单集评测（常见）→ 仅选中那一集；混合则选中所有命中集。
 */
async function applyInferredBaselinesFromRun(
  run,
  { reason = "run", reloadActivePage = true } = {}
) {
  const inferred = inferredBaselineIdsFromRun(run);
  if (!inferred.length) return false;
  const current = selectedBaselineQueryValue();
  const next = inferred.join(",");
  if (current === next) return false;
  await setBaselineScopes(inferred, { reloadActivePage });
  const labels = inferred
    .map((id) => {
      const item = (state.baselineCatalog || []).find((row) => String(row.id) === id);
      return item?.label || id;
    })
    .join("、");
  if (reason === "import") {
    showToast(
      uiText(
        `已自动切换数据集：${labels}`,
        `Dataset auto-selected: ${labels}`
      )
    );
  }
  return true;
}

async function setBaselineScopes(
  rawIds,
  { skipHistory = false, reloadActivePage = true } = {}
) {
  const allowed = new Set(
    (state.baselineCatalog.length
      ? state.baselineCatalog
      : state.config?.baselines || []
    ).map((item) => String(item.id))
  );
  const fallback = defaultBaselineIdsFromConfig();
  let next = normalizeBaselineIds(rawIds, {
    allowed: allowed.size ? allowed : null,
    fallback,
  });
  if (!next.length) {
    next = fallback.slice();
    showToast(uiText("至少保留一个数据集。", "Keep at least one dataset."), true);
  }
  const prev = selectedBaselineQueryValue();
  const nextValue = next.join(",");
  if (prev === nextValue && state.selectedBaselineIds.join(",") === nextValue) {
    renderBaselinePicker();
    return;
  }
  state.selectedBaselineIds = next;
  persistBaselineIds(next);
  // Workset-level hard reset (stronger than filter change).
  state.selectedId = "";
  state.selectedCase = null;
  state.casePage = 1;
  state.clusterKey = "";
  state.reviewIssueIds = [];
  state.reviewAnalysis.data = null;
  state.caseListRequestSeq += 1;
  state.caseRequestSeq += 1;
  state.reviewAnalysis.requestSeq += 1;
  if (typeof clearDetail === "function") {
    clearDetail({ showGallery: state.activePage === "review" });
  }
  renderBaselinePicker();
  if (!skipHistory && typeof pageUrl === "function") {
    const nextUrl = pageUrl(state.activePage || "review", {
      issue: "",
      baselines: next,
    });
    window.history.replaceState(window.history.state || {}, "", nextUrl);
  }
  try {
    await loadConfig();
    // Resolve the compatible Run first: the remaining facets and overview all
    // depend on the final overlay selection.
    await loadRuns({ preserveEmpty: true, clearIncompatible: true });
    await settleInitialRequests(
      [
        loadReviewers(),
        typeof loadWorkAssignees === "function"
          ? loadWorkAssignees()
          : Promise.resolve(),
        loadOverview(),
      ],
      uiText("切换数据集后", "After dataset switch")
    );
    if (!reloadActivePage) return;
    if (state.activePage === "analysis") {
      await enterAnalysisPage({ includeOverview: false });
    } else if (state.activePage === "review") {
      await loadCases({ keepSelection: false, page: 1 });
      if (typeof loadClusters === "function") await loadClusters();
    } else if (state.activePage === "runs") {
      await loadRuns({ preserveEmpty: true });
    } else if (state.activePage === "trail-update") {
      await loadTrailAttributePreview(true);
    } else if (state.activePage === "comparison") {
      state.runComparison.page = 1;
      await loadRunComparison();
    }
  } catch (error) {
    showToast(error.message || String(error), true);
  }
}

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function aresStudioUrl(caseData, issueUrl) {
  const externalLinks = caseData?.external_links || {};
  const tripId = String(
    caseData?.assets?.capture?.trip_id ||
    caseData?.trip_id ||
    externalLinks.ares_trip_id ||
    ""
  ).trim();
  const issueId = String(caseData?.issue_id || "").trim();
  const timestampMs = Number(
    caseData?.assets?.capture?.timestamp_ms ||
    caseData?.camera?.capture?.timestamp_ms ||
    externalLinks.ares_timestamp_ms
  );
  if (!issueUrl || !issueId || !tripId || !Number.isFinite(timestampMs) || timestampMs <= 0) return "";
  try {
    const url = new URL("/static/ares-studio/", issueUrl);
    url.searchParams.set("ds", "voy-ws-car");
    url.searchParams.set("ds.issue_id", issueId);
    url.searchParams.set("ds.trip_id", tripId);
    url.searchParams.set("ds.start", String(Math.round(timestampMs - 10000)));
    url.searchParams.set("ds.end", String(Math.round(timestampMs + 10000)));
    url.searchParams.set("entry_last_page", `/issue/${issueId}`);
    return safeUrl(url.href);
  } catch {
    return "";
  }
}

function safeSameOriginAssetUrl(url) {
  try {
    const parsed = new URL(String(url || ""), window.location.origin);
    const pathname = stripBasePath(parsed.pathname);
    if (parsed.origin !== window.location.origin || !pathname.startsWith("/api/")) return "";
    return `${withBase(pathname)}${parsed.search}`;
  } catch {
    return "";
  }
}

function labelBadge(label, fallback = "—") {
  const actual = label || "";
  const className = MODEL_LABELS.includes(actual) ? `label-${actual}` : "label-empty";
  return `<span class="label-badge ${className}">${escapeHtml(actual || fallback)}</span>`;
}

function formatModelConfidence(value) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric.toFixed(3);
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function evidenceLabel(key) {
  const value = String(key || "");
  const catalogItem = state.config?.missing_evidence_catalog?.find(
    (item) => String(item.key) === value
  );
  if (catalogItem?.label) return catalogItem.label;
  if (value.startsWith("custom:")) {
    const legacyLabel = value.slice("custom:".length);
    return legacyLabel && !/^[a-f0-9]{24,64}$/i.test(legacyLabel)
      ? legacyLabel
      : "自定义缺失信息";
  }
  return value;
}

function missingEvidenceOptionMarkup(item, selected = false, manage = true) {
  const key = String(item?.key || "");
  const deleted = Boolean(item?.deleted);
  const label = String(item?.label || evidenceLabel(key));
  const hint = String(
    item?.hint || (deleted ? "已从共享目录删除；当前 Review 仍保留此历史值" : "")
  );
  // Match Issue-tag chips: compact option + in-chip ⋯ menu for edit/delete.
  const canManage = Boolean(manage && !deleted);
  if (!canManage) {
    return `<label class="tag-option evidence-tag-option${deleted ? " tag-option-deleted" : ""}" data-evidence-option="${escapeHtml(key)}"${hint ? ` title="${escapeHtml(hint)}"` : ""}>
      <input type="checkbox" name="missingEvidence" value="${escapeHtml(key)}" ${selected ? "checked" : ""} />
      <span>${escapeHtml(label)}</span>
    </label>`;
  }
  return `<div class="review-tag-option-row" data-evidence-option="${escapeHtml(key)}">
    <div class="tag-option tag-option-with-menu evidence-tag-option${deleted ? " tag-option-deleted" : ""}"${hint ? ` title="${escapeHtml(hint)}"` : ""}>
      <label class="tag-option-check">
        <input type="checkbox" name="missingEvidence" value="${escapeHtml(key)}" ${selected ? "checked" : ""} />
        <span>${escapeHtml(label)}</span>
      </label>
      <div class="tag-option-menu">
        <button class="tag-option-menu-toggle" type="button" data-tag-menu-toggle="evidence-${escapeHtml(key)}" aria-label="缺失信息操作" aria-haspopup="menu" aria-expanded="false" title="更多操作">⋯</button>
        <div class="tag-option-menu-panel" role="menu" hidden>
          <button class="tag-option-menu-item" type="button" role="menuitem" data-edit-missing-evidence="${escapeHtml(key)}">修改</button>
          <button class="tag-option-menu-item is-danger" type="button" role="menuitem" data-delete-missing-evidence="${escapeHtml(key)}">删除</button>
        </div>
      </div>
    </div>
  </div>`;
}

function tagLabel(key) {
  const value = String(key || "");
  const catalogItem = state.config?.review_tag_catalog?.find(
    (item) => String(item.key) === value
  );
  if (catalogItem?.label) return catalogItem.label;
  if (value.startsWith("custom:")) return value.slice("custom:".length) || value;
  return value;
}

function reviewTagCatalogItem(key) {
  return (state.config?.review_tag_catalog || []).find(
    (item) => String(item.key) === String(key)
  );
}

function reviewTagOptionMarkup(item, selected = false, groupKey = "", manage = true) {
  const key = String(item?.key || "");
  const label = String(item?.label || tagLabel(key));
  const hint = String(item?.hint || "");
  const deleted = Boolean(item?.deleted);
  const canManage = Boolean(manage && !deleted);
  if (!canManage) {
    return `<label class="tag-option${deleted ? " tag-option-deleted" : ""}"${hint ? ` title="${escapeHtml(hint)}"` : ""}>
      <input type="checkbox" name="reviewTags" value="${escapeHtml(key)}"${groupKey ? ` data-tag-group="${escapeHtml(groupKey)}"` : ""} ${selected ? "checked" : ""} />
      <span>${escapeHtml(label)}</span>
    </label>`;
  }
  // Manage actions live inside the option chip via a ⋯ menu (edit / delete).
  return `<div class="review-tag-option-row" data-review-tag-option="${escapeHtml(key)}">
    <div class="tag-option tag-option-with-menu${deleted ? " tag-option-deleted" : ""}"${hint ? ` title="${escapeHtml(hint)}"` : ""}>
      <label class="tag-option-check">
        <input type="checkbox" name="reviewTags" value="${escapeHtml(key)}"${groupKey ? ` data-tag-group="${escapeHtml(groupKey)}"` : ""} ${selected ? "checked" : ""} />
        <span>${escapeHtml(label)}</span>
      </label>
      <div class="tag-option-menu">
        <button class="tag-option-menu-toggle" type="button" data-tag-menu-toggle="${escapeHtml(key)}" aria-label="标签操作" aria-haspopup="menu" aria-expanded="false" title="更多操作">⋯</button>
        <div class="tag-option-menu-panel" role="menu" hidden>
          <button class="tag-option-menu-item" type="button" role="menuitem" data-edit-review-tag="${escapeHtml(key)}">修改</button>
          <button class="tag-option-menu-item is-danger" type="button" role="menuitem" data-delete-review-tag="${escapeHtml(key)}">删除</button>
        </div>
      </div>
    </div>
  </div>`;
}

function frameLabel(frame) {
  if (frame.offset_ms !== undefined && frame.offset_ms !== null) {
    const seconds = Math.round(Number(frame.offset_ms) / 1000);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  if (frame.offset_sec !== undefined && frame.offset_sec !== null) {
    const seconds = Number(frame.offset_sec);
    return `${seconds >= 0 ? "+" : ""}${seconds}s`;
  }
  return frame.frame_number !== undefined ? `#${frame.frame_number}` : "帧";
}

function normalizeApiPayloadUrls(value) {
  if (Array.isArray(value)) return value.map((item) => normalizeApiPayloadUrls(item));
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => {
      if (
        typeof item === "string" &&
        (key === "url" || key.endsWith("_url"))
      ) {
        return [key, withBase(item)];
      }
      return [key, normalizeApiPayloadUrls(item)];
    })
  );
}

async function api(path, options = {}) {
  const method = String(options.method || "GET").toUpperCase();
  const isMutation = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
  // Some POST endpoints are semantically read-only previews (for example a
  // Trail draft whose body contains a Comment).  They may be called from a
  // read-only session, but the server still owns the final write gate.
  const allowReadOnlyMutation = options.allowReadOnlyMutation === true;
  const requestOptions = { ...options };
  delete requestOptions.allowReadOnlyMutation;
  const retryableGet = method === "GET";
  if (
    state.session?.read_only &&
    isMutation &&
    !allowReadOnlyMutation
  ) {
    throw new Error(
      uiText(
        "当前入口为只读预览；请通过获准的企业 SSO 域名访问。",
        "This endpoint is read-only; use the approved enterprise SSO domain."
      )
    );
  }
  let lastError = null;
  for (let attempt = 0; attempt < (retryableGet ? API_GET_MAX_ATTEMPTS : 1); attempt += 1) {
    const controller = retryableGet && !options.signal ? new AbortController() : null;
    const timeoutId = controller
      ? window.setTimeout(() => controller.abort(), API_GET_TIMEOUT_MS)
      : null;
    let response;
    let payload = {};
    try {
      response = await fetch(withBase(path), {
        ...requestOptions,
        ...(controller ? { signal: controller.signal } : {}),
        headers: {
          ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
          ...(isMutation ? { "X-RA-Triage-Request": "browser-v1" } : {}),
          ...(options.headers || {}),
        },
      });
      payload = normalizeApiPayloadUrls(
        await response.json().catch((error) => {
          if (error?.name === "AbortError") throw error;
          return {};
        })
      );
    } catch (error) {
      response = null;
      lastError = error;
      const timedOut = error?.name === "AbortError";
      const callerAborted = Boolean(options.signal?.aborted);
      if (!retryableGet || callerAborted || attempt >= API_GET_MAX_ATTEMPTS - 1) {
        if (timedOut) throw new Error("请求超时，请稍后重试。");
        throw error;
      }
    } finally {
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    }
    if (response) {
      if (response.ok) return payload;
      const message = payload.detail || `请求失败 (${response.status})`;
      if (
        !retryableGet ||
        !API_GET_RETRYABLE_STATUSES.has(response.status) ||
        attempt >= API_GET_MAX_ATTEMPTS - 1
      ) {
        throw new Error(message);
      }
      lastError = new Error(message);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250 * (attempt + 1)));
  }
  throw lastError || new Error("请求失败，请稍后重试。");
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden", "error");
  if (isError) toast.classList.add("error");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 4600);
}

function acknowledgeLocalChange(payload) {
  const revision = Number(payload?.change_revision);
  if (Number.isFinite(revision)) state.changeRevision = revision;
  // A poll that started before this mutation can still return the old
  // revision.  Invalidate that response so it cannot reselect the case.
  state.changePollEpoch += 1;
  state.deferredDetailRefresh = false;
}

async function refreshChangedData() {
  const reviewerSelections = typeof reviewerFilterSelections === "function"
    ? reviewerFilterSelections()
    : undefined;
  if (state.activePage === "review") {
    await Promise.all([
      loadConfig(),
      loadRuns({ preserveEmpty: !state.selectedRunId }),
      loadOverview(),
      loadCases({ keepSelection: true, page: state.casePage }),
      loadClusters(),
      loadReviewers(reviewerSelections),
      typeof loadWorkAssignees === "function"
        ? loadWorkAssignees()
        : Promise.resolve(),
    ]);
    if (state.selectedId) {
      if (
        state.reviewFormDirty ||
        state.savingAnnotation ||
        state.pendingReviewImages.length
      ) {
        if (!state.deferredDetailRefresh) {
          state.deferredDetailRefresh = true;
          showToast("检测到新的协作更新；当前未保存内容已保留，保存后会合并最新数据。");
        }
      } else {
        await selectCase(state.selectedId, { updateRoute: false });
      }
    }
    return;
  }
  if (state.activePage === "analysis") {
    await Promise.all([
      loadConfig(),
      loadRuns({ preserveEmpty: !state.selectedRunId }),
      loadOverview(),
      loadReviewers(reviewerSelections),
      loadReviewReasonAnalysis(),
    ]);
    return;
  }
  if (state.activePage === "runs") {
    await Promise.all([loadRuns({ preserveEmpty: true }), loadOverview()]);
    return;
  }
  if (state.activePage === "comparison") {
    await Promise.all([
      loadRuns({ preserveEmpty: true }),
      loadOverview(),
    ]);
    if (state.session.is_admin) await loadRunComparison();
    return;
  }
  if (state.activePage === "trail-update") {
    // Shared change-revision polling must not refresh Trail status behind the
    // operator's back. The top-bar Refresh button is the explicit refresh
    // boundary for this page.
    return;
  }
  if (state.activePage === "prediction") {
    await Promise.all([loadPredictionBatches(), loadOverview()]);
    return;
  }
  if (state.activePage === "intent") {
    const intent = state.intentLabeling;
    if (!intent.datasetId) return;
    const selected = [...(intent.selectedAssignees || [])];
    intent.assigneeDatasetId = "";
    try {
      await loadIntentAssignees(intent.datasetId, selected, intent.selectedExperimentId);
    } catch (error) {
      if (!intent.selectedExperimentId) throw error;
      // A manager may have just closed the selected experiment in another tab.
      // Fall back to all active assignments instead of leaving stale controls.
      intent.assigneeDatasetId = "";
      await loadIntentAssignees(intent.datasetId, selected, "");
    }
    return;
  }
  if (state.activePage === "intent-experiments") {
    state.intentLabeling.experimentsDatasetId = "";
    await loadIntentExperiments({ force: true });
    return;
  }
  if (state.activePage === "intent-summary") {
    await loadIntentSummary({ datasetId: state.intentLabeling.summaryDatasetId, force: true });
    return;
  }
  if (state.activePage === "status") {
    await loadStatus();
  }
}

function scheduleChangePoll(delay = 5000) {
  clearTimeout(state.changePollTimer);
  state.changePollTimer = window.setTimeout(pollChangeRevision, delay);
}

async function pollChangeRevision() {
  if (state.changePollInFlight) return scheduleChangePoll();
  // Tab in background: poll much less often to free the main thread / network.
  if (document.hidden) return scheduleChangePoll(15000);
  state.changePollInFlight = true;
  const pollEpoch = state.changePollEpoch;
  let delay = 5000;
  try {
    // GT sync status is heavier than a revision counter; refresh it every ~20s
    // instead of every collaboration poll.
    const now = Date.now();
    const wantGtSync =
      !state._lastGtSyncPollAt || now - state._lastGtSyncPollAt > 20000;
    const path = wantGtSync
      ? "/api/change-revision?include_gt_sync=1"
      : "/api/change-revision";
    const data = await api(path);
    if (pollEpoch !== state.changePollEpoch) return;
    if (data.gt_sync) {
      state._lastGtSyncPollAt = now;
      state.gtSync = data.gt_sync;
      if (state.config) state.config.gt_sync = data.gt_sync;
      renderGtSyncStatus(data.gt_sync);
    }
    const revision = Number(data.revision || 0);
    delay = Math.max(4000, Number(data.poll_after_ms || 5000));
    if (state.changeRevision === null) {
      state.changeRevision = revision;
    } else if (revision !== state.changeRevision) {
      await refreshChangedData();
      state.changeRevision = revision;
    }
  } catch (error) {
    delay = 10000;
    console.warn("协作同步暂时不可用", error);
  } finally {
    state.changePollInFlight = false;
    scheduleChangePoll(delay);
  }
}

function startChangePolling() {
  // Do not compete with first-paint gallery/thumbnail traffic.
  scheduleChangePoll(4000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleChangePoll(1500);
  });
}

function isMobileSidebarViewport() {
  return typeof window.matchMedia === "function" && window.matchMedia("(max-width: 639px)").matches;
}

function applySidebarState() {
  const mobile = isMobileSidebarViewport();
  const shell = $("#appShell");
  // Phones keep a narrow logo rail; the existing desktop collapse preference must
  // not turn the mobile drawer into a horizontal tab bar or change desktop state.
  shell.classList.toggle("sidebar-collapsed", mobile ? true : state.sidebarCollapsed);
  shell.classList.toggle("sidebar-mobile-open", mobile && state.mobileSidebarOpen);
  // Keep early-paint pref in sync so hard refresh matches the collapsed width without layout transition.
  if (!mobile && state.sidebarCollapsed) {
    document.documentElement.dataset.sidebarPref = "collapsed";
  } else {
    delete document.documentElement.dataset.sidebarPref;
  }
  const expanded = String(mobile ? state.mobileSidebarOpen : !state.sidebarCollapsed);
  const title = mobile
    ? (state.mobileSidebarOpen
      ? uiText("关闭工具栏", "Close navigation")
      : uiText("打开工具栏", "Open navigation"))
    : (state.sidebarCollapsed
      ? uiText("展开工具栏", "Expand toolbar")
      : uiText("折叠工具栏", "Collapse toolbar"));
  $("#sidebarToggle").setAttribute("aria-expanded", expanded);
  $("#sidebarToggle").title = `${title}（\\）`;
  $("#sidebarToggle").setAttribute("aria-label", title);
  $("#sidebarToggle").hidden = mobile;
  $("#sidebarBrandToggle").setAttribute("aria-expanded", expanded);
  $("#sidebarBrandToggle").title = title;
  $("#sidebarBrandToggle").setAttribute("aria-label", title);
  const backdrop = $("#mobileSidebarBackdrop");
  if (backdrop) backdrop.hidden = !(mobile && state.mobileSidebarOpen);
  document.documentElement.classList.toggle("mobile-sidebar-open", mobile && state.mobileSidebarOpen);
}

function markUiReady() {
  // Enable layout transitions only after the first settled frame (avoids CSS-load LTR wipe).
  if (document.documentElement.classList.contains("ra-ui-ready")) return;
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      document.documentElement.classList.add("ra-ui-ready");
    });
  });
}

/** Mobile: collapse dense filter forms so gallery/charts appear above the fold. */
function bindMobileFilterDrawers() {
  const mq = window.matchMedia("(max-width: 639px)");
  const panels = [...document.querySelectorAll("[data-mobile-filter-panel]")];
  if (!panels.length) return;

  const setOpen = (panel, open) => {
    const key = panel.dataset.mobileFilterPanel;
    panel.classList.toggle("is-open", open);
    document
      .querySelectorAll(`[data-mobile-filter-toggle="${CSS.escape(key)}"]`)
      .forEach((button) => {
        button.setAttribute("aria-expanded", String(open));
        button.classList.toggle("is-active", open);
        const hint = button.querySelector(`[data-mobile-filter-hint="${CSS.escape(key)}"]`);
        if (hint) {
          hint.textContent = open
            ? uiText("收起", "Hide")
            : uiText("展开条件", "Show filters");
        }
      });
  };

  const syncToViewport = () => {
    panels.forEach((panel) => setOpen(panel, !mq.matches));
  };

  document.querySelectorAll("[data-mobile-filter-toggle]").forEach((button) => {
    if (button.dataset.boundMobileFilter === "1") return;
    button.dataset.boundMobileFilter = "1";
    button.addEventListener("click", () => {
      const key = button.dataset.mobileFilterToggle;
      const panel = document.querySelector(
        `[data-mobile-filter-panel="${CSS.escape(key)}"]`
      );
      if (!panel) return;
      setOpen(panel, !panel.classList.contains("is-open"));
    });
  });

  if (typeof mq.addEventListener === "function") {
    mq.addEventListener("change", syncToViewport);
  } else if (typeof mq.addListener === "function") {
    mq.addListener(syncToViewport);
  }
  syncToViewport();
}

function toggleSidebar() {
  if (isMobileSidebarViewport()) {
    state.mobileSidebarOpen = !state.mobileSidebarOpen;
    applySidebarState();
    return;
  }
  state.sidebarCollapsed = !state.sidebarCollapsed;
  localStorage.setItem("ra-triage-sidebar-collapsed", String(state.sidebarCollapsed));
  applySidebarState();
}

function closeMobileSidebar() {
  if (!state.mobileSidebarOpen) return;
  state.mobileSidebarOpen = false;
  applySidebarState();
}
