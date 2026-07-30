const LABELS = ["误触发", "正确触发", "无需协助"];
const PAGE_ROUTES = {
  review: { path: "/review", title: "RA Triage Workbench", eyebrow: "EVALUATION BASELINE · 0508" },
  runs: { path: "/runs", title: "模型结果 Runs", eyebrow: "MODEL RUN REGISTRY" },
  inference: { path: "/inference", title: "单 Case 模型推理", eyebrow: "LIVE ONE-CASE INFERENCE" },
  import: { path: "/import", title: "导入数据与模型结果", eyebrow: "DATA INGESTION" },
};

const state = {
  config: null,
  cases: [],
  selectedId: "",
  selectedCase: null,
  modelRuns: [],
  reviewers: [],
  inferenceJobs: [],
  inferenceRequesters: [],
  selectedRunId: "",
  failureOnly: false,
  clusterKey: "",
  selectedAnnotationLabel: "",
  pollingJobId: "",
  pollTimer: null,
  media: { kind: "bev", index: 0 },
  session: {
    username: "",
    source: "anonymous",
    authenticated: false,
    verified: false,
    can_manage_team_default: false,
  },
  sidebarCollapsed: false,
  activePage: "review",
  inferenceCase: null,
  trailInspection: null,
};

const $ = (selector) => document.querySelector(selector);

function parsePageRoute() {
  const match = Object.entries(PAGE_ROUTES).find(([, config]) => config.path === window.location.pathname);
  const params = new URLSearchParams(window.location.search);
  const legacyHash = decodeURIComponent(window.location.hash.slice(1));
  return {
    page: match?.[0] || "review",
    issue: params.get("issue") || (/^[A-Za-z0-9_-]{3,128}$/.test(legacyHash) ? legacyHash : ""),
    runId: params.get("run") || "",
    failureOnly: params.has("failure") ? params.get("failure") === "1" : params.has("run") ? false : null,
    kind: params.get("kind") === "model" ? "model" : "issues",
  };
}

function pageUrl(page, options = {}) {
  const config = PAGE_ROUTES[page] || PAGE_ROUTES.review;
  const url = new URL(config.path, window.location.origin);
  if (page === "review") {
    const issueId = options.issue ?? state.selectedId;
    const runId = options.runId ?? state.selectedRunId;
    const failureOnly = options.failureOnly ?? state.failureOnly;
    if (issueId) url.searchParams.set("issue", issueId);
    if (runId) url.searchParams.set("run", runId);
    if (failureOnly && runId) url.searchParams.set("failure", "1");
  }
  if (page === "inference") {
    const issueId = options.issue ?? $("#inferIssueInput")?.value.trim() ?? state.selectedId;
    if (issueId) url.searchParams.set("issue", issueId);
  }
  if (page === "import") {
    url.searchParams.set("kind", options.kind === "model" ? "model" : "issues");
  }
  return `${url.pathname}${url.search}`;
}

function showPage(page, { historyMode = "", issue = "", kind = "" } = {}) {
  const target = PAGE_ROUTES[page] ? page : "review";
  const previousPage = state.activePage;
  state.activePage = target;
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("hidden", section.dataset.page !== target);
  });
  document.querySelectorAll(".sidebar-item[data-page-target]").forEach((item) => {
    const active = item.dataset.pageTarget === target;
    item.classList.toggle("active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  $("#pageTitle").textContent = PAGE_ROUTES[target].title;
  $("#pageEyebrow").textContent = PAGE_ROUTES[target].eyebrow;
  document.title = `${PAGE_ROUTES[target].title} · RA Triage`;
  if (previousPage === "inference" && target !== "inference") $("#apiKeyInput").value = "";
  if (target === "runs") {
    renderRunManager();
    renderTrailSyncState();
  }
  if (target === "import") {
    const importKind = kind || new URLSearchParams(window.location.search).get("kind") || "issues";
    setImportKind(importKind);
  }
  if (target === "inference") {
    const issueId = issue || state.selectedId;
    if (issueId) $("#inferIssueInput").value = issueId;
    updateInferenceTarget();
    loadInferenceJobs().catch((error) => showToast(error.message, true));
  }
  if (historyMode === "push") history.pushState({ page: target }, "", pageUrl(target, { issue, kind }));
  if (historyMode === "replace") history.replaceState({ page: target }, "", pageUrl(target, { issue, kind }));
  window.scrollTo({ top: 0, behavior: historyMode === "push" ? "smooth" : "auto" });
}

function navigatePage(page, options = {}) {
  showPage(page, { ...options, historyMode: "push" });
}

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

function labelBadge(label, fallback = "—") {
  const actual = label || "";
  const className = LABELS.includes(actual) ? `label-${actual}` : "label-empty";
  return `<span class="label-badge ${className}">${escapeHtml(actual || fallback)}</span>`;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? escapeHtml(value) : date.toLocaleString("zh-CN", { hour12: false });
}

function evidenceLabel(key) {
  return state.config?.missing_evidence_catalog?.find((item) => item.key === key)?.label || key;
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

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `请求失败 (${response.status})`);
  return payload;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.remove("hidden", "error");
  if (isError) toast.classList.add("error");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.add("hidden"), 4600);
}

function applySidebarState() {
  $("#appShell").classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  $("#sidebarToggle").setAttribute("aria-expanded", String(!state.sidebarCollapsed));
  $("#sidebarToggle").title = state.sidebarCollapsed ? "展开工具栏" : "折叠工具栏";
}

function toggleSidebar() {
  state.sidebarCollapsed = !state.sidebarCollapsed;
  localStorage.setItem("ra-triage-sidebar-collapsed", String(state.sidebarCollapsed));
  applySidebarState();
}

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
  const username = state.session.username;
  $("#sessionUserName").textContent = username || "SSO 未接入";
  $("#userAvatar").textContent = username ? username.slice(0, 1).toUpperCase() : "?";
  $("#sessionUserSource").textContent = state.session.verified
    ? "企业 SSO · 已验证"
    : username
      ? "本机 LCA · 未验证"
      : "直接 IP 会话";
  $("#sidebarUser").title = state.session.verified
    ? `可信代理认证：${username}`
    : username
      ? `本机 LCA 用户：${username}（仅作显示与默认标注人）`
      : "当前没有可用的用户名";
  const requestedBy = $("#requestedByInput");
  if (requestedBy && username && !requestedBy.value) requestedBy.value = username;
  if (requestedBy) requestedBy.readOnly = Boolean(state.session.verified);
  const importActor = $("#modelImportActorSummary");
  if (importActor) {
    importActor.textContent = state.session.verified
      ? `本次导入创建人：${username}（企业 SSO 已验证）`
      : username
        ? `本次导入显示名：${username}（本机 LCA，未验证；不能用于权限）`
        : "当前没有可信 SSO；Run 创建人将记为未记录。";
  }
  const runIdentityNote = $("#runIdentityNote");
  if (runIdentityNote) {
    runIdentityNote.textContent = state.session.verified
      ? `当前展示团队全部 Runs。你是 ${username}（SSO 已验证）；可按创建人或实验作者筛选。${
          state.session.can_manage_team_default
            ? "你有团队默认 Run 管理权限。"
            : "团队默认 Run 仅允许配置的管理员修改。"
        }`
      : "当前展示团队全部 Runs。IP 直连没有可信 SSO；本机 LCA 只作未验证署名，不能修改团队默认。";
  }
}

