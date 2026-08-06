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

function safeUrl(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

function aresStudioUrl(caseData, issueUrl) {
  const tripId = String(caseData?.assets?.capture?.trip_id || caseData?.trip_id || "").trim();
  const issueId = String(caseData?.issue_id || "").trim();
  const timestampMs = Number(
    caseData?.assets?.capture?.timestamp_ms || caseData?.camera?.capture?.timestamp_ms
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
  const className = LABELS.includes(actual) ? `label-${actual}` : "label-empty";
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
  const retryableGet = method === "GET";
  if (
    state.session?.read_only &&
    isMutation
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
        ...options,
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
  if (state.activePage === "review") {
    await Promise.all([
      loadConfig(),
      loadRuns({ preserveEmpty: !state.selectedRunId }),
      loadOverview(),
      loadCases({ keepSelection: true, page: state.casePage }),
      loadClusters(),
      loadReviewers(),
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
      loadReviewers(),
      loadReviewReasonAnalysis(),
    ]);
    return;
  }
  if (state.activePage === "runs") {
    await Promise.all([loadRuns({ preserveEmpty: true }), loadOverview()]);
    return;
  }
  if (state.activePage === "prediction") {
    await Promise.all([loadPredictionBatches(), loadOverview()]);
    return;
  }
  if (state.activePage === "status") {
    await loadStatus();
  }
}

function scheduleChangePoll(delay = 1800) {
  clearTimeout(state.changePollTimer);
  state.changePollTimer = window.setTimeout(pollChangeRevision, delay);
}

async function pollChangeRevision() {
  if (state.changePollInFlight) return scheduleChangePoll();
  if (document.hidden) return scheduleChangePoll(3000);
  state.changePollInFlight = true;
  const pollEpoch = state.changePollEpoch;
  let delay = 1800;
  try {
    const data = await api("/api/change-revision");
    if (pollEpoch !== state.changePollEpoch) return;
    const revision = Number(data.revision || 0);
    delay = Math.max(1000, Number(data.poll_after_ms || 1800));
    if (state.changeRevision === null) {
      state.changeRevision = revision;
    } else if (revision !== state.changeRevision) {
      await refreshChangedData();
      state.changeRevision = revision;
    }
  } catch (error) {
    delay = 5000;
    console.warn("协作同步暂时不可用", error);
  } finally {
    state.changePollInFlight = false;
    scheduleChangePoll(delay);
  }
}

function startChangePolling() {
  scheduleChangePoll(0);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) scheduleChangePoll(0);
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
  $("#sidebarToggle").title = title;
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
