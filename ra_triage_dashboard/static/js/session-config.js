/* ra_triage_dashboard/static/js/session-config.js
 * Session, config, access users, overview
 * Loaded as a classic script (shared global scope). Do not convert to
 * ES modules without auditing cross-file function/state dependencies.
 */
function validDisplayName(value) {
  const username = String(value || "").trim();
  return /^[A-Za-z0-9._@-]{1,128}$/.test(username) ? username : "";
}

async function browserLcaUsername() {
  const endpoints =
    window.location.protocol === "https:"
      ? ["https://127.0.0.1:19888/lcainfo"]
      : ["http://127.0.0.1:18888/lcainfo"];
  for (const endpoint of endpoints) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 1500);
    try {
      const response = await fetch(endpoint, {
        credentials: "omit",
        mode: "cors",
        signal: controller.signal,
      });
      if (!response.ok) continue;
      const payload = await response.json();
      const username = validDisplayName(payload?.LocalUserAccount);
      if (username) return username;
    } catch {
      // LCA is an optional display-name fallback on direct-IP deployments.
    } finally {
      clearTimeout(timer);
    }
  }
  return "";
}

function renderSession() {
  if (typeof updateWorkSplitAdminVisibility === "function") {
    updateWorkSplitAdminVisibility();
  }
  const username = state.session.username;
  const identityPending = Boolean(state.session.identity_pending);
  $("#sessionUserName").textContent = username || (identityPending
    ? t("session.identifying")
    : t("session.unidentified"));
  $("#userAvatar").textContent = username ? username.slice(0, 1).toUpperCase() : "?";
  $("#sessionUserSource").textContent = state.session.read_only
    ? t("session.readonly")
    : state.session.verified
    ? t("session.sso")
    : identityPending
      ? t("session.page_ready")
      : username
      ? t("session.lca")
      : t("session.current");
  $("#sidebarUser").title = state.session.verified
    ? uiText(`可信代理认证：${username}`, `Trusted proxy auth: ${username}`)
    : username
      ? uiText(`本机 LCA 用户：${username}（仅作显示与默认标注人）`, `Local LCA user: ${username} (display / default reviewer only)`)
      : uiText("当前没有可用的用户名", "No username available");
  const logoutLink = $("#sessionLogoutLink");
  if (logoutLink) {
    const logoutUrl = String(state.session.logout_url || "");
    logoutLink.hidden = !logoutUrl || identityPending;
    logoutLink.href = logoutUrl || "#";
    logoutLink.textContent = state.session.verified
      ? t("session.sign_out")
      : t("session.sign_in");
  }
  document.documentElement.dataset.accessMode = state.session.read_only
    ? "read-only"
    : "write";
  const userManagementNav = $("#userManagementNavButton");
  if (userManagementNav) userManagementNav.hidden = !state.session.is_admin;
  const intentLabelingNav = $("#intentLabelingNavButton");
  if (intentLabelingNav) intentLabelingNav.hidden = !["writer", "admin"].includes(state.session.access_role);
  const intentExperimentsNav = $("#intentExperimentsNavButton");
  if (intentExperimentsNav) intentExperimentsNav.hidden = !state.session.is_admin;
  const runComparisonNav = $("#runComparisonNavButton");
  if (runComparisonNav) runComparisonNav.hidden = false;
  const batchActor = $("#batchActorSummary");
  if (batchActor) {
    batchActor.textContent = state.session.verified
      ? uiText(`当前用户：${username}（企业 SSO 已验证）`, `Current user: ${username} (enterprise SSO verified)`)
      : username
        ? uiText(`当前用户：${username}（本机 LCA，仅作审计显示）`, `Current user: ${username} (local LCA, display only)`)
        : uiText("当前用户未识别；服务器会按实际会话记录请求人。", "User not identified; the server records the actual requester.");
  }
  const importActor = $("#modelImportActorSummary");
  if (importActor) {
    importActor.textContent = state.session.verified
      ? uiText(`本次导入创建人：${username}（企业 SSO 已验证）`, `Import owner: ${username} (enterprise SSO verified)`)
      : username
        ? uiText(`本次导入显示名：${username}（本机 LCA，未验证；不能用于权限）`, `Import display name: ${username} (local LCA, unverified; not for authorization)`)
        : uiText("当前没有可信 SSO；Run 创建人将记为未记录。", "No trusted SSO; the Run creator will be recorded as unknown.");
  }
  if (state.activePage === "prediction") ensurePredictionBatchName();
  if (typeof renderGtSyncStatus === "function") renderGtSyncStatus();
}