async function loadSession() {
  const serverSession = await api("/api/session");
  if (serverSession.authenticated && validDisplayName(serverSession.username)) {
    state.session = serverSession;
  } else {
    const username = serverSession.browser_lca_fallback ? await browserLcaUsername() : "";
    state.session = {
      username,
      source: username ? "browser_lca_unverified" : "anonymous",
      authenticated: false,
      verified: false,
      can_manage_team_default: false,
    };
  }
  renderSession();
}

function renderConfig() {
  const baseline = state.config?.baseline || {};
  $(".header-metrics")?.setAttribute("title", baseline.message || "0508 baseline GT 只读");
  if ($("#trailScopeCount")) $("#trailScopeCount").textContent = baseline.count ?? "—";
  const trail = state.trailInspection || state.config?.trail_sync || {};
  if ($("#trailViewId")) $("#trailViewId").textContent = trail.view_id ?? "1000";
  renderTrailSyncState();
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

async function loadStatus() {
  const data = await api("/api/status");
  if (data.baseline || data.trail_sync) {
    state.config = {
      ...(state.config || {}),
      baseline: data.baseline || state.config?.baseline,
      trail_sync: data.trail_sync || state.config?.trail_sync,
    };
    renderConfig();
  }
}

async function loadReviewers() {
  const data = await api("/api/reviewers");
  state.reviewers = data.items || [];
  const select = $("#reviewerFilter");
  if (!select) return;
  const previous = select.value;
  select.innerHTML = `<option value="">全部复核人</option>${state.reviewers
    .map(
      (item) => {
        const trust =
          item.verified_count > 0 && item.unverified_count > 0
            ? " · 混合身份"
            : item.verified
              ? " · SSO"
              : "";
        return `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${item.review_count} 条${trust}</option>`;
      }
    )
    .join("")}`;
  select.value = state.reviewers.some((item) => item.name === previous) ? previous : "";
}

async function loadRuns({ preferDefault = false } = {}) {
  const data = await api("/api/model-runs");
  state.modelRuns = data.items || [];
  const select = $("#modelRunFilter");
  const previousRunId = state.selectedRunId;
  const preferredRunId =
    data.default_model_run_id ||
    state.config?.default_model_run_id ||
    (preferDefault ? state.modelRuns[0]?.id || "" : "");
  const candidate = preferDefault
    ? preferredRunId
    : state.selectedRunId || data.default_model_run_id || state.config?.default_model_run_id || "";
  select.innerHTML = `<option value="">未选择模型 run</option>${state.modelRuns
    .map((run) => {
      const tag = run.is_default ? "默认 · " : "";
      return `<option value="${escapeHtml(run.id)}">${tag}${escapeHtml(run.name)} · ${run.baseline_prediction_count ?? 0} 条 · 错 ${run.failure_count ?? 0}</option>`;
    })
    .join("")}`;
  state.selectedRunId = state.modelRuns.some((run) => run.id === candidate) ? candidate : "";
  select.value = state.selectedRunId;
  const failure = $("#failureOnlyInput");
  failure.disabled = !state.selectedRunId;
  if (preferDefault && !previousRunId && state.selectedRunId) state.failureOnly = true;
  if (!state.selectedRunId) state.failureOnly = false;
  failure.checked = state.failureOnly;
  renderRunFilters();
  renderActiveRun();
  renderRunManager();
}

function runPeople() {
  const values = new Set();
  state.modelRuns.forEach((run) => {
    if (run.created_by) values.add(run.created_by);
    if (run.declared_author) values.add(run.declared_author);
  });
  return [...values].sort((left, right) => left.localeCompare(right, "zh-CN"));
}

function renderRunFilters() {
  const select = $("#runPersonFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  const people = runPeople();
  select.innerHTML = [
    '<option value="">全部人员</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...people.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`),
  ].join("");
  select.value =
    previous === "__me__" || people.includes(previous)
      ? previous
      : "";
}

function activeRun() {
  return state.modelRuns.find((run) => run.id === state.selectedRunId);
}

function renderActiveRun(overview = null) {
  const run = activeRun();
  $("#activeRunName").textContent = run?.name || "尚未选择模型 run";
  if (!run) {
    $("#activeRunMeta").textContent =
      state.config?.trail_sync?.message ||
      "选择团队 Run、创建 Trail 只读快照，或导入 JSON / CSV / XLSX";
    return;
  }
  const coverage = overview?.predictions ?? run.baseline_prediction_count ?? 0;
  const failures = overview?.model_failures ?? run.failure_count ?? 0;
  const reviewed = overview?.reviewed_failures;
  $("#activeRunMeta").textContent =
    `${coverage} / ${state.config?.baseline?.count || "—"} 覆盖 · ${failures} 条判断失败` +
    `${reviewed === undefined ? "" : ` · ${reviewed} 条已复核`}` +
    ` · ${run.kind === "trail_snapshot" ? "Trail 快照" : "文件导入"}`;
}

function renderRunManager() {
  const list = $("#modelRunList");
  if (!list) return;
  const personValue = $("#runPersonFilter")?.value || "";
  const person = personValue === "__me__" ? state.session.username : personValue;
  const kind = $("#runKindFilter")?.value || "";
  const filteredRuns = state.modelRuns.filter((run) => {
    const personMatch =
      !person || run.created_by === person || run.declared_author === person;
    return personMatch && (!kind || run.kind === kind);
  });
  const totalCoverage = filteredRuns.reduce(
    (sum, run) => sum + Number(run.baseline_prediction_count || 0),
    0
  );
  $("#runManagerSummary").textContent =
    `显示 ${filteredRuns.length} / ${state.modelRuns.length} 个团队 Run` +
    ` · 累计 ${totalCoverage} 条 baseline 预测记录`;
  if (!filteredRuns.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有 Model Run。可清除人员/来源筛选、上传批量结果，或创建 Trail 只读快照。</div>';
    return;
  }
  const baselineCount = Number(state.config?.baseline?.count || 0);
  list.innerHTML = filteredRuns
    .map(
      (run) => {
        const coverage = Number(run.baseline_prediction_count || 0);
        const coverageLabel =
          baselineCount && coverage >= baselineCount ? "全量覆盖" : "部分覆盖";
        const creator = run.created_by || "历史未记录";
        const creatorTrust = run.created_by_verified
          ? "SSO 已验证"
          : run.created_by
            ? "未验证"
            : "legacy";
        const declaredAuthor = run.declared_author || "未声明";
        return `<article class="run-row ${run.id === state.selectedRunId ? "active" : ""}">
        <div class="run-row-main">
          <div class="run-row-title">
            <strong>${escapeHtml(run.name)}</strong>
            ${run.is_default ? '<span class="run-default-badge">默认</span>' : ""}
            <span class="run-coverage-badge">${coverageLabel}</span>
          </div>
          <div class="run-row-meta">
            <span>${coverage} / ${state.config?.baseline?.count || "—"} 覆盖</span>
            <span>${run.failure_count ?? 0} 条失败</span>
            <span>${run.kind === "trail_snapshot" ? "Trail 快照" : "文件导入"}</span>
            <span>${formatTime(run.created_at)}</span>
          </div>
          <div class="run-identity-row">
            <span>创建人：<b>${escapeHtml(creator)}</b><em>${escapeHtml(creatorTrust)}</em></span>
            <span>实验作者：<b>${escapeHtml(declaredAuthor)}</b><em>结果包声明</em></span>
          </div>
          <div class="run-row-source" title="${escapeHtml(run.source_name || "")}">${escapeHtml(run.source_name || "无来源文件")}</div>
        </div>
        <div class="run-row-actions">
          <button class="button ${run.id === state.selectedRunId ? "button-primary" : "button-quiet"}" type="button" data-use-run="${escapeHtml(run.id)}">${run.id === state.selectedRunId ? "Review 使用中" : "在 Review 中打开"}</button>
          ${
            run.is_default
              ? ""
              : `<button class="button button-quiet" type="button" data-default-run="${escapeHtml(run.id)}" ${state.session.can_manage_team_default ? "" : "disabled"} title="${state.session.can_manage_team_default ? "修改所有用户的团队默认 Run" : "需要可信 SSO 且位于团队默认管理员名单"}">设为团队默认</button>`
          }
        </div>
      </article>`;
      }
    )
    .join("");
  list.querySelectorAll("[data-use-run]").forEach((button) => {
    button.addEventListener("click", () => useModelRun(button.dataset.useRun));
  });
  list.querySelectorAll("[data-default-run]").forEach((button) => {
    button.addEventListener("click", () => setDefaultRun(button.dataset.defaultRun));
  });
}

async function useModelRun(runId) {
  if (!state.modelRuns.some((run) => run.id === runId)) return;
  state.selectedRunId = runId;
  state.failureOnly = true;
  state.selectedId = "";
  $("#modelRunFilter").value = runId;
  $("#failureOnlyInput").disabled = false;
  $("#failureOnlyInput").checked = true;
  renderActiveRun();
  renderRunManager();
  await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  navigatePage("review");
}

async function setDefaultRun(runId) {
  if (!state.session.can_manage_team_default) {
    showToast(
      "设置团队默认 Run 需要可信 SSO 且位于管理员名单；当前仍可在 Review 中打开任意 Run。",
      true
    );
    return;
  }
  const run = state.modelRuns.find((item) => item.id === runId);
  if (
    !window.confirm(
      `确定将“${run?.name || runId}”设为团队默认吗？\n\n这会改变所有用户进入 Review 时默认选择的 Run，但不会改写模型输出、GT 或人工复核。`
    )
  ) {
    return;
  }
  try {
    await api(`/api/model-runs/${encodeURIComponent(runId)}/default`, { method: "POST", body: "{}" });
    await loadRuns();
    await loadOverview();
    showToast("已更新团队默认 Run；历史输出、GT 和人工复核均未改写。");
  } catch (error) {
    showToast(error.message, true);
  }
}

function issueRow(item) {
  const isSelected = item.issue_id === state.selectedId;
  const title = item.title || item.scenario || "未命名 issue";
  const annotation = item.annotation?.label;
  const prediction = item.prediction?.label;
  const mismatch = item.prediction?.mismatch;
  return `
    <button class="issue-row ${isSelected ? "selected" : ""}" data-issue-id="${escapeHtml(item.issue_id)}">
      <div class="issue-row-top">
        <span class="issue-id">${escapeHtml(item.issue_id)}</span>
        ${mismatch ? '<span class="mismatch-chip">MISMATCH</span>' : labelBadge(annotation, "待 review")}
      </div>
      <div class="issue-title">${escapeHtml(title)}</div>
      <div class="issue-row-meta">
        ${labelBadge(item.gt_label, "GT —")}
        ${prediction ? labelBadge(prediction, "模型 —") : '<span class="quiet-meta">模型 —</span>'}
        ${item.annotation?.author ? `<span class="quiet-meta">复核 · ${escapeHtml(item.annotation.author)}${item.annotation.author_verified ? " · SSO" : ""}</span>` : ""}
      </div>
      ${item.annotation?.missing_evidence?.length ? `<div class="row-evidence">${item.annotation.missing_evidence.map((key) => `<span>${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
    </button>`;
}

function renderCases(data) {
  state.cases = data.items || [];
  $("#caseCount").textContent = data.total ?? 0;
  $("#inferIssueOptions").innerHTML = state.cases
    .map((item) => `<option value="${escapeHtml(item.issue_id)}">${escapeHtml(item.title || item.scenario || "")}</option>`)
    .join("");
  const list = $("#issueList");
  if (!state.cases.length) {
    const hint = state.failureOnly ? "没有符合条件的模型失败 case。可切换 model run 或关闭失败筛选。" : "没有匹配的 Issue。";
    list.innerHTML = `<div class="no-asset">${hint}</div>`;
    return;
  }
  list.innerHTML = state.cases.map(issueRow).join("");
  list.querySelectorAll("[data-issue-id]").forEach((element) => {
    element.addEventListener("click", () => selectCase(element.dataset.issueId));
  });
}

async function loadCases({ keepSelection = true } = {}) {
  const params = new URLSearchParams();
  const search = $("#searchInput").value.trim();
  const gtLabel = $("#gtFilter").value;
  const annotationLabel = $("#annotationFilter").value;
  const annotationAuthor = $("#reviewerFilter").value;
  state.selectedRunId = $("#modelRunFilter").value;
  state.failureOnly = Boolean($("#failureOnlyInput").checked && state.selectedRunId);
  if (search) params.set("search", search);
  if (gtLabel) params.set("gt_label", gtLabel);
  if (annotationLabel) params.set("annotation_label", annotationLabel);
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  if (state.failureOnly) params.set("failure_only", "true");
  if (state.clusterKey) params.set("missing_evidence", state.clusterKey);
  params.set("page_size", "1500");
  renderCases(await api(`/api/cases?${params.toString()}`));
  if (!keepSelection || !state.cases.some((item) => item.issue_id === state.selectedId)) {
    if (state.cases[0]) await selectCase(state.cases[0].issue_id);
    else clearDetail();
  }
}

async function loadClusters() {
  const params = new URLSearchParams();
  if (state.selectedRunId) params.set("model_run_id", state.selectedRunId);
  params.set("failure_only", String(Boolean(state.failureOnly && state.selectedRunId)));
  const annotationAuthor = $("#reviewerFilter")?.value;
  if (annotationAuthor) params.set("annotation_author", annotationAuthor);
  const data = await api(`/api/review-clusters?${params.toString()}`);
  const list = $("#clusterList");
  if (!(data.items || []).length) {
    list.innerHTML = '<span class="muted">标注缺失信息后，这里会按错误模式自动聚类。</span>';
    return;
  }
  list.innerHTML = data.items
    .map(
      (item) => `<button type="button" class="cluster-chip ${state.clusterKey === item.key ? "active" : ""}" data-cluster-key="${escapeHtml(item.key)}">
        <span>${escapeHtml(evidenceLabel(item.key))}</span><b>${item.count}</b>
      </button>`
    )
    .join("");
  list.querySelectorAll("[data-cluster-key]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.clusterKey = button.dataset.clusterKey === state.clusterKey ? "" : button.dataset.clusterKey;
      await loadCases({ keepSelection: false });
      await loadClusters();
    });
  });
}

function clearDetail() {
  state.selectedId = "";
  state.selectedCase = null;
  $("#detailPane").innerHTML = `
    <div class="empty-state">
      <div class="empty-glyph" aria-hidden="true">+</div>
      <h2>选择一个 case 开始 review</h2>
      <p>可在左侧筛选失败 case；模型 run 的完整历史与导入操作放在全局工具栏中。</p>
    </div>`;
  $("#reviewPane").innerHTML = `
    <div class="review-placeholder"><span class="eyebrow">HUMAN REVIEW</span><h2>人工复核</h2><p>选择 Issue 后记录结论和模型遗漏的关键信息。</p></div>`;
}

function heroFrameIndex(frames) {
  const exact = frames.findIndex((frame) => Number(frame.offset_ms ?? frame.offset_sec * 1000) === 0);
  if (exact >= 0) return exact;
  return Math.floor(frames.length / 2);
}

function heroMediaSection(bev, camera) {
  const frames = bev?.frames || [];
  if (!bev?.available || !frames.length) {
    return '<section class="hero-media"><div class="section-heading"><div><span class="eyebrow">ARES CAPTURE</span><h3>BEV 主视图</h3></div></div><div class="no-asset">没有找到 Ares Capture BEV 帧。</div></section>';
  }
  const index = heroFrameIndex(frames);
  const frame = frames[index];
  const cameraCount = camera?.frames?.length || 0;
  return `
    <section class="hero-media">
      <div class="section-heading">
        <div><span class="eyebrow">PRIMARY REVIEW CANVAS</span><h3>Ares Capture · BEV</h3></div>
        <small>默认 ${escapeHtml(frameLabel(frame))} · 点击进入时序预览</small>
      </div>
      <button type="button" class="hero-media-button" data-media-kind="bev" data-media-index="${index}" aria-label="打开 BEV 与 Camera 时序预览">
        <img src="${escapeHtml(frame.url)}" alt="Ares Capture BEV ${escapeHtml(frameLabel(frame))}" />
        <span class="hero-media-overlay">展开预览 · ${escapeHtml(frameLabel(frame))}</span>
      </button>
      <div class="hero-media-meta">
        <span><b>${frames.length}</b> 帧 BEV 时序</span>
        <span>${cameraCount ? `<b>${cameraCount}</b> 帧 Camera 可在预览中切换` : "Camera 暂不可用"}</span>
      </div>
    </section>`;
}

function predictionCards(caseData) {
  const predictions = caseData.predictions || [];
  if (!predictions.length) {
    return '<div class="no-asset">当前 case 没有 Run 模型输出。可创建 Trail 只读快照或上传批量结果；单 Case Job 不会自动进入这里。</div>';
  }
  return `<div class="model-list">${predictions
    .map((prediction) => {
      const selected = prediction.model_run_id === state.selectedRunId;
      const extra = prediction.model_extra?.ra_stuck_auto_result_info;
      const detail = prediction.model_reason || (typeof extra === "object" ? extra.text || "" : "") || "模型未返回解释。";
      return `<article class="model-card ${selected ? "active" : ""}">
        <div class="model-card-head"><div><span class="eyebrow">${escapeHtml(prediction.run_kind || "model run")}</span><h3>${escapeHtml(prediction.run_name || "模型输出")}</h3></div>${labelBadge(prediction.model_label, "未输出")}</div>
        <p>${escapeHtml(detail)}</p>
        <div class="model-card-meta">${prediction.model_confidence ?? "—"} confidence · ${formatTime(prediction.created_at)}${prediction.run_created_by ? ` · 创建人 ${escapeHtml(prediction.run_created_by)}` : ""}</div>
      </article>`;
    })
    .join("")}</div>`;
}

function inferenceJobCards(jobs) {
  if (!jobs?.length) {
    return '<div class="no-asset">这个 issue 还没有单 Case Debug Job。</div>';
  }
  return `<div class="job-mini-list">${jobs
    .map((job) => {
      const detail = job.result?.result || {};
      const statusLabel = {
        queued: "排队中",
        running: "运行中",
        succeeded: "成功",
        failed: "失败",
      }[job.status] || job.status;
      return `<article class="job-mini-row">
        <div>
          <strong>${escapeHtml(job.model_name || "preflight")}</strong>
          <span>${escapeHtml(job.issue_id)} · ${formatTime(job.created_at)}</span>
        </div>
        <div class="job-mini-meta">
          <span class="job-status status-${escapeHtml(job.status)}">${escapeHtml(statusLabel)}</span>
          ${detail.model_label ? labelBadge(detail.model_label, "—") : ""}
          <span>${job.requested_by ? `请求人 ${escapeHtml(job.requested_by)}${job.requested_by_verified ? " · SSO" : ""}` : "请求人未记录"}</span>
        </div>
      </article>`;
    })
    .join("")}</div>`;
}

function renderDetail(caseData) {
  const title = caseData.title || caseData.scenario || "未命名 issue";
  const primary = (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) || caseData.predictions?.[0];
  const trailUrl = safeUrl(caseData.trail_url);
  $("#detailPane").innerHTML = `
    <div class="detail-header">
      <div class="detail-title-row">
        <div class="detail-title"><span class="eyebrow">CASE REVIEW</span><h2>${escapeHtml(title)}</h2><span class="detail-id">${escapeHtml(caseData.issue_id)}</span></div>
        <div class="detail-actions">${trailUrl ? `<a class="button button-quiet" href="${escapeHtml(trailUrl)}" target="_blank" rel="noreferrer">打开 Trail</a>` : ""}</div>
      </div>
      <p class="detail-summary">${escapeHtml(caseData.summary || caseData.review_note || "暂无补充描述。请结合 BEV、Camera 与触发后时序复核。")}</p>
      <div class="comparison-strip">
        <div><span>0508 GT</span>${labelBadge(caseData.gt_label, "GT 缺失")}</div>
        <div><span>当前模型</span>${labelBadge(primary?.model_label, "未输出")}</div>
        <div><span>对比</span><b class="${primary?.model_label && primary.model_label !== caseData.gt_label ? "comparison-fail" : "comparison-neutral"}">${primary?.model_label ? primary.model_label === caseData.gt_label ? "一致" : "不一致" : "不可比较"}</b></div>
      </div>
      ${caseData.review_note ? `<div class="review-note"><span>历史备注</span>${escapeHtml(caseData.review_note)}</div>` : ""}
    </div>
    ${heroMediaSection(caseData.assets, caseData.camera)}
    <section class="section"><div class="section-heading"><div><span class="eyebrow">MODEL RUN COMPARISON</span><h3>评测 Run 输出历史</h3></div><small>当前 Review run 会高亮</small></div>${predictionCards(caseData)}</section>
    <section class="section"><div class="section-heading"><div><span class="eyebrow">DEBUG JOBS</span><h3>单 Case 推理记录</h3></div><small>仅调试，不进入 Run 统计</small></div>${inferenceJobCards(caseData.jobs)}</section>`;
  $("#detailPane").querySelectorAll("[data-media-kind]").forEach((button) => {
    button.addEventListener("click", () => openMedia(button.dataset.mediaKind, Number(button.dataset.mediaIndex)));
  });
}

function annotationHistory(annotations) {
  if (!annotations?.length) return '<p class="muted history-empty">尚无人工 review；保存后会保留旧版本。</p>';
  return annotations
    .map(
      (annotation) => `<article class="history-row">
        <div class="history-head">${labelBadge(annotation.label, annotation.review_status === "needs_gt_review" ? "GT 待复核" : "已记录")}<span>${formatTime(annotation.created_at)}</span></div>
        ${annotation.missing_evidence?.length ? `<div class="tags">${annotation.missing_evidence.map((key) => `<span class="tag evidence-tag">${escapeHtml(evidenceLabel(key))}</span>`).join("")}</div>` : ""}
        ${annotation.tags?.length ? `<div class="tags">${annotation.tags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}</div>` : ""}
        ${annotation.note ? `<p>${escapeHtml(annotation.note)}</p>` : ""}
        ${annotation.author ? `<small>${escapeHtml(annotation.author)}${annotation.author_verified ? " · SSO 已验证" : " · 未验证/历史"}</small>` : ""}
      </article>`)
    .join("");
}

function renderReview(caseData) {
  const previous = caseData.annotations?.[0] || {};
  state.selectedAnnotationLabel = previous.label || "";
  const chosenEvidence = new Set(previous.missing_evidence || []);
  const catalog = state.config?.missing_evidence_catalog || [];
  const author = state.session.username || previous.author || "";
  const authorLocked = Boolean(state.session.verified && state.session.username);
  $("#reviewPane").innerHTML = `
    <div class="review-title"><div><span class="eyebrow">HUMAN REVIEW</span><h2>标注与错误归因</h2></div><span class="review-issue">${escapeHtml(caseData.issue_id)}</span></div>
    <form class="review-form" id="annotationForm">
      <div class="review-context"><span>GT ${escapeHtml(caseData.gt_label || "—")}</span><span>模型 ${escapeHtml((caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId)?.model_label || "—")}</span></div>
      <div><label><span>人工最终判断</span></label><div class="label-buttons">${LABELS.map((label) => `<button class="label-choice ${state.selectedAnnotationLabel === label ? "active" : ""}" data-annotation-label="${label}" type="button">${label}</button>`).join("")}</div></div>
      <label><span>复核状态</span><select id="reviewStatusInput"><option value="pending">待补充</option><option value="reviewed" ${previous.review_status === "reviewed" ? "selected" : ""}>已复核</option><option value="needs_gt_review" ${previous.review_status === "needs_gt_review" ? "selected" : ""}>GT 需复核</option></select></label>
      <label class="review-reason">
        <span>模型为什么判错？</span>
        <small>请写清交通灯、routing、绕行空间、时序或 RA / SWAG 操作链等关键依据。</small>
        <textarea id="annotationNote" placeholder="例如：自车 routing 为右转，前车直行等灯；右侧存在可安全通行空间，模型只看到排队而遗漏 routing 与绕行条件。">${escapeHtml(previous.note || "")}</textarea>
      </label>
      <details class="evidence-dropdown">
        <summary>缺失信息（多选）<span class="evidence-summary-count" id="evidenceSummaryCount">已选 ${chosenEvidence.size} 项</span></summary>
        <div class="evidence-options">${catalog.map((item) => `<label class="evidence-option" title="${escapeHtml(item.hint || "")}"><input type="checkbox" name="missingEvidence" value="${escapeHtml(item.key)}" ${chosenEvidence.has(item.key) ? "checked" : ""} /><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.hint || "")}</small></span></label>`).join("")}</div>
      </details>
      <label><span>补充 tags（可选，逗号分隔）</span><input id="annotationTags" value="${escapeHtml((previous.tags || []).join(", "))}" placeholder="例如：右转, 双闪, 遮挡" autocomplete="off" /></label>
      <label><span>标注人${authorLocked ? "（SSO）" : "（可编辑）"}</span><input id="annotationAuthor" value="${escapeHtml(author)}" placeholder="姓名或工号" autocomplete="off" ${authorLocked ? "readonly" : ""} /></label>
      <button class="button button-primary full-width" type="submit">保存新的 review 版本</button>
    </form>
    <section class="annotation-history"><div class="subheading"><span>Review 历史</span><small>追加式，不覆盖旧记录</small></div>${annotationHistory(caseData.annotations)}</section>`;
  $("#reviewPane").querySelectorAll("[data-annotation-label]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedAnnotationLabel = button.dataset.annotationLabel;
      $("#reviewPane").querySelectorAll("[data-annotation-label]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  $("#reviewPane").querySelectorAll('input[name="missingEvidence"]').forEach((input) => {
    input.addEventListener("change", updateEvidenceSummary);
  });
  $("#annotationForm").addEventListener("submit", saveAnnotation);
}

