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
    ? uiText("身份识别中…", "Identifying user…")
    : uiText("用户未识别", "User not identified"));
  $("#userAvatar").textContent = username ? username.slice(0, 1).toUpperCase() : "?";
  $("#sessionUserSource").textContent = state.session.read_only
    ? uiText("只读预览", "Read-only preview")
    : state.session.verified
    ? uiText("企业 SSO · 已验证", "Enterprise SSO · verified")
    : identityPending
      ? uiText("页面可先使用", "Page ready")
      : username
      ? uiText("本机 LCA · 未验证", "Local LCA · unverified")
      : uiText("当前会话", "Current session");
  $("#sidebarUser").title = state.session.verified
    ? `可信代理认证：${username}`
    : username
      ? `本机 LCA 用户：${username}（仅作显示与默认标注人）`
      : "当前没有可用的用户名";
  const logoutLink = $("#sessionLogoutLink");
  if (logoutLink) {
    const logoutUrl = String(state.session.logout_url || "");
    logoutLink.hidden = !logoutUrl || identityPending;
    logoutLink.href = logoutUrl || "#";
    logoutLink.textContent = state.session.verified
      ? uiText("退出", "Sign out")
      : uiText("重新登录", "Sign in again");
  }
  document.documentElement.dataset.accessMode = state.session.read_only
    ? "read-only"
    : "write";
  const userManagementNav = $("#userManagementNavButton");
  if (userManagementNav) userManagementNav.hidden = !state.session.is_admin;
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
}

async function loadSession() {
  const serverSession = await api("/api/session");
  if (serverSession.authenticated && validDisplayName(serverSession.username)) {
    state.session = serverSession;
    renderSession();
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

function renderConfig() {
  const baseline = state.config?.baseline || {};
  $(".header-metrics")?.setAttribute("title", baseline.message || "0508 baseline GT 只读");
  if ($("#trailScopeCount")) $("#trailScopeCount").textContent = baseline.count ?? "—";
  const trail = state.trailInspection || state.config?.trail_sync || {};
  if ($("#trailViewId")) $("#trailViewId").textContent = trail.view_id ?? "2410";
  renderTrailSyncState();
  renderBatchRuntimeSummary();
  updateFilteredPredictionButton();
  renderAnalysisCatalogFilters();
}

function renderAnalysisCatalogFilters() {
  const evidenceSelect = $("#analysisEvidenceFilter");
  if (evidenceSelect) {
    const previous = evidenceSelect.value;
    evidenceSelect.innerHTML = [
      '<option value="">全部缺失信息</option>',
      ...(state.config?.missing_evidence_catalog || []).filter((item) => !item.deleted).map(
        (item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`
      ),
    ].join("");
    evidenceSelect.value = [...evidenceSelect.options].some(
      (option) => option.value === previous
    )
      ? previous
      : "";
  }
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
  const renderTagSelect = (selector, section, placeholder) => {
    const select = $(selector);
    if (!select) return;
    const previous = select.value;
    const groups = [];
    tagCatalog
      .filter((item) => item.section === section)
      .forEach((item) => {
        const key = item.group || "other";
        let group = groups.find((entry) => entry.key === key);
        if (!group) {
          group = { key, items: [] };
          groups.push(group);
        }
        group.items.push(item);
      });
    select.innerHTML = [
      `<option value="">${escapeHtml(placeholder)}</option>`,
      ...groups.map(
        (group) => `<optgroup label="${escapeHtml(groupLabels[group.key] || group.key)}">${group.items
          .map((item) => `<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`)
          .join("")}</optgroup>`
      ),
    ].join("");
    select.value = [...select.options].some((option) => option.value === previous)
      ? previous
      : "";
  };
  renderTagSelect("#analysisSceneFilter", "scene", "全部场景");
  renderTagSelect("#analysisTriggerFilter", "interaction_decision", "全部触发判定");
  renderTagSelect("#analysisEgressFilter", "egress", "全部脱困方式");
}

function renderAccessUsers() {
  const target = $("#accessUserList");
  if (!target) return;
  if (!state.accessUsers.length) {
    target.innerHTML = '<div class="no-asset">尚未配置可写用户。</div>';
    return;
  }
  target.innerHTML = state.accessUsers.map((item) => `
    <div class="access-row" data-access-user="${escapeHtml(item.username)}">
      <div class="access-identity"><strong>${escapeHtml(item.username)}</strong><small>${item.role === "admin" ? "管理员 · 可管理用户" : "可写用户"}</small></div>
      <select data-access-role aria-label="${escapeHtml(item.username)} 权限"><option value="writer"${item.role === "writer" ? " selected" : ""}>可写</option><option value="admin"${item.role === "admin" ? " selected" : ""}>管理员</option></select>
      <div class="access-row-actions"><button class="button button-quiet" type="button" data-save-access-user>保存</button><button class="button button-danger" type="button" data-remove-access-user>移除权限</button></div>
    </div>
  `).join("");
}

async function loadAccessUsers() {
  if (!state.session.is_admin) return;
  const result = await api("/api/access-users");
  state.accessUsers = result.items || [];
  renderAccessUsers();
}

async function saveAccessUser(username, role) {
  const result = await api(`/api/access-users/${encodeURIComponent(username)}`, {
    method: "PUT",
    body: JSON.stringify({ role }),
  });
  acknowledgeLocalChange(result);
  await loadAccessUsers();
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
  $("#statReviewed").textContent = data.reviewed_failures ?? data.labelled ?? "—";
  $("#statPredictions").textContent = data.predictions ?? "—";
  renderActiveRun(data);
}

async function loadOverview() {
  const query = state.selectedRunId ? `?model_run_id=${encodeURIComponent(state.selectedRunId)}` : "";
  renderOverview(await api(`/api/overview${query}`));
}