async function loadSession() {
  const serverSession = await api("/api/session");
  if (serverSession.authenticated && validDisplayName(serverSession.username)) {
    state.session = serverSession;
    renderSession();
    try {
      await loadMentionUsers();
    } catch (_error) {
      state.mentionUsers = [];
      renderMentionUsers();
    }
    return;
  }
  state.session = {
    username: "",
    source: "anonymous",
    identity_pending: Boolean(serverSession.browser_lca_fallback),
    authenticated: false,
    verified: false,
    is_admin: false,
    access_role: "viewer",
    can_manage_team_default: false,
    can_write: serverSession.can_write !== false,
    read_only: Boolean(serverSession.read_only),
  };
  renderSession();
  if (!serverSession.browser_lca_fallback) return;
  // Local LCA is only a display-name fallback.  It can take up to 1.5s and
  // must never hold the Review gallery or a deep-linked Issue behind it.
  void browserLcaUsername().then((username) => {
    if (state.session.authenticated || state.session.verified) return;
    state.session = {
      ...state.session,
      username,
      source: username ? "browser_lca_unverified" : "anonymous",
      identity_pending: false,
    };
    renderSession();
  }).catch(() => {
    state.session = { ...state.session, identity_pending: false };
    renderSession();
  });
}

function multiFilterOptionHtml(item, selectedSet, { onlyThis = false } = {}) {
  const value = String(item.value ?? item.key ?? "");
  const label = String(item.label ?? value);
  const onlyButton = onlyThis
    ? `<button type="button" class="multi-filter-only" data-multi-only="${escapeHtml(value)}" title="只选这一项" aria-label="只选 ${escapeHtml(label)}">仅此项</button>`
    : "";
  return `<div class="multi-filter-option-row${onlyThis ? " has-only" : ""}">
    <label class="multi-filter-option">
      <input type="checkbox" data-multi-value="${escapeHtml(value)}" data-label="${escapeHtml(label)}" value="${escapeHtml(value)}"${selectedSet.has(value) ? " checked" : ""} />
      <span>${escapeHtml(label)}</span>
    </label>
    ${onlyButton}
  </div>`;
}

function multiFilterAllValues(root) {
  if (!root) return [];
  return [...root.querySelectorAll('input[type="checkbox"][data-multi-value]')].map(
    (input) => input.value
  );
}