function updateEvidenceSummary() {
  const count = document.querySelectorAll('input[name="missingEvidence"]:checked').length;
  const target = $("#evidenceSummaryCount");
  if (target) target.textContent = `已选 ${count} 项`;
}

async function selectCase(issueId, { updateRoute = true } = {}) {
  if (!issueId) return;
  state.selectedId = issueId;
  renderCases({ items: state.cases, total: $("#caseCount").textContent });
  try {
    const data = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    state.selectedCase = data;
    renderDetail(data);
    renderReview(data);
    if (!$("#inferIssueInput").value) $("#inferIssueInput").value = issueId;
    if (state.activePage === "inference" && $("#inferIssueInput").value === issueId) {
      renderInferenceCaseSummary(data);
    }
    if (updateRoute && state.activePage === "review") {
      showPage("review", { historyMode: "replace", issue: issueId });
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

async function saveAnnotation(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const payload = {
    label: state.selectedAnnotationLabel,
    review_status: $("#reviewStatusInput").value,
    tags: $("#annotationTags").value.split(",").map((tag) => tag.trim()).filter(Boolean),
    missing_evidence: [...document.querySelectorAll('input[name="missingEvidence"]:checked')].map((input) => input.value),
    note: $("#annotationNote").value,
    author: $("#annotationAuthor").value,
  };
  try {
    await api(`/api/cases/${encodeURIComponent(state.selectedId)}/annotations`, { method: "POST", body: JSON.stringify(payload) });
    showToast("已保存新的 review 版本，并更新缺失信息聚类。");
    await Promise.all([loadOverview(), loadClusters(), loadCases(), loadReviewers()]);
    await selectCase(state.selectedId);
  } catch (error) {
    showToast(error.message, true);
  }
}

function mediaFrames(kind) {
  if (!state.selectedCase) return [];
  return (kind === "bev" ? state.selectedCase.assets : state.selectedCase.camera)?.frames || [];
}

function openDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog && !dialog.open) dialog.showModal();
}

function closeDialog(id) {
  const dialog = $(`#${id}`);
  if (dialog?.open) dialog.close();
}

function renderMediaDialog() {
  const bev = mediaFrames("bev");
  const camera = mediaFrames("camera");
  if (!mediaFrames(state.media.kind).length) state.media.kind = bev.length ? "bev" : "camera";
  const frames = mediaFrames(state.media.kind);
  state.media.index = Math.max(0, Math.min(state.media.index, Math.max(frames.length - 1, 0)));
  const current = frames[state.media.index];
  if (!current) return;
  $("#mediaEyebrow").textContent = state.media.kind === "bev" ? "ARES CAPTURE / BEV" : "CAMERA / AFTER_COMPRESS";
  $("#mediaTitle").textContent = `${state.selectedCase?.issue_id || ""} · ${frameLabel(current)} · ${state.media.index + 1}/${frames.length}`;
  $("#mediaPreviewImage").src = current.url;
  $("#mediaPreviewImage").alt = `${state.media.kind} ${frameLabel(current)}`;
  $("#mediaModeTabs").innerHTML = `
    <button type="button" class="media-mode ${state.media.kind === "bev" ? "active" : ""}" data-media-mode="bev" ${bev.length ? "" : "disabled"}>BEV <span>${bev.length}</span></button>
    <button type="button" class="media-mode ${state.media.kind === "camera" ? "active" : ""}" data-media-mode="camera" ${camera.length ? "" : "disabled"}>Camera <span>${camera.length}</span></button>`;
  $("#mediaTimeline").innerHTML = frames.map((frame, index) => `<button type="button" class="timeline-dot ${index === state.media.index ? "active" : ""}" data-media-frame="${index}" title="${escapeHtml(frameLabel(frame))}">${escapeHtml(frameLabel(frame))}</button>`).join("");
  $("#mediaModeTabs").querySelectorAll("[data-media-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.kind = button.dataset.mediaMode;
      state.media.index = 0;
      renderMediaDialog();
    });
  });
  $("#mediaTimeline").querySelectorAll("[data-media-frame]").forEach((button) => {
    button.addEventListener("click", () => {
      state.media.index = Number(button.dataset.mediaFrame);
      renderMediaDialog();
    });
  });
}