function renderMultiFilter(
  root,
  {
    options = [],
    groups = null,
    selected = null,
    onChange = null,
    onlyThis = false,
  } = {}
) {
  if (!root || root.matches?.("select")) return;
  const previous = selected == null ? getMultiFilterValues(root) : parseFilterList(selected);
  const selectedSet = new Set(previous);
  const optionOpts = { onlyThis: Boolean(onlyThis) };
  const body = groups?.length
    ? groups
        .map(
          (group) => `<div class="multi-filter-group">
        <div class="multi-filter-group-label">${escapeHtml(group.label)}</div>
        ${(group.items || [])
          .map((item) => multiFilterOptionHtml(item, selectedSet, optionOpts))
          .join("")}
      </div>`
        )
        .join("")
    : options
        .map((item) => multiFilterOptionHtml(item, selectedSet, optionOpts))
        .join("");
  root.classList.toggle("has-only-actions", Boolean(onlyThis));
  root.innerHTML = `
    <button type="button" class="multi-filter-trigger" aria-haspopup="listbox" aria-expanded="false">
      <span class="multi-filter-summary"></span>
      <span class="multi-filter-caret" aria-hidden="true"></span>
    </button>
    <div class="multi-filter-panel" hidden>
      <div class="multi-filter-toolbar">
        <button type="button" class="multi-filter-action" data-multi-select-all><span class="ui-lang-zh">全选</span><span class="ui-lang-en">All</span></button>
        <button type="button" class="multi-filter-action" data-multi-invert><span class="ui-lang-zh">反选</span><span class="ui-lang-en">Invert</span></button>
        <button type="button" class="multi-filter-action" data-multi-clear><span class="ui-lang-zh">清除</span><span class="ui-lang-en">Clear</span></button>
      </div>
      <div class="multi-filter-options">${body || '<div class="multi-filter-empty"><span class="ui-lang-zh">暂无选项</span><span class="ui-lang-en">No options</span></div>'}</div>
    </div>`;
  updateMultiFilterSummary(root);
  const trigger = root.querySelector(".multi-filter-trigger");
  const panel = root.querySelector(".multi-filter-panel");
  const emitChange = () => {
    updateMultiFilterSummary(root);
    onChange?.(getMultiFilterValues(root));
  };
  trigger?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    const willOpen = Boolean(panel?.hidden);
    closeAllMultiFilters();
    if (typeof closeGatewayModelPicker === "function") closeGatewayModelPicker();
    if (typeof closeGatewayProviderPicker === "function") closeGatewayProviderPicker();
    if (typeof closeAllUiSelects === "function") closeAllUiSelects();
    if (willOpen && panel) {
      root.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
      const triggerWidth = trigger.getBoundingClientRect().width;
      const preferredWidth = onlyThis
        ? Math.max(triggerWidth, 360)
        : Math.max(triggerWidth, 160);
      openAnchoredPanel(panel, trigger, {
        maxHeight: 280,
        // Baseline rows include a per-item action, so give their labels room.
        minWidth: preferredWidth,
        matchAnchorWidth: true,
        maxWidth: onlyThis
          ? preferredWidth
          : Math.max(triggerWidth, 280),
      });
    }
  });
  panel?.addEventListener("click", (event) => event.stopPropagation());
  root.querySelector("[data-multi-select-all]")?.addEventListener("click", (event) => {
    event.preventDefault();
    setMultiFilterValues(root, multiFilterAllValues(root));
    emitChange();
  });
  root.querySelector("[data-multi-invert]")?.addEventListener("click", (event) => {
    event.preventDefault();
    const selectedNow = new Set(getMultiFilterValues(root));
    const inverted = multiFilterAllValues(root).filter((value) => !selectedNow.has(value));
    setMultiFilterValues(root, inverted);
    emitChange();
  });
  root.querySelector("[data-multi-clear]")?.addEventListener("click", (event) => {
    event.preventDefault();
    setMultiFilterValues(root, []);
    emitChange();
  });
  root.querySelectorAll("[data-multi-only]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const value = String(button.getAttribute("data-multi-only") || "").trim();
      if (!value) return;
      setMultiFilterValues(root, [value]);
      emitChange();
    });
  });
  root.querySelectorAll('input[data-multi-value]').forEach((input) => {
    input.addEventListener("change", () => emitChange());
  });
}

function renderConfig() {
  const baseline = state.config?.baseline || {};
  const catalog = Array.isArray(state.config?.baselines)
    ? state.config.baselines
    : [];
  const selected = new Set(normalizeBaselineIds(state.selectedBaselineIds));
  const selectedItems = catalog.filter((item) => selected.has(String(item.id)));
  const selectedTitle = selectedItems.length
    ? selectedItems
        .map((item) => `${item.label || item.id} · ${item.count ?? "—"}`)
        .join(" + ")
    : baseline.message || uiText("当前 GT 数据集", "Selected GT dataset");
  $(".header-metrics")?.setAttribute("title", selectedTitle);
  const defaultIds = defaultBaselineIdsFromConfig(state.config);
  const trailBaseline = catalog.find((item) => defaultIds.includes(String(item.id))) || baseline;
  const scopeText = String(trailBaseline.count ?? "—");
  const scopeLabel = String(trailBaseline.label || trailBaseline.id || "0508");
  if ($("#trailScopeCount")) $("#trailScopeCount").textContent = scopeText;
  if ($("#trailScopeCountEn")) $("#trailScopeCountEn").textContent = scopeText;
  if ($("#trailScopeLabel")) $("#trailScopeLabel").textContent = scopeLabel;
  if ($("#trailScopeLabelEn")) $("#trailScopeLabelEn").textContent = scopeLabel;
  const trail = state.trailInspection || state.config?.trail_sync || {};
  const viewText = String(trail.view_id ?? "2410");
  if ($("#trailViewId")) $("#trailViewId").textContent = viewText;
  if ($("#trailViewIdEn")) $("#trailViewIdEn").textContent = viewText;
  renderTrailSyncState();
  renderGtSyncStatus(state.config?.gt_sync || state.gtSync);
  renderBatchRuntimeSummary();
  updateFilteredPredictionButton();
  if (typeof renderReviewCatalogFilters === "function") {
    renderReviewCatalogFilters();
  }
  renderAnalysisCatalogFilters();
}

function renderAnalysisCatalogFilters() {
  const onChange = () => scheduleAnalysisFilterReload();
  renderMultiFilter($("#analysisStatusFilter"), {
    options: [
      { value: "pending", label: t("status.pending") },
      { value: "reviewed", label: t("status.matches_gt") },
      { value: "needs_gt_review", label: t("status.needs_gt") },
    ],
    selected: getMultiFilterValues($("#analysisStatusFilter")),
    onChange,
  });
  renderMultiFilter($("#analysisGtFilter"), {
    options: LABELS.map((label) => ({ value: label, label })),
    selected: getMultiFilterValues($("#analysisGtFilter")),
    onChange,
  });
  renderMultiFilter($("#analysisModelLabelFilter"), {
    options: MODEL_LABELS.map((label) => ({ value: label, label })),
    selected: getMultiFilterValues($("#analysisModelLabelFilter")),
    onChange,
  });
  renderMultiFilter($("#analysisExclusionFilter"), {
    options: [
      {
        value: "included",
        label: uiText("不含问题排除", "Exclude shielded cases"),
      },
      {
        value: "excluded",
        label: uiText("仅问题排除", "Only shielded cases"),
      },
    ],
    selected: getMultiFilterValues($("#analysisExclusionFilter")),
    onChange,
  });
  renderMultiFilter($("#analysisEvidenceFilter"), {
    options: (state.config?.missing_evidence_catalog || [])
      .filter((item) => !item.deleted)
      .map((item) => ({ value: item.key, label: item.label })),
    selected: getMultiFilterValues($("#analysisEvidenceFilter")),
    onChange,
  });
  const groupLabels = {
    environment: "环境",
    self_intent: "自车意图",
    false_trigger: "误触发",
    true_trigger: "应该触发",
    ra: "正确触发",
    no_assist: "无需协助",
  };
  const tagCatalog = (state.config?.review_tag_catalog || []).filter(
    (item) => item.visible !== false && !item.deleted
  );
  const renderTagMulti = (selector, section) => {
    const root = $(selector);
    if (!root) return;
    const groups = [];
    tagCatalog
      .filter((item) => item.section === section)
      .forEach((item) => {
        const key = item.group || "other";
        let group = groups.find((entry) => entry.key === key);
        if (!group) {
          group = { key, label: groupLabels[key] || key, items: [] };
          groups.push(group);
        }
        group.items.push({ value: item.key, label: item.label });
      });
    renderMultiFilter(root, {
      groups,
      selected: getMultiFilterValues(root),
      onChange,
    });
  };
  renderTagMulti("#analysisSceneFilter", "scene");
  renderTagMulti("#analysisTriggerFilter", "interaction_decision");
  renderTagMulti("#analysisEgressFilter", "egress");
}