function openMedia(kind, index) {
  if (!mediaFrames(kind).length) return;
  state.media.kind = kind;
  state.media.index = index;
  renderMediaDialog();
  openDialog("mediaDialog");
}

function moveMedia(delta) {
  const frames = mediaFrames(state.media.kind);
  if (!frames.length) return;
  state.media.index = (state.media.index + delta + frames.length) % frames.length;
  renderMediaDialog();
}

function renderInferenceCaseSummary(caseData) {
  state.inferenceCase = caseData;
  const primary =
    (caseData.predictions || []).find((item) => item.model_run_id === state.selectedRunId) ||
    caseData.predictions?.[0];
  $("#inferCaseSummary").innerHTML = `
    <strong>${escapeHtml(caseData.issue_id)}</strong>
    <span>${escapeHtml(caseData.title || caseData.scenario || "未命名 issue")}</span>
    <div>${labelBadge(caseData.gt_label, "GT —")}${labelBadge(primary?.model_label, "模型 —")}</div>`;
  $("#inferOpenReviewButton").disabled = false;
}

async function updateInferenceTarget() {
  const issueId = $("#inferIssueInput").value.trim();
  state.inferenceCase = null;
  $("#inferOpenReviewButton").disabled = !issueId;
  if (!/^[A-Za-z0-9_-]{3,128}$/.test(issueId)) {
    $("#inferCaseSummary").textContent = issueId
      ? "Issue ID 格式不合法。"
      : "从 Review 队列选择 case，或直接输入 baseline 中的 issue id。";
    return;
  }
  if (state.selectedCase?.issue_id === issueId) {
    renderInferenceCaseSummary(state.selectedCase);
    return;
  }
  $("#inferCaseSummary").textContent = "正在读取 Issue…";
  try {
    const data = await api(`/api/cases/${encodeURIComponent(issueId)}`);
    if ($("#inferIssueInput").value.trim() === issueId) renderInferenceCaseSummary(data);
  } catch (error) {
    if ($("#inferIssueInput").value.trim() === issueId) {
      $("#inferCaseSummary").textContent = error.message;
      $("#inferOpenReviewButton").disabled = true;
    }
  }
}