function renderAccessUsers() {
  const target = $("#accessUserList");
  if (!target) return;
  if (!state.accessUsers.length) {
    target.innerHTML = `<div class="no-asset">${escapeHtml(t("access.empty"))}</div>`;
    return;
  }
  target.innerHTML = state.accessUsers.map((item) => `
    <div class="access-row" data-access-user="${escapeHtml(item.username)}">
      <div class="access-identity"><strong>${escapeHtml(item.username)}</strong><small>${escapeHtml(item.role === "admin" ? t("access.admin_user") : t("access.writer_user"))}</small></div>
      <select data-access-role aria-label="${escapeHtml(t("access.role_aria", { user: item.username }))}"><option value="writer"${item.role === "writer" ? " selected" : ""}>${escapeHtml(t("access.writer"))}</option><option value="admin"${item.role === "admin" ? " selected" : ""}>${escapeHtml(t("access.admin"))}</option></select>
      <div class="access-row-actions"><button class="button button-quiet" type="button" data-save-access-user>${escapeHtml(t("access.save"))}</button><button class="button button-danger" type="button" data-remove-access-user>${escapeHtml(t("access.remove"))}</button></div>
    </div>
  `).join("");
}

async function loadAccessUsers() {
  if (!state.session.is_admin) return;
  const result = await api("/api/access-users");
  state.accessUsers = result.items || [];
  renderAccessUsers();
}

function renderMentionUsers() {
  const target = $("#mentionUserList");
  if (!target) return;
  if (!state.mentionUsers.length) {
    target.innerHTML = `<div class="no-asset">尚未配置可 @ 人员。</div>`;
    return;
  }
  target.innerHTML = state.mentionUsers.map((item) => `
    <div class="access-row" data-mention-user="${escapeHtml(item.username)}">
      <div class="access-identity"><strong>${escapeHtml(item.display_name || item.username)}</strong><small>@${escapeHtml(item.username)} · ${item.enabled ? "可被提及并接收 DChat" : "已停用通知"}</small></div>
      <label class="access-enabled-toggle"><input type="checkbox" data-mention-enabled${item.enabled ? " checked" : ""} /> 启用</label>
      <div class="access-row-actions"><button class="button button-quiet" type="button" data-save-mention-user>保存</button><button class="button button-danger" type="button" data-remove-mention-user>移除</button></div>
    </div>
  `).join("");
}

async function loadMentionUsers() {
  if (!state.session?.verified) {
    state.mentionUsers = [];
    renderMentionUsers();
    return;
  }
  const result = await api("/api/mention-users");
  state.mentionUsers = result.items || [];
  renderMentionUsers();
  document.querySelectorAll("textarea[data-mention-composer]").forEach((textarea) => {
    const root = textarea.parentElement?.querySelector("[data-mention-composer-root]");
    updateReviewMentionComposer(textarea, root);
  });
  updateReviewMentionComposer();
}

async function saveMentionUser(username, enabled) {
  const result = await api(`/api/mention-users/${encodeURIComponent(username)}`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
  acknowledgeLocalChange(result);
  await loadMentionUsers();
}

async function saveAccessUser(username, role) {
  const result = await api(`/api/access-users/${encodeURIComponent(username)}`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });
  acknowledgeLocalChange(result);
  await Promise.all([loadAccessUsers(), loadMentionUsers()]);
}

function renderTrailSyncState() {
  const target = $("#trailSyncState");
  if (!target) return;
  const trail = state.trailInspection || state.config?.trail_sync || {};
  const status = trail.status || "not_started";
  const visibleFields = trail.fields_visible?.length
    ? trail.fields_visible.join("、")
    : "尚未发现模型字段";
  const coverage =
    trail.usable_predictions === undefined
      ? ""
      : ` · 可用 ${trail.usable_predictions} / ${trail.queried_issues ?? "—"}`;
  target.className = `trail-sync-state ${
    ["preview_ready", "ready"].includes(status)
      ? "ok"
      : ["failed", "unavailable", "empty"].includes(status)
        ? "warn"
        : "pending"
  }`;
  target.innerHTML = `
    <strong>${escapeHtml(trail.message || "尚未检查 Trail 模型字段。")}</strong>
    <span>字段：${escapeHtml(visibleFields)}${escapeHtml(coverage)}</span>`;
  const checkButton = $("#checkTrailButton");
  const createButton = $("#syncTrailButton");
  const running = status === "running";
  if (checkButton) checkButton.disabled = running;
  if (createButton) {
    createButton.disabled = running || !trail.can_create;
    createButton.title = trail.can_create
      ? "创建或复用本地不可变快照；不会改变团队默认 Run"
      : "请先检查字段；所有 baseline issue 分片必须完整返回，结果本身可为部分覆盖";
  }
}