function renderJobRequesterFilter() {
  const select = $("#jobRequesterFilter");
  if (!select) return;
  const previous = select.value;
  const mine = state.session.username;
  select.innerHTML = [
    '<option value="">全部请求人</option>',
    mine ? `<option value="__me__">我的 · ${escapeHtml(mine)}</option>` : "",
    ...state.inferenceRequesters.map(
      (item) => {
        const trust =
          item.verified_count > 0 && item.unverified_count > 0
            ? " · 混合身份"
            : item.verified
              ? " · SSO"
              : "";
        return `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)} · ${item.job_count} 个${trust}</option>`;
      }
    ),
  ].join("");
  const names = state.inferenceRequesters.map((item) => item.name);
  select.value =
    previous === "__me__" || names.includes(previous)
      ? previous
      : "";
}

function renderInferenceJobs(total = state.inferenceJobs.length) {
  const list = $("#inferenceJobList");
  if (!list) return;
  $("#jobHistorySummary").textContent =
    `显示 ${state.inferenceJobs.length} / ${total} 个 Debug Job` +
    " · 默认展示全员 · 不计入 Model Run";
  if (!state.inferenceJobs.length) {
    list.innerHTML = '<div class="no-asset">当前筛选下没有单 Case 推理任务。</div>';
    return;
  }
  list.innerHTML = state.inferenceJobs
    .map((job) => {
      const detail = job.result?.result || {};
      const statusLabel = {
        queued: "排队中",
        running: "运行中",
        succeeded: "成功",
        failed: "失败",
      }[job.status] || job.status;
      return `<article class="job-history-row">
        <div class="job-history-main">
          <div class="run-row-title">
            <strong>${escapeHtml(job.issue_id)}</strong>
            <span class="job-status status-${escapeHtml(job.status)}">${escapeHtml(statusLabel)}</span>
            <span class="debug-only-badge">DEBUG ONLY</span>
          </div>
          <div class="run-row-meta">
            <span>${escapeHtml(job.model_name || "preflight")}</span>
            <span>prompt ${escapeHtml(job.config?.prompt_version || "—")}</span>
            <span>${formatTime(job.created_at)}</span>
            <span>${job.requested_by ? `请求人 ${escapeHtml(job.requested_by)}${job.requested_by_verified ? " · SSO" : " · 未验证"}` : "请求人未记录"}</span>
          </div>
          ${
            detail.model_label || job.error_text
              ? `<div class="job-result-preview">${detail.model_label ? `输出：${escapeHtml(detail.model_label)} · ${escapeHtml(detail.model_reason || "无 reason")}` : `错误：${escapeHtml(job.error_text)}`}</div>`
              : ""
          }
        </div>
        <div class="run-row-actions">
          <button class="button button-quiet" type="button" data-show-job="${escapeHtml(job.id)}">查看结果</button>
          <button class="button button-quiet" type="button" data-job-review="${escapeHtml(job.issue_id)}">打开 Review</button>
        </div>
      </article>`;
    })
    .join("");
  list.querySelectorAll("[data-show-job]").forEach((button) => {
    button.addEventListener("click", () => {
      const job = state.inferenceJobs.find((item) => item.id === button.dataset.showJob);
      if (job) showJob(job);
      $("#jobResult")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  });
  list.querySelectorAll("[data-job-review]").forEach((button) => {
    button.addEventListener("click", async () => {
      const issueId = button.dataset.jobReview;
      navigatePage("review", { issue: issueId });
      await selectCase(issueId);
    });
  });
}

async function loadInferenceJobs() {
  if (!$("#inferenceJobList")) return;
  const params = new URLSearchParams({ page_size: "200" });
  const requesterValue = $("#jobRequesterFilter")?.value || "";
  const requester = requesterValue === "__me__" ? state.session.username : requesterValue;
  const status = $("#jobStatusFilter")?.value || "";
  if (requester) params.set("requested_by", requester);
  if (status) params.set("status", status);
  const data = await api(`/api/inference/jobs?${params.toString()}`);
  state.inferenceJobs = data.items || [];
  state.inferenceRequesters = data.requesters || [];
  renderJobRequesterFilter();
  renderInferenceJobs(data.total ?? state.inferenceJobs.length);
}

function showJob(job) {
  const target = $("#jobResult");
  target.classList.remove("hidden");
  const result = job.result || {};
  if (["queued", "running"].includes(job.status)) {
    target.textContent = `任务${job.status === "queued" ? "排队中" : "运行中"}…\nissue: ${job.issue_id}\n默认最多等待 12 分钟。`;
  } else if (job.status === "failed") {
    target.textContent = `任务失败\n${job.error_text || result.error || "未知错误"}`;
  } else if (result.dry_run) {
    target.textContent = `预检通过\nTrail issue: ${result.issue_id}\ntrip: ${result.trip_id}\nAres BEV: ${result.bev_asset_available ? "可用" : "未使用"}\nRA Tools 回写: ${result.ra_tools_enabled}`;
  } else {
    const detail = result.result || {};
    target.textContent = `推理完成\n标签：${detail.model_label || "—"}\n置信度：${detail.model_confidence ?? "—"}\n耗时：${detail.duration_sec ?? "—"}s\n\n${detail.model_reason || "模型未返回 reason。"}`;
  }
}

async function pollJob(jobId) {
  clearInterval(state.pollTimer);
  state.pollingJobId = jobId;
  const tick = async () => {
    try {
      const data = await api(`/api/inference/jobs/${encodeURIComponent(jobId)}`);
      showJob(data.job);
      if (!["queued", "running"].includes(data.job.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        state.pollingJobId = "";
        await Promise.all([loadOverview(), loadInferenceJobs()]);
        if (state.activePage === "review" && state.selectedId === data.job.issue_id) {
          await selectCase(state.selectedId);
        }
      }
    } catch (error) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      state.pollingJobId = "";
      showToast(error.message, true);
    }
  };
  await tick();
  if (state.pollingJobId === jobId) {
    state.pollTimer = setInterval(tick, 2000);
  }
}

async function submitInference({ dryRun }) {
  const issueId = $("#inferIssueInput").value.trim();
  if (!issueId) return showToast("请先输入 Issue ID。", true);
  const keyInput = $("#apiKeyInput");
  const payload = {
    issue_id: issueId,
    model_name: $("#modelNameInput").value.trim(),
    prompt_version: $("#promptVersionInput").value.trim(),
    base_url: $("#baseUrlInput").value.trim(),
    api_key: keyInput.value,
    max_tokens: Number($("#maxTokensInput").value || 512),
    requested_by: $("#requestedByInput").value.trim(),
    use_bev_animation: $("#useBevInput").checked,
    use_ra_options: $("#useRaOptionsInput").checked,
    dry_run: dryRun,
  };
  if (dryRun) Object.assign(payload, { model_name: "", base_url: "", api_key: "" });
  try {
    showPage("inference", { historyMode: "replace", issue: issueId });
    const result = await api("/api/inference/jobs", { method: "POST", body: JSON.stringify(payload) });
    keyInput.value = "";
    showJob(result.job);
    await loadInferenceJobs();
    await pollJob(result.job.id);
  } catch (error) {
    keyInput.value = "";
    showToast(error.message, true);
  }
}

function currentImportKind() {
  return $("#importKind input[name='kind']:checked").value;
}

function updateImportFields() {
  const isModel = currentImportKind() === "model";
  $("#runNameField").classList.toggle("hidden", !isModel);
  $("#issueImportOptions").classList.toggle("hidden", isModel);
}

function setImportKind(kind) {
  const input = $(`#importKind input[name="kind"][value="${kind}"]`);
  if (input) input.checked = true;
  updateImportFields();
}

async function submitImport(event) {
  event.preventDefault();
  const file = $("#importFile").files[0];
  if (!file) return showToast("请选择文件。", true);
  const kind = currentImportKind();
  const form = new FormData();
  form.append("file", file);
  const endpoint = kind === "model" ? "/api/import/model-results" : "/api/import/issues";
  if (kind === "model") {
    form.append("run_name", $("#runNameInput").value.trim());
    form.append("created_by", state.session.username || "");
  }
  else {
    form.append("source", $("#issueSourceInput").value.trim() || "manual_upload");
    form.append("replace_gt", String($("#replaceGtInput").checked));
  }
  const target = $("#importResult");
  target.classList.remove("hidden");
  target.textContent = "正在导入…";
  try {
    const result = await api(endpoint, { method: "POST", body: form });
    target.textContent = JSON.stringify(result, null, 2);
    showToast(kind === "model" ? "模型 run 已导入；可从列表切换对比。" : "Issue 工作集已导入。");
    await Promise.all([loadRuns(), loadOverview(), loadCases({ keepSelection: true }), loadClusters()]);
  } catch (error) {
    target.textContent = `导入失败：${error.message}`;
    showToast(error.message, true);
  }
}

async function syncTrail(mode = "preview") {
  const createRun = mode === "create";
  const button = createRun ? $("#syncTrailButton") : $("#checkTrailButton");
  button.disabled = true;
  button.textContent = createRun ? "创建中…" : "检查中…";
  try {
    const result = await api("/api/trail-model-sync", {
      method: "POST",
      body: JSON.stringify({
        mode,
        requested_by: state.session.username || "",
      }),
    });
    state.trailInspection = result;
    state.config = {
      ...(state.config || {}),
      trail_sync: result,
      default_model_run_id: state.config?.default_model_run_id || "",
    };
    renderConfig();
    if (createRun && result.run_id) {
      await loadRuns();
    }
    showToast(
      result.message || (createRun ? "Trail 只读快照处理完成。" : "Trail 字段检查完成。"),
      ["failed", "unavailable"].includes(result.status)
    );
  } catch (error) {
    showToast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = createRun ? "创建只读 Trail 快照" : "检查字段可见性";
    renderTrailSyncState();
  }
}

async function refreshAll({ resetSelection = false } = {}) {
  await loadConfig();
  await loadRuns();
  await Promise.all([
    loadStatus(),
    loadOverview(),
    loadCases({ keepSelection: !resetSelection }),
    loadClusters(),
    loadReviewers(),
    loadInferenceJobs(),
  ]);
}

function bindEvents() {
  document.querySelectorAll("[data-page-target]").forEach((element) => {
    element.addEventListener("click", (event) => {
      if (
        element.tagName === "A" &&
        (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0)
      ) {
        return;
      }
      event.preventDefault();
      navigatePage(element.dataset.pageTarget, {
        issue: element.dataset.pageTarget === "inference" ? state.selectedId : "",
        kind: element.dataset.pageTarget === "import" ? "issues" : "",
      });
    });
  });
  $("#filterForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#modelRunFilter").addEventListener("change", async () => {
    const previousRunId = state.selectedRunId;
    state.selectedRunId = $("#modelRunFilter").value;
    if (!state.selectedRunId) state.failureOnly = false;
    if (state.selectedRunId && !previousRunId) state.failureOnly = true;
    $("#failureOnlyInput").disabled = !state.selectedRunId;
    $("#failureOnlyInput").checked = state.failureOnly;
    renderActiveRun();
    renderRunManager();
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#failureOnlyInput").addEventListener("change", async () => {
    state.failureOnly = $("#failureOnlyInput").checked;
    await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
  });
  $("#clearClusterButton").addEventListener("click", async () => {
    state.clusterKey = "";
    await Promise.all([loadCases({ keepSelection: false }), loadClusters()]);
  });
  $("#refreshButton").addEventListener("click", async () => {
    try {
      await refreshAll();
      if (state.selectedId) await selectCase(state.selectedId);
      showToast("页面数据已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#checkTrailButton").addEventListener("click", () => syncTrail("preview"));
  $("#syncTrailButton").addEventListener("click", () => syncTrail("create"));
  $("#runManagerImportButton").addEventListener("click", () => {
    $("#importResult").classList.add("hidden");
    $("#importResult").textContent = "";
    navigatePage("import", { kind: "model" });
  });
  $("#manageRunsButton").addEventListener("click", () => navigatePage("runs"));
  $("#refreshRunsButton").addEventListener("click", async () => {
    try {
      await loadRuns();
      await loadOverview();
      showToast("模型 run 列表已刷新。");
    } catch (error) {
      showToast(error.message, true);
    }
  });
  $("#runPersonFilter").addEventListener("change", renderRunManager);
  $("#runKindFilter").addEventListener("change", renderRunManager);
  $("#jobRequesterFilter").addEventListener("change", () => {
    loadInferenceJobs().catch((error) => showToast(error.message, true));
  });
  $("#jobStatusFilter").addEventListener("change", () => {
    loadInferenceJobs().catch((error) => showToast(error.message, true));
  });
  $("#refreshInferenceJobsButton").addEventListener("click", () => {
    loadInferenceJobs()
      .then(() => showToast("单 Case 任务历史已刷新。"))
      .catch((error) => showToast(error.message, true));
  });
  $("#sidebarToggle").addEventListener("click", toggleSidebar);
  document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => closeDialog(button.dataset.close)));
  $("#importKind").querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      updateImportFields();
      if (state.activePage === "import") {
        showPage("import", { historyMode: "replace", kind: currentImportKind() });
      }
    });
  });
  $("#importFile").addEventListener("change", () => { $("#importFileName").textContent = $("#importFile").files[0]?.name || "未选择文件"; });
  $("#importForm").addEventListener("submit", submitImport);
  $("#inferIssueInput").addEventListener("change", () => {
    updateInferenceTarget();
    if (state.activePage === "inference") {
      showPage("inference", { historyMode: "replace", issue: $("#inferIssueInput").value.trim() });
    }
  });
  $("#inferOpenReviewButton").addEventListener("click", async () => {
    const issueId = $("#inferIssueInput").value.trim();
    if (!issueId) return;
    navigatePage("review", { issue: issueId });
    await selectCase(issueId);
  });
  $("#preflightButton").addEventListener("click", () => submitInference({ dryRun: true }));
  $("#inferForm").addEventListener("submit", (event) => { event.preventDefault(); submitInference({ dryRun: false }); });
  $("#mediaPrevButton").addEventListener("click", () => moveMedia(-1));
  $("#mediaNextButton").addEventListener("click", () => moveMedia(1));
  document.addEventListener("keydown", (event) => {
    if (!$("#mediaDialog").open) return;
    if (["ArrowLeft", "ArrowUp"].includes(event.key)) { event.preventDefault(); moveMedia(-1); }
    if (["ArrowRight", "ArrowDown"].includes(event.key)) { event.preventDefault(); moveMedia(1); }
    if (event.key.toLowerCase() === "b" && mediaFrames("bev").length) { state.media.kind = "bev"; state.media.index = 0; renderMediaDialog(); }
    if (event.key.toLowerCase() === "c" && mediaFrames("camera").length) { state.media.kind = "camera"; state.media.index = 0; renderMediaDialog(); }
  });
  window.addEventListener("popstate", async () => {
    const route = parsePageRoute();
    const validRouteRun = route.runId && state.modelRuns.some((run) => run.id === route.runId);
    const nextFailureOnly = route.failureOnly ?? state.failureOnly;
    if (
      validRouteRun &&
      (route.runId !== state.selectedRunId || nextFailureOnly !== state.failureOnly)
    ) {
      state.selectedRunId = route.runId;
      $("#modelRunFilter").value = route.runId;
      state.failureOnly = nextFailureOnly;
      $("#failureOnlyInput").checked = state.failureOnly;
      await Promise.all([loadCases({ keepSelection: false }), loadClusters(), loadOverview()]);
    }
    showPage(route.page, { issue: route.issue, kind: route.kind });
    if (route.page === "review" && route.issue && route.issue !== state.selectedId) {
      await selectCase(route.issue, { updateRoute: false });
    }
  });
}

async function bootstrap() {
  const initialRoute = parsePageRoute();
  state.sidebarCollapsed = localStorage.getItem("ra-triage-sidebar-collapsed") === "true";
  applySidebarState();
  bindEvents();
  updateImportFields();
  showPage(initialRoute.page, { issue: initialRoute.issue, kind: initialRoute.kind });
  try {
    await Promise.all([loadConfig(), loadSession()]);
    state.selectedRunId = initialRoute.runId || state.config.default_model_run_id || "";
    state.failureOnly =
      initialRoute.failureOnly ??
      Boolean(state.config.default_failure_only && state.selectedRunId);
    await loadRuns({ preferDefault: !initialRoute.runId });
    $("#failureOnlyInput").checked = state.failureOnly;
    await Promise.all([
      loadStatus(),
      loadOverview(),
      loadCases({ keepSelection: false }),
      loadClusters(),
      loadReviewers(),
      loadInferenceJobs(),
    ]);
    if (initialRoute.issue && initialRoute.issue !== state.selectedId) {
      await selectCase(initialRoute.issue, { updateRoute: false });
    }
    showPage(initialRoute.page, {
      historyMode: "replace",
      issue: initialRoute.issue || state.selectedId,
      kind: initialRoute.kind,
    });
  } catch (error) {
    showToast(`启动失败：${error.message}`, true);
  }
}

window.addEventListener("DOMContentLoaded", bootstrap);