async function loadConfig() {
  state.config = await api("/api/dashboard-config");
  state.gtSync = state.config?.gt_sync || state.gtSync;
  const catalog = Array.isArray(state.config?.baselines)
    ? state.config.baselines
    : [];
  state.baselineCatalog = catalog;
  const allowed = new Set(catalog.map((item) => String(item.id)));
  const routeIds = normalizeBaselineIds(
    new URLSearchParams(window.location.search).get("baselines"),
    { allowed: allowed.size ? allowed : null, fallback: [] }
  );
  const storedIds = normalizeBaselineIds(readStoredBaselineIds(), {
    allowed: allowed.size ? allowed : null,
    fallback: [],
  });
  const defaults = defaultBaselineIdsFromConfig(state.config);
  if (!state.selectedBaselineIds?.length || state.selectedBaselineIds.join(",") === "0508") {
    state.selectedBaselineIds = normalizeBaselineIds(
      routeIds.length ? routeIds : storedIds.length ? storedIds : defaults,
      { allowed: allowed.size ? allowed : null, fallback: defaults }
    );
  } else {
    state.selectedBaselineIds = normalizeBaselineIds(state.selectedBaselineIds, {
      allowed: allowed.size ? allowed : null,
      fallback: defaults,
    });
  }
  persistBaselineIds(state.selectedBaselineIds);
  renderBaselinePicker();
  renderConfig();
}

function markSessionUnavailable() {
  state.session = {
    ...state.session,
    username: "",
    source: "session_unavailable",
    identity_pending: false,
    authenticated: false,
    verified: false,
    is_admin: false,
    access_role: "viewer",
    can_manage_team_default: false,
    can_write: false,
    read_only: true,
  };
  renderSession();
}

function resolveSessionInBackground() {
  const request = loadSession().catch(() => {
    markSessionUnavailable();
    showToast("身份暂时无法确认，页面已按只读模式打开；稍后会自动重试。", true);
    if (!state.sessionRetryTimer) {
      state.sessionRetryTimer = window.setTimeout(() => {
        state.sessionRetryTimer = null;
        loadSession().catch(() => markSessionUnavailable());
      }, 5000);
    }
    return null;
  });
  return request;
}

async function settleInitialRequests(requests, scope) {
  const results = await Promise.allSettled(requests);
  const failures = results.filter((result) => result.status === "rejected");
  if (failures.length) {
    showToast(
      `${scope}有 ${failures.length} 项暂时未加载；可点击刷新重试。`,
      true
    );
  }
  return results;
}

function renderOverview(data) {
  $("#statIssues").textContent = data.issues ?? "—";
  $("#statFailures").textContent = data.model_failures ?? "—";
  // The top bar is a human-Review progress metric.  It must include every
  // effective Review for the active Run/dataset (including model matches),
  // rather than only the mismatch subset used by the error-analysis view.
  $("#statReviewed").textContent = data.labelled ?? data.reviewed_failures ?? "—";
  const reviewedMetric = $("#statReviewed")?.closest("div");
  if (reviewedMetric) {
    reviewedMetric.title = uiText(
      "统计当前数据集和模型 Run 下已有 Review 的 Issue；包含模型与 GT 一致的 Review。",
      "Counts every issue with an effective Review in the current dataset and Model Run, including model/GT matches."
    );
  }
  $("#statPredictions").textContent = data.predictions ?? "—";
  renderActiveRun(data);
}

async function loadOverview() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  appendBaselineParams(params);
  const query = params.toString() ? `?${params.toString()}` : "";
  renderOverview(await api(`/api/overview${query}`));
}
